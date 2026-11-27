"""Offline tests for plan application, failure artifacts, and rollback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from conftest import (
    US_MOBILE,
    FakeAPI,
    audit_report_n,
    experiment,
    make_config,
    make_plan,
    payloads_for,
    segment,
)
from engine.apply import run_apply
from engine.plan import approval_token, build_plan
from engine.rollback import run_rollback
from engine.sampling import build_sample
from engine.segments import (
    audience_segment_ids,
    find_range_segment,
    segment_is_range,
    segment_matches,
)
from engine.util import EngineError, Refusal
from engine.verify import run_verify


def _apply_result_for(plan: Dict[str, Any], experiment_id: int = 5) -> Dict[str, Any]:
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


def test_apply_requires_exact_token(bucket_segments: List[Dict[str, Any]]) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments,
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(Refusal):
            run_apply(make_config(), plan, "iso-wrong")
    assert fake.calls == []


def test_apply_rejects_edited_plan_even_with_recomputed_public_token(
    bucket_segments: List[Dict[str, Any]],
) -> None:
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


def test_apply_refuses_running_experiment(bucket_segments: List[Dict[str, Any]]) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", status="running", segment_ids=[4]), experiment(6, "Draft B")],
        bucket_segments,
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(Refusal):
            run_apply(make_config(), plan, plan["approval_token"])
    assert not any(call.startswith("PATCH") for call in fake.calls)


def test_apply_refuses_blocked_running_change(bucket_segments: List[Dict[str, Any]]) -> None:
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


def test_apply_creates_composed_us_mobile_segments_and_restore_files(
    bucket_segments: List[Dict[str, Any]],
    tmp_path: Path,
) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments,
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        result = run_apply(make_config(), plan, plan["approval_token"], out_dir=str(tmp_path))

    assert result["pass"] is True
    assert fake.experiments[5]["status"] == "running"
    assert fake.experiments[6]["status"] == "running"
    assert [item["name"] for item in result["segments"]["created"]] == [
        "exp_iso_us_mobile_0_49",
        "exp_iso_us_mobile_50_99",
    ]
    assert result["segments"]["reused"] == []
    seg_a_id = audience_segment_ids(fake.experiments[5])[0]
    seg_b_id = audience_segment_ids(fake.experiments[6])[0]
    assert seg_a_id not in (7, 8)
    assert seg_b_id not in (7, 8)

    seg_a = fake.segments[seg_a_id]
    seg_b = fake.segments[seg_b_id]
    assert segment_matches(
        seg_a, {"country": "US", "platform": "mobile", "flagsmith_experiment_bucket": 10}
    )
    assert not segment_matches(
        seg_a, {"country": "GB", "platform": "mobile", "flagsmith_experiment_bucket": 10}
    )
    assert not segment_matches(
        seg_a, {"country": "US", "platform": "desktop", "flagsmith_experiment_bucket": 10}
    )
    assert segment_matches(
        seg_b, {"country": "US", "platform": "mobile", "flagsmith_experiment_bucket": 75}
    )
    assert not segment_matches(
        seg_b, {"country": "GB", "platform": "mobile", "flagsmith_experiment_bucket": 75}
    )

    found = find_range_segment(
        list(fake.segments.values()),
        "flagsmith_experiment_bucket",
        0,
        49,
        base_rules=US_MOBILE["rules"],
    )
    assert found is not None and found["id"] == seg_a_id
    assert not segment_is_range(
        fake.segments[7], "flagsmith_experiment_bucket", 0, 49, base_rules=US_MOBILE["rules"]
    )

    assert (tmp_path / "restore-5.json").is_file()
    assert (tmp_path / "restore-6.json").is_file()
    assert len(result["restore_files"]) == 2
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(Refusal):
            run_apply(make_config(), plan, plan["approval_token"])


def test_apply_reuses_pure_bucket_segments_for_untargeted_drafts(
    bucket_segments: List[Dict[str, Any]],
) -> None:
    plan = make_plan(bucket_segments, draft_segment_ids=[])
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[]), experiment(6, "Draft B", segment_ids=[])],
        bucket_segments,
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        result = run_apply(make_config(), plan, plan["approval_token"])
    assert result["pass"] is True
    assert result["segments"]["created"] == []
    assert [item["id"] for item in result["segments"]["reused"]] == [7, 8]
    assert audience_segment_ids(fake.experiments[5]) == [7]
    assert audience_segment_ids(fake.experiments[6]) == [8]


def test_apply_creates_pure_bucket_segments_when_missing() -> None:
    plan = make_plan([US_MOBILE], draft_segment_ids=[])
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[]), experiment(6, "Draft B", segment_ids=[])],
        [US_MOBILE],
    )
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        result = run_apply(make_config(), plan, plan["approval_token"])
    assert result["pass"] is True
    assert [item["name"] for item in result["segments"]["created"]] == [
        "exp_iso_0_49",
        "exp_iso_50_99",
    ]
    assert len(fake.calls) > 0


def test_plan_three_way_us_mobile_apply_and_verify() -> None:
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
    assert all(fake.experiments[eid]["status"] == "running" for eid in (5, 6, 7))
    assert [audience_segment_ids(fake.experiments[item])[0] for item in (5, 6, 7)] == [5, 6, 7]

    samples = build_sample(30)
    ranges = {5: (0, 32), 6: (33, 65), 7: (66, 99)}
    payloads = payloads_for(
        samples,
        {
            sample.identifier: [
                next(eid for eid, (lo, hi) in ranges.items() if lo <= sample.bucket <= hi)
            ]
            for sample in samples
            if sample.traits["country"] == "US" and sample.traits["platform"] == "mobile"
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


def test_apply_failure_writes_artifact(
    bucket_segments: List[Dict[str, Any]],
    tmp_path: Path,
) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments,
    )
    fake.fail_start_for = {6}
    with mock.patch("engine.apply.AdminAPI", return_value=fake):
        with pytest.raises(EngineError) as excinfo:
            run_apply(make_config(), plan, plan["approval_token"], out_dir=str(tmp_path))
    assert "after 1 started experiment(s)" in str(excinfo.value)
    artifact = json.loads((tmp_path / "apply-failure.json").read_text(encoding="utf-8"))
    assert artifact["pass"] is False
    assert artifact["segments"] == {
        "created": [
            {"id": 9, "name": "exp_iso_us_mobile_0_49"},
            {"id": 10, "name": "exp_iso_us_mobile_50_99"},
        ],
        "reused": [],
    }
    assert artifact["restore"]
    assert len(artifact["changes"]) == 2
    assert artifact["changes"][0]["experiment_id"] == 5
    assert artifact["changes"][0]["status"] == "running"
    assert artifact["changes"][1]["experiment_id"] == 6
    assert artifact["changes"][1]["status"] == "applying"


def test_apply_failure_counts_only_started_experiments_and_records_segments(
    tmp_path: Path,
) -> None:
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
            run_apply(make_config(), plan, plan["approval_token"], out_dir=str(tmp_path))
    message = str(excinfo.value)
    assert "after 2 started experiment(s)" in message
    assert "after 3" not in message
    artifact = json.loads((tmp_path / "apply-failure.json").read_text(encoding="utf-8"))
    assert len(artifact["segments"]["created"]) == 3
    assert all(item.get("id") for item in artifact["segments"]["created"])
    assert artifact["rollback"][0].startswith("python3 -m engine.cli rollback")
    assert [item["status"] for item in artifact["changes"]] == [
        "running",
        "running",
        "applying",
    ]


def test_rollback_created_experiment_restores_in_place(
    bucket_segments: List[Dict[str, Any]],
) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", status="created", segment_ids=[7], enabled=False)],
        bucket_segments,
    )
    with mock.patch("engine.rollback.AdminAPI", return_value=fake):
        result = run_rollback(make_config(), _apply_result_for(plan))
    assert result["pass"] is True
    assert result["live_restore"] is True
    assert result["requires_recreate"] is False
    assert audience_segment_ids(fake.experiments[5]) == [4]
    assert fake.experiments[5]["experiment_rollout"]["enabled"] is True


def test_rollback_running_experiment_recreates_draft(
    bucket_segments: List[Dict[str, Any]],
) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [experiment(5, "Draft A", status="running", segment_ids=[7])],
        bucket_segments,
    )
    with mock.patch("engine.rollback.AdminAPI", return_value=fake):
        result = run_rollback(make_config(), _apply_result_for(plan))
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


def test_rollback_deletes_created_segments() -> None:
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


def test_rollback_deletes_segments_even_without_changes() -> None:
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


def test_rollback_sanitizes_secrets() -> None:
    cfg = make_config(admin_key="secret-admin-key-xyz", env_key="secret-env-key-abc")

    class ExplodingAPI:
        def resolve_project_id(self) -> int:
            return 1

        def get(self, path: str) -> Dict[str, Any]:
            raise RuntimeError(f"boom {cfg.admin_key} {cfg.env_key}")

    apply_result = {
        "project_id": 1,
        "changes": [{"experiment_id": 5, "from_segment_ids": [4], "to_segment_ids": [7]}],
        "restore": {"5": {"audience": {"segment_ids": [4]}}},
        "segments": {"created": [], "reused": []},
    }
    with mock.patch("engine.rollback.AdminAPI", return_value=ExplodingAPI()):
        rolled = run_rollback(cfg, apply_result)
    assert rolled["pass"] is False
    err_text = rolled["experiments"][0]["error"]
    assert cfg.admin_key not in err_text
    assert cfg.env_key not in err_text
