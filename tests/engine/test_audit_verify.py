"""Offline tests for sampling, segment matching, audit, and verification."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest import mock

import pytest

from conftest import (
    GB_MOBILE,
    US_MOBILE,
    FakeAPI,
    experiment,
    make_config,
    make_plan,
    payloads_for,
    segment,
)
from engine.audit import run_audit
from engine.sampling import (
    bucket_for,
    build_sample,
    enrollment_by_experiment,
    jaccard,
    traits_match,
)
from engine.segments import (
    audience_segment_ids,
    compose_segment_rules,
    find_bucket_segment,
    find_range_segment,
    segment_has_percentage_split,
    segment_is_bucket_range,
    segment_is_range,
    segment_matches,
)
from engine.util import EngineError
from engine.verify import run_verify


def test_bucket_is_stable_and_in_range() -> None:
    assert bucket_for("iso_0001") == bucket_for("iso_0001")
    for index in range(1, 200):
        assert 0 <= bucket_for(f"iso_{index:04d}") <= 99


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


def test_malformed_experiment_metadata_raises_engine_error() -> None:
    payload = {
        "iso_0001": {
            "flags": [{"metadata": {"experiment": {"in_experiment": True, "name": "bad"}}}]
        }
    }
    with pytest.raises(EngineError):
        enrollment_by_experiment(payload)

    non_dict = {"iso_0001": {"flags": [{"metadata": "invalid"}]}}
    with pytest.raises(EngineError):
        enrollment_by_experiment(non_dict)


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
    assert not segment_is_range(risky, "flagsmith_experiment_bucket", 0, 49)


def test_segment_is_range_with_and_without_base_rules() -> None:
    pure_low = segment(7, "exp_iso_0_49", "LESS_THAN", "50")
    composed_low = {
        "id": 11,
        "name": "exp_iso_us_mobile_0_49",
        "rules": compose_segment_rules(US_MOBILE["rules"], "flagsmith_experiment_bucket", 0, 49),
    }

    assert segment_is_range(pure_low, "flagsmith_experiment_bucket", 0, 49)
    assert not segment_is_range(
        pure_low, "flagsmith_experiment_bucket", 0, 49, base_rules=US_MOBILE["rules"]
    )
    assert segment_is_range(
        composed_low, "flagsmith_experiment_bucket", 0, 49, base_rules=US_MOBILE["rules"]
    )
    assert not segment_is_range(composed_low, "flagsmith_experiment_bucket", 0, 49)
    assert not segment_is_range(
        composed_low, "flagsmith_experiment_bucket", 0, 49, base_rules=GB_MOBILE["rules"]
    )

    found = find_range_segment(
        [pure_low, composed_low],
        "flagsmith_experiment_bucket",
        0,
        49,
        base_rules=US_MOBILE["rules"],
    )
    assert found is not None and found["id"] == 11


def test_segment_is_range_rejects_foreign_trait_and_identity_key() -> None:
    foreign_cond = {"operator": "NOT_EQUAL", "property": "other_trait", "value": "x"}
    identity_cond = {"operator": "NOT_EQUAL", "property": "$.identity.key", "value": "user_1"}
    for extra in (foreign_cond, identity_cond):
        pure = {
            "id": 20,
            "name": "polluted_pure",
            "rules": [
                {
                    "type": "ALL",
                    "rules": [],
                    "conditions": [
                        {
                            "operator": "LESS_THAN",
                            "property": "flagsmith_experiment_bucket",
                            "value": "50",
                        },
                        extra,
                    ],
                }
            ],
        }
        composed = {
            "id": 21,
            "name": "polluted_composed",
            "rules": compose_segment_rules(
                US_MOBILE["rules"], "flagsmith_experiment_bucket", 0, 49
            )
            + [{"type": "ALL", "rules": [], "conditions": [extra]}],
        }
        assert not segment_is_range(pure, "flagsmith_experiment_bucket", 0, 49)
        assert not segment_is_range(
            composed,
            "flagsmith_experiment_bucket",
            0,
            49,
            base_rules=US_MOBILE["rules"],
        )


def test_find_bucket_segment_prefers_existing(bucket_segments: List[Dict[str, Any]]) -> None:
    found = find_bucket_segment(bucket_segments, "flagsmith_experiment_bucket", "LESS_THAN", "50")
    assert found is not None and found["id"] == 7
    assert (
        find_bucket_segment(bucket_segments, "flagsmith_experiment_bucket", "GREATER_THAN", "50")
        is None
    )


def test_audience_ids_from_detail() -> None:
    assert audience_segment_ids(experiment(5, "A", segment_ids=[4])) == [4]
    assert audience_segment_ids(experiment(5, "A")) == []


def test_run_audit_projects_created_and_measures_running(
    bucket_segments: List[Dict[str, Any]],
) -> None:
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
    with mock.patch("engine.audit.AdminAPI", return_value=fake), mock.patch(
        "engine.audit.persist_sample", return_value=payloads
    ):
        report = run_audit(make_config(), samples=10, threshold=0.05)
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


def test_audit_reports_multi_exposure_and_risk(
    bucket_segments: List[Dict[str, Any]],
) -> None:
    experiments = [
        experiment(2, "Running", status="running", segment_ids=[4]),
        experiment(5, "Draft A", segment_ids=[4]),
        experiment(6, "Draft B", segment_ids=[4]),
    ]
    fake = FakeAPI(experiments, bucket_segments)
    samples = build_sample(10)
    payloads = payloads_for(samples, {sample.identifier: [2, 5, 6] for sample in samples})
    with mock.patch("engine.audit.AdminAPI", return_value=fake), mock.patch(
        "engine.audit.persist_sample", return_value=payloads
    ):
        report = run_audit(make_config(), samples=10, threshold=0.05)
    assert report["multi_exposed_rate"] == 0.5
    assert report["max_exposure_count"] == 3
    assert report["risk"] == "critical"


def test_run_audit_no_experiments_is_none(bucket_segments: List[Dict[str, Any]]) -> None:
    fake = FakeAPI([], bucket_segments)
    with mock.patch("engine.audit.AdminAPI", return_value=fake), mock.patch(
        "engine.audit.persist_sample"
    ) as persist:
        report = run_audit(make_config(), samples=10)
    assert report["verdict"] == "none"
    assert report["experiments"] == []
    assert report["risk"] == "none"
    persist.assert_not_called()


def test_verify_zero_overlap_and_running(bucket_segments: List[Dict[str, Any]]) -> None:
    plan = make_plan(bucket_segments)
    composed = [
        {
            "id": 9,
            "name": "exp_iso_us_mobile_0_49",
            "rules": compose_segment_rules(
                US_MOBILE["rules"], "flagsmith_experiment_bucket", 0, 49
            ),
        },
        {
            "id": 10,
            "name": "exp_iso_us_mobile_50_99",
            "rules": compose_segment_rules(
                US_MOBILE["rules"], "flagsmith_experiment_bucket", 50, 99
            ),
        },
    ]
    fake = FakeAPI(
        [
            experiment(5, "Draft A", status="running", segment_ids=[9]),
            experiment(6, "Draft B", status="running", segment_ids=[10]),
        ],
        bucket_segments + composed,
    )
    samples = build_sample(20)
    payloads = payloads_for(
        samples,
        {
            sample.identifier: [5 if sample.bucket < 50 else 6]
            for sample in samples
            if sample.traits["country"] == "US" and sample.traits["platform"] == "mobile"
        },
    )
    with mock.patch("engine.verify.AdminAPI", return_value=fake), mock.patch(
        "engine.verify.persist_sample", return_value=payloads
    ):
        result = run_verify(make_config(), plan, samples=20)
    assert result["after_jaccard"] == 0.0
    assert result["pass"] is True
    assert result["overlaps"][0]["verdict"] == "isolated"


def test_verify_detects_residual_overlap(bucket_segments: List[Dict[str, Any]]) -> None:
    plan = make_plan(bucket_segments)
    fake = FakeAPI(
        [
            experiment(5, "Draft A", status="running", segment_ids=[7]),
            experiment(6, "Draft B", status="running", segment_ids=[8]),
        ],
        bucket_segments,
    )
    samples = build_sample(20)
    payloads = payloads_for(samples, {sample.identifier: [5, 6] for sample in samples})
    with mock.patch("engine.verify.AdminAPI", return_value=fake), mock.patch(
        "engine.verify.persist_sample", return_value=payloads
    ):
        result = run_verify(make_config(), plan, samples=20)
    assert result["after_jaccard"] == 1.0
    assert result["pass"] is False


def test_verify_fails_if_audience_not_applied(bucket_segments: List[Dict[str, Any]]) -> None:
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


def test_verify_custom_sample_prefix_uses_uncached_identities(
    bucket_segments: List[Dict[str, Any]],
) -> None:
    plan = make_plan(bucket_segments)
    composed = [
        {
            "id": seg_id,
            "name": f"exp_iso_us_mobile_{lo}_{hi}",
            "rules": compose_segment_rules(US_MOBILE["rules"], "flagsmith_experiment_bucket", lo, hi),
        }
        for seg_id, lo, hi in ((9, 0, 49), (10, 50, 99))
    ]
    fake = FakeAPI(
        [
            experiment(5, "Draft A", status="running", segment_ids=[9]),
            experiment(6, "Draft B", status="running", segment_ids=[10]),
        ],
        bucket_segments + composed,
    )
    samples = build_sample(20, prefix="verify")
    payloads = payloads_for(
        samples,
        {
            s.identifier: [5 if s.bucket < 50 else 6]
            for s in samples
            if s.traits["country"] == "US" and s.traits["platform"] == "mobile"
        },
    )
    seen: List[str] = []

    def fake_persist(_cfg: Any, sample_list: List[Any], workers: int = 8) -> Dict[str, Any]:
        seen.extend(item.identifier for item in sample_list)
        return payloads

    with mock.patch("engine.verify.AdminAPI", return_value=fake), mock.patch(
        "engine.verify.persist_sample", side_effect=fake_persist
    ):
        result = run_verify(make_config(), plan, samples=20, sample_prefix="verify")
    assert result["pass"] is True
    assert len(seen) == 20 and seen[0] == "verify_0001"
    assert all(identifier.startswith("verify_") for identifier in seen)
