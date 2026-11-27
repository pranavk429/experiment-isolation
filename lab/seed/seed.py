#!/usr/bin/env python3
"""Seed the Experiment Isolation Lab with two deliberately colliding drafts.

Creates (idempotently, matched by name via engine.seed helpers):
  * features pricing_banner and onboarding_tip, each with a 50/50 variant
  * segment us_mobile (country=US AND platform=mobile)
  * metric Purchase (occurrence)
  * DRAFT experiments "Pricing banner" and "Onboarding tip", both targeting
    us_mobile with a 100% rollout

Both drafts share the same audience and collide 100%. They are left in
status=created on purpose: Flagsmith only lets a draft experiment change its
audience, which is what the isolation workflow needs.

Rerunning is convergent: active experiments on these two features (including
running ones from a demo and [rollback] drafts) are paused/removed and replaced
with clean drafts; stale exp_iso_* bucket segments are deleted.

Pass --start to start them and make live enrollment measurable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lablib  # noqa: E402, F401
from engine.api import AdminAPI, ApiError  # noqa: E402
from engine.api import request_json as engine_request_json  # noqa: E402
from engine.config import Config  # noqa: E402
from engine.seed import (  # noqa: E402
    ensure_feature_with_variant,
    ensure_purchase_metric,
    ensure_us_mobile_segment,
)
from engine.segments import audience_segment_ids  # noqa: E402
from engine.util import EngineError  # noqa: E402
from lablib import (  # noqa: E402
    DEFAULT_API_URL,
    ENV_PATH,
    LAB_DIR,
    LabError,
    find_by_name,
    load_env,
    now_iso,
    require,
    write_json,
)

DEV_NAME = "Development"
SEGMENT_NAME = "us_mobile"
METRIC_NAME = "Purchase"
STATE_PATH = LAB_DIR / "seed" / "seed_state.json"
SAMPLE_TRAITS = ["country", "platform", "flagsmith_experiment_bucket"]

FEATURES = [
    {
        "name": "pricing_banner",
        "description": "Experiment Isolation demo: pricing banner copy.",
        "variant": "urgent",
        "experiment": "Pricing banner",
        "hypothesis": "An urgent inventory banner increases checkout conversion for US mobile visitors.",
    },
    {
        "name": "onboarding_tip",
        "description": "Experiment Isolation demo: onboarding tip length.",
        "variant": "short",
        "experiment": "Onboarding tip",
        "hypothesis": "A shorter onboarding tip increases first-session activation for US mobile visitors.",
    },
]


class _LabAdminAPI(AdminAPI):
    """AdminAPI supporting both Master Api-Key and user Token credentials."""

    def __init__(self, config: Config, auth_scheme: str = "Api-Key") -> None:
        super().__init__(config)
        self._auth_scheme = auth_scheme

    def _request(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None
    ) -> Any:
        if self._auth_scheme == "Api-Key":
            return super()._request(method, path, payload)
        url = path if path.startswith("http") else f"{self.base}{path}"
        safe_path = path.replace(self.config.env_key, "<env>")
        return engine_request_json(
            method,
            url,
            headers={"Authorization": f"Token {self.config.admin_key}"},
            payload=payload,
            timeout=60.0,
            secrets=(self.config.admin_key, self.config.env_key),
            safe_path=safe_path,
        )


def experiment_payload(
    spec: Dict[str, str],
    feature: Dict[str, Any],
    option: Dict[str, Any],
    metric: Dict[str, Any],
    segment: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "feature": feature["id"],
        "name": spec["experiment"],
        "hypothesis": spec["hypothesis"],
        "metrics": [{"metric": metric["id"], "expected_direction": "increase"}],
        "experiment_rollout": {
            "enabled": True,
            "rollout_percentage": 100,
            "feature_state_value": {"type": "string", "value": "control"},
            "multivariate_feature_state_values": [
                {
                    "multivariate_feature_option": option["id"],
                    "percentage_allocation": 50,
                }
            ],
            "audience": {"match": "any", "segment_ids": [segment["id"]]},
        },
    }


def experiment_feature_id(experiment: Dict[str, Any]) -> Optional[int]:
    feature = experiment.get("feature")
    if isinstance(feature, dict):
        value = feature.get("id")
        return int(value) if value is not None else None
    if isinstance(feature, int):
        return feature
    return None


def experiment_detail(api: AdminAPI, dev_key: str, experiment_id: int) -> Dict[str, Any]:
    detail = api.get(f"/api/v1/environments/{dev_key}/experiments/{experiment_id}/")
    if not isinstance(detail, dict):
        raise LabError(f"Could not read experiment {experiment_id}")
    return detail


def remove_experiment(api: AdminAPI, dev_key: str, experiment: Dict[str, Any]) -> None:
    """Pause if needed, then delete a conflicting experiment."""
    experiment_id = int(experiment["id"])
    detail = experiment_detail(api, dev_key, experiment_id)
    status = str(detail.get("status", ""))
    label = f"{detail.get('name')} (id {experiment_id}, {status})"
    if status == "running":
        print(f"Experiment: pausing {label} before removal")
        try:
            api.post(f"/api/v1/environments/{dev_key}/experiments/{experiment_id}/pause/", {})
        except (ApiError, EngineError) as exc:
            raise LabError(f"Could not pause {label}: {exc}. Run: bash lab/run.sh reset") from exc
        detail = experiment_detail(api, dev_key, experiment_id)
        if str(detail.get("status", "")) == "running":
            raise LabError(
                f"Experiment {label} is still running after pause. Run: bash lab/run.sh reset"
            )
    try:
        api.delete(f"/api/v1/environments/{dev_key}/experiments/{experiment_id}/")
    except (ApiError, EngineError) as exc:
        raise LabError(f"Could not remove {label}: {exc}. Run: bash lab/run.sh reset") from exc
    print(f"Experiment: removed conflicting {label}")


def active_experiments_for_feature(
    api: AdminAPI, dev_key: str, feature_id: int
) -> List[Dict[str, Any]]:
    experiments = api.get_all(f"/api/v1/environments/{dev_key}/experiments/")
    return [
        experiment
        for experiment in experiments
        if experiment_feature_id(experiment) == feature_id
        and str(experiment.get("status", "")).lower() != "completed"
    ]


def cleanup_bucket_segments(api: AdminAPI, project_id: int) -> None:
    """Remove stale exp_iso_* segments so a rerun starts from one clean audience."""
    segments = api.get_all(f"/api/v1/projects/{project_id}/segments/")
    removed: List[str] = []
    for segment in segments:
        name = str(segment.get("name", ""))
        if not name.startswith("exp_iso_"):
            continue
        try:
            api.delete(f"/api/v1/projects/{project_id}/segments/{segment['id']}/")
        except (ApiError, EngineError) as exc:
            print(f"Segment: could not remove stale {name} ({exc}); leaving it")
            continue
        removed.append(name)
    if removed:
        print(f"Segments: removed stale {', '.join(removed)}")


def _guard_cross_feature_name(
    api: AdminAPI, dev_key: str, spec: Dict[str, str], feature_id: int
) -> None:
    for item in api.get_all(f"/api/v1/environments/{dev_key}/experiments/"):
        owner = experiment_feature_id(item)
        if (
            item.get("name") == spec["experiment"]
            and owner not in (None, feature_id)
            and str(item.get("status", "")).lower() != "completed"
        ):
            raise LabError(
                f"Experiment {spec['experiment']!r} already exists on a different feature "
                f"(id {owner}). Run: bash lab/run.sh reset"
            )


def _reconcile_feature_experiments(
    api: AdminAPI,
    dev_key: str,
    spec: Dict[str, str],
    feature_id: int,
    segment_id: int,
) -> Optional[Dict[str, Any]]:
    reusable: Optional[Dict[str, Any]] = None
    wanted_audience = [segment_id]
    for item in active_experiments_for_feature(api, dev_key, feature_id):
        detail = experiment_detail(api, dev_key, int(item["id"]))
        status = str(detail.get("status", "")).lower()
        audience = audience_segment_ids(detail)
        if (
            detail.get("name") == spec["experiment"]
            and status == "created"
            and audience == wanted_audience
        ):
            reusable = detail
            print(
                f"Experiment: reusing clean draft {detail.get('name')} "
                f"(id {detail.get('id')}, audience {audience})"
            )
            continue
        print(
            f"Experiment: cleaning up {detail.get('name')} "
            f"(id {detail.get('id')}, status {status}, audience {audience})"
        )
        remove_experiment(api, dev_key, detail)
    return reusable


def _create_draft(
    api: AdminAPI,
    dev_key: str,
    spec: Dict[str, str],
    feature: Dict[str, Any],
    option: Dict[str, Any],
    metric: Dict[str, Any],
    segment: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        experiment = api.post(
            f"/api/v1/environments/{dev_key}/experiments/",
            experiment_payload(spec, feature, option, metric, segment),
        )
    except (ApiError, EngineError) as exc:
        if "409" in str(exc) or "active experiment" in str(exc).lower():
            raise LabError(
                f"An active experiment still owns feature {feature.get('name')!r}: {exc}. "
                "Run: bash lab/run.sh reset"
            ) from exc
        raise LabError(str(exc)) from exc
    if not isinstance(experiment, dict) or experiment.get("id") is None:
        raise LabError("Experiment creation returned an unexpected response")
    print(
        f"Experiment: created draft {experiment.get('name')} "
        f"(id {experiment.get('id')}, audience {SEGMENT_NAME})"
    )
    return experiment_detail(api, dev_key, int(experiment["id"]))


def _maybe_start_experiment(
    api: AdminAPI,
    dev_key: str,
    spec: Dict[str, str],
    experiment: Dict[str, Any],
    start: bool,
) -> Dict[str, Any]:
    status = str(experiment.get("status", ""))
    if start and status == "created":
        try:
            started = api.post(
                f"/api/v1/environments/{dev_key}/experiments/{experiment['id']}/start/", {}
            )
        except (ApiError, EngineError) as exc:
            raise LabError(
                f"Starting experiment {spec['experiment']} failed: {exc}. Run: bash lab/run.sh reset"
            ) from exc
        if not isinstance(started, dict):
            raise LabError(f"Starting experiment {spec['experiment']} returned an unexpected response")
        print(f"Experiment: started {started.get('name')} (enrollment is now measurable)")
        return started
    if status == "created":
        print("Experiment: left as draft (safe to retarget; pass --start to run it)")
    elif status == "running":
        print("Experiment: already running; audience is locked while running (re-targeting requires recreate)")
    elif status in ("paused", "completed"):
        print(f"Experiment: status is {status}; seeding will not modify it")
    return experiment


def ensure_experiment(
    api: AdminAPI,
    dev_key: str,
    spec: Dict[str, str],
    feature: Dict[str, Any],
    option: Dict[str, Any],
    metric: Dict[str, Any],
    segment: Dict[str, Any],
    start: bool,
) -> Dict[str, Any]:
    """Converge the feature to one clean draft with the shared us_mobile audience."""
    feature_id = int(feature["id"])
    _guard_cross_feature_name(api, dev_key, spec, feature_id)
    reusable = _reconcile_feature_experiments(api, dev_key, spec, feature_id, int(segment["id"]))
    experiment = reusable or _create_draft(api, dev_key, spec, feature, option, metric, segment)
    return _maybe_start_experiment(api, dev_key, spec, experiment, start)


def current_audience_ids(
    api: AdminAPI, dev_key: str, experiment_id: int, fallback: List[int]
) -> List[int]:
    """Read the audience actually stored on the experiment, not the seed intent."""
    try:
        detail = experiment_detail(api, dev_key, experiment_id)
    except LabError:
        return fallback
    return audience_segment_ids(detail) or fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--dev-key", default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the drafts after creating them (makes enrollment measurable).",
    )
    return parser.parse_args()


def _resolve_credential(args: argparse.Namespace, env: Dict[str, str]) -> Tuple[str, str]:
    if args.token:
        scheme = "Api-Key" if args.token.startswith("ser.") else "Token"
        return args.token, scheme
    master_key = env.get("LAB_ADMIN_API_KEY") or env.get("FLAGSMITH_API_KEY")
    if master_key:
        return master_key, "Api-Key"
    token = require(env.get("LAB_ADMIN_TOKEN"), "No admin token. Run: python3 lab/bootstrap.py")
    return token, "Token"


def _resolve_context(args: argparse.Namespace, env: Dict[str, str]) -> Dict[str, Any]:
    base_url = (
        args.api_url or env.get("LAB_API_URL") or env.get("FLAGSMITH_API_URL") or DEFAULT_API_URL
    ).rstrip("/")
    credential, scheme = _resolve_credential(args, env)
    project_id = args.project_id or int(
        require(env.get("LAB_PROJECT_ID"), "LAB_PROJECT_ID missing; run bootstrap first")
    )
    dev_key = args.dev_key or env.get("LAB_DEV_ENV_KEY") or ""
    config = Config(api_url=base_url, admin_key=credential, env_key=dev_key, project=str(project_id))
    api = _LabAdminAPI(config, auth_scheme=scheme)
    if not dev_key:
        envs = api.get_all(f"/api/v1/environments/?project={project_id}")
        dev = find_by_name(envs, DEV_NAME)
        dev_key = require((dev or {}).get("api_key"), "Development environment not found")
        config.env_key = dev_key
    return {
        "base_url": base_url,
        "api": api,
        "project_id": project_id,
        "dev_key": dev_key,
        "dev_id": env.get("LAB_DEV_ENV_ID", ""),
        "project_name": env.get("LAB_PROJECT_NAME", ""),
    }


def _seed_experiments(
    api: AdminAPI,
    dev_key: str,
    feature_records: List[Dict[str, Any]],
    metric: Dict[str, Any],
    segment: Dict[str, Any],
    start: bool,
) -> List[Dict[str, Any]]:
    state_experiments: List[Dict[str, Any]] = []
    for record in feature_records:
        experiment = ensure_experiment(
            api,
            dev_key,
            record["spec"],
            record["feature"],
            record["option"],
            metric,
            segment,
            start,
        )
        audience_ids = current_audience_ids(api, dev_key, int(experiment["id"]), [int(segment["id"])])
        state_experiments.append(
            {
                "id": experiment["id"],
                "name": experiment.get("name"),
                "feature": record["feature"].get("name", record["spec"]["name"]),
                "status": experiment.get("status"),
                "audience_segment_ids": audience_ids,
                "rollout_percentage": 100,
            }
        )
    return state_experiments


def _build_state(
    ctx: Dict[str, Any],
    segment: Dict[str, Any],
    metric: Dict[str, Any],
    state_experiments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    dev_id = ctx["dev_id"]
    return {
        "generated_at": now_iso(),
        "environment": {
            "id": int(dev_id) if str(dev_id).isdigit() else None,
            "name": DEV_NAME,
            "key_prefix": ctx["dev_key"][:4],
        },
        "project": {"id": ctx["project_id"], "name": ctx["project_name"]},
        "segment": {"id": segment["id"], "name": segment.get("name", SEGMENT_NAME)},
        "metric": {"id": metric["id"], "name": metric.get("name", METRIC_NAME)},
        "experiments": state_experiments,
        "sample_traits": SAMPLE_TRAITS,
        "notes": "Both drafts intentionally share the us_mobile segment.",
    }


def _print_summary(state_experiments: List[Dict[str, Any]]) -> None:
    print("")
    print(f"Seeded {len(state_experiments)} experiments in {DEV_NAME}.")
    for record in state_experiments:
        segs = ", ".join(str(v) for v in record.get("audience_segment_ids") or [])
        print(
            f"  - {record.get('name')} (id {record.get('id')}): "
            f"{record.get('status')}, audience segment(s) {segs}"
        )
    print(f"  State: {STATE_PATH}")
    audiences = [tuple(record.get("audience_segment_ids") or []) for record in state_experiments]
    if audiences and all(audience == audiences[0] for audience in audiences):
        print("  All experiments share the same audience segment(s): overlap is expected.")
    elif all(
        not set(left).intersection(right)
        for index, left in enumerate(audiences)
        for right in audiences[index + 1 :]
    ):
        print("  Audiences are disjoint across experiments.")
    else:
        print("  Audiences differ; inspect the dashboard for pairwise overlap.")


def main() -> int:
    args = parse_args()
    ctx = _resolve_context(args, load_env())
    api, project_id, dev_key = ctx["api"], ctx["project_id"], ctx["dev_key"]
    mode = "draft + started" if args.start else "draft only"
    print("Experiment Isolation Lab seed")
    print(f"  API:   {ctx['base_url']}")
    print(f"  Env:   {ENV_PATH}")
    print(f"  Mode:  {mode}\n")

    feature_records: List[Dict[str, Any]] = []
    for spec in FEATURES:
        ensured = ensure_feature_with_variant(api, project_id, spec)
        feature, option = ensured["feature"], ensured["variant"]
        print(f"Feature: {feature.get('name')} (id {feature.get('id')}, variant {spec['variant']})")
        feature_records.append({"spec": spec, "feature": feature, "option": option})

    segment = ensure_us_mobile_segment(api, project_id)
    print(f"Segment: {segment.get('name', SEGMENT_NAME)} (id {segment.get('id')})")
    metric = ensure_purchase_metric(api, dev_key)
    print(f"Metric: {metric.get('name', METRIC_NAME)} (id {metric.get('id')})")

    state_experiments = _seed_experiments(api, dev_key, feature_records, metric, segment, args.start)
    # Remove only stale exp_iso_* bucket segments; keep us_mobile and unrelated segments.
    cleanup_bucket_segments(api, project_id)
    write_json(STATE_PATH, _build_state(ctx, segment, metric, state_experiments))
    _print_summary(state_experiments)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (LabError, EngineError) as exc:
        print(f"seed: error: {exc}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("seed: interrupted", file=sys.stderr)
        sys.exit(130)
