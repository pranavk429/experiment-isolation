"""Idempotent demo seed: two draft experiments that collide on us_mobile.

Creates two multivariate features, one keyed 50% variant each, and two
experiments with status=created. Never starts them.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional, Sequence

from .api import AdminAPI
from .config import Config
from .segments import fetch_segments, segment_has_percentage_split
from .util import EngineError, compact_json

FEATURES: List[Dict[str, str]] = [
    {
        "name": "express_checkout",
        "variant_key": "one_click",
        "experiment": "Express checkout",
        "hypothesis": "A one-click express checkout button increases completed purchases.",
    },
    {
        "name": "discount_badge",
        "variant_key": "bold_sale",
        "experiment": "Discount badge",
        "hypothesis": "A bold discount badge on product cards increases completed purchases.",
    },
    {
        "name": "free_shipping",
        "variant_key": "free_ship",
        "experiment": "Free shipping",
        "hypothesis": "A free-shipping threshold message increases completed purchases.",
    },
]


def _features(api: AdminAPI, project_id: int) -> List[Dict[str, Any]]:
    return api.get_all(f"/api/v1/projects/{project_id}/features/")


def _ensure_variant(
    api: AdminAPI, project_id: int, feature: Dict[str, Any], key: str
) -> Dict[str, Any]:
    for option in feature.get("multivariate_options") or []:
        if option.get("key") == key or option.get("string_value") == key:
            return option
    created = api.post(
        f"/api/v1/projects/{project_id}/features/{feature['id']}/mv-options/",
        {
            "feature": int(feature["id"]),
            "type": "unicode",
            "string_value": key,
            "default_percentage_allocation": 50,
            "key": key,
        },
    )
    if not isinstance(created, dict) or created.get("id") is None:
        raise EngineError(f"Could not add variant {key} to {feature.get('name')}")
    return created


def ensure_feature_with_variant(
    api: AdminAPI, project_id: int, spec: Dict[str, str]
) -> Dict[str, Any]:
    """Ensure a feature and its 50% multivariate variant exist and are unarchived."""
    feature = next(
        (item for item in _features(api, project_id) if item.get("name") == spec["name"]),
        None,
    )
    if feature is None:
        payload: Dict[str, Any] = {
            "name": spec["name"],
            "initial_value": "control",
            "default_enabled": True,
        }
        if spec.get("description"):
            payload["description"] = spec["description"]
        feature = api.post(f"/api/v1/projects/{project_id}/features/", payload)
        if not isinstance(feature, dict) or feature.get("id") is None:
            raise EngineError(f"Could not create feature {spec['name']}")
    if feature.get("is_archived"):
        raise EngineError(f"Feature {spec['name']} is archived; unarchive it first")
    variant_key = spec.get("variant_key") or spec.get("variant") or ""
    variant = _ensure_variant(api, project_id, feature, variant_key)
    return {"feature": feature, "variant": variant}


def ensure_us_mobile_segment(api: AdminAPI, project_id: int) -> Dict[str, Any]:
    """Find or create the us_mobile segment and reject PERCENTAGE_SPLIT rules."""
    segments = fetch_segments(api, project_id)
    segment = next((item for item in segments if item.get("name") == "us_mobile"), None)
    if segment is None:
        segment = api.post(
            f"/api/v1/projects/{project_id}/segments/",
            {
                "name": "us_mobile",
                "project": project_id,
                "description": "Synthetic US mobile audience.",
                "rules": [
                    {
                        "type": "ALL",
                        "rules": [],
                        "conditions": [
                            {"operator": "EQUAL", "property": "country", "value": "US"},
                            {"operator": "EQUAL", "property": "platform", "value": "mobile"},
                        ],
                    }
                ],
            },
        )
        if not isinstance(segment, dict) or segment.get("id") is None:
            raise EngineError("Could not create audience segment us_mobile")
    if segment_has_percentage_split(segment):
        raise EngineError(
            f"Audience segment {segment.get('id')} contains PERCENTAGE_SPLIT"
        )
    return segment


def ensure_purchase_metric(api: AdminAPI, env_key: str) -> Dict[str, Any]:
    """Find or create the Purchase experiment metric in *env_key*."""
    metrics = api.get_all(f"/api/v1/environments/{env_key}/experiment-metrics/")
    metric = next((item for item in metrics if item.get("name") == "Purchase"), None)
    if metric is not None:
        return metric
    created = api.post(
        f"/api/v1/environments/{env_key}/experiment-metrics/",
        {
            "name": "Purchase",
            "description": "Checkout conversion for the isolation demo.",
            "definition": {"event": "purchase", "version": 1},
            "aggregation": "occurrence",
            "direction": "up",
        },
    )
    if not isinstance(created, dict) or created.get("id") is None:
        raise EngineError("Could not create metric Purchase")
    return created


def _experiments(api: AdminAPI, env_key: str) -> List[Dict[str, Any]]:
    return api.get_all(f"/api/v1/environments/{env_key}/experiments/")


def _active_for_feature(
    experiments: Sequence[Dict[str, Any]], feature_id: int
) -> Optional[Dict[str, Any]]:
    for experiment in experiments:
        experiment_feature = experiment.get("feature") or {}
        if (
            isinstance(experiment_feature, dict)
            and int(experiment_feature.get("id") or 0) == int(feature_id)
            and experiment.get("status") != "completed"
        ):
            return experiment
    return None


def _remove_experiment(api: AdminAPI, env_key: str, experiment_id: int, status: str) -> None:
    if status == "running":
        api.post(f"/api/v1/environments/{env_key}/experiments/{experiment_id}/pause/", {})
    if status in ("running", "paused", "created"):
        api.delete(f"/api/v1/environments/{env_key}/experiments/{experiment_id}/")


def _ensure_experiment(
    api: AdminAPI,
    config: Config,
    spec: Dict[str, str],
    feature: Dict[str, Any],
    variant: Dict[str, Any],
    reset: bool = False,
    metric_id: int = 1,
    segment_id: int = 4,
) -> Dict[str, Any]:
    active = _active_for_feature(_experiments(api, config.env_key), int(feature["id"]))
    if active is not None:
        status = str(active.get("status"))
        experiment_id = int(active["id"])
        if status == "created" and not reset:
            return {
                "id": experiment_id,
                "name": active.get("name"),
                "status": status,
                "created_now": False,
            }
        if status in ("running", "paused") and not reset:
            raise EngineError(
                f"Experiment {experiment_id} for {spec['name']} is {status}; "
                "run seed --reset to delete it and recreate a draft"
            )
        _remove_experiment(api, config.env_key, experiment_id, status)
    return _create_draft_experiment(api, config, spec, feature, variant, metric_id, segment_id)


def _create_draft_experiment(
    api: AdminAPI,
    config: Config,
    spec: Dict[str, str],
    feature: Dict[str, Any],
    variant: Dict[str, Any],
    metric_id: int,
    segment_id: int,
) -> Dict[str, Any]:
    payload = {
        "feature": int(feature["id"]),
        "name": spec["experiment"],
        "hypothesis": spec["hypothesis"],
        "metrics": [{"metric": metric_id, "expected_direction": "increase"}],
        "experiment_rollout": {
            "enabled": True,
            "rollout_percentage": 100,
            "feature_state_value": {"type": "string", "value": "control"},
            "multivariate_feature_state_values": [
                {"multivariate_feature_option": int(variant["id"]), "percentage_allocation": 50}
            ],
            "audience": {"match": "any", "segment_ids": [segment_id]},
        },
    }
    created = api.post(f"/api/v1/environments/{config.env_key}/experiments/", payload)
    if not isinstance(created, dict) or created.get("id") is None:
        raise EngineError(f"Could not create experiment {spec['experiment']}")
    detail = api.get(f"/api/v1/environments/{config.env_key}/experiments/{created['id']}/")
    if not isinstance(detail, dict):
        raise EngineError(f"Could not read back experiment {created['id']}")
    if detail.get("status") != "created":
        raise EngineError(f"Experiment {created['id']} is {detail.get('status')}, expected created")
    return {
        "id": int(created["id"]),
        "name": created.get("name"),
        "status": detail.get("status"),
        "created_now": True,
    }


def _reset_or_guard_existing(
    api: AdminAPI,
    config: Config,
    existing_features: Dict[str, Dict[str, Any]],
    existing_experiments: Sequence[Dict[str, Any]],
    reset: bool,
) -> None:
    for spec in FEATURES:
        feature = existing_features.get(spec["name"])
        if feature is None:
            continue
        active = _active_for_feature(existing_experiments, int(feature["id"]))
        if active is None:
            continue
        status = str(active.get("status"))
        if not reset:
            if status in ("running", "paused"):
                raise EngineError(
                    f"Experiment {active['id']} for {spec['name']} is {status}; "
                    "run seed --reset to delete it and recreate a draft"
                )
            continue
        _remove_experiment(api, config.env_key, int(active["id"]), status)


def run_seed(
    config: Optional[Config] = None, count: int = 2, reset: bool = False
) -> Dict[str, Any]:
    """Create or reuse *count* demo features and draft collision experiments."""
    if count not in (2, 3):
        raise EngineError("--experiments must be 2 or 3")
    config = config or Config.load()
    api = AdminAPI(config)
    project_id = api.resolve_project_id()
    metric_id = int(ensure_purchase_metric(api, config.env_key)["id"])
    segment_id = int(ensure_us_mobile_segment(api, project_id)["id"])
    existing_features = {str(item.get("name")): item for item in _features(api, project_id)}
    _reset_or_guard_existing(api, config, existing_features, _experiments(api, config.env_key), reset)

    feature_rows: List[Dict[str, Any]] = []
    experiment_rows: List[Dict[str, Any]] = []
    for spec in FEATURES[:count]:
        ensured = ensure_feature_with_variant(api, project_id, spec)
        feature, variant = ensured["feature"], ensured["variant"]
        feature_rows.append(
            {"id": int(feature["id"]), "name": spec["name"], "variant": spec["variant_key"], "variant_id": int(variant["id"])}
        )
        experiment_rows.append(
            _ensure_experiment(
                api, config, spec, feature, variant, reset=reset, metric_id=metric_id, segment_id=segment_id
            )
        )
    env_info = api.environment()
    return {
        "product": "experiment-isolation-seed",
        "environment": config.public_environment(
            str(env_info.get("name") or "unknown"), int(env_info.get("id") or 0)
        ),
        "segment_id": segment_id,
        "metric_id": metric_id,
        "features": feature_rows,
        "experiments": experiment_rows,
        "started": any(row.get("status") == "running" for row in experiment_rows),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry used by seed/demo_seed.py."""
    parser = argparse.ArgumentParser(description="Seed draft collision experiments.")
    parser.add_argument("--experiments", type=int, default=2, choices=(2, 3))
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_seed(count=args.experiments, reset=args.reset)
    except Exception as exc:
        sys.stderr.write(f"seed failed: {exc}\n")
        return 20
    statuses = ", ".join(
        f"{row['id']}={row.get('status')}" for row in result["experiments"]
    )
    sys.stderr.write(
        f"seed: {len(result['experiments'])} experiment(s) [{statuses}]; "
        f"started={result.get('started')} -> stdout\n"
    )
    sys.stdout.write(f"{compact_json(result)}\n")
    return 0
