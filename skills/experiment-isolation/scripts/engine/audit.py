"""Read-only experiment overlap audit."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .api import AdminAPI
from .config import Config
from .sampling import (
    SAMPLE_TRAITS,
    SampleIdentity,
    build_sample,
    cleanup_identities,
    enrollment_by_experiment,
    jaccard,
    persist_sample,
)
from .segments import (
    audience_has_percentage_split,
    audience_segment_ids,
    fetch_segments,
    segment_map,
    segment_matches,
)
from .util import EngineError


def list_experiments(api: AdminAPI, env_key: str) -> List[Dict[str, Any]]:
    """Return full detail for every non-completed experiment, sorted by id."""
    summaries = api.get_all(f"/api/v1/environments/{env_key}/experiments/")
    details: List[Dict[str, Any]] = []
    for summary in sorted(summaries, key=lambda item: int(item.get("id") or 0)):
        if summary.get("status") == "completed":
            continue
        detail = api.get(f"/api/v1/environments/{env_key}/experiments/{summary['id']}/")
        if isinstance(detail, dict):
            details.append(detail)
    return details


def rollout_percentage(experiment: Dict[str, Any]) -> float:
    rollout = experiment.get("experiment_rollout") or {}
    raw = rollout.get("rollout_percentage")
    try:
        return float(raw if raw is not None else 100.0)
    except (TypeError, ValueError):
        return 100.0


def projected_eligible(
    experiment: Dict[str, Any],
    identity: SampleIdentity,
    segments: Dict[int, Dict[str, Any]],
) -> bool:
    """Predict enrollment for a draft experiment that is not serving traffic.

    Flagsmith reports in_experiment only for running experiments, so a draft's
    audience must be evaluated from its segment rules. This is clearly labelled
    as projected in the audit; after apply it becomes measured.
    """
    segment_ids = audience_segment_ids(experiment)
    if segment_ids:
        rollout = experiment.get("experiment_rollout") or {}
        audience = rollout.get("audience") or {}
        match = str(audience.get("match") or "any").lower()
        checks = [
            segment_matches(segments[int(segment_id)], identity.traits)
            if int(segment_id) in segments
            else False
            for segment_id in segment_ids
        ]
        eligible = any(checks) if match == "any" else all(checks)
        if not eligible:
            return False
    percentage = rollout_percentage(experiment)
    if percentage >= 100.0:
        return True
    if percentage <= 0.0:
        return False
    digest = hashlib.sha256(
        f"{experiment.get('id')}:{identity.identifier}".encode("utf-8")
    ).hexdigest()
    return (int(digest[0:8], 16) % 100) < percentage


def _enrolled_sets(
    experiments: Sequence[Dict[str, Any]],
    samples: Sequence[SampleIdentity],
    payloads: Dict[str, Dict[str, Any]],
    segments: Dict[int, Dict[str, Any]],
) -> Tuple[Dict[int, Set[str]], Dict[int, str]]:
    measured = enrollment_by_experiment(payloads)
    enrolled: Dict[int, Set[str]] = {}
    basis: Dict[int, str] = {}
    for experiment in experiments:
        experiment_id = int(experiment["id"])
        if experiment.get("status") != "created":
            basis[experiment_id] = "measured"
            enrolled[experiment_id] = set(measured.get(experiment_id, set()))
            continue
        basis[experiment_id] = "projected"
        try:
            enrolled[experiment_id] = {
                sample.identifier
                for sample in samples
                if projected_eligible(experiment, sample, segments)
            }
        except Exception as exc:
            raise EngineError(
                f"Cannot project audience for draft experiment {experiment_id}: {exc}"
            ) from exc
    return enrolled, basis


def _empty_audit_report(
    config: Config,
    environment: Dict[str, Any],
    project_id: int,
    samples: int,
    threshold: float,
) -> Dict[str, Any]:
    """Return the empty audit report structure for zero active experiments."""
    return {
        "environment": config.public_environment(
            str(environment.get("name") or "unknown"),
            int(environment.get("id") or 0),
        ),
        "project_id": project_id,
        "sample_size": samples,
        "threshold": threshold,
        "experiments": [],
        "overlaps": [],
        "collisions": [],
        "verdict": "none",
        "multi_exposed_rate": 0.0,
        "max_exposure_count": 0,
        "risk": "none",
        "sample_traits": SAMPLE_TRAITS,
    }


def _build_experiment_rows(
    experiments: Sequence[Dict[str, Any]],
    enrolled: Dict[int, Set[str]],
    basis: Dict[int, str],
    segments: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build summary rows for each non-completed experiment."""
    rows: List[Dict[str, Any]] = []
    for experiment in experiments:
        experiment_id = int(experiment["id"])
        audience_ids = audience_segment_ids(experiment)
        feature = experiment.get("feature") or {}
        rows.append(
            {
                "id": experiment_id,
                "name": experiment.get("name"),
                "feature": feature.get("name") if isinstance(feature, dict) else None,
                "status": experiment.get("status"),
                "audience_segment_ids": audience_ids,
                "rollout_percentage": rollout_percentage(experiment),
                "enrolled": len(enrolled[experiment_id]),
                "basis": basis[experiment_id],
                "audience_has_percentage_split": audience_has_percentage_split(
                    audience_ids, segments
                ),
            }
        )
    return rows


