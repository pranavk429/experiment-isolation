"""Shared pytest fixtures and in-memory Flagsmith FakeAPI for offline tests."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

from engine.api import ApiError
from engine.config import Config
from engine.plan import build_plan
from engine.util import EngineError

US_MOBILE: Dict[str, Any] = {
    "id": 4,
    "name": "us_mobile",
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
}

GB_MOBILE: Dict[str, Any] = {
    "id": 9,
    "name": "gb_mobile",
    "rules": [
        {
            "type": "ALL",
            "rules": [],
            "conditions": [
                {"operator": "EQUAL", "property": "country", "value": "GB"},
                {"operator": "EQUAL", "property": "platform", "value": "mobile"},
            ],
        }
    ],
}


def make_config(
    admin_key: str = "test-admin-key",
    env_key: str = "test-env-key",
    project: str = "1",
) -> Config:
    return Config(
        api_url="http://localhost:8000",
        admin_key=admin_key,
        env_key=env_key,
        project=project,
    )


def audience(*segment_ids: int) -> Dict[str, Any]:
    return {
        "match": "any",
        "segments": [
            {"id": segment_id, "name": f"segment-{segment_id}"}
            for segment_id in segment_ids
        ],
    }


def experiment(
    experiment_id: int,
    name: str,
    status: str = "created",
    segment_ids: Optional[List[int]] = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    return {
        "id": experiment_id,
        "name": name,
        "status": status,
        "feature": {"id": 100 + experiment_id, "name": f"feature_{experiment_id}"},
        "experiment_rollout": {
            "enabled": enabled,
            "rollout_percentage": 100.0,
            "feature_state_value": {"type": "string", "value": "control"},
            "multivariate_feature_state_values": [],
            "audience": audience(*(segment_ids or [])),
        },
    }


def segment(segment_id: int, name: str, operator: str, value: str) -> Dict[str, Any]:
    return {
        "id": segment_id,
        "name": name,
        "rules": [
            {
                "type": "ALL",
                "rules": [],
                "conditions": [
                    {
                        "operator": operator,
                        "property": "flagsmith_experiment_bucket",
                        "value": value,
                    }
                ],
            }
        ],
    }


class FakeAPI:
    """In-memory stand-in for the Flagsmith Admin API."""

    def __init__(
        self,
        experiments: Optional[List[Dict[str, Any]]] = None,
        segments: Optional[List[Dict[str, Any]]] = None,
        *,
        features: Optional[List[Dict[str, Any]]] = None,
        metrics: Optional[List[Dict[str, Any]]] = None,
        project_id: int = 1,
        environment_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.environment_data = dict(environment_data or {"id": 1, "name": "Development"})
        self.project_id = project_id
        self.experiments = {
            int(item["id"]): copy.deepcopy(item) for item in (experiments or [])
        }
        initial_segments = [copy.deepcopy(US_MOBILE)] if segments is None else segments
        self.segments = {int(item["id"]): copy.deepcopy(item) for item in initial_segments}
        self.features = {
            int(item["id"]): copy.deepcopy(item) for item in (features or [])
        }
        self.metrics = {
            int(item["id"]): copy.deepcopy(item) for item in (metrics or [])
        }
        self.next_segment_id = max(self.segments.keys() or [0]) + 1
        self.next_experiment_id = max(self.experiments.keys() or [0]) + 1
        self.next_feature_id = max(self.features.keys() or [100]) + 1
        self.next_metric_id = max(self.metrics.keys() or [0]) + 1
        self.next_option_id = 1000
        self.calls: List[str] = []
        self.fail_start_for: set = set()

    def environment(self) -> Dict[str, Any]:
        return dict(self.environment_data)

    def resolve_project_id(self) -> int:
        return self.project_id

    def get_all(self, path: str, limit: int = 500) -> List[Dict[str, Any]]:
        if "/experiment-metrics/" in path:
            return [copy.deepcopy(item) for item in self.metrics.values()][:limit]
        if "/segments/" in path:
            return [copy.deepcopy(item) for item in self.segments.values()][:limit]
        if "/features/" in path:
            return [copy.deepcopy(item) for item in self.features.values()][:limit]
        if "/experiments/" in path:
            return [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "status": item["status"],
                    "feature": copy.deepcopy(item["feature"]),
                }
                for item in self.experiments.values()
            ][:limit]
        if path.rstrip("/").endswith("/projects"):
            return [{"id": self.project_id, "name": "Test"}]
        raise EngineError(f"FakeAPI has no get_all for {path}")

    def get(self, path: str) -> Dict[str, Any]:
        if "/segments/" in path:
            segment_id = int(path.rstrip("/").rsplit("/", 1)[-1])
            if segment_id not in self.segments:
                raise ApiError(404, path, "not found")
            return copy.deepcopy(self.segments[segment_id])
        if "/experiments/" in path:
            experiment_id = int(path.rstrip("/").rsplit("/", 1)[-1])
            if experiment_id not in self.experiments:
                raise ApiError(404, path, "not found")
            return copy.deepcopy(self.experiments[experiment_id])
        if "/features/" in path:
            feature_id = int(path.rstrip("/").rsplit("/", 1)[-1])
            if feature_id not in self.features:
                raise ApiError(404, path, "not found")
            return copy.deepcopy(self.features[feature_id])
        if path.startswith("/api/v1/environments/") and path.rstrip("/").count("/") == 4:
            return dict(self.environment_data)
        raise EngineError(f"FakeAPI has no GET for {path}")

    def _experiment_id(self, path: str) -> int:
        return int(path.split("/experiments/", 1)[1].split("/", 1)[0])

    def patch(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(f"PATCH {path}")
        experiment_id = self._experiment_id(path)
        item = self.experiments[experiment_id]
        item["experiment_rollout"] = {
            "enabled": payload["enabled"],
            "rollout_percentage": payload["rollout_percentage"],
            "feature_state_value": payload["feature_state_value"],
            "multivariate_feature_state_values": payload[
                "multivariate_feature_state_values"
            ],
            "audience": audience(*payload["audience"].get("segment_ids", [])),
        }
        return copy.deepcopy(item)

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.calls.append(f"POST {path}")
        body = payload or {}
        if path.endswith("/start/"):
            experiment_id = self._experiment_id(path)
            if experiment_id in self.fail_start_for:
                raise EngineError("forced start failure")
            item = self.experiments[experiment_id]
            item["status"] = "running"
            item["experiment_rollout"]["enabled"] = True
            return copy.deepcopy(item)
        if path.endswith("/pause/"):
            item = self.experiments[self._experiment_id(path)]
            item["status"] = "paused"
            return copy.deepcopy(item)
        if path.endswith("/experiment-metrics/"):
            metric_id = self.next_metric_id
            self.next_metric_id += 1
            created = {"id": metric_id, **copy.deepcopy(body)}
            self.metrics[metric_id] = created
            return copy.deepcopy(created)
        if "/mv-options/" in path:
            feature_id = int(path.split("/features/", 1)[1].split("/", 1)[0])
            option_id = self.next_option_id
            self.next_option_id += 1
            option = {
                "id": option_id,
                "key": body.get("key"),
                "string_value": body.get("string_value"),
            }
            if feature_id in self.features:
                self.features[feature_id].setdefault("multivariate_options", []).append(option)
            return copy.deepcopy(option)
        if path.endswith("/features/"):
            feature_id = self.next_feature_id
            self.next_feature_id += 1
            feature = {
                "id": feature_id,
                "name": body["name"],
                "initial_value": body.get("initial_value", "control"),
                "default_enabled": body.get("default_enabled", True),
                "multivariate_options": [],
            }
            self.features[feature_id] = feature
            return copy.deepcopy(feature)
        if "/segments/" in path:
            created = {
                "id": self.next_segment_id,
                "name": body["name"],
                "rules": body["rules"],
            }
            self.next_segment_id += 1
            self.segments[created["id"]] = created
            return copy.deepcopy(created)
        if path.endswith("/experiments/") and "feature" in body:
            created_id = self.next_experiment_id
            self.next_experiment_id += 1
            rollout = copy.deepcopy(body["experiment_rollout"])
            rollout["audience"] = audience(*rollout.get("audience", {}).get("segment_ids", []))
            item = {
                "id": created_id,
                "name": body["name"],
                "hypothesis": body.get("hypothesis"),
                "status": "created",
                "feature": {"id": body["feature"], "name": f"feature_{body['feature']}"},
                "metrics": copy.deepcopy(body.get("metrics") or []),
                "experiment_rollout": rollout,
            }
            self.experiments[created_id] = item
            return copy.deepcopy(item)
        raise EngineError(f"FakeAPI has no POST for {path}")

    def delete(self, path: str) -> None:
        self.calls.append(f"DELETE {path}")
        if "/experiments/" in path:
            self.experiments.pop(self._experiment_id(path), None)
        elif "/segments/" in path:
            segment_id = int(path.rstrip("/").rsplit("/", 1)[-1])
            self.segments.pop(segment_id, None)


@pytest.fixture()
def bucket_segments() -> List[Dict[str, Any]]:
    return [
        copy.deepcopy(US_MOBILE),
        segment(7, "exp_bucket_a", "LESS_THAN", "50"),
        segment(8, "exp_bucket_b", "GREATER_THAN_INCLUSIVE", "50"),
    ]


def experiment_row(
    experiment_id: int,
    name: str,
    status: str = "created",
    segment_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    return {
        "id": experiment_id,
        "name": name,
        "feature": f"feature_{experiment_id}",
        "status": status,
        "audience_segment_ids": [] if segment_ids is None else list(segment_ids),
        "rollout_percentage": 100.0,
        "enrolled": 50,
        "basis": "projected" if status == "created" else "measured",
        "audience_has_percentage_split": False,
    }


def audit_report(experiments: List[Dict[str, Any]], jaccard_value: float = 1.0) -> Dict[str, Any]:
    return {
        "environment": {"id": 1, "name": "Development", "key_prefix": "test"},
        "project_id": 1,
        "sample_size": 100,
        "threshold": 0.05,
        "experiments": experiments,
        "overlaps": [
            {
                "a": 5,
                "b": 6,
                "shared": 100,
                "union": 100,
                "jaccard": jaccard_value,
                "a_rate": 1.0,
                "b_rate": 1.0,
                "verdict": "collision" if jaccard_value >= 0.05 else "clear",
            }
        ],
        "collisions": [[5, 6]] if jaccard_value >= 0.05 else [],
        "verdict": "collision" if jaccard_value >= 0.05 else "clear",
        "sample_traits": ["country", "platform", "flagsmith_experiment_bucket"],
    }


def audit_report_n(
    ids: List[int],
    jaccard_value: float = 1.0,
    segment_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    seg_ids = [4] if segment_ids is None else list(segment_ids)
    rows = [experiment_row(item, f"Draft {item}", segment_ids=seg_ids) for item in ids]
    overlaps = []
    for left_index in range(len(ids)):
        for right_index in range(left_index + 1, len(ids)):
            overlaps.append(
                {
                    "a": ids[left_index],
                    "b": ids[right_index],
                    "shared": 50,
                    "union": 50,
                    "jaccard": jaccard_value,
                    "a_rate": 0.5,
                    "b_rate": 0.5,
                    "verdict": "collision" if jaccard_value >= 0.05 else "clear",
                }
            )
    return {
        "environment": {"id": 1, "name": "Development", "key_prefix": "test"},
        "project_id": 1,
        "sample_size": 100,
        "threshold": 0.05,
        "experiments": rows,
        "overlaps": overlaps,
        "collisions": [
            [item["a"], item["b"]]
            for item in overlaps
            if item["verdict"] == "collision"
        ],
        "verdict": "collision" if jaccard_value >= 0.05 else "clear",
        "multi_exposed_rate": 0.5 if jaccard_value >= 0.05 else 0.0,
        "max_exposure_count": 2,
        "risk": "critical" if jaccard_value >= 0.05 else "none",
        "sample_traits": ["country", "platform", "flagsmith_experiment_bucket"],
    }


def make_plan(
    segments: Optional[List[Dict[str, Any]]] = None,
    *,
    draft_segment_ids: Optional[List[int]] = None,
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    seg_ids = [4] if draft_segment_ids is None else list(draft_segment_ids)
    report = audit_report(
        [
            experiment_row(5, "Draft A", segment_ids=seg_ids),
            experiment_row(6, "Draft B", segment_ids=seg_ids),
            experiment_row(2, "Running", status="running", segment_ids=seg_ids),
        ]
    )
    fake = FakeAPI(
        [
            experiment(5, "Draft A", segment_ids=seg_ids),
            experiment(6, "Draft B", segment_ids=seg_ids),
        ],
        segments,
    )
    cfg = config or make_config()
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        return build_plan(report, config=cfg)


def payloads_for(
    samples: List[Any],
    experiment_ids_by_identity: Optional[Dict[str, List[int]]] = None,
) -> Dict[str, Dict[str, Any]]:
    payloads: Dict[str, Dict[str, Any]] = {}
    for sample in samples:
        ids = (experiment_ids_by_identity or {}).get(sample.identifier, [])
        flags = [
            {"metadata": {"experiment": {"id": experiment_id, "in_experiment": True}}}
            for experiment_id in ids
        ]
        payloads[sample.identifier] = {
            "identifier": sample.identifier,
            "traits": [
                {"trait_key": key, "trait_value": value}
                for key, value in sample.traits.items()
            ],
            "flags": flags,
        }
    return payloads
