"""Tests for the Experiment Isolation Lab storefront and seed helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from conftest import FakeAPI, segment
from engine.sampling import bucket_for

ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def storefront() -> ModuleType:
    return _load_module("lab_storefront_app", ROOT / "lab" / "storefront" / "app.py")


@pytest.fixture(scope="module")
def lab_seed() -> ModuleType:
    return _load_module("lab_seed_script", ROOT / "lab" / "seed" / "seed.py")


def test_storefront_stable_bucket_matches_engine(storefront: ModuleType) -> None:
    for identifier in ("demo-us-mobile-001", "iso_0001", "iso_0042"):
        bucket = storefront.stable_bucket(identifier)
        assert 0 <= bucket <= 99
        assert bucket == bucket_for(identifier)


def test_storefront_parse_identity_defaults_and_validation(storefront: ModuleType) -> None:
    assert storefront.parse_identity({}) == ("demo-us-mobile-001", "US", "mobile")
    assert storefront.parse_identity(
        {"identifier": ["alice_1"], "country": ["gb"], "platform": ["DESKTOP"]}
    ) == ("alice_1", "GB", "desktop")
    assert storefront.parse_identity(
        {"identifier": ["alice_1"], "country": ["FR"], "platform": ["tablet"]}
    ) == ("alice_1", "US", "mobile")
    with pytest.raises(ValueError):
        storefront.parse_identity({"identifier": ["bad identifier with spaces!"]})


def test_storefront_flag_card_renders_variants_and_control(storefront: ModuleType) -> None:
    assert "pricing_banner" in storefront.FLAGS
    assert "onboarding_tip" in storefront.FLAGS

    pricing_urgent = storefront.flag_card(
        "pricing_banner",
        {
            "enabled": True,
            "value": "urgent",
            "variant": "urgent",
            "in_experiment": True,
            "experiment_name": "Pricing banner",
        },
    )
    assert "Only 3 seats left — save 20% today." in pricing_urgent
    assert "preview urgent" in pricing_urgent

    pricing_control = storefront.flag_card(
        "pricing_banner",
        {
            "enabled": True,
            "value": "control",
            "variant": "control",
            "in_experiment": True,
            "experiment_name": "Pricing banner",
        },
    )
    assert "Simple pricing that scales with your team." in pricing_control
    assert "preview urgent" not in pricing_control

    onboarding_short = storefront.flag_card(
        "onboarding_tip",
        {
            "enabled": True,
            "value": "short",
            "variant": "short",
            "in_experiment": True,
            "experiment_name": "Onboarding tip",
        },
    )
    assert "Start with a 3-step tour. You can finish setup later." in onboarding_short
    assert "preview short" in onboarding_short

    onboarding_control = storefront.flag_card(
        "onboarding_tip",
        {
            "enabled": True,
            "value": "control",
            "variant": "control",
            "in_experiment": False,
            "experiment_name": "Onboarding tip",
        },
    )
    assert "Welcome! Take the full guided tour to set up your workspace." in onboarding_control
    assert "preview short" not in onboarding_control


def test_lab_seed_variants_match_storefront_and_cleanup_targets_only_exp_iso(
    storefront: ModuleType,
    lab_seed: ModuleType,
) -> None:
    for spec in lab_seed.FEATURES:
        flag_spec = storefront.FLAGS[spec["name"]]
        assert flag_spec.get("variant_key") == spec["variant"]

    payload = lab_seed.experiment_payload(
        lab_seed.FEATURES[0],
        {"id": 10},
        {"id": 20},
        {"id": 30},
        {"id": 4},
    )
    rollout = payload["experiment_rollout"]
    assert rollout["rollout_percentage"] == 100
    assert rollout["audience"] == {"match": "any", "segment_ids": [4]}
    assert rollout["multivariate_feature_state_values"][0]["percentage_allocation"] == 50

    fake = FakeAPI(
        segments=[
            {"id": 4, "name": "us_mobile", "rules": []},
            segment(7, "exp_iso_us_mobile_0_49", "LESS_THAN", "50"),
            segment(8, "exp_iso_us_mobile_50_99", "GREATER_THAN_INCLUSIVE", "50"),
        ]
    )
    lab_seed.cleanup_bucket_segments(fake, 1)

    assert sorted(fake.segments) == [4]
    assert fake.calls == [
        "DELETE /api/v1/projects/1/segments/7/",
        "DELETE /api/v1/projects/1/segments/8/",
    ]