def _compute_risk(
    enrolled: Dict[int, Set[str]], samples: int
) -> Tuple[float, int, str]:
    """Compute multi-exposure rate, max simultaneous count, and risk tier."""
    exposure_counts: Counter = Counter()
    for experiment_id in enrolled:
        for identifier in enrolled[experiment_id]:
            exposure_counts[identifier] += 1
    multi_exposed = sum(1 for count in exposure_counts.values() if count >= 2)
    max_exposure_count = max(exposure_counts.values()) if exposure_counts else 0
    multi_exposed_rate = multi_exposed / float(samples)
    if multi_exposed == 0:
        risk = "none"
    elif max_exposure_count >= 3 or multi_exposed_rate > 0.25:
        risk = "critical"
    elif multi_exposed_rate > 0.05:
        risk = "elevated"
    else:
        risk = "low"
    return round(multi_exposed_rate, 4), max_exposure_count, risk


def _compute_overlaps(
    ids: Sequence[int],
    enrolled: Dict[int, Set[str]],
    samples: int,
    threshold: float,
) -> Tuple[List[Dict[str, Any]], List[List[int]]]:
    """Compute pairwise Jaccard overlaps and thresholded collision pairs."""
    overlaps: List[Dict[str, Any]] = []
    collisions: List[List[int]] = []
    for left_index in range(len(ids)):
        for right_index in range(left_index + 1, len(ids)):
            left, right = ids[left_index], ids[right_index]
            shared, union, similarity = jaccard(enrolled[left], enrolled[right])
            collision = shared > 0 and similarity >= threshold
            overlaps.append(
                {
                    "a": left,
                    "b": right,
                    "shared": shared,
                    "union": union,
                    "jaccard": round(similarity, 4),
                    "a_rate": round(len(enrolled[left]) / float(samples), 4),
                    "b_rate": round(len(enrolled[right]) / float(samples), 4),
                    "verdict": "collision" if collision else "clear",
                }
            )
            if collision:
                collisions.append([left, right])
    return overlaps, collisions


def run_audit(
    config: Config,
    samples: int = 500,
    threshold: float = 0.05,
    workers: int = 8,
    cleanup: bool = False,
) -> Dict[str, Any]:
    """Build the audit report and return it as a plain dict."""
    if not 0.0 <= threshold <= 1.0:
        raise EngineError("--threshold must be between 0 and 1")
    api = AdminAPI(config)
    environment = api.environment()
    project_id = api.resolve_project_id()
    experiments = list_experiments(api, config.env_key)
    report = _empty_audit_report(config, environment, project_id, samples, threshold)
    if not experiments:
        return report

    segments = segment_map(fetch_segments(api, project_id))
    sample_list = build_sample(samples)
    payloads = persist_sample(config, sample_list, workers=workers)
    enrolled, basis = _enrolled_sets(experiments, sample_list, payloads, segments)
    experiment_rows = _build_experiment_rows(experiments, enrolled, basis, segments)
    multi_exposed_rate, max_exposure_count, risk = _compute_risk(enrolled, samples)
    overlaps, collisions = _compute_overlaps(
        [row["id"] for row in experiment_rows], enrolled, samples, threshold
    )
    report.update(
        {
            "experiments": experiment_rows,
            "overlaps": overlaps,
            "collisions": collisions,
            "verdict": "collision" if collisions else "clear",
            "multi_exposed_rate": multi_exposed_rate,
            "max_exposure_count": max_exposure_count,
            "risk": risk,
        }
    )
    if cleanup:
        report["cleanup"] = cleanup_identities(
            config, [sample.identifier for sample in sample_list]
        )
    return report


def experiment_by_id(report: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {int(item["id"]): item for item in report.get("experiments") or []}


def overlap_for(report: Dict[str, Any], a: int, b: int) -> Optional[Dict[str, Any]]:
    for overlap in report.get("overlaps") or []:
        if {int(overlap["a"]), int(overlap["b"])} == {int(a), int(b)}:
            return overlap
    return None
