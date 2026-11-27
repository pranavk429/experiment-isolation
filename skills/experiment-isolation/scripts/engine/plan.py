"""Build an N-way isolation plan from an audit report (read-only)."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .api import AdminAPI
from .audit import rollout_percentage
from .config import Config
from .segments import (
    audience_segment_ids,
    compose_segment_rules,
    extract_base_rules,
    fetch_segments,
    find_range_segment,
    segment_map,
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
            {"trait": trait, "operator": "GREATER_THAN_INCLUSIVE", "value": str(lo)}
        )
    conditions.append({"trait": trait, "operator": "LESS_THAN", "value": str(hi + 1)})
    return conditions


def _legacy_operator(lo: int, hi: int) -> Tuple[str, str]:
    if lo == 0:
        return "LESS_THAN", str(hi + 1)
    if hi == BUCKET_COUNT - 1:
        return "GREATER_THAN_INCLUSIVE", str(lo)
    return "RANGE", f"{lo}-{hi}"


def _slugify_segment_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    if slug.startswith("exp_iso_"):
        slug = slug[len("exp_iso_") :]
    slug = re.sub(r"(?:^|_)\d+_\d+$", "", slug)
    return slug.strip("_")


def _experiment_base_targeting(
    experiment: Dict[str, Any], seg_by_id: Dict[int, Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], str]:
    """Extract combined non-bucket base rules and normalized slug for an experiment."""
    combined: List[Dict[str, Any]] = []
    slug_parts: List[str] = []
    for seg_id in experiment.get("audience_segment_ids") or []:
        seg = seg_by_id.get(int(seg_id))
        if not seg:
            continue
        rules = extract_base_rules(seg, TRAIT)
        if not rules:
            continue
        combined.extend(rules)
        part = _slugify_segment_name(str(seg.get("name") or ""))
        if part and part not in slug_parts:
            slug_parts.append(part)
    if len(combined) > 1 and all(
        rule.get("type") == "ALL" and not rule.get("rules") for rule in combined
    ):
        merged = [cond for rule in combined for cond in rule.get("conditions") or []]
        combined = [{"type": "ALL", "rules": [], "conditions": merged}]
    base_slug = "_".join(slug_parts) or ("targeted" if combined else "")
    return combined, base_slug


def _segment_plan(
    segments: Sequence[Dict[str, Any]],
    lo: int,
    hi: int,
    base_rules: Optional[List[Dict[str, Any]]] = None,
    base_slug: str = "",
) -> Dict[str, Any]:
    """Plan one composed audience segment for [lo, hi] and optional *base_rules*."""
    rules = list(base_rules or [])
    slug = base_slug or "targeted"
    canonical = f"exp_iso_{slug}_{lo}_{hi}" if rules else f"exp_iso_{lo}_{hi}"
    existing = find_range_segment(segments, TRAIT, lo, hi, base_rules=rules)
    operator, value = _legacy_operator(lo, hi)
    composed = compose_segment_rules(rules, TRAIT, lo, hi)
    conditions = composed[0]["conditions"] if composed else range_conditions(TRAIT, lo, hi)
    return {
        "name": (existing.get("name") or canonical) if existing else canonical,
        "trait": TRAIT,
        "lo": lo,
        "hi": hi,
        "operator": operator,
        "value": value,
        "base_rules": rules,
        "conditions": conditions,
        "id": int(existing["id"]) if existing else None,
        "existing": bool(existing),
    }


def _token_material(
    environment_id: int,
    threshold: float,
    segments: Sequence[Dict[str, Any]],
    changes: Sequence[Dict[str, Any]],
    project_id: Optional[int],
    restore: Optional[Dict[str, Any]],
    environment_name: str,
) -> Dict[str, Any]:
    return {
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
                item.get("conditions") or [],
                item.get("base_rules") or [],
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
    """Content-bound 8-hex confirmation token (HMAC-bound when *secret* is set)."""
    material = _token_material(
        environment_id, threshold, segments, changes, project_id, restore, environment_name
    )
    payload = compact_json(material).encode("utf-8")
    digest = (
        hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        if secret
        else hashlib.sha256(payload).hexdigest()
    )
    return f"iso-{digest[:8]}"


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
    wanted = {int(item) for item in ids}
    values = [
        float(item.get("jaccard") or 0.0)
        for item in audit.get("overlaps") or []
        if int(item["a"]) in wanted and int(item["b"]) in wanted
    ]
    return max(values) if values else None


def _blocked_running(
    audit: Dict[str, Any],
    created_ids: Sequence[int],
    immutable_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    created = {int(item) for item in created_ids}
    status_by_id = {
        int(row["id"]): str(row.get("status") or "running")
        for row in immutable_rows
    }
    overlaps: Dict[int, List[int]] = {}
    for pair in audit.get("collisions") or []:
        a, b = int(pair[0]), int(pair[1])
        if a in status_by_id and b in created:
            overlaps.setdefault(a, []).append(b)
        elif b in status_by_id and a in created:
            overlaps.setdefault(b, []).append(a)
    blocked: List[Dict[str, Any]] = []
    for experiment_id in sorted(overlaps):
        peers = ", ".join(str(item) for item in sorted(set(overlaps[experiment_id])))
        status = status_by_id[experiment_id]
        blocked.append(
            {
                "experiment_id": experiment_id,
                "reason": (
                    f"{status} experiment overlaps draft experiment(s) {peers}; "
                    f"its audience cannot change while {status}"
                ),
                "pause_isolate_restart": (
                    f"complete or delete experiment {experiment_id}, then recreate it "
                    "with a disjoint range; pausing is not enough because paused "
                    "experiments cannot change audience"
                ),
            }
        )
    return blocked


def _collision_components(
    candidate_ids: Set[int], collisions: Sequence[Sequence[int]]
) -> List[List[int]]:
    """Partition colliding draft ids into sorted connected components."""
    adj: Dict[int, Set[int]] = {cid: set() for cid in candidate_ids}
    for pair in collisions:
        a, b = int(pair[0]), int(pair[1])
        if a in adj and b in adj and a != b:
            adj[a].add(b)
            adj[b].add(a)
    visited: Set[int] = set()
    components: List[List[int]] = []
    for start in sorted(adj):
        if start in visited:
            continue
        comp: List[int] = []
        queue = deque([start])
        visited.add(start)
        while queue:
            node = queue.popleft()
            comp.append(node)
            for neighbor in sorted(adj[node]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(comp))
    components.sort(key=lambda items: items[0])
    return components


def _schedule(
    ids: Sequence[int], max_concurrent: int, min_bucket_width: int
) -> List[str]:
    capacity = max(1, min(max_concurrent, BUCKET_COUNT // max(1, min_bucket_width)))
    batches = [
        f"batch {index // capacity + 1}: {', '.join(str(item) for item in ids[index : index + capacity])}"
        for index in range(0, len(ids), capacity)
    ]
    batches.append(
        f"run at most {capacity} concurrent experiment(s), or lower --min-bucket-width "
        "only if the ranges remain valid"
    )
    return batches


def _empty_plan_base(
    audit: Dict[str, Any],
    threshold: float,
    max_concurrent: int,
    min_bucket_width: int,
    running: Sequence[Dict[str, Any]],
    candidates: Sequence[Dict[str, Any]],
    blocked: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Initialize the base plan response dictionary."""
    return {
        "product": "experiment-isolation",
        "environment": audit.get("environment") or {},
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
        "blocked_running": blocked,
        "rollback": [],
        "notes": [],
        "unchanged_running": [int(row["id"]) for row in running],
        "candidate_experiments": [int(row["id"]) for row in candidates],
    }


