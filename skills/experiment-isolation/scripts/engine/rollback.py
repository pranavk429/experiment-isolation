"""Direct-API rollback for an applied plan.

Flagsmith 2.291.0 rejects audience changes on a started or paused experiment.
The honest restore is therefore:
- created experiment: PATCH rollout disabled with the old audience, then restore;
- started/paused experiment: delete it and create a new DRAFT with the old
  audience (never claim an in-place rollback).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .api import AdminAPI, ApiError
from .config import Config
from .segments import audience_segment_ids
from .util import EngineError, sanitize_text


def _detail(api: AdminAPI, env_key: str, experiment_id: int) -> Optional[Dict[str, Any]]:
    try:
        detail = api.get(f"/api/v1/environments/{env_key}/experiments/{experiment_id}/")
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
        "multivariate_feature_state_values": restore.get("multivariate_feature_state_values")
        or [],
        "audience": {"match": "any", "segment_ids": [int(item) for item in audience_ids]},
    }
    api.patch(f"/api/v1/environments/{env_key}/experiments/{experiment_id}/rollout/", payload)
    detail = _detail(api, env_key, experiment_id)
    if detail is None:
        raise EngineError(f"Experiment {experiment_id} disappeared during restore")
    rollout = detail.get("experiment_rollout") or {}
    if audience_segment_ids(detail) != sorted(int(item) for item in audience_ids):
        raise EngineError(f"Experiment {experiment_id} audience did not restore")
    if bool(rollout.get("enabled")) != enabled:
        raise EngineError(f"Experiment {experiment_id} rollout state did not restore")


def _recreate_payload(detail: Dict[str, Any], restore: Dict[str, Any]) -> Tuple[Dict[str, Any], List[int]]:
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
    old_ids = [int(item) for item in (restore.get("audience") or {}).get("segment_ids") or []]
    base_name = str(detail.get("name") or "experiment").replace(" [rollback]", "").strip()
    payload = {
        "feature": int(feature_id),
        "name": f"{base_name} [rollback]"[:255],
        "hypothesis": detail.get("hypothesis") or "",
        "metrics": metrics,
        "experiment_rollout": {
            "enabled": bool(restore.get("enabled", True)),
            "rollout_percentage": restore.get("rollout_percentage", 100),
            "feature_state_value": restore.get("feature_state_value")
            or {"type": "string", "value": "control"},
            "multivariate_feature_state_values": restore.get("multivariate_feature_state_values")
            or [],
            "audience": {"match": "any", "segment_ids": old_ids},
        },
    }
    return payload, old_ids


def _recreate_draft(
    api: AdminAPI,
    env_key: str,
    detail: Dict[str, Any],
    restore: Dict[str, Any],
) -> int:
    payload, old_ids = _recreate_payload(detail, restore)
    created = api.post(f"/api/v1/environments/{env_key}/experiments/", payload)
    if not isinstance(created, dict) or created.get("id") is None:
        raise EngineError("Flagsmith did not return the recreated experiment id")
    new_id = int(created["id"])
    verified = _detail(api, env_key, new_id)
    if verified is None or verified.get("status") != "created":
        raise EngineError(f"Recreated experiment {new_id} is not a draft")
    if audience_segment_ids(verified) != sorted(old_ids):
        raise EngineError(f"Recreated experiment {new_id} audience did not verify")
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
            api.delete(f"/api/v1/projects/{project_id}/segments/{segment_id}/")
        except ApiError as exc:
            if exc.status != 404:
                raise
        deleted.append({"id": int(segment_id), "name": segment.get("name")})
    return deleted


def _restore_created_draft(
    api: AdminAPI,
    env_key: str,
    experiment_id: int,
    detail: Dict[str, Any],
    saved: Dict[str, Any],
) -> Dict[str, Any]:
    """Restore a still-draft experiment's original audience and rollout state in place."""
    saved_audience = [
        int(item) for item in (saved.get("audience") or {}).get("segment_ids") or []
    ]
    current_audience = audience_segment_ids(detail)
    if bool((detail.get("experiment_rollout") or {}).get("enabled")):
        _patch_rollout(api, env_key, experiment_id, saved, current_audience, False)
    _patch_rollout(api, env_key, experiment_id, saved, saved_audience, False)
    if bool(saved.get("enabled", True)):
        _patch_rollout(api, env_key, experiment_id, saved, saved_audience, True)
    return {
        "action": "restored",
        "live_restore": True,
        "requires_recreate": False,
        "verified": True,
    }


