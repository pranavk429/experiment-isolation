"""Approved application of a plan: disable rollout, change audience, start."""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .api import AdminAPI
from .config import Config
from .plan import approval_token
from .segments import (
    audience_segment_ids,
    compose_segment_rules,
    fetch_segments,
    segment_is_range,
)
from .util import EngineError, Refusal, sanitize_text, write_json


def _spec_range(spec: Dict[str, Any]) -> Tuple[int, int]:
    """Read a range from new-style lo/hi or the legacy single-bound schema."""
    if spec.get("lo") is not None and spec.get("hi") is not None:
        return int(spec["lo"]), int(spec["hi"])
    operator = str(spec.get("operator") or "").upper()
    value = str(spec.get("value"))
    try:
        number = int(value)
    except ValueError as exc:
        raise EngineError(f"Invalid segment value {value!r}") from exc
    if operator == "LESS_THAN":
        return 0, number - 1
    if operator == "GREATER_THAN_INCLUSIVE":
        return number, 99
    raise EngineError("Segment spec has no bucket range")


def _segment_spec_key(spec: Dict[str, Any]) -> str:
    lo, hi = _spec_range(spec)
    return f"{spec.get('name') or ''}:{lo}:{hi}"


def _validate_segment(segment: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    lo, hi = _spec_range(spec)
    return segment_is_range(
        segment, str(spec.get("trait")), lo, hi, base_rules=spec.get("base_rules")
    )


def _segment_conditions(spec: Dict[str, Any]) -> List[Dict[str, str]]:
    raw = spec.get("conditions")
    if isinstance(raw, list) and raw:
        return [
            {
                "operator": str(item.get("operator")),
                "property": str(item.get("trait") or item.get("property")),
                "value": str(item.get("value")),
            }
            for item in raw
            if isinstance(item, dict)
        ]
    lo, hi = _spec_range(spec)
    trait = str(spec.get("trait"))
    conditions: List[Dict[str, str]] = []
    if lo > 0:
        conditions.append(
            {"operator": "GREATER_THAN_INCLUSIVE", "property": trait, "value": str(lo)}
        )
    conditions.append({"operator": "LESS_THAN", "property": trait, "value": str(hi + 1)})
    return conditions


def _segment_rules(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    base_rules = spec.get("base_rules") or []
    if base_rules:
        lo, hi = _spec_range(spec)
        return compose_segment_rules(base_rules, str(spec.get("trait")), lo, hi)
    return [{"type": "ALL", "rules": [], "conditions": _segment_conditions(spec)}]


def _ensure_one_segment(
    api: AdminAPI,
    project_id: int,
    spec: Dict[str, Any],
    segments: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], bool]:
    """Resolve, validate, or create a single planned segment."""
    if spec.get("id"):
        segment = api.get(f"/api/v1/projects/{project_id}/segments/{int(spec['id'])}/")
        if not isinstance(segment, dict) or not _validate_segment(segment, spec):
            raise EngineError(
                f"Planned segment {spec.get('id')} no longer matches its trait rule"
            )
        return segment, False
    existing = next((item for item in segments if item.get("name") == spec.get("name")), None)
    if existing is not None:
        if not _validate_segment(existing, spec):
            raise EngineError(f"Segment name {spec.get('name')} exists with different rules")
        return existing, False
    segment = api.post(
        f"/api/v1/projects/{project_id}/segments/",
        {"name": spec.get("name"), "project": project_id, "rules": _segment_rules(spec)},
    )
    if not isinstance(segment, dict) or segment.get("id") is None:
        raise EngineError(f"Could not create segment {spec.get('name')}")
    return segment, True


def ensure_segments(
    api: AdminAPI,
    project_id: int,
    specs: Sequence[Dict[str, Any]],
    created_out: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, int], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Create or reuse the bucket-range segments; verify every result."""
    segments = fetch_segments(api, project_id)
    ids: Dict[str, int] = {}
    created: List[Dict[str, Any]] = []
    reused: List[Dict[str, Any]] = []
    for spec in specs:
        segment, was_created = _ensure_one_segment(api, project_id, spec, segments)
        entry = {"id": int(segment["id"]), "name": segment.get("name")}
        if was_created:
            created.append(entry)
            if created_out is not None:
                created_out.append(entry)
            if not _validate_segment(segment, spec):
                raise EngineError(f"Created segment {segment.get('id')} did not verify")
            segments.append(segment)
        else:
            reused.append(entry)
        ids[_segment_spec_key(spec)] = int(segment["id"])
    return ids, created, reused


def _rollout_payload(
    detail: Dict[str, Any], audience_ids: Sequence[int], enabled: bool
) -> Dict[str, Any]:
    rollout = detail.get("experiment_rollout") or {}
    audience = rollout.get("audience") or {}
    return {
        "enabled": enabled,
        "rollout_percentage": rollout.get("rollout_percentage", 100),
        "feature_state_value": rollout.get("feature_state_value")
        or {"type": "string", "value": "control"},
        "multivariate_feature_state_values": rollout.get("multivariate_feature_state_values")
        or [],
        "audience": {
            "match": audience.get("match") or "any",
            "segment_ids": list(audience_ids),
        },
    }


def _detail(api: AdminAPI, env_key: str, experiment_id: int) -> Dict[str, Any]:
    detail = api.get(f"/api/v1/environments/{env_key}/experiments/{experiment_id}/")
    if not isinstance(detail, dict):
        raise EngineError(f"Could not read experiment {experiment_id}")
    return detail


def _patch_and_verify(
    api: AdminAPI,
    env_key: str,
    experiment_id: int,
    payload: Dict[str, Any],
    expected_audience: Sequence[int],
    expected_enabled: bool,
) -> None:
    api.patch(
        f"/api/v1/environments/{env_key}/experiments/{experiment_id}/rollout/",
        payload,
    )
    detail = _detail(api, env_key, experiment_id)
    rollout = detail.get("experiment_rollout") or {}
    if bool(rollout.get("enabled")) != expected_enabled:
        raise EngineError(
            f"Experiment {experiment_id} rollout.enabled did not become {expected_enabled}"
        )
    if audience_segment_ids(detail) != sorted(int(item) for item in expected_audience):
        raise EngineError(f"Experiment {experiment_id} audience did not verify")


def _start_and_verify(api: AdminAPI, env_key: str, experiment_id: int) -> Dict[str, Any]:
    api.post(f"/api/v1/environments/{env_key}/experiments/{experiment_id}/start/", {})
    detail = _detail(api, env_key, experiment_id)
    if detail.get("status") != "running":
        raise EngineError(f"Experiment {experiment_id} did not reach running")
    if not bool((detail.get("experiment_rollout") or {}).get("enabled")):
        raise EngineError(f"Experiment {experiment_id} is running with rollout disabled")
    return detail


def _expected_token(
    config: Config, plan: Dict[str, Any], changes: Sequence[Dict[str, Any]]
) -> str:
    environment = plan.get("environment") or {}
    return approval_token(
        int(environment.get("id") or 0),
        float(plan.get("threshold", 0.05)),
        plan.get("segments_to_create") or [],
        changes,
        project_id=int(plan.get("project_id") or 0),
        restore=plan.get("restore") or {},
        secret=config.admin_key,
        environment_name=str(environment.get("name") or ""),
    )


def _write_failure(
    config: Config,
    plan: Dict[str, Any],
    out_dir: Optional[str],
    error: Exception,
    created_segments: Sequence[Dict[str, Any]],
    reused_segments: Sequence[Dict[str, Any]],
    applied: Sequence[Dict[str, Any]],
    steps: Sequence[Dict[str, Any]],
) -> Optional[str]:
    artifact = {
        "product": "experiment-isolation",
        "pass": False,
        "error": sanitize_text(str(error), config.admin_key, config.env_key),
        "environment": plan.get("environment"),
        "project_id": plan.get("project_id"),
        "scope": "planned_experiments",
        "segments": {"created": list(created_segments), "reused": list(reused_segments)},
        "changes": list(applied),
        "steps": list(steps),
        "restore": plan.get("restore") or {},
        "blocked_running": plan.get("blocked_running") or [],
        "rollback": [
            "python3 -m engine.cli rollback --apply apply-failure.json --out rollback.json"
        ],
    }
    if not out_dir:
        return None
    path = str(Path(out_dir) / "apply-failure.json")
    write_json(path, artifact)
    return path


def _verify_approval(
    config: Config,
    plan: Dict[str, Any],
    approval: str,
    changes: Sequence[Dict[str, Any]],
) -> None:
    """Validate HMAC approval token and reject blocked running experiment targets."""
    expected = _expected_token(config, plan, changes)
    stored = str(plan.get("approval_token") or "")
    token_ok = (
        bool(approval)
        and bool(expected)
        and bool(stored)
        and hmac.compare_digest(approval.encode("utf-8"), expected.encode("utf-8"))
        and hmac.compare_digest(stored.encode("utf-8"), expected.encode("utf-8"))
    )
    if not token_ok:
        raise Refusal("Approval token does not match this plan; nothing was changed")
    blocked_ids = {
        int(item["experiment_id"])
        for item in plan.get("blocked_running") or []
        if item.get("experiment_id") is not None
    }
    for change in changes:
        if int(change["experiment_id"]) in blocked_ids:
            raise Refusal(
                f"Experiment {change['experiment_id']} is blocked because it is running; "
                "apply never modifies it"
            )


def _preflight_drafts(
    api: AdminAPI, env_key: str, changes: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Confirm every target experiment is still in draft status before mutating."""
    preflight: List[Dict[str, Any]] = []
    for change in changes:
        experiment_id = int(change["experiment_id"])
        detail = _detail(api, env_key, experiment_id)
        status = str(detail.get("status"))
        if status != "created":
            raise Refusal(
                f"Experiment {experiment_id} is {status}; running experiments cannot change audience"
            )
        preflight.append(
            {
                "experiment_id": experiment_id,
                "detail": detail,
                "current_ids": audience_segment_ids(detail),
                "from_ids": sorted(int(item) for item in change.get("from_segment_ids") or []),
            }
        )
    return preflight


def _resolve_target_ids(
    plan: Dict[str, Any],
    changes: Sequence[Dict[str, Any]],
    preflight: Sequence[Dict[str, Any]],
    segment_ids: Dict[str, int],
) -> None:
    """Resolve target segment IDs and verify experiment audiences match the audit."""
    segment_specs = {spec.get("name"): spec for spec in plan.get("segments_to_create") or []}
    for change, item in zip(changes, preflight):
        target_spec = segment_specs.get(change.get("to_segment"))
        if target_spec is not None:
            target_id = segment_ids[_segment_spec_key(target_spec)]
        elif change.get("to_segment_ids"):
            target_id = int(change["to_segment_ids"][0])
        else:
            raise EngineError(f"Plan has no target segment for experiment {item['experiment_id']}")
        if item["current_ids"] not in (item["from_ids"], [target_id]):
            raise Refusal(
                f"Experiment {item['experiment_id']} audience changed since the audit; re-audit first"
            )
        item["target_id"] = target_id


def _retarget_rollout(
    api: AdminAPI,
    env_key: str,
    experiment_id: int,
    detail: Dict[str, Any],
    current_ids: Sequence[int],
    target_id: int,
    steps: List[Dict[str, Any]],
) -> None:
    """Disable rollout if needed and patch the draft experiment's audience."""
    if current_ids != [target_id]:
        _patch_and_verify(
            api, env_key, experiment_id, _rollout_payload(detail, current_ids, False), current_ids, False
        )
        steps.append({"experiment_id": experiment_id, "step": "disable_rollout", "verified": True})
        _patch_and_verify(
            api, env_key, experiment_id, _rollout_payload(detail, [target_id], False), [target_id], False
        )
        steps.append(
            {"experiment_id": experiment_id, "step": "patch_audience", "to": [target_id], "verified": True}
        )
    elif bool((detail.get("experiment_rollout") or {}).get("enabled")):
        _patch_and_verify(
            api, env_key, experiment_id, _rollout_payload(detail, [target_id], False), [target_id], False
        )
        steps.append({"experiment_id": experiment_id, "step": "disable_rollout", "verified": True})


def _apply_single_experiment(
    api: AdminAPI,
    config: Config,
    plan: Dict[str, Any],
    item: Dict[str, Any],
    applied: List[Dict[str, Any]],
    steps: List[Dict[str, Any]],
    out_dir: Optional[str],
    rollback_files: List[str],
) -> None:
    """Retarget, start, verify, and record rollback state for one draft experiment."""
    experiment_id = item["experiment_id"]
    target_id = item["target_id"]
    current_change: Dict[str, Any] = {
        "experiment_id": experiment_id,
        "from_segment_ids": item["from_ids"],
        "to_segment_ids": [target_id],
        "status": "applying",
        "verified": False,
    }
    applied.append(current_change)
    restore = (plan.get("restore") or {}).get(str(experiment_id))
    if not isinstance(restore, dict):
        raise EngineError(f"Plan has no rollback snapshot for {experiment_id}")
    _retarget_rollout(
        api, config.env_key, experiment_id, item["detail"], item["current_ids"], target_id, steps
    )
    running = _start_and_verify(api, config.env_key, experiment_id)
    if audience_segment_ids(running) != [target_id]:
        raise EngineError(f"Experiment {experiment_id} audience changed during start")
    steps.append({"experiment_id": experiment_id, "step": "start", "status": "running", "verified": True})
    current_change["status"] = "running"
    current_change["verified"] = True
    if out_dir:
        filename = f"restore-{experiment_id}.json"
        write_json(str(Path(out_dir) / filename), restore)
        rollback_files.append(filename)


def _noop_apply_result(plan: Dict[str, Any], approval: str) -> Dict[str, Any]:
    if approval != "noop":
        raise Refusal("No-op plan requires the explicit --approve noop confirmation")
    return {
        "product": "experiment-isolation",
        "environment": plan.get("environment"),
        "project_id": plan.get("project_id"),
        "scope": "planned_experiments",
        "approval_token_verified": True,
        "changes": [],
        "pass": True,
        "noop": True,
        "blocked_running": plan.get("blocked_running") or [],
        "rollback": [],
    }


def _apply_success_result(
    plan: Dict[str, Any],
    project_id: int,
    created_segments: List[Dict[str, Any]],
    reused_segments: List[Dict[str, Any]],
    applied: List[Dict[str, Any]],
    steps: List[Dict[str, Any]],
    rollback_files: List[str],
) -> Dict[str, Any]:
    rollback = ["python3 -m engine.cli rollback --apply apply.json --out rollback.json"]
    rollback.extend(
        f"delete segment by id {seg['id']} (name {seg['name']}) after rollback"
        for seg in created_segments
    )
    return {
        "product": "experiment-isolation",
        "environment": plan.get("environment"),
        "project_id": project_id,
        "scope": "planned_experiments",
        "approval_token_verified": True,
        "segments": {"created": created_segments, "reused": reused_segments},
        "changes": applied,
        "steps": steps,
        "pass": True,
        "blocked_running": plan.get("blocked_running") or [],
        "rollback": rollback,
        "restore": plan.get("restore") or {},
        "restore_files": rollback_files,
    }


def _execute_apply(
    api: AdminAPI,
    config: Config,
    plan: Dict[str, Any],
    project_id: int,
    changes: Sequence[Dict[str, Any]],
    preflight: Sequence[Dict[str, Any]],
    out_dir: Optional[str],
) -> Dict[str, Any]:
    created_segments: List[Dict[str, Any]] = []
    reused_segments: List[Dict[str, Any]] = []
    applied: List[Dict[str, Any]] = []
    steps: List[Dict[str, Any]] = []
    rollback_files: List[str] = []
    try:
        segment_ids, created_segments, reused_segments = ensure_segments(
            api, project_id, plan.get("segments_to_create") or [], created_out=created_segments
        )
        _resolve_target_ids(plan, changes, preflight, segment_ids)
        for item in preflight:
            _apply_single_experiment(
                api, config, plan, item, applied, steps, out_dir, rollback_files
            )
    except Exception as exc:
        failure_path = _write_failure(
            config, plan, out_dir, exc, created_segments, reused_segments, applied, steps
        )
        suffix = f" State saved to {failure_path}." if failure_path else ""
        started = sum(1 for step in steps if step.get("step") == "start" and step.get("verified"))
        raise EngineError(
            f"Apply failed after {started} started experiment(s).{suffix} Run the rollback command."
        ) from exc
    return _apply_success_result(
        plan, project_id, created_segments, reused_segments, applied, steps, rollback_files
    )


def run_apply(
    config: Config,
    plan: Dict[str, Any],
    approval: str,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a plan after exact token approval. Refuses running experiments."""
    if plan.get("feasible") is False:
        raise Refusal(
            str(plan.get("refusal") or "Plan is infeasible; no partial isolation is allowed")
        )
    changes = list(plan.get("audience_changes") or [])
    if not changes:
        return _noop_apply_result(plan, approval)
    _verify_approval(config, plan, approval, changes)
    api = AdminAPI(config)
    environment = api.environment()
    planned_env = plan.get("environment") or {}
    if planned_env.get("id") is not None and int(planned_env["id"]) != int(
        environment.get("id") or 0
    ):
        raise Refusal("Plan targets a different environment; nothing was changed")
    project_id = int(plan.get("project_id") or api.resolve_project_id())
    preflight = _preflight_drafts(api, config.env_key, changes)
    return _execute_apply(api, config, plan, project_id, changes, preflight, out_dir)