def _infeasible_plan(
    base: Dict[str, Any],
    candidates: Sequence[Dict[str, Any]],
    width: int,
    max_comp: int,
    max_concurrent: int,
    min_bucket_width: int,
) -> Dict[str, Any]:
    """Populate refusal and staggered schedule for an infeasible plan."""
    candidate_ids = [int(row["id"]) for row in candidates]
    reasons: List[str] = []
    if width < min_bucket_width:
        reasons.append(f"range width {width} is below --min-bucket-width {min_bucket_width}")
    if max_comp > max_concurrent:
        reasons.append(f"{max_comp} colliding drafts exceed --max-concurrent {max_concurrent}")
    refusal = f"{'; '.join(reasons)}; no partial isolation was planned"
    base.update(
        {
            "feasible": False,
            "deferred_experiments": candidate_ids,
            "schedule": _schedule(candidate_ids, max_concurrent, min_bucket_width),
            "refusal": refusal,
        }
    )
    base["notes"].append(refusal)
    return base


def _append_running_notes(base: Dict[str, Any], audit: Dict[str, Any]) -> None:
    """Add clear operator guidance about running and blocked experiments."""
    blocked = base["blocked_running"]
    if blocked:
        base["notes"].append(
            f"{len(blocked)} blocked running experiment(s); apply will not modify them"
        )
    base["notes"].append(
        "a paused experiment cannot change audience; to isolate a running "
        "experiment, complete/delete it and recreate it, or isolate before launch"
    )
    unchanged = set(base["unchanged_running"])
    running_collisions = [
        f"{pair[0]}/{pair[1]}"
        for pair in audit.get("collisions") or []
        if int(pair[0]) in unchanged and int(pair[1]) in unchanged
    ]
    if running_collisions:
        base["notes"].append(f"running collision(s) remain: {', '.join(running_collisions)}")


