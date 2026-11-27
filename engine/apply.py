"""Approved application of a plan: disable rollout, change audience, start."""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .api import AdminAPI
from .config import Config
from .plan import approval_token
from .segments import audience_segment_ids, fetch_segments, segment_is_range
from .util import EngineError, Refusal, write_json


def _spec_range(spec: Dict[str, Any]) -> Tuple[int, int]:
    """Read a range from new-style lo/hi or the legacy single-bound schema."""
    if spec.get("lo") is not None and spec.get("hi") is not None:
        return int(spec["lo"]), int(spec["hi"])
    operator = str(spec.get("operator") or "").upper()
    value = str(spec.get("value"))
    try:
        number = int(value)
    except ValueError as exc:
        raise EngineError("Invalid segment value %r" % value) from exc
    if operator == "LESS_THAN":
        return 0, number - 1
    if operator == "GREATER_THAN_INCLUSIVE":
        return number, 99
    raise EngineError("Segment spec has no bucket range")


def _segment_spec_key(spec: Dict[str, Any]) -> str:
    lo, hi = _spec_range(spec)
    return "%s:%s" % (lo, hi)


def _validate_segment(segment: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    lo, hi = _spec_range(spec)
    return segment_is_range(segment, str(spec.get("trait")), lo, hi)


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
            {
                "operator": "GREATER_THAN_INCLUSIVE",
                "property": trait,
                "value": str(lo),
            }
        )
    conditions.append({"operator": "LESS_THAN", "property": trait, "value": str(hi + 1)})
    return conditions


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
        key = _segment_spec_key(spec)
        segment: Optional[Dict[str, Any]] = None
        if spec.get("id"):
            segment = api.get(
                "/api/v1/projects/%s/segments/%s/" % (project_id, int(spec["id"]))
            )
            if not isinstance(segment, dict) or not _validate_segment(segment, spec):
                raise EngineError(
                    "Planned segment %s no longer matches its trait rule" % spec.get("id")
                )
        if segment is None:
            for item in segments:
                if item.get("name") == spec.get("name"):
                    segment = item
                    break
            if segment is not None and not _validate_segment(segment, spec):
                raise EngineError(
                    "Segment name %s exists with different rules" % spec.get("name")
                )
        if segment is None:
            segment = api.post(
                "/api/v1/projects/%s/segments/" % project_id,
                {
                    "name": spec.get("name"),
                    "project": project_id,
                    "rules": [
                        {
                            "type": "ALL",
                            "rules": [],
                            "conditions": _segment_conditions(spec),
                        }
                    ],
                },
            )
            if not isinstance(segment, dict) or segment.get("id") is None:
                raise EngineError("Could not create segment %s" % spec.get("name"))
            created_entry = {"id": int(segment["id"]), "name": segment.get("name")}
            created.append(created_entry)
            if created_out is not None:
                created_out.append(created_entry)
            if not _validate_segment(segment, spec):
                raise EngineError("Created segment %s did not verify" % segment.get("id"))
            segments.append(segment)
        else:
            reused.append({"id": int(segment["id"]), "name": segment.get("name")})
        ids[key] = int(segment["id"])
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
    detail = api.get(
        "/api/v1/environments/%s/experiments/%s/" % (env_key, experiment_id)
    )
    if not isinstance(detail, dict):
        raise EngineError("Could not read experiment %s" % experiment_id)
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
        "/api/v1/environments/%s/experiments/%s/rollout/"
        % (env_key, experiment_id),
        payload,
    )
    detail = _detail(api, env_key, experiment_id)
    rollout = detail.get("experiment_rollout") or {}
    if bool(rollout.get("enabled")) != expected_enabled:
        raise EngineError(
            "Experiment %s rollout.enabled did not become %s"
            % (experiment_id, expected_enabled)
        )
    if audience_segment_ids(detail) != sorted(int(item) for item in expected_audience):
        raise EngineError("Experiment %s audience did not verify" % experiment_id)


def _start_and_verify(api: AdminAPI, env_key: str, experiment_id: int) -> Dict[str, Any]:
    api.post(
        "/api/v1/environments/%s/experiments/%s/start/" % (env_key, experiment_id),
        {},
    )
    detail = _detail(api, env_key, experiment_id)
    if detail.get("status") != "running":
        raise EngineError("Experiment %s did not reach running" % experiment_id)
    if not bool((detail.get("experiment_rollout") or {}).get("enabled")):
        raise EngineError("Experiment %s is running with rollout disabled" % experiment_id)
    return detail


def _expected_token(config: Config, plan: Dict[str, Any], changes: Sequence[Dict[str, Any]]) -> str:
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


