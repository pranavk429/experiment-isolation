"""Offline tests for the Experiment Isolation engine.

No network calls: the Flagsmith API is replaced with an in-memory fake.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

from engine.api import ApiError
from engine.apply import run_apply
from engine.audit import run_audit
from engine.config import Config, load_env_file
from engine.plan import approval_token, build_plan
from engine.receipt import build_receipt
from engine.sampling import (
    build_sample,
    bucket_for,
    enrollment_by_experiment,
    jaccard,
    traits_match,
)
from engine.segments import (
    audience_segment_ids,
    find_bucket_segment,
    segment_has_percentage_split,
    segment_is_bucket_range,
    segment_matches,
)
from engine.util import EngineError, Refusal, compact_json, estimate_tokens
from engine.verify import run_verify


def make_config() -> Config:
    return Config(
        api_url="http://localhost:8000",
        admin_key="test-admin-key",
        env_key="test-env-key",
        project="1",
    )


def audience(*segment_ids: int) -> Dict[str, Any]:
    return {
        "match": "any",
        "segments": [
            {"id": segment_id, "name": "segment-%s" % segment_id}
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
        "feature": {"id": 100 + experiment_id, "name": "feature_%s" % experiment_id},
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


US_MOBILE = {
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


class FakeAPI:
    """Tiny in-memory stand-in for the admin API."""

    def __init__(
        self,
        experiments: List[Dict[str, Any]],
        segments: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.environment_data = {"id": 1, "name": "Development"}
        self.experiments = {int(item["id"]): copy.deepcopy(item) for item in experiments}
        self.segments = {
            int(item["id"]): copy.deepcopy(item) for item in (segments or [US_MOBILE])
        }
        self.next_segment_id = max(self.segments.keys() or [0]) + 1
        self.next_experiment_id = max(self.experiments.keys() or [0]) + 1
        self.calls: List[str] = []
        self.fail_start_for: set = set()

    def environment(self) -> Dict[str, Any]:
        return dict(self.environment_data)

    def resolve_project_id(self) -> int:
        return 1

    def get_all(self, path: str, limit: int = 500) -> List[Dict[str, Any]]:
        if "/segments/" in path:
            return [copy.deepcopy(item) for item in self.segments.values()]
        if "/experiments/" in path:
            return [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "status": item["status"],
                    "feature": item["feature"],
                }
                for item in self.experiments.values()
            ]
        if path.rstrip("/").endswith("/projects"):
            return [{"id": 1, "name": "Test"}]
        raise EngineError("FakeAPI has no get_all for %s" % path)

    def get(self, path: str) -> Dict[str, Any]:
        if path == "/api/v1/environments/test-env-key/":
            return dict(self.environment_data)
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
        raise EngineError("FakeAPI has no GET for %s" % path)

    def _experiment_id(self, path: str) -> int:
        return int(path.split("/experiments/", 1)[1].split("/", 1)[0])

    def patch(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append("PATCH " + path)
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
        self.calls.append("POST " + path)
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
        if "/segments/" in path:
            created = {
                "id": self.next_segment_id,
                "name": payload["name"],
                "rules": payload["rules"],
            }
            self.next_segment_id += 1
            self.segments[created["id"]] = created
            return copy.deepcopy(created)
        if path.endswith("/experiments/") and payload and "feature" in payload:
            created_id = self.next_experiment_id
            self.next_experiment_id += 1
            rollout = copy.deepcopy(payload["experiment_rollout"])
            rollout["audience"] = audience(*rollout.get("audience", {}).get("segment_ids", []))
            item = {
                "id": created_id,
                "name": payload["name"],
                "hypothesis": payload.get("hypothesis"),
                "status": "created",
                "feature": {"id": payload["feature"], "name": "feature"},
                "metrics": payload.get("metrics") or [],
                "experiment_rollout": rollout,
            }
            self.experiments[created_id] = item
            return copy.deepcopy(item)
        raise EngineError("FakeAPI has no POST for %s" % path)

    def delete(self, path: str) -> None:
        self.calls.append("DELETE " + path)
        if "/experiments/" in path:
            self.experiments.pop(self._experiment_id(path), None)
        elif "/segments/" in path:
            segment_id = int(path.rstrip("/").rsplit("/", 1)[-1])
            self.segments.pop(segment_id, None)


@pytest.fixture()
def bucket_segments() -> List[Dict[str, Any]]:
    return [
        US_MOBILE,
        segment(7, "exp_bucket_a", "LESS_THAN", "50"),
        segment(8, "exp_bucket_b", "GREATER_THAN_INCLUSIVE", "50"),
    ]


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


def experiment_row(
    experiment_id: int,
    name: str,
    status: str = "created",
    segment_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    return {
        "id": experiment_id,
        "name": name,
        "feature": "feature_%s" % experiment_id,
        "status": status,
        "audience_segment_ids": segment_ids or [],
        "rollout_percentage": 100.0,
        "enrolled": 50,
        "basis": "projected" if status == "created" else "measured",
        "audience_has_percentage_split": False,
    }


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def test_bucket_is_stable_and_in_range() -> None:
    assert bucket_for("iso_0001") == bucket_for("iso_0001")
    for index in range(1, 200):
        assert 0 <= bucket_for("iso_%04d" % index) <= 99


def test_sample_matrix_is_deterministic() -> None:
    first = build_sample(100)
    second = build_sample(100)
    assert [(item.identifier, item.traits) for item in first] == [
        (item.identifier, item.traits) for item in second
    ]
    countries = [item.traits["country"] for item in first]
    platforms = [item.traits["platform"] for item in first]
    assert countries.count("US") == 70
    assert countries.count("GB") == 30
    assert platforms.count("mobile") == 80
    assert platforms.count("desktop") == 20


def test_jaccard() -> None:
    assert jaccard({"a", "b"}, {"b", "c"}) == (1, 3, 1 / 3)
    assert jaccard(set(), set()) == (0, 0, 0.0)


def test_traits_match_accepts_string_and_int_values() -> None:
    payload = {
        "traits": [
            {"trait_key": "country", "trait_value": "US"},
            {"trait_key": "flagsmith_experiment_bucket", "trait_value": 10},
        ]
    }
    assert traits_match(payload, {"country": "US", "flagsmith_experiment_bucket": "10"})
    assert not traits_match(payload, {"country": "GB"})


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


def test_us_mobile_segment_matches(bucket_segments: List[Dict[str, Any]]) -> None:
    us_mobile = bucket_segments[0]
    assert segment_matches(us_mobile, {"country": "US", "platform": "mobile"})
    assert not segment_matches(us_mobile, {"country": "US", "platform": "desktop"})
    assert not segment_matches(us_mobile, {"country": "GB", "platform": "mobile"})


def test_bucket_segments_are_disjoint(bucket_segments: List[Dict[str, Any]]) -> None:
    low = bucket_segments[1]
    high = bucket_segments[2]
    assert segment_matches(low, {"flagsmith_experiment_bucket": 0})
    assert segment_matches(low, {"flagsmith_experiment_bucket": 49})
    assert not segment_matches(low, {"flagsmith_experiment_bucket": 50})
    assert segment_matches(high, {"flagsmith_experiment_bucket": 50})
    assert segment_matches(high, {"flagsmith_experiment_bucket": 99})
    assert not segment_matches(high, {"flagsmith_experiment_bucket": 49})


def test_percentage_split_is_detected() -> None:
    risky = {
        "id": 2,
        "name": "half_users",
        "rules": [
            {
                "type": "ALL",
                "rules": [],
                "conditions": [
                    {"operator": "PERCENTAGE_SPLIT", "property": "$.identity.key", "value": "50"}
                ],
            }
        ],
    }
    assert segment_has_percentage_split(risky)
    assert not segment_is_bucket_range(risky, "flagsmith_experiment_bucket", "LESS_THAN", "50")


def test_find_bucket_segment_prefers_existing(bucket_segments: List[Dict[str, Any]]) -> None:
    found = find_bucket_segment(bucket_segments, "flagsmith_experiment_bucket", "LESS_THAN", "50")
    assert found is not None and found["id"] == 7
    assert (
        find_bucket_segment(
            bucket_segments, "flagsmith_experiment_bucket", "GREATER_THAN", "50"
        )
        is None
    )


def test_audience_ids_from_detail() -> None:
    assert audience_segment_ids(experiment(5, "A", segment_ids=[4])) == [4]
    assert audience_segment_ids(experiment(5, "A")) == []


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def payloads_for(samples, experiment_ids_by_identity=None):
    payloads = {}
    for sample in samples:
        flags = []
        ids = (experiment_ids_by_identity or {}).get(sample.identifier, [])
        for experiment_id in ids:
            flags.append(
                {
                    "metadata": {
                        "experiment": {"id": experiment_id, "in_experiment": True}
                    }
                }
            )
        payloads[sample.identifier] = {
            "identifier": sample.identifier,
            "traits": [
                {"trait_key": key, "trait_value": value}
                for key, value in sample.traits.items()
            ],
            "flags": flags,
        }
    return payloads


def test_run_audit_projects_created_and_measures_running(bucket_segments) -> None:
    experiments = [
        experiment(2, "Running", status="running", segment_ids=[4]),
        experiment(5, "Draft A", segment_ids=[4]),
        experiment(6, "Draft B", segment_ids=[4]),
    ]
    fake = FakeAPI(experiments, bucket_segments)
    samples = build_sample(10)
    payloads = payloads_for(
        samples,
        {
            sample.identifier: [2]
            for sample in samples
            if sample.traits["country"] == "US" and sample.traits["platform"] == "mobile"
        },
    )
    config = make_config()
    with mock.patch("engine.audit.AdminAPI", return_value=fake), mock.patch(
        "engine.audit.persist_sample", return_value=payloads
    ):
        report = run_audit(config, samples=10, threshold=0.05)
    assert report["sample_size"] == 10
    assert len(report["experiments"]) == 3
    drafts = [item for item in report["experiments"] if item["status"] == "created"]
    assert all(item["basis"] == "projected" for item in drafts)
    assert all(item["enrolled"] == 5 for item in drafts)
    pair = [item for item in report["overlaps"] if {item["a"], item["b"]} == {5, 6}][0]
    assert pair["jaccard"] == 1.0
    assert report["verdict"] == "collision"


def test_run_audit_refuses_bad_threshold() -> None:
    with pytest.raises(EngineError):
        run_audit(make_config(), samples=10, threshold=2.0)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def test_plan_isolates_created_pair(bucket_segments) -> None:
    rows = [
        experiment_row(5, "Draft A", segment_ids=[4]),
        experiment_row(6, "Draft B", segment_ids=[4]),
        experiment_row(2, "Running", status="running", segment_ids=[4]),
    ]
    report = audit_report(rows)
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments,
    )
    config = make_config()
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=config)
    assert plan["approval_token"].startswith("iso-")
    assert len(plan["approval_token"]) == 12
    assert plan["before_jaccard"] == 1.0
    assert any(
        "a paused experiment cannot change audience" in item for item in plan["notes"]
    )
    assert not any("pause or recreate" in item for item in plan["notes"])
    assert plan["segments_to_create"][0]["id"] == 7
    assert plan["segments_to_create"][1]["id"] == 8
    assert plan["audience_changes"][0]["to_segment_ids"] == [7]
    assert plan["audience_changes"][1]["to_segment_ids"] == [8]
    assert plan["unchanged_running"] == [2]
    assert set(plan["restore"]) == {"5", "6"}
    assert plan["rollback"] == [
        "python3 -m engine.cli rollback --apply apply.json --out rollback.json"
    ]
    assert not any("flagsmith api" in item for item in plan["rollback"])


def test_plan_creates_segments_when_missing() -> None:
    report = audit_report(
        [experiment_row(5, "Draft A", segment_ids=[4]), experiment_row(6, "Draft B", segment_ids=[4])]
    )
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        [US_MOBILE],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    assert plan["segments_to_create"][0]["existing"] is False
    assert plan["segments_to_create"][0]["id"] is None
    assert plan["segments_to_create"][0]["name"] == "exp_iso_0_49"
    assert plan["audience_changes"][0]["to_segment_ids"] == []
    assert plan["audience_changes"][0]["to_segment"] == "exp_iso_0_49"


def test_plan_noop_when_drafts_do_not_collide() -> None:
    report = audit_report(
        [experiment_row(5, "Draft A", segment_ids=[4]), experiment_row(6, "Draft B", segment_ids=[4])],
        jaccard_value=0.0,
    )
    plan = build_plan(report)
    assert plan["audience_changes"] == []
    assert plan["approval_token"] is None
    assert plan["before_jaccard"] == 0.0


def test_plan_refuses_percentage_split_audience() -> None:
    rows = [
        experiment_row(5, "Draft A", segment_ids=[4]),
        experiment_row(6, "Draft B", segment_ids=[4]),
    ]
    rows[0]["audience_has_percentage_split"] = True
    with pytest.raises(Refusal):
        build_plan(audit_report(rows))


def test_approval_token_is_deterministic() -> None:
    segments = [
        {"name": "a", "operator": "LESS_THAN", "value": "50"},
        {"name": "b", "operator": "GREATER_THAN_INCLUSIVE", "value": "50"},
    ]
    changes = [{"experiment_id": 5, "from_segment_ids": [4], "to_segment_ids": [7]}]
    first = approval_token(1, 0.05, segments, changes)
    second = approval_token(1, 0.05, segments, changes)
    assert first == second
    assert first != approval_token(2, 0.05, segments, changes)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def make_plan(bucket_segments) -> Dict[str, Any]:
    report = audit_report(
        [
            experiment_row(5, "Draft A", segment_ids=[4]),
            experiment_row(6, "Draft B", segment_ids=[4]),
            experiment_row(2, "Running", status="running", segment_ids=[4]),
        ]
    )
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments,
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        return build_plan(report, config=make_config())


def test_apply_requires_exact_token(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments,
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(Refusal):
            run_apply(make_config(), plan, "iso-wrong")
    assert fake.calls == []


def test_apply_refuses_running_experiment(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", status="running", segment_ids=[4]), experiment(6, "Draft B")],
        bucket_segments,
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(Refusal):
            run_apply(make_config(), plan, plan["approval_token"])
    assert not any(call.startswith("PATCH") for call in fake.calls)


def test_apply_starts_both_and_writes_restore_files(bucket_segments, tmp_path: Path) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments,
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        result = run_apply(
            make_config(), plan, plan["approval_token"], out_dir=str(tmp_path)
        )
    assert result["pass"] is True
    assert fake.experiments[5]["status"] == "running"
    assert fake.experiments[6]["status"] == "running"
    assert audience_segment_ids(fake.experiments[5]) == [7]
    assert audience_segment_ids(fake.experiments[6]) == [8]
    assert (tmp_path / "restore-5.json").is_file()
    assert (tmp_path / "restore-6.json").is_file()
    assert result["segments"]["created"] == []
    assert len(result["restore_files"]) == 2
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(Refusal):
            run_apply(make_config(), plan, plan["approval_token"])


def test_apply_creates_segments_when_missing(bucket_segments) -> None:
    # Build a plan whose stated segment ids do not exist.
    plan = make_plan(bucket_segments)
    plan["segments_to_create"] = [
        {
            "name": "exp_iso_0_49",
            "trait": "flagsmith_experiment_bucket",
            "operator": "LESS_THAN",
            "value": "50",
            "id": None,
            "existing": False,
        },
        {
            "name": "exp_iso_50_99",
            "trait": "flagsmith_experiment_bucket",
            "operator": "GREATER_THAN_INCLUSIVE",
            "value": "50",
            "id": None,
            "existing": False,
        },
    ]
    for change, name in zip(plan["audience_changes"], ("exp_iso_0_49", "exp_iso_50_99")):
        change["to_segment_ids"] = []
        change["to_segment"] = name
    plan["approval_token"] = approval_token(
        plan["environment"]["id"],
        plan["threshold"],
        plan["segments_to_create"],
        plan["audience_changes"],
        project_id=plan["project_id"],
        restore=plan["restore"],
        secret=make_config().admin_key,
        environment_name=plan["environment"]["name"],
    )
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        [US_MOBILE],
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        result = run_apply(make_config(), plan, plan["approval_token"])
    assert result["pass"] is True
    assert len(result["segments"]["created"]) == 2
    assert len(fake.calls) > 0


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def test_verify_zero_overlap_and_running(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [
            experiment(5, "Draft A", status="running", segment_ids=[7]),
            experiment(6, "Draft B", status="running", segment_ids=[8]),
        ],
        bucket_segments,
    )
    samples = build_sample(20)
    payloads = payloads_for(
        samples,
        {
            sample.identifier: [5 if sample.bucket < 50 else 6]
            for sample in samples
        },
    )
    with mock.patch("engine.verify.AdminAPI", return_value=fake), mock.patch(
        "engine.verify.persist_sample", return_value=payloads
    ):
        result = run_verify(make_config(), plan, samples=20)
    assert result["after_jaccard"] == 0.0
    assert result["pass"] is True
    assert result["overlaps"][0]["verdict"] == "isolated"


def test_verify_detects_residual_overlap(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [
            experiment(5, "Draft A", status="running", segment_ids=[7]),
            experiment(6, "Draft B", status="running", segment_ids=[8]),
        ],
        bucket_segments,
    )
    samples = build_sample(20)
    payloads = payloads_for(
        samples, {sample.identifier: [5, 6] for sample in samples}
    )
    with mock.patch("engine.verify.AdminAPI", return_value=fake), mock.patch(
        "engine.verify.persist_sample", return_value=payloads
    ):
        result = run_verify(make_config(), plan, samples=20)
    assert result["after_jaccard"] == 1.0
    assert result["pass"] is False


def test_verify_fails_if_audience_not_applied(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [
            experiment(5, "Draft A", status="running", segment_ids=[4]),
            experiment(6, "Draft B", status="running", segment_ids=[8]),
        ],
        bucket_segments,
    )
    samples = build_sample(10)
    payloads = payloads_for(samples, {sample.identifier: [] for sample in samples})
    with mock.patch("engine.verify.AdminAPI", return_value=fake), mock.patch(
        "engine.verify.persist_sample", return_value=payloads
    ):
        result = run_verify(make_config(), plan, samples=10)
    assert result["pass"] is False


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def test_receipt_is_compact_and_has_rollback(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    report = audit_report(
        [
            experiment_row(5, "Draft A", segment_ids=[4]),
            experiment_row(6, "Draft B", segment_ids=[4]),
        ]
    )
    verify = {
        "sample_size": 100,
        "before_jaccard": 1.0,
        "after_jaccard": 0.0,
        "pass": True,
        "overlaps": [],
    }
    receipt = build_receipt(report, plan, verify)
    assert receipt["pass"] is True
    assert receipt["changes"] == 4
    assert receipt["before"]["verdict"] == "collision"
    assert receipt["after"]["verdict"] == "isolated"
    assert receipt["rollback"]
    assert len(compact_json(receipt)) < 500
    assert estimate_tokens(receipt) < 125
    assert set(receipt["token_count"]) == {"audit", "plan", "apply", "verify", "receipt"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_load_env_file_does_not_override(tmp_path: Path) -> None:
    env_file = tmp_path / "flagsmith.env"
    env_file.write_text(
        "export FLAGSMITH_API_URL=http://localhost:8000\n"
        "export FLAGSMITH_PROJECT=Readiness Lab\n",
        encoding="utf-8",
    )
    with mock.patch.dict(os.environ, {"FLAGSMITH_PROJECT": "keep-me"}, clear=True):
        load_env_file(env_file)
        assert os.environ["FLAGSMITH_PROJECT"] == "keep-me"
        assert os.environ["FLAGSMITH_API_URL"] == "http://localhost:8000"


def test_config_repr_hides_secrets() -> None:
    config = make_config()
    assert "test-admin-key" not in repr(config)
    assert "test-env-key" not in repr(config)


# ---------------------------------------------------------------------------
# N-way isolation and traffic-aware feasibility
# ---------------------------------------------------------------------------


def audit_report_n(ids: List[int], jaccard_value: float = 1.0) -> Dict[str, Any]:
    rows = [experiment_row(item, "Draft %s" % item, segment_ids=[4]) for item in ids]
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


def test_audit_reports_multi_exposure_and_risk(bucket_segments) -> None:
    experiments = [
        experiment(2, "Running", status="running", segment_ids=[4]),
        experiment(5, "Draft A", segment_ids=[4]),
        experiment(6, "Draft B", segment_ids=[4]),
    ]
    fake = FakeAPI(experiments, bucket_segments)
    samples = build_sample(10)
    payloads = payloads_for(
        samples,
        {sample.identifier: [2, 5, 6] for sample in samples},
    )
    with mock.patch("engine.audit.AdminAPI", return_value=fake), mock.patch(
        "engine.audit.persist_sample", return_value=payloads
    ):
        report = run_audit(make_config(), samples=10, threshold=0.05)
    assert report["multi_exposed_rate"] == 0.5
    assert report["max_exposure_count"] == 3
    assert report["risk"] == "critical"


def test_plan_allocates_three_disjoint_ranges(bucket_segments) -> None:
    report = audit_report_n([5, 6, 7])
    fake = FakeAPI(
        [
            experiment(5, "Draft A", segment_ids=[4]),
            experiment(6, "Draft B", segment_ids=[4]),
            experiment(7, "Draft C", segment_ids=[4]),
        ],
        bucket_segments,
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    assert plan["feasible"] is True
    assert plan["bucket_width"] == 33
    assert plan["deferred_experiments"] == []
    assert len(plan["segments_to_create"]) == 3
    assert len(plan["audience_changes"]) == 3
    assert [[item["lo"], item["hi"]] for item in plan["segments_to_create"]] == [
        [0, 32],
        [33, 65],
        [66, 99],
    ]
    assert [item["to_segment"] for item in plan["audience_changes"]] == [
        "exp_iso_0_32",
        "exp_iso_33_65",
        "exp_iso_66_99",
    ]
    assert plan["approval_token"].startswith("iso-")


def test_plan_three_way_apply_and_verify(bucket_segments) -> None:
    report = audit_report_n([5, 6, 7])
    fake = FakeAPI(
        [
            experiment(5, "Draft A", segment_ids=[4]),
            experiment(6, "Draft B", segment_ids=[4]),
            experiment(7, "Draft C", segment_ids=[4]),
        ],
        [US_MOBILE],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        applied = run_apply(make_config(), plan, plan["approval_token"])
    assert applied["pass"] is True
    assert len(applied["changes"]) == 3
    assert len(applied["segments"]["created"]) == 3
    assert all(
        fake.experiments[experiment_id]["status"] == "running"
        for experiment_id in (5, 6, 7)
    )
    assert [audience_segment_ids(fake.experiments[item])[0] for item in (5, 6, 7)] == [
        5,
        6,
        7,
    ]

    samples = build_sample(30)
    ranges = {5: (0, 32), 6: (33, 65), 7: (66, 99)}
    payloads = payloads_for(
        samples,
        {
            sample.identifier: [
                next(
                    experiment_id
                    for experiment_id, (lo, hi) in ranges.items()
                    if lo <= sample.bucket <= hi
                )
            ]
            for sample in samples
        },
    )
    with mock.patch("engine.verify.AdminAPI", return_value=fake), mock.patch(
        "engine.verify.persist_sample", return_value=payloads
    ):
        verified = run_verify(make_config(), plan, samples=30)
    assert verified["max_pairwise_jaccard"] == 0.0
    assert verified["after_multi_exposed_rate"] == 0.0
    assert verified["pass"] is True
    assert len(verified["overlaps"]) == 3


def test_plan_refuses_infeasible_concurrency() -> None:
    report = audit_report_n([5, 6, 7, 8, 9])
    plan = build_plan(report, max_concurrent=4, min_bucket_width=5)
    assert plan["feasible"] is False
    assert plan["bucket_width"] == 20
    assert plan["deferred_experiments"] == [5, 6, 7, 8, 9]
    assert plan["audience_changes"] == []
    assert plan["approval_token"] is None
    assert plan["schedule"]
    assert "no partial isolation" in plan["refusal"]


def test_plan_refuses_infeasible_width() -> None:
    ids = list(range(1, 22))
    report = audit_report_n(ids)
    plan = build_plan(report, max_concurrent=100, min_bucket_width=5)
    assert plan["feasible"] is False
    assert plan["bucket_width"] == 4
    assert plan["deferred_experiments"] == ids


def test_plan_reports_blocked_running() -> None:
    report = audit_report_n([5, 6])
    report["experiments"].append(experiment_row(2, "Running", status="running", segment_ids=[4]))
    for item in report["experiments"]:
        if item["id"] == 2:
            item["audience_has_percentage_split"] = False
    report["overlaps"].append(
        {
            "a": 2,
            "b": 5,
            "shared": 50,
            "union": 50,
            "jaccard": 1.0,
            "a_rate": 0.5,
            "b_rate": 0.5,
            "verdict": "collision",
        }
    )
    report["collisions"].append([2, 5])
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        [US_MOBILE, segment(7, "exp_bucket_a", "LESS_THAN", "50"), segment(8, "exp_bucket_b", "GREATER_THAN_INCLUSIVE", "50")],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    assert plan["blocked_running"]
    assert plan["blocked_running"][0]["experiment_id"] == 2
    assert "pause" in plan["blocked_running"][0]["pause_isolate_restart"]


def test_apply_refuses_blocked_running_change(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    plan["blocked_running"] = [
        {
            "experiment_id": 2,
            "reason": "running",
            "pause_isolate_restart": "complete or delete experiment 2",
        }
    ]
    plan["audience_changes"].append(
        {
            "experiment_id": 2,
            "from_segment_ids": [4],
            "to_segment_ids": [],
            "to_segment": "exp_iso_0_49",
            "bucket_range": [0, 49],
            "requires_rollout_disable": True,
        }
    )
    plan["approval_token"] = approval_token(
        plan["environment"]["id"],
        plan["threshold"],
        plan["segments_to_create"],
        plan["audience_changes"],
        project_id=plan["project_id"],
        restore=plan["restore"],
        secret=make_config().admin_key,
        environment_name=plan["environment"]["name"],
    )
    with pytest.raises(Refusal):
        run_apply(make_config(), plan, plan["approval_token"])
    assert plan["audience_changes"][-1]["experiment_id"] == 2


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_cli_audit_exit_10_on_collision(tmp_path: Path) -> None:
    from engine.cli import main

    report = {
        "verdict": "collision",
        "experiments": [],
        "collisions": [],
        "sample_size": 10,
    }
    out = tmp_path / "audit.json"
    with mock.patch("engine.cli.Config.load", return_value=make_config()), mock.patch(
        "engine.cli.run_audit", return_value=report
    ):
        code = main(["audit", "--samples", "10", "--out", str(out)])
    assert code == 10
    assert out.is_file()


def test_cli_audit_exit_0_when_clear(tmp_path: Path) -> None:
    from engine.cli import main

    report = {"verdict": "clear", "experiments": [], "collisions": [], "sample_size": 10}
    out = tmp_path / "audit.json"
    with mock.patch("engine.cli.Config.load", return_value=make_config()), mock.patch(
        "engine.cli.run_audit", return_value=report
    ):
        code = main(["audit", "--samples", "10", "--out", str(out)])
    assert code == 0


def test_cli_verify_exit_10_when_failed(tmp_path: Path) -> None:
    from engine.cli import main

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        json.dumps(
            {
                "audience_changes": [{"experiment_id": 5}],
                "before_jaccard": 1.0,
                "before_multi_exposed_rate": 1.0,
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "verify.json"
    failed = {
        "sample_size": 10,
        "before_jaccard": 1.0,
        "after_jaccard": 1.0,
        "pass": False,
    }
    with mock.patch("engine.cli.Config.load", return_value=make_config()), mock.patch(
        "engine.cli.run_verify", return_value=failed
    ):
        code = main(["verify", "--plan", str(plan_file), "--samples", "10", "--out", str(out)])
    assert code == 10
    passed = dict(failed)
    passed["after_jaccard"] = 0.0
    passed["pass"] = True
    with mock.patch("engine.cli.Config.load", return_value=make_config()), mock.patch(
        "engine.cli.run_verify", return_value=passed
    ):
        code = main(["verify", "--plan", str(plan_file), "--samples", "10", "--out", str(out)])
    assert code == 0


def test_cli_plan_exit_10_when_infeasible(tmp_path: Path) -> None:
    from engine.cli import main

    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps({"experiments": []}), encoding="utf-8")
    out = tmp_path / "plan.json"
    infeasible = {
        "feasible": False,
        "audience_changes": [],
        "bucket_width": 4,
        "approval_token": None,
        "before_jaccard": 1.0,
        "refusal": "cannot fit",
    }
    with mock.patch("engine.cli.build_plan", return_value=infeasible):
        code = main(
            [
                "plan",
                "--audit",
                str(audit_file),
                "--max-concurrent",
                "4",
                "--min-bucket-width",
                "5",
                "--out",
                str(out),
            ]
        )
    assert code == 10
    assert out.is_file()


def test_cli_apply_missing_token_exit_10(tmp_path: Path) -> None:
    from engine.cli import main

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        json.dumps(
            {
                "feasible": True,
                "environment": {"id": 1, "name": "Development"},
                "project_id": 1,
                "threshold": 0.05,
                "audience_changes": [
                    {
                        "experiment_id": 5,
                        "from_segment_ids": [4],
                        "to_segment_ids": [],
                        "to_segment": "exp_iso_0_49",
                        "bucket_range": [0, 49],
                    }
                ],
                "approval_token": "iso-12345678",
                "segments_to_create": [],
                "restore": {},
            }
        ),
        encoding="utf-8",
    )
    with mock.patch("engine.cli.Config.load", return_value=make_config()):
        code = main(["apply", "--plan", str(plan_file), "--out", str(tmp_path / "apply.json")])
    assert code == 10


def test_receipt_includes_multi_exposure_rates(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    report = audit_report_n([5, 6])
    report["multi_exposed_rate"] = 0.75
    verify = {
        "sample_size": 100,
        "before_jaccard": 1.0,
        "after_jaccard": 0.0,
        "after_multi_exposed_rate": 0.0,
        "pass": True,
        "overlaps": [],
    }
    receipt = build_receipt(report, plan, verify)
    assert receipt["before"]["multi_exposed_rate"] == 0.75
    assert receipt["after"]["multi_exposed_rate"] == 0.0
    assert receipt["scope"] == "planned_experiments"
    assert "remaining_environment_collisions" in receipt
    assert estimate_tokens(receipt) <= 125



def test_run_audit_no_experiments_is_none(bucket_segments) -> None:
    fake = FakeAPI([], bucket_segments)
    with mock.patch("engine.audit.AdminAPI", return_value=fake), mock.patch(
        "engine.audit.persist_sample"
    ) as persist:
        report = run_audit(make_config(), samples=10)
    assert report["verdict"] == "none"
    assert report["experiments"] == []
    assert report["risk"] == "none"
    persist.assert_not_called()


def test_cli_apply_blocked_running_exit_10(tmp_path: Path) -> None:
    from engine.cli import main

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        json.dumps(
            {
                "feasible": True,
                "environment": {"id": 1},
                "audience_changes": [
                    {
                        "experiment_id": 2,
                        "from_segment_ids": [4],
                        "to_segment_ids": [],
                        "to_segment": "exp_iso_0_49",
                        "bucket_range": [0, 49],
                    }
                ],
                "blocked_running": [
                    {
                        "experiment_id": 2,
                        "reason": "running",
                        "pause_isolate_restart": "complete or delete experiment 2",
                    }
                ],
                "approval_token": "iso-12345678",
                "segments_to_create": [],
            }
        ),
        encoding="utf-8",
    )
    with mock.patch("engine.cli.Config.load", return_value=make_config()):
        code = main(
            [
                "apply",
                "--plan",
                str(plan_file),
                "--approve",
                "iso-12345678",
                "--out",
                str(tmp_path / "apply.json"),
            ]
        )
    assert code == 10



# ---------------------------------------------------------------------------
# Rollback, token binding, failure artifacts, seed guard
# ---------------------------------------------------------------------------


def apply_result_for(plan, experiment_id=5):
    return {
        "product": "experiment-isolation",
        "project_id": plan.get("project_id"),
        "changes": [
            {
                "experiment_id": experiment_id,
                "from_segment_ids": [4],
                "to_segment_ids": [7],
            }
        ],
        "restore": plan.get("restore") or {},
        "segments": {"created": [], "reused": []},
    }


def test_apply_rejects_edited_plan_even_with_recomputed_public_token(bucket_segments) -> None:
    plan = make_plan(bucket_segments)
    plan["audience_changes"][0]["to_segment_ids"] = [999]
    plan["approval_token"] = approval_token(
        plan["environment"]["id"],
        plan["threshold"],
        plan["segments_to_create"],
        plan["audience_changes"],
    )
    with pytest.raises(Refusal):
        run_apply(make_config(), plan, plan["approval_token"])


def test_apply_noop_requires_explicit_noop_token() -> None:
    plan = {
        "feasible": True,
        "environment": {"id": 1, "name": "Development"},
        "project_id": 1,
        "audience_changes": [],
        "approval_token": None,
        "restore": {},
    }
    with pytest.raises(Refusal):
        run_apply(make_config(), plan, "iso-wrong")
    result = run_apply(make_config(), plan, "noop")
    assert result["pass"] is True
    assert result["noop"] is True
    assert result["approval_token_verified"] is True


def test_rollback_created_experiment_restores_in_place(bucket_segments) -> None:
    from engine.rollback import run_rollback

    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", status="created", segment_ids=[7], enabled=False)],
        bucket_segments,
    )
    apply_result = apply_result_for(plan)
    with mock.patch("engine.rollback.AdminAPI", return_value=fake):
        result = run_rollback(make_config(), apply_result)
    assert result["pass"] is True
    assert result["live_restore"] is True
    assert result["requires_recreate"] is False
    assert audience_segment_ids(fake.experiments[5]) == [4]
    assert fake.experiments[5]["experiment_rollout"]["enabled"] is True


def test_rollback_running_experiment_recreates_draft(bucket_segments) -> None:
    from engine.rollback import run_rollback

    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", status="running", segment_ids=[7])],
        bucket_segments,
    )
    apply_result = apply_result_for(plan)
    with mock.patch("engine.rollback.AdminAPI", return_value=fake):
        result = run_rollback(make_config(), apply_result)
    assert result["pass"] is True
    assert result["live_restore"] is False
    assert result["requires_recreate"] is True
    entry = result["experiments"][0]
    assert entry["action"] == "recreated_draft"
    assert entry["new_experiment_id"] in fake.experiments
    assert 5 not in fake.experiments
    recreated = fake.experiments[entry["new_experiment_id"]]
    assert recreated["status"] == "created"
    assert audience_segment_ids(recreated) == [4]


def test_rollback_deletes_created_segments(bucket_segments) -> None:
    from engine.rollback import run_rollback

    report = audit_report_n([5, 6, 7])
    fake = FakeAPI(
        [
            experiment(5, "Draft A", segment_ids=[4]),
            experiment(6, "Draft B", segment_ids=[4]),
            experiment(7, "Draft C", segment_ids=[4]),
        ],
        [US_MOBILE],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        applied = run_apply(make_config(), plan, plan["approval_token"])
    assert len(applied["segments"]["created"]) == 3
    with mock.patch("engine.rollback.AdminAPI", return_value=fake):
        rolled = run_rollback(make_config(), applied)
    assert rolled["pass"] is True
    assert len(rolled["segments_deleted"]) == 3
    assert not any(segment_id in fake.segments for segment_id in (5, 6, 7))


def test_apply_failure_writes_artifact(bucket_segments, tmp_path: Path) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments,
    )
    fake.fail_start_for = {6}
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(EngineError) as excinfo:
            run_apply(
                make_config(), plan, plan["approval_token"], out_dir=str(tmp_path)
            )
    assert "after 1 started experiment(s)" in str(excinfo.value)
    artifact = json.loads((tmp_path / "apply-failure.json").read_text(encoding="utf-8"))
    assert artifact["pass"] is False
    assert artifact["segments"] == {"created": [], "reused": [{"id": 7, "name": "exp_bucket_a"}, {"id": 8, "name": "exp_bucket_b"}]}
    assert artifact["restore"]
    assert len(artifact["changes"]) == 2
    assert artifact["changes"][0]["experiment_id"] == 5
    assert artifact["changes"][0]["status"] == "running"
    assert artifact["changes"][1]["experiment_id"] == 6
    assert artifact["changes"][1]["status"] == "applying"


def test_malformed_experiment_metadata_raises_engine_error() -> None:
    payload = {
        "iso_0001": {
            "flags": [
                {"metadata": {"experiment": {"in_experiment": True, "name": "bad"}}}
            ]
        }
    }
    with pytest.raises(EngineError):
        enrollment_by_experiment(payload)


def test_cli_audit_engine_error_exit_20(tmp_path: Path) -> None:
    from engine.cli import main

    with mock.patch("engine.cli.Config.load", return_value=make_config()), mock.patch(
        "engine.cli.run_audit", side_effect=EngineError("malformed experiment metadata")
    ):
        code = main(["audit", "--samples", "10", "--out", str(tmp_path / "audit.json")])
    assert code == 20


def test_seed_refuses_running_without_reset() -> None:
    from engine.seed import FEATURES, _ensure_experiment

    fake = FakeAPI([experiment(5, "Express checkout", status="running")], [US_MOBILE])
    feature = {"id": 105}
    variant = {"id": 1}
    with pytest.raises(EngineError) as excinfo:
        _ensure_experiment(fake, make_config(), FEATURES[0], feature, variant)
    assert "--reset" in str(excinfo.value)
    result = _ensure_experiment(
        fake, make_config(), FEATURES[0], feature, variant, reset=True
    )
    assert result["status"] == "created"
    assert result["created_now"] is True
    assert 5 not in fake.experiments


def test_plan_nway_rollback_names_segments() -> None:
    report = audit_report_n([5, 6, 7])
    fake = FakeAPI(
        [
            experiment(5, "Draft A", segment_ids=[4]),
            experiment(6, "Draft B", segment_ids=[4]),
            experiment(7, "Draft C", segment_ids=[4]),
        ],
        [US_MOBILE],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    assert any(
        "delete segment by name exp_iso_0_32" in item for item in plan["rollback"]
    )



def test_apply_failure_records_created_segment_ids(bucket_segments, tmp_path: Path) -> None:
    report = audit_report_n([5, 6, 7])
    fake = FakeAPI(
        [
            experiment(5, "Draft A", segment_ids=[4]),
            experiment(6, "Draft B", segment_ids=[4]),
            experiment(7, "Draft C", segment_ids=[4]),
        ],
        [US_MOBILE],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    fake.fail_start_for = {6}
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(EngineError):
            run_apply(
                make_config(), plan, plan["approval_token"], out_dir=str(tmp_path)
            )
    artifact = json.loads((tmp_path / "apply-failure.json").read_text(encoding="utf-8"))
    assert len(artifact["segments"]["created"]) == 3
    assert all(item.get("id") for item in artifact["segments"]["created"])
    assert artifact["rollback"][0].startswith("python3 -m engine.cli rollback")


def test_plan_blocked_note_recommends_recreate_not_pause() -> None:
    report = audit_report_n([5, 6])
    report["experiments"].append(experiment_row(2, "Running", status="running", segment_ids=[4]))
    report["overlaps"].append(
        {
            "a": 2,
            "b": 5,
            "shared": 50,
            "union": 50,
            "jaccard": 1.0,
            "a_rate": 0.5,
            "b_rate": 0.5,
            "verdict": "collision",
        }
    )
    report["collisions"].append([2, 5])
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        [US_MOBILE, segment(7, "exp_bucket_a", "LESS_THAN", "50"), segment(8, "exp_bucket_b", "GREATER_THAN_INCLUSIVE", "50")],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    note = plan["blocked_running"][0]["pause_isolate_restart"]
    assert "complete or delete" in note
    assert "pausing is not enough" in note



def test_rollback_deletes_segments_even_without_changes() -> None:
    from engine.rollback import run_rollback

    fake = FakeAPI([], [segment(5, "exp_iso_tmp", "LESS_THAN", "50")])
    apply_result = {
        "project_id": 1,
        "changes": [],
        "segments": {"created": [{"id": 5, "name": "exp_iso_tmp"}], "reused": []},
        "restore": {},
    }
    with mock.patch("engine.rollback.AdminAPI", return_value=fake):
        result = run_rollback(make_config(), apply_result)
    assert result["pass"] is True
    assert result["segments_deleted"] == [{"id": 5, "name": "exp_iso_tmp"}]
    assert 5 not in fake.segments



def test_apply_failure_counts_only_started_experiments(bucket_segments, tmp_path: Path) -> None:
    report = audit_report_n([5, 6, 7])
    fake = FakeAPI(
        [
            experiment(5, "Draft A", segment_ids=[4]),
            experiment(6, "Draft B", segment_ids=[4]),
            experiment(7, "Draft C", segment_ids=[4]),
        ],
        [US_MOBILE],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    fake.fail_start_for = {7}
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(EngineError) as excinfo:
            run_apply(
                make_config(), plan, plan["approval_token"], out_dir=str(tmp_path)
            )
    message = str(excinfo.value)
    assert "after 2 started experiment(s)" in message
    assert "after 3" not in message
    artifact = json.loads((tmp_path / "apply-failure.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in artifact["changes"]] == [
        "running",
        "running",
        "applying",
    ]