def _recreate_started_experiment(
    api: AdminAPI,
    env_key: str,
    experiment_id: int,
    detail: Dict[str, Any],
    saved: Dict[str, Any],
) -> Dict[str, Any]:
    """Pause/delete a started experiment and recreate a draft with the prior audience."""
    status = detail.get("status")
    if status == "running":
        api.post(f"/api/v1/environments/{env_key}/experiments/{experiment_id}/pause/", {})
    if status in ("running", "paused"):
        api.delete(f"/api/v1/environments/{env_key}/experiments/{experiment_id}/")
    new_id = _recreate_draft(api, env_key, detail, saved)
    return {
        "action": "recreated_draft",
        "live_restore": False,
        "requires_recreate": True,
        "new_experiment_id": new_id,
        "verified": True,
    }


def _rollback_single_experiment(
    api: AdminAPI,
    config: Config,
    change: Dict[str, Any],
    restore: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    """Roll back one applied experiment and sanitize any caught exception."""
    experiment_id = int(change["experiment_id"])
    saved = restore.get(str(experiment_id))
    entry: Dict[str, Any] = {
        "experiment_id": experiment_id,
        "from_segment_ids": change.get("to_segment_ids") or [],
        "to_segment_ids": change.get("from_segment_ids") or [],
    }
    try:
        if not isinstance(saved, dict):
            raise EngineError(f"Apply artifact has no restore state for {experiment_id}")
        detail = _detail(api, config.env_key, experiment_id)
        if detail is None:
            entry.update({"status_before": "missing", "action": "already_removed", "live_restore": False, "requires_recreate": False, "verified": True})
            return entry, True
        entry["status_before"] = detail.get("status")
        outcome = (
            _restore_created_draft(api, config.env_key, experiment_id, detail, saved)
            if detail.get("status") == "created"
            else _recreate_started_experiment(api, config.env_key, experiment_id, detail, saved)
        )
        entry.update(outcome)
        return entry, True
    except Exception as exc:
        entry.update(
            {
                "action": "failed",
                "live_restore": False,
                "requires_recreate": True,
                "verified": False,
                "error": sanitize_text(str(exc), config.admin_key, config.env_key),
            }
        )
        return entry, False


def _empty_rollback_result() -> Dict[str, Any]:
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
        return _empty_rollback_result()

    api = AdminAPI(config)
    project_id = int(
        apply_result.get("project_id") or (plan or {}).get("project_id") or api.resolve_project_id()
    )
    results: List[Dict[str, Any]] = []
    all_ok = True
    for change in reversed(changes):
        entry, ok = _rollback_single_experiment(api, config, change, restore)
        results.append(entry)
        all_ok = all_ok and ok

    deleted: List[Dict[str, Any]] = []
    if all_ok:
        try:
            deleted = _delete_segments(api, project_id, created_segments)
        except Exception as exc:
            all_ok = False
            results.append({"experiment_id": None, "action": "segment_delete_failed", "verified": False, "error": sanitize_text(str(exc), config.admin_key, config.env_key)})
    return {
        "product": "experiment-isolation",
        "scope": "planned_experiments",
        "experiments": results,
        "segments_deleted": deleted,
        "live_restore": bool(results) and all(item.get("live_restore") for item in results),
        "requires_recreate": any(item.get("requires_recreate") for item in results),
        "pass": all_ok,
    }