def _sanitize(config: Config, text: str) -> str:
    clean = text.replace(config.admin_key, "<redacted>").replace(config.env_key, "<env>")
    return " ".join(clean.split())[:400]


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
        "error": _sanitize(config, str(error)),
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
        if approval != "noop":
            raise Refusal(
                "No-op plan requires the explicit --approve noop confirmation"
            )
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
                "Experiment %s is blocked because it is running; apply never modifies it"
                % change["experiment_id"]
            )

    api = AdminAPI(config)
    environment = api.environment()
    planned_environment = plan.get("environment") or {}
    if planned_environment.get("id") is not None and int(planned_environment["id"]) != int(
        environment.get("id") or 0
    ):
        raise Refusal("Plan targets a different environment; nothing was changed")
    project_id = int(plan.get("project_id") or api.resolve_project_id())

    preflight: List[Dict[str, Any]] = []
    for change in changes:
        experiment_id = int(change["experiment_id"])
        detail = _detail(api, config.env_key, experiment_id)
        status = str(detail.get("status"))
        if status != "created":
            raise Refusal(
                "Experiment %s is %s; running experiments cannot change audience"
                % (experiment_id, status)
            )
        current_ids = audience_segment_ids(detail)
        from_ids = sorted(int(item) for item in change.get("from_segment_ids") or [])
        preflight.append(
            {
                "experiment_id": experiment_id,
                "detail": detail,
                "current_ids": current_ids,
                "from_ids": from_ids,
            }
        )

    created_segments: List[Dict[str, Any]] = []
    reused_segments: List[Dict[str, Any]] = []
    applied: List[Dict[str, Any]] = []
    steps: List[Dict[str, Any]] = []
    rollback_files: List[str] = []
    current_change: Optional[Dict[str, Any]] = None
    try:
        segment_ids, created_segments, reused_segments = ensure_segments(
            api,
            project_id,
            plan.get("segments_to_create") or [],
            created_out=created_segments,
        )
        segment_specs = {
            spec.get("name"): spec for spec in plan.get("segments_to_create") or []
        }
        for change, item in zip(changes, preflight):
            target_spec = segment_specs.get(change.get("to_segment"))
            if target_spec is not None:
                target_id = segment_ids[_segment_spec_key(target_spec)]
            else:
                if not change.get("to_segment_ids"):
                    raise EngineError(
                        "Plan has no target segment for experiment %s"
                        % item["experiment_id"]
                    )
                target_id = int(change["to_segment_ids"][0])
            if item["current_ids"] not in (item["from_ids"], [target_id]):
                raise Refusal(
                    "Experiment %s audience changed since the audit; re-audit first"
                    % item["experiment_id"]
                )
            item["target_id"] = target_id

        current_change: Optional[Dict[str, Any]] = None
        for item in preflight:
            experiment_id = item["experiment_id"]
            detail = item["detail"]
            target_id = item["target_id"]
            current_change = {
                "experiment_id": experiment_id,
                "from_segment_ids": item["from_ids"],
                "to_segment_ids": [target_id],
                "status": "applying",
                "verified": False,
            }
            restore = (plan.get("restore") or {}).get(str(experiment_id))
            if not isinstance(restore, dict):
                raise EngineError("Plan has no rollback snapshot for %s" % experiment_id)
            current_ids = item["current_ids"]
            if current_ids != [target_id]:
                disabled_current = _rollout_payload(detail, current_ids, False)
                _patch_and_verify(
                    api, config.env_key, experiment_id, disabled_current, current_ids, False
                )
                steps.append(
                    {"experiment_id": experiment_id, "step": "disable_rollout", "verified": True}
                )
                disabled_target = _rollout_payload(detail, [target_id], False)
                _patch_and_verify(
                    api, config.env_key, experiment_id, disabled_target, [target_id], False
                )
                steps.append(
                    {
                        "experiment_id": experiment_id,
                        "step": "patch_audience",
                        "to": [target_id],
                        "verified": True,
                    }
                )
            elif bool((detail.get("experiment_rollout") or {}).get("enabled")):
                disabled_target = _rollout_payload(detail, [target_id], False)
                _patch_and_verify(
                    api, config.env_key, experiment_id, disabled_target, [target_id], False
                )
                steps.append(
                    {"experiment_id": experiment_id, "step": "disable_rollout", "verified": True}
                )
            running = _start_and_verify(api, config.env_key, experiment_id)
            if audience_segment_ids(running) != [target_id]:
                raise EngineError(
                    "Experiment %s audience changed during start" % experiment_id
                )
            steps.append(
                {
                    "experiment_id": experiment_id,
                    "step": "start",
                    "status": "running",
                    "verified": True,
                }
            )
            current_change["status"] = "running"
            current_change["verified"] = True
            applied.append(current_change)
            current_change = None
            if out_dir:
                filename = "restore-%s.json" % experiment_id
                write_json(str(Path(out_dir) / filename), restore)
                rollback_files.append(filename)
    except Exception as exc:
        if current_change is not None and current_change not in applied:
            applied.append(current_change)
        failure_path = _write_failure(
            config,
            plan,
            out_dir,
            exc,
            created_segments,
            reused_segments,
            applied,
            steps,
        )
        suffix = " State saved to %s." % failure_path if failure_path else ""
        started = sum(
            1
            for step in steps
            if step.get("step") == "start" and step.get("verified") is True
        )
        raise EngineError(
            "Apply failed after %d started experiment(s).%s Run the rollback command."
            % (started, suffix)
        ) from exc

    rollback = ["python3 -m engine.cli rollback --apply apply.json --out rollback.json"]
    for segment in created_segments:
        rollback.append(
            "delete segment by id %s (name %s) after rollback"
            % (segment["id"], segment["name"])
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
