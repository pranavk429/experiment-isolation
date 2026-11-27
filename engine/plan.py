"""Build an N-way isolation plan from an audit report (read-only)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .api import AdminAPI
from .audit import rollout_percentage
from .config import Config
from .segments import (
    audience_segment_ids,
    fetch_segments,
    find_range_segment,
)
from .util import EngineError, Refusal, compact_json

TRAIT = "flagsmith_experiment_bucket"
BUCKET_COUNT = 100


def equal_ranges(count: int) -> List[Tuple[int, int]]:
    """Partition 0..99 into *count* proportional inclusive ranges."""
    if count < 1:
        raise EngineError("Cannot partition buckets for zero experiments")
    bounds = [(index * BUCKET_COUNT) // count for index in range(count + 1)]
    return [(bounds[index], bounds[index + 1] - 1) for index in range(count)]


def range_conditions(trait: str, lo: int, hi: int) -> List[Dict[str, str]]:
    """Flagsmith conditions for the inclusive bucket range [lo, hi]."""
    conditions: List[Dict[str, str]] = []
    if lo > 0:
        conditions.append(
            {
                "trait": trait,
                "operator": "GREATER_THAN_INCLUSIVE",
                "value": str(lo),
            }
        )
    conditions.append({"trait": trait, "operator": "LESS_THAN", "value": str(hi + 1)})
    return conditions


def _legacy_operator(lo: int, hi: int) -> Tuple[str, str]:
    if lo == 0:
        return "LESS_THAN", str(hi + 1)
    if hi == BUCKET_COUNT - 1:
        return "GREATER_THAN_INCLUSIVE", str(lo)
    return "RANGE", "%s-%s" % (lo, hi)


def _segment_plan(
    segments: Sequence[Dict[str, Any]], lo: int, hi: int
) -> Dict[str, Any]:
    canonical = "exp_iso_%s_%s" % (lo, hi)
    existing = find_range_segment(segments, TRAIT, lo, hi)
    operator, value = _legacy_operator(lo, hi)
    if existing:
        return {
            "name": existing.get("name") or canonical,
            "trait": TRAIT,
            "lo": lo,
            "hi": hi,
            "operator": operator,
            "value": value,
            "conditions": range_conditions(TRAIT, lo, hi),
            "id": int(existing["id"]),
            "existing": True,
        }
    return {
        "name": canonical,
        "trait": TRAIT,
        "lo": lo,
        "hi": hi,
        "operator": operator,
        "value": value,
        "conditions": range_conditions(TRAIT, lo, hi),
        "id": None,
        "existing": False,
    }


def approval_token(
    environment_id: int,
    threshold: float,
    segments: Sequence[Dict[str, Any]],
    changes: Sequence[Dict[str, Any]],
    project_id: Optional[int] = None,
    restore: Optional[Dict[str, Any]] = None,
    secret: str = "",
    environment_name: str = "",
) -> str:
    """Content-bound 8-hex confirmation token.

    With a secret (the local admin key), the token is an HMAC so editing a plan
    without the key produces a different value. It is a confirmation token, not
    a public signature.
    """
    material = {
        "environment": {"id": environment_id, "name": environment_name},
        "project": project_id,
        "threshold": threshold,
        "segments": [
            [
                item["name"],
                item.get("lo"),
                item.get("hi"),
                item.get("operator"),
                item.get("value"),
            ]
            for item in segments
        ],
        "changes": [
            [
                item["experiment_id"],
                item["from_segment_ids"],
                item["to_segment_ids"],
                item.get("to_segment"),
                item.get("bucket_range"),
            ]
            for item in changes
        ],
        "restore": restore or {},
    }
    payload = compact_json(material).encode("utf-8")
    if secret:
        digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    else:
        digest = hashlib.sha256(payload).hexdigest()
    return "iso-" + digest[:8]


def _restore_payload(detail: Dict[str, Any]) -> Dict[str, Any]:
    rollout = detail.get("experiment_rollout") or {}
    return {
        "enabled": bool(rollout.get("enabled", True)),
        "rollout_percentage": rollout_percentage(detail),
        "feature_state_value": rollout.get("feature_state_value")
        or {"type": "string", "value": "control"},
        "multivariate_feature_state_values": rollout.get("multivariate_feature_state_values")
        or [],
        "audience": {
            "match": "any",
            "segment_ids": audience_segment_ids(detail),
        },
    }


def _max_pair_jaccard(audit: Dict[str, Any], ids: Sequence[int]) -> Optional[float]:
    wanted = set(int(item) for item in ids)
    values = [
        float(item.get("jaccard") or 0.0)
        for item in audit.get("overlaps") or []
        if int(item["a"]) in wanted and int(item["b"]) in wanted
    ]
    return max(values) if values else None


def _blocked_running(
    audit: Dict[str, Any],
    candidate_ids: Sequence[int],
    running_ids: Sequence[int],
) -> List[Dict[str, Any]]:
    candidates = set(int(item) for item in candidate_ids)
    running = set(int(item) for item in running_ids)
    overlaps: Dict[int, List[int]] = {}
    for pair in audit.get("collisions") or []:
        a, b = int(pair[0]), int(pair[1])
        if a in running and b in candidates:
            overlaps.setdefault(a, []).append(b)
        elif b in running and a in candidates:
            overlaps.setdefault(b, []).append(a)
    blocked: List[Dict[str, Any]] = []
    for experiment_id in sorted(overlaps):
        peers = sorted(set(overlaps[experiment_id]))
        blocked.append(
            {
                "experiment_id": experiment_id,
                "reason": "running experiment overlaps draft experiment(s) %s; "
                "its audience cannot change while running"
                % ", ".join(str(item) for item in peers),
                "pause_isolate_restart": "complete or delete experiment %s, then recreate it "
                "with a disjoint range; pausing is not enough because paused experiments "
                "cannot change audience" % experiment_id,
            }
        )
    return blocked


def _schedule(
    ids: Sequence[int], max_concurrent: int, min_bucket_width: int
) -> List[str]:
    capacity = max(1, min(max_concurrent, BUCKET_COUNT // max(1, min_bucket_width)))
    batches = [
        "batch %d: %s"
        % (index // capacity + 1, ", ".join(str(item) for item in ids[index : index + capacity]))
        for index in range(0, len(ids), capacity)
    ]
    batches.append(
        "run at most %d concurrent experiment(s), or raise --min-bucket-width "
        "only if the ranges remain valid" % capacity
    )
    return batches


def build_plan(
    audit: Dict[str, Any],
    config: Optional[Config] = None,
    max_concurrent: int = 4,
    min_bucket_width: int = 5,
) -> Dict[str, Any]:
    """Return an N-way plan. Only status=created experiments are changed."""
    if max_concurrent < 1:
        raise EngineError("--max-concurrent must be at least 1")
    if min_bucket_width < 1:
        raise EngineError("--min-bucket-width must be at least 1")
    threshold = float(audit.get("threshold", 0.05))
    rows = list(audit.get("experiments") or [])
    created = [row for row in rows if row.get("status") == "created"]
    running = [row for row in rows if row.get("status") == "running"]
    created_ids = set(int(row["id"]) for row in created)
    candidate_ids = set()
    for pair in audit.get("collisions") or []:
        a, b = int(pair[0]), int(pair[1])
        if a in created_ids and b in created_ids:
            candidate_ids.add(a)
            candidate_ids.add(b)
    candidates = sorted(
        [row for row in created if int(row["id"]) in candidate_ids],
        key=lambda row: int(row["id"]),
    )
    environment = audit.get("environment") or {}
    base: Dict[str, Any] = {
        "product": "experiment-isolation",
        "environment": environment,
        "project_id": audit.get("project_id"),
        "threshold": threshold,
        "feasible": True,
        "bucket_width": None,
        "max_concurrent": max_concurrent,
        "min_bucket_width": min_bucket_width,
        "deferred_experiments": [],
        "schedule": [],
        "segments_to_create": [],
        "audience_changes": [],
        "approval_token": None,
        "before_jaccard": None,
        "before_multi_exposed_rate": audit.get("multi_exposed_rate"),
        "blocked_running": _blocked_running(
            audit, [int(row["id"]) for row in candidates], [int(row["id"]) for row in running]
        ),
        "rollback": [],
        "notes": [],
        "unchanged_running": [int(row["id"]) for row in running],
        "candidate_experiments": [int(row["id"]) for row in candidates],
    }
    if len(candidates) < 2:
        if len(created) >= 2:
            base["before_jaccard"] = _max_pair_jaccard(
                audit, [int(row["id"]) for row in created]
            )
        base["notes"].append("fewer than two colliding draft experiments; no changes")
        return base

    count = len(candidates)
    ranges = equal_ranges(count)
    width = BUCKET_COUNT // count
    base["bucket_width"] = width
    base["before_jaccard"] = _max_pair_jaccard(
        audit, [int(row["id"]) for row in candidates]
    )
    if width < min_bucket_width or count > max_concurrent:
        base["feasible"] = False
        base["deferred_experiments"] = [int(row["id"]) for row in candidates]
        base["schedule"] = _schedule(
            [int(row["id"]) for row in candidates], max_concurrent, min_bucket_width
        )
        reasons: List[str] = []
        if width < min_bucket_width:
            reasons.append(
                "range width %d is below --min-bucket-width %d"
                % (width, min_bucket_width)
            )
        if count > max_concurrent:
            reasons.append(
                "%d colliding drafts exceed --max-concurrent %d"
                % (count, max_concurrent)
            )
        base["refusal"] = (
            "%s; no partial isolation was planned" % "; ".join(reasons)
        )
        base["notes"].append(base["refusal"])
        return base

    for row in candidates:
        if row.get("audience_has_percentage_split"):
            raise Refusal(
                "Draft experiment %s has a PERCENTAGE_SPLIT audience; "
                "replace it with a trait segment before planning." % row["id"]
            )

    if config is None:
        config = Config.load()
    api = AdminAPI(config)
    project_id = int(audit.get("project_id") or api.resolve_project_id())
    existing_segments = fetch_segments(api, project_id)
    planned_segments = [_segment_plan(existing_segments, lo, hi) for lo, hi in ranges]

    changes: List[Dict[str, Any]] = []
    restore: Dict[str, Any] = {}
    rollback: List[str] = [
        "python3 -m engine.cli rollback --apply apply.json --out rollback.json"
    ]
    for experiment, segment in zip(candidates, planned_segments):
        experiment_id = int(experiment["id"])
        change = {
            "experiment_id": experiment_id,
            "experiment": experiment.get("name"),
            "from_segment_ids": list(experiment.get("audience_segment_ids") or []),
            "to_segment_ids": [segment["id"]] if segment.get("id") else [],
            "to_segment": segment["name"],
            "bucket_range": [segment["lo"], segment["hi"]],
            "requires_rollout_disable": True,
        }
        changes.append(change)
        detail = api.get(
            "/api/v1/environments/%s/experiments/%s/" % (config.env_key, experiment_id)
        )
        if not isinstance(detail, dict):
            raise EngineError("Cannot read experiment %s for rollback snapshot" % experiment_id)
        restore[str(experiment_id)] = _restore_payload(detail)
    for segment in planned_segments:
        if not segment.get("existing"):
            rollback.append(
                "delete segment by name %s after rollback" % segment["name"]
            )

    running_collisions = [
        pair
        for pair in audit.get("collisions") or []
        if int(pair[0]) in base["unchanged_running"]
        and int(pair[1]) in base["unchanged_running"]
    ]
    if base["blocked_running"]:
        base["notes"].append(
            "%d blocked running experiment(s); apply will not modify them"
            % len(base["blocked_running"])
        )
    base["notes"].append(
        "a paused experiment cannot change audience; to isolate a running "
        "experiment, complete/delete it and recreate it, or isolate before launch"
    )
    if running_collisions:
        base["notes"].append(
            "running collision(s) remain: %s"
            % ", ".join("%s/%s" % (pair[0], pair[1]) for pair in running_collisions)
        )
    base.update(
        {
            "segments_to_create": planned_segments,
            "audience_changes": changes,
            "restore": restore,
            "rollback": rollback,
        }
    )
    base["approval_token"] = approval_token(
        int(environment.get("id") or 0),
        threshold,
        planned_segments,
        changes,
        project_id=project_id,
        restore=restore,
        secret=config.admin_key,
        environment_name=str(environment.get("name") or ""),
    )
    return base
