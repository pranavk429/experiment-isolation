#!/usr/bin/env python3
"""Seed the Experiment Isolation Lab with two deliberately colliding drafts.

Creates (idempotently, matched by name):
  * features pricing_banner and onboarding_tip, each with a 50/50 variant
  * segment us_mobile (country=US AND platform=mobile)
  * metric Purchase (occurrence)
  * DRAFT experiments "Pricing banner" and "Onboarding tip", both targeting
    us_mobile with a 100% rollout

Both drafts therefore share the same audience and collide 100%. They are left
in status=created on purpose: Flagsmith only lets a draft experiment change its
audience, which is exactly what the isolation workflow needs.

Rerunning is convergent: active experiments on these two features (including
running ones from a demo and [rollback] drafts) are paused/removed and replaced
with clean drafts; stale exp_iso_* bucket segments are deleted. This avoids the
HTTP 409 "active experiment already exists" failure on rerun.

Pass --start to start them and make live enrollment measurable. Running
experiments cannot be retargeted without pausing them first.

Uses the management API with the admin token/master key from lab/.env. Never
prints a key.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lablib import (
    DEFAULT_API_URL,
    ENV_PATH,
    LAB_DIR,
    LabError,
    find_by_name,
    get_list,
    load_env,
    now_iso,
    request_json,
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


def ensure_feature(
    base_url: str, token: str, project_id: int, spec: Dict[str, str]
) -> tuple:
    features = get_list(
        "/projects/%d/features/" % project_id, base_url=base_url, token=token
    )
    feature = find_by_name(features, spec["name"])
    if not feature:
        feature = request_json(
            "POST",
            "/projects/%d/features/" % project_id,
            base_url=base_url,
            token=token,
            payload={
                "name": spec["name"],
                "description": spec["description"],
                "default_enabled": True,
                "initial_value": "control",
                "type": "MULTIVARIATE",
                "multivariate_options": [
                    {
                        "type": "unicode",
                        "string_value": spec["variant"],
                        "default_percentage_allocation": 50,
                    }
                ],
            },
        )
        if not isinstance(feature, dict):
            raise LabError("Feature creation returned an unexpected response for %s" % spec["name"])
        print("Feature: created %s (id %s)" % (feature.get("name"), feature.get("id")))
    else:
        print("Feature: reusing %s (id %s)" % (feature.get("name"), feature.get("id")))

    options = feature.get("multivariate_options") or []
    option = next(
        (
            candidate
            for candidate in options
            if str(candidate.get("string_value", "")) == spec["variant"]
            or str(candidate.get("key", "")) == spec["variant"]
        ),
        None,
    )
    if option is None:
        option = request_json(
            "POST",
            "/projects/%d/features/%s/mv-options/" % (project_id, feature["id"]),
            base_url=base_url,
            token=token,
            payload={
                "feature": feature["id"],
                "type": "unicode",
                "string_value": spec["variant"],
                "default_percentage_allocation": 50,
            },
        )
        if not isinstance(option, dict):
            raise LabError("Variant creation returned an unexpected response for %s" % spec["name"])
        print("Variant: added %r to %s" % (spec["variant"], spec["name"]))
    return feature, option


def ensure_segment(base_url: str, token: str, project_id: int) -> Dict[str, Any]:
    segments = get_list(
        "/projects/%d/segments/" % project_id, base_url=base_url, token=token
    )
    segment = find_by_name(segments, SEGMENT_NAME)
    if segment:
        print("Segment: reusing %s (id %s)" % (SEGMENT_NAME, segment.get("id")))
        return segment
    segment = request_json(
        "POST",
        "/projects/%d/segments/" % project_id,
        base_url=base_url,
        token=token,
        payload={
            "name": SEGMENT_NAME,
            "description": "Synthetic US mobile audience used by both lab drafts.",
            "rules": [
                {
                    "type": "ALL",
                    "conditions": [
                        {"operator": "EQUAL", "property": "country", "value": "US"},
                        {"operator": "EQUAL", "property": "platform", "value": "mobile"},
                    ],
                }
            ],
        },
    )
    if not isinstance(segment, dict):
        raise LabError("Segment creation returned an unexpected response")
    print("Segment: created %s (id %s)" % (SEGMENT_NAME, segment.get("id")))
    return segment


def ensure_metric(base_url: str, token: str, dev_key: str) -> Dict[str, Any]:
    metrics = get_list(
        "/environments/%s/experiment-metrics/" % dev_key, base_url=base_url, token=token
    )
    metric = find_by_name(metrics, METRIC_NAME)
    if metric:
        print("Metric: reusing %s (id %s)" % (METRIC_NAME, metric.get("id")))
        return metric
    metric = request_json(
        "POST",
        "/environments/%s/experiment-metrics/" % dev_key,
        base_url=base_url,
        token=token,
        payload={
            "name": METRIC_NAME,
            "description": "Checkout conversion for the isolation demo.",
            "definition": {"event": "purchase", "version": 1},
            "aggregation": "occurrence",
            "direction": "up",
        },
    )
    if not isinstance(metric, dict):
        raise LabError("Metric creation returned an unexpected response")
    print("Metric: created %s (id %s)" % (METRIC_NAME, metric.get("id")))
    return metric


def experiment_payload(
    spec: Dict[str, str], feature: Dict[str, Any], option: Dict[str, Any],
    metric: Dict[str, Any], segment: Dict[str, Any]
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


def experiment_detail(
    base_url: str, token: str, dev_key: str, experiment_id: int
) -> Dict[str, Any]:
    detail = request_json(
        "GET",
        "/environments/%s/experiments/%s/" % (dev_key, experiment_id),
        base_url=base_url,
        token=token,
    )
    if not isinstance(detail, dict):
        raise LabError("Could not read experiment %s" % experiment_id)
    return detail


def audience_ids_from_detail(
    detail: Dict[str, Any], fallback: Optional[List[int]] = None
) -> List[int]:
    rollout = detail.get("experiment_rollout") or {}
    audience = rollout.get("audience") or {}
    segments = audience.get("segments") or []
    ids = sorted(
        {
            int(segment["id"])
            for segment in segments
            if isinstance(segment, dict) and segment.get("id") is not None
        }
    )
    return ids or list(fallback or [])


def remove_experiment(
    base_url: str, token: str, dev_key: str, experiment: Dict[str, Any]
) -> None:
    """Pause if needed, then delete a conflicting experiment."""
    experiment_id = int(experiment["id"])
    detail = experiment_detail(base_url, token, dev_key, experiment_id)
    status = str(detail.get("status", ""))
    label = "%s (id %s, %s)" % (detail.get("name"), experiment_id, status)
    if status == "running":
        print("Experiment: pausing %s before removal" % label)
        try:
            request_json(
                "POST",
                "/environments/%s/experiments/%s/pause/" % (dev_key, experiment_id),
                base_url=base_url,
                token=token,
                payload={},
            )
        except LabError as exc:
            raise LabError(
                "Could not pause %s: %s. Run: bash lab/run.sh reset" % (label, exc)
            ) from exc
        detail = experiment_detail(base_url, token, dev_key, experiment_id)
        status = str(detail.get("status", ""))
        if status == "running":
            raise LabError(
                "Experiment %s is still running after pause. Run: bash lab/run.sh reset" % label
            )
    try:
        request_json(
            "DELETE",
            "/environments/%s/experiments/%s/" % (dev_key, experiment_id),
            base_url=base_url,
            token=token,
        )
    except LabError as exc:
        raise LabError(
            "Could not remove %s: %s. Run: bash lab/run.sh reset" % (label, exc)
        ) from exc
    print("Experiment: removed conflicting %s" % label)


def active_experiments_for_feature(
    base_url: str, token: str, dev_key: str, feature_id: int
) -> List[Dict[str, Any]]:
    experiments = get_list(
        "/environments/%s/experiments/" % dev_key, base_url=base_url, token=token
    )
    return [
        experiment
        for experiment in experiments
        if experiment_feature_id(experiment) == feature_id
        and str(experiment.get("status", "")).lower() != "completed"
    ]


def cleanup_bucket_segments(base_url: str, token: str, project_id: int) -> None:
    """Remove stale exp_iso_* segments so a rerun starts from one clean audience."""
    segments = get_list(
        "/projects/%d/segments/" % project_id, base_url=base_url, token=token
    )
    removed = []
    for segment in segments:
        name = str(segment.get("name", ""))
        if not name.startswith("exp_iso_"):
            continue
        try:
            request_json(
                "DELETE",
                "/projects/%d/segments/%s/" % (project_id, segment["id"]),
                base_url=base_url,
                token=token,
            )
        except LabError as exc:
            print("Segment: could not remove stale %s (%s); leaving it" % (name, exc))
            continue
        removed.append(name)
    if removed:
        print("Segments: removed stale %s" % ", ".join(removed))


def ensure_experiment(
    base_url: str,
    token: str,
    dev_key: str,
    spec: Dict[str, str],
    feature: Dict[str, Any],
    option: Dict[str, Any],
    metric: Dict[str, Any],
    segment: Dict[str, Any],
    start: bool,
) -> Dict[str, Any]:
    """Converge the feature to one clean draft with the shared us_mobile audience.

    A previous demo can leave running experiments; a rollback can leave
    [rollback] drafts. Flagsmith rejects a second active experiment for a
    feature with HTTP 409, so conflicting experiments are paused and removed
    before the canonical draft is created. If repair fails, the error points
    the operator at the one-command reset.
    """
    all_experiments = get_list(
        "/environments/%s/experiments/" % dev_key, base_url=base_url, token=token
    )
    for item in all_experiments:
        if (
            item.get("name") == spec["experiment"]
            and experiment_feature_id(item) not in (None, int(feature["id"]))
            and str(item.get("status", "")).lower() != "completed"
        ):
            raise LabError(
                "Experiment %r already exists on a different feature (id %s). "
                "Run: bash lab/run.sh reset"
                % (spec["experiment"], experiment_feature_id(item))
            )

    reusable: Optional[Dict[str, Any]] = None
    wanted_audience = [int(segment["id"])]
    for item in active_experiments_for_feature(base_url, token, dev_key, int(feature["id"])):
        detail = experiment_detail(base_url, token, dev_key, int(item["id"]))
        status = str(detail.get("status", "")).lower()
        audience = audience_ids_from_detail(detail)
        if (
            detail.get("name") == spec["experiment"]
            and status == "created"
            and audience == wanted_audience
        ):
            reusable = detail
            print(
                "Experiment: reusing clean draft %s (id %s, audience %s)"
                % (detail.get("name"), detail.get("id"), audience)
            )
            continue
        print(
            "Experiment: cleaning up %s (id %s, status %s, audience %s)"
            % (detail.get("name"), detail.get("id"), status, audience)
        )
        remove_experiment(base_url, token, dev_key, detail)

    if reusable is None:
        try:
            experiment = request_json(
                "POST",
                "/environments/%s/experiments/" % dev_key,
                base_url=base_url,
                token=token,
                payload=experiment_payload(spec, feature, option, metric, segment),
            )
        except LabError as exc:
            if "409" in str(exc) or "active experiment" in str(exc).lower():
                raise LabError(
                    "An active experiment still owns feature %r: %s. "
                    "Run: bash lab/run.sh reset" % (feature.get("name"), exc)
                ) from exc
            raise
        if not isinstance(experiment, dict):
            raise LabError("Experiment creation returned an unexpected response")
        print(
            "Experiment: created draft %s (id %s, audience %s)"
            % (experiment.get("name"), experiment.get("id"), SEGMENT_NAME)
        )
        experiment = experiment_detail(base_url, token, dev_key, int(experiment["id"]))
    else:
        experiment = reusable

    status = str(experiment.get("status", ""))
    if start and status == "created":
        try:
            experiment = request_json(
                "POST",
                "/environments/%s/experiments/%s/start/" % (dev_key, experiment["id"]),
                base_url=base_url,
                token=token,
                payload={},
            )
        except LabError as exc:
            raise LabError(
                "Starting experiment %s failed: %s. Run: bash lab/run.sh reset"
                % (spec["experiment"], exc)
            ) from exc
        if not isinstance(experiment, dict):
            raise LabError("Starting experiment %s returned an unexpected response" % spec["experiment"])
        print("Experiment: started %s (enrollment is now measurable)" % experiment.get("name"))
    elif status == "created":
        print("Experiment: left as draft (safe to retarget; pass --start to run it)")
    elif status == "running":
        print("Experiment: already running; audience changes now require a pause")
    elif status in ("paused", "completed"):
        print("Experiment: status is %s; seeding will not modify it" % status)
    return experiment


def current_audience_ids(
    base_url: str,
    token: str,
    dev_key: str,
    experiment_id: int,
    fallback: List[int],
) -> List[int]:
    """Read the audience actually stored on the experiment, not the seed intent."""
    try:
        detail = request_json(
            "GET",
            "/environments/%s/experiments/%s/" % (dev_key, experiment_id),
            base_url=base_url,
            token=token,
        )
    except LabError:
        return fallback
    rollout = (detail or {}).get("experiment_rollout") or {}
    audience = rollout.get("audience") or {}
    segments = audience.get("segments") or []
    ids = sorted(
        {
            int(segment["id"])
            for segment in segments
            if isinstance(segment, dict) and segment.get("id") is not None
        }
    )
    return ids or fallback


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


def main() -> int:
    args = parse_args()
    env = load_env()
    base_url = (args.api_url or env.get("LAB_API_URL") or env.get("FLAGSMITH_API_URL") or DEFAULT_API_URL).rstrip("/")
    api_base = base_url + "/api/v1"
    token = require(
        args.token or env.get("LAB_ADMIN_TOKEN") or env.get("FLAGSMITH_API_KEY"),
        "No admin token. Run: python3 lab/bootstrap.py",
    )
    project_id = args.project_id or int(require(env.get("LAB_PROJECT_ID"), "LAB_PROJECT_ID missing; run bootstrap first"))
    dev_key = args.dev_key or env.get("LAB_DEV_ENV_KEY")
    if not dev_key:
        environments = get_list(
            "/environments/?project=%d" % project_id, base_url=api_base, token=token
        )
        dev = find_by_name(environments, DEV_NAME)
        dev_key = require((dev or {}).get("api_key"), "Development environment not found")
        env["LAB_DEV_ENV_KEY"] = dev_key
    dev_id = env.get("LAB_DEV_ENV_ID", "")
    project_name = env.get("LAB_PROJECT_NAME", "")

    print("Experiment Isolation Lab seed")
    print("  API:   %s" % base_url)
    print("  Env:   %s" % ENV_PATH)
    print("  Mode:  %s" % ("draft + started" if args.start else "draft only"))
    print("")

    feature_records: List[Dict[str, Any]] = []
    for spec in FEATURES:
        feature, option = ensure_feature(api_base, token, project_id, spec)
        feature_records.append({"spec": spec, "feature": feature, "option": option})

    segment = ensure_segment(api_base, token, project_id)
    metric = ensure_metric(api_base, token, dev_key)

    experiments: List[Dict[str, Any]] = []
    state_experiments: List[Dict[str, Any]] = []
    for record in feature_records:
        experiment = ensure_experiment(
            api_base,
            token,
            dev_key,
            record["spec"],
            record["feature"],
            record["option"],
            metric,
            segment,
            args.start,
        )
        experiments.append(experiment)
        audience_ids = current_audience_ids(
            api_base,
            token,
            dev_key,
            int(experiment["id"]),
            [int(segment["id"])],
        )
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

    # A previous demo leaves exp_iso_* bucket segments behind. Remove only
    # those; never touch the shared us_mobile segment or unrelated segments.
    cleanup_bucket_segments(api_base, token, project_id)

    state = {
        "generated_at": now_iso(),
        "environment": {
            "id": int(dev_id) if str(dev_id).isdigit() else None,
            "name": DEV_NAME,
            "key_prefix": dev_key[:4],
        },
        "project": {"id": project_id, "name": project_name},
        "segment": {"id": segment["id"], "name": segment.get("name", SEGMENT_NAME)},
        "metric": {"id": metric["id"], "name": metric.get("name", METRIC_NAME)},
        "experiments": state_experiments,
        "sample_traits": SAMPLE_TRAITS,
        "notes": "Both drafts intentionally share the us_mobile segment.",
    }
    write_json(STATE_PATH, state)

    print("")
    print("Seeded %d experiments in %s." % (len(experiments), DEV_NAME))
    for record in state_experiments:
        print(
            "  - %s (id %s): %s, audience segment(s) %s"
            % (
                record.get("name"),
                record.get("id"),
                record.get("status"),
                ", ".join(str(value) for value in record.get("audience_segment_ids") or []),
            )
        )
    print("  State: %s" % STATE_PATH)
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
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LabError as exc:
        print("seed: error: %s" % exc, file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("seed: interrupted", file=sys.stderr)
        sys.exit(130)
