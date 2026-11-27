"""Direct-API rollback for an applied plan.

Flagsmith 2.291.0 rejects audience changes on a started or paused experiment.
The honest restore is therefore:
- created experiment: PATCH rollout disabled with the old audience, then restore;
- started/paused experiment: delete it and create a new DRAFT with the old
  audience (never claim an in-place rollback).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .api import AdminAPI, ApiError
from .config import Config
from .segments import audience_segment_ids
from .util import EngineError


def _detail(api: AdminAPI, env_key: str, experiment_id: int) -> Optional[Dict[str, Any]]:
    try:
        detail = api.get(
            "/api/v1/environments/%s/experiments/%s/" % (env_key, experiment_id)
        )
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise
    return detail if isinstance(detail, dict) else None


def _patch_rollout(
    api: AdminAPI,
    env_key: str,
    experiment_id: int,
    restore: Dict[str, Any],
    audience_ids: Sequence[int],
    enabled: bool,
) -> None:
    payload = {
        "enabled": enabled,
        "rollout_percentage": restore.get("rollout_percentage", 100),
        "feature_state_value": restore.get("feature_state_value")
        or {"type": "string", "value": "control"},
        "multivariate_feature_state_values": restore.get(
            "multivariate_feature_state_values"
        )
        or [],
        "audience": {"match": "any", "segment_ids": [int(item) for item in audience_ids]},
    }
    api.patch(
        "/api/v1/environments/%s/experiments/%s/rollout/" % (env_key, experiment_id),
        payload,
    )
    detail = _detail(api, env_key, experiment_id)
    if detail is None:
        raise EngineError("Experiment %s disappeared during restore" % experiment_id)
    rollout = detail.get("experiment_rollout") or {}
    if audience_segment_ids(detail) != sorted(int(item) for item in audience_ids):
        raise EngineError("Experiment %s audience did not restore" % experiment_id)
    if bool(rollout.get("enabled")) != enabled:
        raise EngineError("Experiment %s rollout state did not restore" % experiment_id)


def _recreate_draft(
    api: AdminAPI,
    env_key: str,
    detail: Dict[str, Any],
    restore: Dict[str, Any],
) -> int:
    feature = detail.get("feature") or {}
    feature_id = feature.get("id")
    if feature_id is None:
        raise EngineError("Cannot recreate experiment: missing feature id")
    metrics = [
        {
            "metric": int(item["metric"]),
            "expected_direction": item.get("expected_direction") or "increase",
        }
        for item in detail.get("metrics") or []
        if item.get("metric") is not None
    ]
    audience = restore.get("audience") or {}
    old_ids = [int(item) for item in audience.get("segment_ids") or []]
    base_name = str(detail.get("name") or "experiment").replace(" [rollback]", "").strip()
    payload = {
        "feature": int(feature_id),
        "name": (base_name + " [rollback]")[:255],
        "hypothesis": detail.get("hypothesis") or "",
        "metrics": metrics,
        "experiment_rollout": {
            "enabled": bool(restore.get("enabled", True)),
            "rollout_percentage": restore.get("rollout_percentage", 100),
            "feature_state_value": restore.get("feature_state_value")
            or {"type": "string", "value": "control"},
            "multivariate_feature_state_values": restore.get(
                "multivariate_feature_state_values"
            )
            or [],
            "audience": {"match": "any", "segment_ids": old_ids},
        },
    }
    created = api.post("/api/v1/environments/%s/experiments/" % env_key, payload)
    if not isinstance(created, dict) or created.get("id") is None:
        raise EngineError("Flagsmith did not return the recreated experiment id")
    new_id = int(created["id"])
    verified = _detail(api, env_key, new_id)
    if verified is None or verified.get("status") != "created":
        raise EngineError("Recreated experiment %s is not a draft" % new_id)
    if audience_segment_ids(verified) != sorted(old_ids):
        raise EngineError("Recreated experiment %s audience did not verify" % new_id)
    return new_id


def _delete_segments(
    api: AdminAPI, project_id: int, created_segments: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    deleted: List[Dict[str, Any]] = []
    for segment in created_segments:
        segment_id = segment.get("id")
        if segment_id is None:
            continue
        try:
            api.delete("/api/v1/projects/%s/segments/%s/" % (project_id, segment_id))
            deleted.append({"id": int(segment_id), "name": segment.get("name")})
        except ApiError as exc:
            if exc.status != 404:
                raise
            deleted.append({"id": int(segment_id), "name": segment.get("name")})
    return deleted


def run_rollback(
    config: Config,
    apply_result: Dict[str, Any],
    plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Restore drafts where possible; recreate started experiments honestly."""
    changes = list(apply_result.get("changes") or [])
    restore = apply_result.get("restore") or (plan or {}).get("restore") or {}
    created_segments = (apply_result.get("segments") or {}).get("created") or []
    if not changes and not created_segments:
        return {
            "product": "experiment-isolation",
            "scope": "planned_experiments",
            "experiments": [],
            "segments_deleted": [],
            "live_restore": False,
            "requires_recreate": False,
            "pass": True,
            "noop": True,
        }

    api = AdminAPI(config)
    project_id = int(
        apply_result.get("project_id")
        or (plan or {}).get("project_id")
        or api.resolve_project_id()
    )
    results: List[Dict[str, Any]] = []
    all_ok = True
    for change in reversed(changes):
        experiment_id = int(change["experiment_id"])
        saved = restore.get(str(experiment_id))
        entry: Dict[str, Any] = {
            "experiment_id": experiment_id,
            "from_segment_ids": change.get("to_segment_ids") or [],
            "to_segment_ids": change.get("from_segment_ids") or [],
        }
        try:
            if not isinstance(saved, dict):
                raise EngineError("Apply artifact has no restore state for %s" % experiment_id)
            detail = _detail(api, config.env_key, experiment_id)
            if detail is None:
                entry.update(
                    {
                        "status_before": "missing",
                        "action": "already_removed",
                        "live_restore": False,
                        "requires_recreate": False,
                        "verified": True,
                    }
                )
                results.append(entry)
                continue
            entry["status_before"] = detail.get("status")
            if detail.get("status") == "created":
                saved_audience = [
                    int(item) for item in (saved.get("audience") or {}).get("segment_ids") or []
                ]
                current_audience = audience_segment_ids(detail)
                if bool((detail.get("experiment_rollout") or {}).get("enabled")):
                    _patch_rollout(
                        api,
                        config.env_key,
                        experiment_id,
                        saved,
                        current_audience,
                        False,
                    )
                _patch_rollout(
                    api, config.env_key, experiment_id, saved, saved_audience, False
                )
                if bool(saved.get("enabled", True)):
                    _patch_rollout(
                        api, config.env_key, experiment_id, saved, saved_audience, True
                    )
                entry.update(
                    {
                        "action": "restored",
                        "live_restore": True,
                        "requires_recreate": False,
                        "verified": True,
                    }
                )
            else:
                if detail.get("status") == "running":
                    api.post(
                        "/api/v1/environments/%s/experiments/%s/pause/"
                        % (config.env_key, experiment_id),
                        {},
                    )
                if detail.get("status") in ("running", "paused"):
                    api.delete(
                        "/api/v1/environments/%s/experiments/%s/"
                        % (config.env_key, experiment_id)
                    )
                new_id = _recreate_draft(api, config.env_key, detail, saved)
                entry.update(
                    {
                        "action": "recreated_draft",
                        "live_restore": False,
                        "requires_recreate": True,
                        "new_experiment_id": new_id,
                        "verified": True,
                    }
                )
            results.append(entry)
        except Exception as exc:
            all_ok = False
            entry.update(
                {
                    "action": "failed",
                    "live_restore": False,
                    "requires_recreate": True,
                    "verified": False,
                    "error": str(exc)[:400],
                }
            )
            results.append(entry)

    deleted: List[Dict[str, Any]] = []
    if all_ok:
        try:
            deleted = _delete_segments(api, project_id, created_segments)
        except Exception as exc:
            all_ok = False
            deleted = []
            results.append(
                {
                    "experiment_id": None,
                    "action": "segment_delete_failed",
                    "verified": False,
                    "error": str(exc)[:400],
                }
            )
    return {
        "product": "experiment-isolation",
        "scope": "planned_experiments",
        "experiments": results,
        "segments_deleted": deleted,
        "live_restore": bool(results) and all(item.get("live_restore") for item in results),
        "requires_recreate": any(item.get("requires_recreate") for item in results),
        "pass": all_ok,
    }