def _assign_component_ranges(
    components: Sequence[Sequence[int]],
) -> Dict[int, Tuple[int, int]]:
    """Assign equal disjoint bucket ranges independently per collision component."""
    assigned: Dict[int, Tuple[int, int]] = {}
    for comp in components:
        for experiment_id, bounds in zip(comp, equal_ranges(len(comp))):
            assigned[experiment_id] = bounds
    return assigned


def _populate_changes_and_restore(
    api: AdminAPI,
    config: Config,
    candidates: Sequence[Dict[str, Any]],
    assigned_ranges: Dict[int, Tuple[int, int]],
    existing_segments: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[str]]:
    """Build planned segments, audience changes, and rollback snapshots."""
    seg_by_id = segment_map(existing_segments)
    planned_segments: List[Dict[str, Any]] = []
    seen_segments: Set[Tuple[str, int, int]] = set()
    changes: List[Dict[str, Any]] = []
    restore: Dict[str, Any] = {}
    rollback = ["python3 -m engine.cli rollback --apply apply.json --out rollback.json"]
    for experiment in candidates:
        experiment_id = int(experiment["id"])
        lo, hi = assigned_ranges[experiment_id]
        base_rules, base_slug = _experiment_base_targeting(experiment, seg_by_id)
        seg_plan = _segment_plan(
            existing_segments, lo, hi, base_rules=base_rules, base_slug=base_slug
        )
        dedup_key = (str(seg_plan["name"]), int(seg_plan["lo"]), int(seg_plan["hi"]))
        if dedup_key not in seen_segments:
            seen_segments.add(dedup_key)
            planned_segments.append(seg_plan)
        changes.append(
            {
                "experiment_id": experiment_id,
                "experiment": experiment.get("name"),
                "from_segment_ids": list(experiment.get("audience_segment_ids") or []),
                "to_segment_ids": [seg_plan["id"]] if seg_plan.get("id") else [],
                "to_segment": seg_plan["name"],
                "bucket_range": [seg_plan["lo"], seg_plan["hi"]],
                "requires_rollout_disable": True,
            }
        )
        detail = api.get(f"/api/v1/environments/{config.env_key}/experiments/{experiment_id}/")
        if not isinstance(detail, dict):
            raise EngineError(f"Cannot read experiment {experiment_id} for rollback snapshot")
        restore[str(experiment_id)] = _restore_payload(detail)
    for seg_plan in planned_segments:
        if not seg_plan.get("existing"):
            rollback.append(f"delete segment by name {seg_plan['name']} after rollback")
    return planned_segments, changes, restore, rollback


