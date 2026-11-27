"""Offline tests for CLI exit codes, config loading, EdgeAPI redaction, receipt, and seed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from conftest import (
    US_MOBILE,
    FakeAPI,
    audit_report,
    audit_report_n,
    experiment,
    experiment_row,
    make_config,
    make_plan,
)
from engine.api import ApiError, EdgeAPI
from engine.cli import main
from engine.config import Config, _host_scoped_key_name, load_env_file
from engine.receipt import build_receipt
from engine.seed import FEATURES, _ensure_experiment, run_seed
from engine.util import ConfigError, EngineError, compact_json, estimate_tokens


def test_cli_audit_exit_10_on_collision(tmp_path: Path) -> None:
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
    report = {"verdict": "clear", "experiments": [], "collisions": [], "sample_size": 10}
    out = tmp_path / "audit.json"
    with mock.patch("engine.cli.Config.load", return_value=make_config()), mock.patch(
        "engine.cli.run_audit", return_value=report
    ):
        code = main(["audit", "--samples", "10", "--out", str(out)])
    assert code == 0


def test_cli_audit_engine_error_exit_20(tmp_path: Path) -> None:
    with mock.patch("engine.cli.Config.load", return_value=make_config()), mock.patch(
        "engine.cli.run_audit", side_effect=EngineError("malformed experiment metadata")
    ):
        code = main(["audit", "--samples", "10", "--out", str(tmp_path / "audit.json")])
    assert code == 20


def test_cli_verify_exit_10_when_failed_and_0_when_passed(tmp_path: Path) -> None:
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


def test_cli_apply_blocked_running_exit_10(tmp_path: Path) -> None:
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


def test_config_load_avoids_cross_env_bleed_and_accepts_env_key(tmp_path: Path) -> None:
    default_env = tmp_path / "flagsmith.env"
    default_env.write_text(
        "export FLAGSMITH_API_URL=http://localhost:8000\n"
        "export FLAGSMITH_API_KEY_localhost_8000=admin-8000\n"
        "export DEV_ENV_KEY=env-8000\n"
        "export FLAGSMITH_PROJECT=1\n",
        encoding="utf-8",
    )
    with mock.patch("engine.config.DEFAULT_ENV_FILE", default_env):
        env = {
            "FLAGSMITH_API_URL": "http://localhost:8010",
            "FLAGSMITH_API_KEY_localhost_8010": "admin-8010",
            "FLAGSMITH_ENVIRONMENT_KEY": "env-8010",
            "FLAGSMITH_PROJECT": "2",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = Config.load()
            assert cfg.api_url == "http://localhost:8010"
            assert cfg.admin_key == "admin-8010"
            assert cfg.env_key == "env-8010"

        env_no_key = {
            "FLAGSMITH_API_URL": "http://localhost:8010",
            "FLAGSMITH_API_KEY_localhost_8010": "admin-8010",
        }
        with mock.patch.dict(os.environ, env_no_key, clear=True):
            with pytest.raises(ConfigError) as excinfo:
                Config.load()
            assert "flagsmith-local" not in str(excinfo.value)

        with mock.patch.dict(os.environ, {}, clear=True):
            cfg_default = Config.load()
            assert cfg_default.api_url == "http://localhost:8000"
            assert cfg_default.env_key == "env-8000"


def test_edge_api_sanitizes_secrets() -> None:
    cfg = make_config(admin_key="secret-admin-key-xyz", env_key="secret-env-key-abc")
    edge = EdgeAPI(cfg)
    http_err = urllib.error.HTTPError(
        url="http://localhost:8000/api/v1/identities/",
        code=500,
        msg="Server Error",
        hdrs={},
        fp=BytesIO(b'{"detail":"bad key secret-env-key-abc"}'),
    )
    with mock.patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(ApiError) as excinfo:
            edge.identity("iso_0001")
    assert cfg.env_key not in str(excinfo.value)
    assert "<redacted>" in str(excinfo.value) or "<env>" in str(excinfo.value)


def test_receipt_is_compact_and_has_rollback(bucket_segments: List[Dict[str, Any]]) -> None:
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


def test_receipt_includes_multi_exposure_rates(bucket_segments: List[Dict[str, Any]]) -> None:
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


def test_seed_resolves_segment_and_metric_by_name() -> None:
    us_mobile = dict(US_MOBILE)
    us_mobile["id"] = 9
    fake = FakeAPI(
        experiments=[],
        segments=[us_mobile],
        metrics=[{"id": 7, "name": "Purchase"}],
        project_id=3,
    )
    with mock.patch("engine.seed.AdminAPI", return_value=fake):
        res = run_seed(config=make_config(), count=2, reset=False)

    assert res["segment_id"] == 9
    assert res["metric_id"] == 7
    assert len(res["experiments"]) == 2
    first_exp = next(iter(fake.experiments.values()))
    assert first_exp["metrics"][0]["metric"] == 7
    assert first_exp["experiment_rollout"]["audience"]["segments"][0]["id"] == 9


def test_seed_refuses_running_without_reset() -> None:
    fake = FakeAPI([experiment(5, "Express checkout", status="running")], [US_MOBILE])
    feature = {"id": 105}
    variant = {"id": 1}
    with pytest.raises(EngineError) as excinfo:
        _ensure_experiment(fake, make_config(), FEATURES[0], feature, variant)
    assert "--reset" in str(excinfo.value)
    result = _ensure_experiment(fake, make_config(), FEATURES[0], feature, variant, reset=True)
    assert result["status"] == "created"
    assert result["created_now"] is True
    assert 5 not in fake.experiments


def test_repo_root_engine_shim_cli_help() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "engine.cli", "--help"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Discover overlapping Flagsmith experiments" in result.stdout


def test_host_scoped_key_name_sanitizes_hyphenated_hostname() -> None:
    assert (
        _host_scoped_key_name("http://flagsmith-dev.internal:8010")
        == "FLAGSMITH_API_KEY_flagsmith_dev_internal_8010"
    )
    env = {
        "FLAGSMITH_API_URL": "http://flagsmith-dev.internal:8010",
        "ISO_ALLOW_REMOTE": "1",
        "FLAGSMITH_API_KEY_flagsmith_dev_internal_8010": "admin-remote",
        "DEV_ENV_KEY": "env-remote",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = Config.load()
        assert cfg.admin_key == "admin-remote"


def test_receipt_remaining_collisions_ignores_non_colliding_overlaps() -> None:
    plan = {"audience_changes": [{"experiment_id": 5}, {"experiment_id": 6}]}
    report = {
        "environment": {"name": "Development"},
        "sample_size": 100,
        "verdict": "collision",
        "multi_exposed_rate": 0.5,
        "overlaps": [
            {"a": 5, "b": 6, "jaccard": 0.0, "verdict": "clear"},
            {"a": 2, "b": 3, "jaccard": 0.9, "verdict": "collision"},
            {"a": 5, "b": 7, "jaccard": 0.8, "verdict": "collision"},
        ],
        "collisions": [[2, 3], [5, 7]],
    }
    verify = {
        "sample_size": 100,
        "before_jaccard": 0.9,
        "after_jaccard": 0.0,
        "after_multi_exposed_rate": 0.0,
        "pass": True,
        "overlaps": [],
    }
    receipt = build_receipt(report, plan, verify)
    assert receipt["remaining_environment_collisions"] == 2
    assert estimate_tokens(receipt) <= 125

    report_two = dict(
        report,
        overlaps=[
            {"a": 5, "b": 6, "jaccard": 1.0, "verdict": "collision"},
            {"a": 5, "b": 7, "jaccard": 0.0, "verdict": "clear"},
            {"a": 2, "b": 3, "jaccard": 0.9, "verdict": "collision"},
        ],
        collisions=[[5, 6], [2, 3]],
    )
    receipt_two = build_receipt(
        report_two,
        {"audience_changes": [{"experiment_id": 5}, {"experiment_id": 6}, {"experiment_id": 7}]},
        verify,
    )
    assert receipt_two["remaining_environment_collisions"] == 1


def test_cli_verify_passes_sample_prefix(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        json.dumps({"audience_changes": [{"experiment_id": 5}]}),
        encoding="utf-8",
    )
    out = tmp_path / "verify.json"
    passed = {
        "sample_size": 10,
        "before_jaccard": 1.0,
        "after_jaccard": 0.0,
        "pass": True,
    }
    with mock.patch("engine.cli.Config.load", return_value=make_config()), mock.patch(
        "engine.cli.run_verify", return_value=passed
    ) as mock_verify:
        code = main(
            [
                "verify",
                "--plan",
                str(plan_file),
                "--samples",
                "10",
                "--sample-prefix",
                "verify",
                "--out",
                str(out),
            ]
        )
    assert code == 0
    assert mock_verify.call_args.kwargs["sample_prefix"] == "verify"
