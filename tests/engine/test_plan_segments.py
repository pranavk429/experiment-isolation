"""Offline tests for isolation planning and composed/pure segment allocation."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest import mock

import pytest

from conftest import (
    GB_MOBILE,
    US_MOBILE,
    FakeAPI,
    audit_report,
    audit_report_n,
    experiment,
    experiment_row,
    make_config,
    segment,
)
from engine.plan import approval_token, build_plan
from engine.segments import compose_segment_rules
from engine.util import Refusal


def test_plan_us_mobile_preserves_targeting_and_ignores_pure_buckets(
    bucket_segments: List[Dict[str, Any]],
) -> None:
    pure_extra = [
        segment(10, "exp_iso_0_49", "LESS_THAN", "50"),
        segment(11, "exp_iso_50_99", "GREATER_THAN_INCLUSIVE", "50"),
    ]
    rows = [
        experiment_row(5, "Draft A", segment_ids=[4]),
        experiment_row(6, "Draft B", segment_ids=[4]),
        experiment_row(2, "Running", status="running", segment_ids=[4]),
    ]
    report = audit_report(rows)
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments + pure_extra,
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())

    assert plan["approval_token"].startswith("iso-")
    assert len(plan["approval_token"]) == 12
    assert plan["before_jaccard"] == 1.0
    assert any("a paused experiment cannot change audience" in item for item in plan["notes"])
    assert not any("pause or recreate" in item for item in plan["notes"])

    assert [item["name"] for item in plan["segments_to_create"]] == [
        "exp_iso_us_mobile_0_49",
        "exp_iso_us_mobile_50_99",
    ]
    assert all(item["existing"] is False and item["id"] is None for item in plan["segments_to_create"])
    assert all(item["base_rules"] == US_MOBILE["rules"] for item in plan["segments_to_create"])
    assert plan["audience_changes"][0]["to_segment"] == "exp_iso_us_mobile_0_49"
    assert plan["audience_changes"][1]["to_segment"] == "exp_iso_us_mobile_50_99"
    assert plan["audience_changes"][0]["to_segment_ids"] == []
    assert plan["audience_changes"][1]["to_segment_ids"] == []
    assert plan["unchanged_running"] == [2]
    assert set(plan["restore"]) == {"5", "6"}
    assert plan["rollback"][0] == "python3 -m engine.cli rollback --apply apply.json --out rollback.json"
    assert any("delete segment by name exp_iso_us_mobile_0_49" in item for item in plan["rollback"])
    assert not any("flagsmith api" in item for item in plan["rollback"])


def test_plan_reuses_existing_composed_us_mobile_segments(
    bucket_segments: List[Dict[str, Any]],
) -> None:
    composed = [
        {
            "id": 12,
            "name": "exp_iso_us_mobile_0_49",
            "rules": compose_segment_rules(
                US_MOBILE["rules"], "flagsmith_experiment_bucket", 0, 49
            ),
        },
        {
            "id": 13,
            "name": "exp_iso_us_mobile_50_99",
            "rules": compose_segment_rules(
                US_MOBILE["rules"], "flagsmith_experiment_bucket", 50, 99
            ),
        },
    ]
    report = audit_report(
        [experiment_row(5, "Draft A", segment_ids=[4]), experiment_row(6, "Draft B", segment_ids=[4])]
    )
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[4]), experiment(6, "Draft B", segment_ids=[4])],
        bucket_segments + composed,
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())

    assert [item["id"] for item in plan["segments_to_create"]] == [12, 13]
    assert all(item["existing"] is True for item in plan["segments_to_create"])
    assert plan["audience_changes"][0]["to_segment_ids"] == [12]
    assert plan["audience_changes"][1]["to_segment_ids"] == [13]


def test_plan_reuses_pure_bucket_segments_when_untargeted(
    bucket_segments: List[Dict[str, Any]],
) -> None:
    report = audit_report(
        [experiment_row(5, "Draft A", segment_ids=[]), experiment_row(6, "Draft B", segment_ids=[])]
    )
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[]), experiment(6, "Draft B", segment_ids=[])],
        bucket_segments,
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())

    assert plan["segments_to_create"][0]["id"] == 7
    assert plan["segments_to_create"][0]["name"] == "exp_bucket_a"
    assert plan["segments_to_create"][1]["id"] == 8
    assert plan["segments_to_create"][1]["name"] == "exp_bucket_b"
    assert all(item["existing"] is True for item in plan["segments_to_create"])
    assert plan["audience_changes"][0]["to_segment_ids"] == [7]
    assert plan["audience_changes"][1]["to_segment_ids"] == [8]


def test_plan_creates_pure_bucket_segments_when_missing_for_untargeted() -> None:
    report = audit_report(
        [experiment_row(5, "Draft A", segment_ids=[]), experiment_row(6, "Draft B", segment_ids=[])]
    )
    fake = FakeAPI(
        [experiment(5, "Draft A", segment_ids=[]), experiment(6, "Draft B", segment_ids=[])],
        [US_MOBILE],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())

    assert plan["segments_to_create"][0]["existing"] is False
    assert plan["segments_to_create"][0]["id"] is None
    assert plan["segments_to_create"][0]["name"] == "exp_iso_0_49"
    assert plan["segments_to_create"][1]["name"] == "exp_iso_50_99"
    assert plan["audience_changes"][0]["to_segment_ids"] == []
    assert plan["audience_changes"][0]["to_segment"] == "exp_iso_0_49"


def test_plan_allocates_three_disjoint_us_mobile_ranges(
    bucket_segments: List[Dict[str, Any]],
) -> None:
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
        "exp_iso_us_mobile_0_32",
        "exp_iso_us_mobile_33_65",
        "exp_iso_us_mobile_66_99",
    ]
    assert all(item["base_rules"] == US_MOBILE["rules"] for item in plan["segments_to_create"])
    assert any("delete segment by name exp_iso_us_mobile_0_32" in item for item in plan["rollback"])
    assert plan["approval_token"].startswith("iso-")


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


def test_plan_reports_blocked_running_when_single_draft_collides_with_running() -> None:
    report = {
        "environment": {"id": 1, "name": "Development", "key_prefix": "test"},
        "project_id": 1,
        "sample_size": 100,
        "threshold": 0.05,
        "experiments": [
            experiment_row(2, "Running", status="running", segment_ids=[4]),
            experiment_row(5, "Single Draft", status="created", segment_ids=[4]),
        ],
        "overlaps": [
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
        ],
        "collisions": [[2, 5]],
        "verdict": "collision",
        "multi_exposed_rate": 0.5,
    }
    plan = build_plan(report)
    assert plan["feasible"] is False
    assert plan["audience_changes"] == []
    assert plan["segments_to_create"] == []
    assert plan["approval_token"] is None
    assert plan["deferred_experiments"] == [5]
    assert plan["refusal"]
    assert len(plan["blocked_running"]) == 1
    assert plan["blocked_running"][0]["experiment_id"] == 2
    assert "running" in plan["blocked_running"][0]["reason"]
    assert plan["before_jaccard"] == 1.0
    assert any("blocked running" in note.lower() for note in plan["notes"])


def test_plan_blocked_running_recommends_recreate_not_pause(
    bucket_segments: List[Dict[str, Any]],
) -> None:
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
        bucket_segments,
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config())
    assert plan["feasible"] is False
    assert plan["audience_changes"] == []
    assert plan["segments_to_create"] == []
    assert plan["approval_token"] is None
    assert plan["deferred_experiments"] == [5, 6]
    assert plan["refusal"]
    assert plan["blocked_running"]
    assert plan["blocked_running"][0]["experiment_id"] == 2
    note = plan["blocked_running"][0]["pause_isolate_restart"]
    assert "complete or delete" in note
    assert "pausing is not enough" in note


def test_plan_blocks_paused_experiment_colliding_with_draft() -> None:
    report = {
        "environment": {"id": 1, "name": "Development", "key_prefix": "test"},
        "project_id": 1,
        "sample_size": 100,
        "threshold": 0.05,
        "experiments": [
            experiment_row(3, "Paused", status="paused", segment_ids=[4]),
            experiment_row(5, "Draft A", status="created", segment_ids=[4]),
        ],
        "overlaps": [
            {
                "a": 3,
                "b": 5,
                "shared": 50,
                "union": 50,
                "jaccard": 1.0,
                "a_rate": 0.5,
                "b_rate": 0.5,
                "verdict": "collision",
            }
        ],
        "collisions": [[3, 5]],
        "verdict": "collision",
        "multi_exposed_rate": 0.5,
    }
    plan = build_plan(report)
    assert plan["feasible"] is False
    assert plan["unchanged_running"] == [3]
    assert plan["audience_changes"] == []
    assert plan["approval_token"] is None
    assert plan["deferred_experiments"] == [5]
    assert plan["refusal"]
    assert len(plan["blocked_running"]) == 1
    assert plan["blocked_running"][0]["experiment_id"] == 3
    assert "paused" in plan["blocked_running"][0]["reason"]


def test_plan_partitions_independent_collision_components() -> None:
    report = {
        "environment": {"id": 1, "name": "Development", "key_prefix": "test"},
        "project_id": 1,
        "sample_size": 100,
        "threshold": 0.05,
        "experiments": [
            experiment_row(5, "US A", segment_ids=[4]),
            experiment_row(6, "US B", segment_ids=[4]),
            experiment_row(7, "GB A", segment_ids=[9]),
            experiment_row(8, "GB B", segment_ids=[9]),
        ],
        "overlaps": [
            {
                "a": 5,
                "b": 6,
                "shared": 50,
                "union": 50,
                "jaccard": 1.0,
                "a_rate": 0.5,
                "b_rate": 0.5,
                "verdict": "collision",
            },
            {
                "a": 7,
                "b": 8,
                "shared": 30,
                "union": 30,
                "jaccard": 1.0,
                "a_rate": 0.3,
                "b_rate": 0.3,
                "verdict": "collision",
            },
        ],
        "collisions": [[5, 6], [7, 8]],
        "verdict": "collision",
        "multi_exposed_rate": 0.8,
    }
    fake = FakeAPI(
        [
            experiment(5, "US A", segment_ids=[4]),
            experiment(6, "US B", segment_ids=[4]),
            experiment(7, "GB A", segment_ids=[9]),
            experiment(8, "GB B", segment_ids=[9]),
        ],
        [US_MOBILE, GB_MOBILE],
    )
    with mock.patch("engine.plan.AdminAPI", return_value=fake):
        plan = build_plan(report, config=make_config(), max_concurrent=4)

    assert plan["feasible"] is True
    assert plan["bucket_width"] == 50
    by_id = {row["experiment_id"]: row for row in plan["audience_changes"]}
    assert by_id[5]["bucket_range"] == [0, 49]
    assert by_id[6]["bucket_range"] == [50, 99]
    assert by_id[7]["bucket_range"] == [0, 49]
    assert by_id[8]["bucket_range"] == [50, 99]
    assert by_id[5]["to_segment"] == "exp_iso_us_mobile_0_49"
    assert by_id[7]["to_segment"] == "exp_iso_gb_mobile_0_49"


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


def test_plan_infeasible_schedule_suggests_lower_min_bucket_width() -> None:
    ids = list(range(1, 22))
    report = audit_report_n(ids)
    plan = build_plan(report, max_concurrent=100, min_bucket_width=5)
    assert plan["feasible"] is False
    assert any("lower --min-bucket-width" in item for item in plan["schedule"])
    assert not any("raise --min-bucket-width" in item for item in plan["schedule"])


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
