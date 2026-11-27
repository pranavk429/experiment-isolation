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

METRIC_ID = 1
SEGMENT_ID = 4
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
    return api.get_all("/api/v1/projects/%s/features/" % project_id)


def _ensure_variant(api: AdminAPI, project_id: int, feature: Dict[str, Any], key: str) -> Dict[str, Any]:
    for option in feature.get("multivariate_options") or []:
        if option.get("key") == key:
            return option
    created = api.post(
        "/api/v1/projects/%s/features/%s/mv-options/" % (project_id, feature["id"]),
        {
            "feature": int(feature["id"]),
            "type": "unicode",
            "string_value": key,
            "default_percentage_allocation": 50,
            "key": key,
        },
    )
    if not isinstance(created, dict) or created.get("id") is None:
        raise EngineError("Could not add variant %s to %s" % (key, feature.get("name")))
    return created


def _ensure_feature(api: AdminAPI, project_id: int, spec: Dict[str, str]) -> Dict[str, Any]:
    feature: Optional[Dict[str, Any]] = None
    for item in _features(api, project_id):
        if item.get("name") == spec["name"]:
            feature = item
            break
    if feature is None:
        feature = api.post(
            "/api/v1/projects/%s/features/" % project_id,
            {
                "name": spec["name"],
                "initial_value": "control",
                "default_enabled": True,
            },
        )
        if not isinstance(feature, dict) or feature.get("id") is None:
            raise EngineError("Could not create feature %s" % spec["name"])
    if feature.get("is_archived"):
        raise EngineError("Feature %s is archived; unarchive it first" % spec["name"])
    variant = _ensure_variant(api, project_id, feature, spec["variant_key"])
    return {"feature": feature, "variant": variant}


def _experiments(api: AdminAPI, env_key: str) -> List[Dict[str, Any]]:
    return api.get_all("/api/v1/environments/%s/experiments/" % env_key)


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


def _ensure_experiment(
    api: AdminAPI,
    config: Config,
    spec: Dict[str, str],
    feature: Dict[str, Any],
    variant: Dict[str, Any],
    reset: bool = False,
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
                "Experiment %s for %s is %s; run seed --reset to delete it and "
                "recreate a draft" % (experiment_id, spec["name"], status)
            )
        if status in ("running", "paused", "created"):
            if status == "running":
                api.post(
                    "/api/v1/environments/%s/experiments/%s/pause/"
                    % (config.env_key, experiment_id),
                    {},
                )
            api.delete(
                "/api/v1/environments/%s/experiments/%s/"
                % (config.env_key, experiment_id)
            )
    payload = {
        "feature": int(feature["id"]),
        "name": spec["experiment"],
        "hypothesis": spec["hypothesis"],
        "metrics": [{"metric": METRIC_ID, "expected_direction": "increase"}],
        "experiment_rollout": {
            "enabled": True,
            "rollout_percentage": 100,
            "feature_state_value": {"type": "string", "value": "control"},
            "multivariate_feature_state_values": [
                {
                    "multivariate_feature_option": int(variant["id"]),
                    "percentage_allocation": 50,
                }
            ],
            "audience": {"match": "any", "segment_ids": [SEGMENT_ID]},
        },
    }
    created = api.post(
        "/api/v1/environments/%s/experiments/" % config.env_key, payload
    )
    if not isinstance(created, dict) or created.get("id") is None:
        raise EngineError("Could not create experiment %s" % spec["experiment"])
    detail = api.get(
        "/api/v1/environments/%s/experiments/%s/" % (config.env_key, created["id"])
    )
    if not isinstance(detail, dict):
        raise EngineError("Could not read back experiment %s" % created["id"])
    if detail.get("status") != "created":
        raise EngineError(
            "Experiment %s is %s, expected created" % (created["id"], detail.get("status"))
        )
    return {
        "id": int(created["id"]),
        "name": created.get("name"),
        "status": detail.get("status"),
        "created_now": True,
    }


def run_seed(
    config: Optional[Config] = None, count: int = 2, reset: bool = False
) -> Dict[str, Any]:
    """Create or reuse *count* demo features and draft collision experiments."""
    if count not in (2, 3):
        raise EngineError("--experiments must be 2 or 3")
    config = config or Config.load()
    api = AdminAPI(config)
    project_id = api.resolve_project_id()
    metrics = api.get_all("/api/v1/environments/%s/experiment-metrics/" % config.env_key)
    if not any(int(metric.get("id") or 0) == METRIC_ID for metric in metrics):
        raise EngineError("Metric %s not found" % METRIC_ID)
    segments = fetch_segments(api, project_id)
    segment = next(
        (item for item in segments if int(item.get("id") or 0) == SEGMENT_ID), None
    )
    if segment is None:
        raise EngineError("Audience segment %s (us_mobile) not found" % SEGMENT_ID)
    if segment.get("name") != "us_mobile":
        raise EngineError(
            "Segment %s is %r, expected us_mobile" % (SEGMENT_ID, segment.get("name"))
        )
    if segment_has_percentage_split(segment):
        raise EngineError("Audience segment %s contains PERCENTAGE_SPLIT" % SEGMENT_ID)

    specs = FEATURES[:count]
    existing_features = {str(item.get("name")): item for item in _features(api, project_id)}
    existing_experiments = _experiments(api, config.env_key)
    if reset:
        for spec in FEATURES:
            feature = existing_features.get(spec["name"])
            if feature is None:
                continue
            active = _active_for_feature(existing_experiments, int(feature["id"]))
            if active is None:
                continue
            status = str(active.get("status"))
            if status not in ("running", "paused", "created"):
                continue
            if status == "running":
                api.post(
                    "/api/v1/environments/%s/experiments/%s/pause/"
                    % (config.env_key, active["id"]),
                    {},
                )
            api.delete(
                "/api/v1/environments/%s/experiments/%s/"
                % (config.env_key, active["id"])
            )
    if not reset:
        for spec in FEATURES:
            feature = existing_features.get(spec["name"])
            if feature is None:
                continue
            active = _active_for_feature(existing_experiments, int(feature["id"]))
            if active is not None and str(active.get("status")) in ("running", "paused"):
                raise EngineError(
                    "Experiment %s for %s is %s; run seed --reset to delete it "
                    "and recreate a draft"
                    % (active["id"], spec["name"], active.get("status"))
                )

    feature_rows: List[Dict[str, Any]] = []
    experiment_rows: List[Dict[str, Any]] = []
    for spec in specs:
        ensured = _ensure_feature(api, project_id, spec)
        feature = ensured["feature"]
        variant = ensured["variant"]
        feature_rows.append(
            {
                "id": int(feature["id"]),
                "name": spec["name"],
                "variant": spec["variant_key"],
                "variant_id": int(variant["id"]),
            }
        )
        experiment_rows.append(
            _ensure_experiment(api, config, spec, feature, variant, reset=reset)
        )
    return {
        "product": "experiment-isolation-seed",
        "environment": config.public_environment(
            str(api.environment().get("name") or "unknown"),
            int(api.environment().get("id") or 0),
        ),
        "segment_id": SEGMENT_ID,
        "metric_id": METRIC_ID,
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
        sys.stderr.write("seed failed: %s\n" % exc)
        return 20
    statuses = ", ".join(
        "%s=%s" % (row["id"], row.get("status")) for row in result["experiments"]
    )
    sys.stderr.write(
        "seed: %d experiment(s) [%s]; started=%s -> stdout\n"
        % (len(result["experiments"]), statuses, result.get("started"))
    )
    sys.stdout.write(compact_json(result) + "\n")
    return 0
