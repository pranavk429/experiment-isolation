"""Post-apply verification: resample and prove the planned audiences are disjoint."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from .api import AdminAPI
from .config import Config
from .sampling import (
    build_sample,
    cleanup_identities,
    enrollment_by_experiment,
    jaccard,
    persist_sample,
)
from .segments import audience_segment_ids, fetch_segments
from .util import EngineError, Refusal


def run_verify(
    config: Config,
    plan: Dict[str, Any],
    samples: int = 500,
    workers: int = 8,
    cleanup: bool = False,
) -> Dict[str, Any]:
    """Resample identities and measure the planned experiments' enrollment."""
    if plan.get("feasible") is False:
        raise Refusal(str(plan.get("refusal") or "Plan is infeasible; nothing to verify"))
    changes = list(plan.get("audience_changes") or [])
    before = plan.get("before_jaccard")
    before_multi = plan.get("before_multi_exposed_rate")
    if not changes:
        return {
            "sample_size": samples,
            "before_jaccard": before,
            "after_jaccard": 0.0,
            "max_pairwise_jaccard": 0.0,
            "before_multi_exposed_rate": before_multi,
            "after_multi_exposed_rate": 0.0,
            "pass": True,
            "overlaps": [],
            "noop": True,
        }
    ids = [int(change["experiment_id"]) for change in changes]
    if len(ids) < 2:
        raise EngineError("Verify expects at least two planned experiments")

    api = AdminAPI(config)
    known_segments = fetch_segments(api, int(plan.get("project_id") or api.resolve_project_id()))
    segment_id_by_name = {
        str(item.get("name")): int(item["id"])
        for item in known_segments
        if item.get("id") is not None
    }
    statuses: Dict[int, str] = {}
    for experiment_id in ids:
        detail = api.get(
            "/api/v1/environments/%s/experiments/%s/" % (config.env_key, experiment_id)
        )
        if not isinstance(detail, dict):
            raise EngineError("Cannot read experiment %s" % experiment_id)
        statuses[experiment_id] = str(detail.get("status"))
        if not bool((detail.get("experiment_rollout") or {}).get("enabled")):
            statuses[experiment_id] = "rollout_disabled"
        change = next(item for item in changes if int(item["experiment_id"]) == experiment_id)
        planned = list(change.get("to_segment_ids") or [])
        if not planned and change.get("to_segment"):
            resolved = segment_id_by_name.get(str(change.get("to_segment")))
            if resolved is not None:
                planned = [resolved]
        if not planned:
            statuses[experiment_id] = "audience_unknown"
        elif audience_segment_ids(detail) != sorted(int(item) for item in planned):
            statuses[experiment_id] = "audience_mismatch"

    sample_list = build_sample(samples)
    payloads = persist_sample(config, sample_list, workers=workers)
    measured = enrollment_by_experiment(payloads)
    enrolled: Dict[int, set] = {
        experiment_id: measured.get(experiment_id, set()) for experiment_id in ids
    }

    overlaps: List[Dict[str, Any]] = []
    max_jaccard = 0.0
    for left_index in range(len(ids)):
        for right_index in range(left_index + 1, len(ids)):
            left, right = ids[left_index], ids[right_index]
            shared, union, similarity = jaccard(enrolled[left], enrolled[right])
            max_jaccard = max(max_jaccard, similarity)
            overlaps.append(
                {
                    "a": left,
                    "b": right,
                    "shared": shared,
                    "union": union,
                    "jaccard": round(similarity, 4),
                    "a_rate": round(len(enrolled[left]) / float(samples), 4),
                    "b_rate": round(len(enrolled[right]) / float(samples), 4),
                    "verdict": "isolated" if similarity == 0.0 else "collision",
                }
            )

    exposure_counts: Counter = Counter()
    for experiment_id in ids:
        for identifier in enrolled[experiment_id]:
            exposure_counts[identifier] += 1
    multi_exposed = sum(1 for count in exposure_counts.values() if count >= 2)
    after_multi = multi_exposed / float(samples)
    all_running = all(statuses.get(experiment_id) == "running" for experiment_id in ids)
    all_nonempty = all(len(enrolled[experiment_id]) > 0 for experiment_id in ids)
    pass_result = max_jaccard == 0.0 and after_multi == 0.0 and all_running and all_nonempty
    result: Dict[str, Any] = {
        "sample_size": samples,
        "before_jaccard": before,
        "after_jaccard": round(max_jaccard, 4),
        "max_pairwise_jaccard": round(max_jaccard, 4),
        "before_multi_exposed_rate": before_multi,
        "after_multi_exposed_rate": round(after_multi, 4),
        "pass": pass_result,
        "overlaps": overlaps,
        "experiments": [
            {
                "id": experiment_id,
                "status": statuses.get(experiment_id),
                "enrolled": len(enrolled[experiment_id]),
            }
            for experiment_id in ids
        ],
    }
    if cleanup:
        result["cleanup"] = cleanup_identities(
            config, [sample.identifier for sample in sample_list]
        )
    return result