def _partition_audit_rows(
    audit: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Set[int], Set[int], List[Dict[str, Any]]]:
    rows = list(audit.get("experiments") or [])
    created = [row for row in rows if row.get("status") == "created"]
    immutable = sorted(
        (row for row in rows if row.get("status") in ("running", "paused")),
        key=lambda row: int(row["id"]),
    )
    created_ids = {int(row["id"]) for row in created}
    candidate_ids = {
        int(eid)
        for pair in audit.get("collisions") or []
        if int(pair[0]) in created_ids and int(pair[1]) in created_ids
        for eid in (pair[0], pair[1])
    }
    candidates = sorted(
        (row for row in created if int(row["id"]) in candidate_ids),
        key=lambda row: int(row["id"]),
    )
    return created, immutable, created_ids, candidate_ids, candidates


def _blocked_plan(
    base: Dict[str, Any],
    audit: Dict[str, Any],
    created_ids: Set[int],
    blocked: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Refuse planning when drafts collide with immutable running or paused experiments."""
    colliding_drafts = sorted(
        {
            int(eid)
            for pair in audit.get("collisions") or []
            for eid in pair
            if int(eid) in created_ids
        }
    )
    pair_ids = sorted(created_ids) + [int(item["experiment_id"]) for item in blocked]
    refusal = (
        f"{len(blocked)} immutable running/paused experiment(s) overlap draft "
        "audience(s); complete or delete and recreate them before planning"
    )
    base.update(
        {
            "feasible": False,
            "deferred_experiments": colliding_drafts,
            "segments_to_create": [],
            "audience_changes": [],
            "approval_token": None,
            "before_jaccard": _max_pair_jaccard(audit, pair_ids),
            "refusal": refusal,
        }
    )
    base["notes"].append(refusal)
    _append_running_notes(base, audit)
    return base


def _noop_plan(
    base: Dict[str, Any],
    audit: Dict[str, Any],
    created: Sequence[Dict[str, Any]],
    created_ids: Set[int],
) -> Dict[str, Any]:
    if len(created) >= 2:
        base["before_jaccard"] = _max_pair_jaccard(audit, sorted(created_ids))
    base["notes"].append("fewer than two colliding draft experiments; no changes")
    return base


def _build_feasible_plan(
    base: Dict[str, Any],
    audit: Dict[str, Any],
    config: Config,
    candidates: Sequence[Dict[str, Any]],
    components: Sequence[Sequence[int]],
    threshold: float,
) -> Dict[str, Any]:
    api = AdminAPI(config)
    project_id = int(audit.get("project_id") or api.resolve_project_id())
    planned_segments, changes, restore, rollback = _populate_changes_and_restore(
        api, config, candidates, _assign_component_ranges(components), fetch_segments(api, project_id)
    )
    _append_running_notes(base, audit)
    base.update(
        {
            "segments_to_create": planned_segments,
            "audience_changes": changes,
            "restore": restore,
            "rollback": rollback,
        }
    )
    env = base["environment"]
    base["approval_token"] = approval_token(
        int(env.get("id") or 0), threshold, planned_segments, changes,
        project_id=project_id, restore=restore, secret=config.admin_key,
        environment_name=str(env.get("name") or ""),
    )
    return base


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
    created, immutable, created_ids, candidate_ids, candidates = _partition_audit_rows(audit)
    blocked = _blocked_running(audit, sorted(created_ids), immutable)
    base = _empty_plan_base(
        audit, threshold, max_concurrent, min_bucket_width, immutable, candidates, blocked
    )
    if blocked:
        return _blocked_plan(base, audit, created_ids, blocked)
    if len(candidates) < 2:
        return _noop_plan(base, audit, created, created_ids)

    components = _collision_components(candidate_ids, audit.get("collisions") or [])
    width = min(BUCKET_COUNT // len(comp) for comp in components)
    max_comp = max(len(comp) for comp in components)
    base["bucket_width"] = width
    base["before_jaccard"] = _max_pair_jaccard(audit, sorted(candidate_ids))
    if width < min_bucket_width or max_comp > max_concurrent:
        return _infeasible_plan(
            base, candidates, width, max_comp, max_concurrent, min_bucket_width
        )
    for row in candidates:
        if row.get("audience_has_percentage_split"):
            raise Refusal(
                f"Draft experiment {row['id']} has a PERCENTAGE_SPLIT audience; "
                "replace it with a trait segment before planning."
            )
    return _build_feasible_plan(base, audit, config or Config.load(), candidates, components, threshold)
