#!/usr/bin/env python3
"""Write an explicitly-labelled sample audit.json from the seed state.

This is the graceful fallback for lab/run.sh when engine.cli is not available
yet. It never pretends to be a measured audit: _meta.source is "sample" and the
dashboard renders a visible SAMPLE chip.

The shape matches the engine contract's audit.json so the dashboard and any
consumer can be developed before the engine lands.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lablib import LAB_DIR, LabError, now_iso, read_json, write_json

DASHBOARD_DIR = LAB_DIR / "dashboard"
DEFAULT_STATE = LAB_DIR / "seed" / "seed_state.json"
DEFAULT_SAMPLE = DASHBOARD_DIR / "audit.sample.json"
DEFAULT_OUT = DASHBOARD_DIR / "audit.json"


def _audience_ids(experiment: Dict[str, Any]) -> Set[int]:
    return {
        int(value)
        for value in (experiment.get("audience_segment_ids") or [])
        if str(value).isdigit()
    }


def _pair_jaccard(left: Dict[str, Any], right: Dict[str, Any]) -> float:
    left_ids = _audience_ids(left)
    right_ids = _audience_ids(right)
    if not left_ids or not right_ids or left_ids == right_ids:
        return 1.0
    if left_ids.isdisjoint(right_ids):
        return 0.0
    # Partial segment overlap is unknown without identities; use a midpoint.
    return 0.5


def _build_overlaps(experiments: List[Dict[str, Any]], threshold: float) -> List[Dict[str, Any]]:
    overlaps: List[Dict[str, Any]] = []
    for left_index, left in enumerate(experiments):
        for right in experiments[left_index + 1 :]:
            jaccard = _pair_jaccard(left, right)
            shared = int(round(500 * jaccard / (1 + jaccard))) if jaccard > 0 else 0
            overlaps.append(
                {
                    "a": left["id"],
                    "b": right["id"],
                    # The seeded population is 50% US/mobile. Illustrative only.
                    "shared": shared,
                    "union": 500 - shared,
                    "jaccard": jaccard,
                    "a_rate": 0.5,
                    "b_rate": 0.5,
                    "verdict": "collision" if jaccard > threshold else "isolated",
                }
            )
    return overlaps


def build_from_state(state: Dict[str, Any], threshold: float, reason: str) -> Dict[str, Any]:
    experiments: List[Dict[str, Any]] = list(state.get("experiments") or [])
    if not experiments:
        raise LabError("seed state has no experiments; run python3 lab/seed/seed.py first")

    overlaps = _build_overlaps(experiments, threshold)
    collisions = [[ov["a"], ov["b"]] for ov in overlaps if ov["jaccard"] > threshold]
    max_jaccard = max([ov["jaccard"] for ov in overlaps] or [0.0])
    verdict = "collision" if collisions else "isolated"
    segment = state.get("segment") or {}
    return {
        "_meta": {
            "source": "sample",
            "reason": reason,
            "generated_at": now_iso(),
            "note": (
                "Illustrative fallback built from lab seed state. It is not a measured "
                "audit. Run lab/run.sh after engine.cli exists to replace it."
            ),
        },
        "environment": state.get("environment")
        or {"id": None, "name": "Development", "key_prefix": "lab"},
        "sample_size": 500,
        "threshold": threshold,
        "experiments": experiments,
        "overlaps": overlaps,
        "collisions": collisions,
        "verdict": verdict,
        "sample_traits": state.get("sample_traits")
        or ["country", "platform", "flagsmith_experiment_bucket"],
        "audience_segment": {"id": segment.get("id"), "name": segment.get("name", "us_mobile")},
        "before_after": {
            "before": {"max_jaccard": max_jaccard, "verdict": verdict},
            "after": {
                "max_jaccard": 0.0 if verdict == "collision" else max_jaccard,
                "verdict": "isolated",
            },
            "note": (
                "Illustrative target only. Real before/after is read from "
                "receipt.json or verify.json after plan/apply/verify."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--threshold", type=float, default=0.05)
    parser.add_argument(
        "--reason",
        default="engine.cli is not available in this checkout",
        help="Why the sample fallback was used (shown in the dashboard).",
    )
    args = parser.parse_args()

    state = read_json(args.state)
    if isinstance(state, dict) and state.get("experiments"):
        audit = build_from_state(state, args.threshold, args.reason)
    else:
        audit = read_json(args.sample)
        if not isinstance(audit, dict):
            raise LabError(
                "No seed state and no audit.sample.json. Run python3 lab/seed/seed.py first."
            )
        audit.setdefault("_meta", {})
        audit["_meta"].update(
            {
                "source": "sample",
                "reason": args.reason,
                "generated_at": now_iso(),
            }
        )
    write_json(args.out, audit)
    print(f"Sample audit written to {args.out}")
    print(f"  Source: sample ({args.reason})")
    print("  This is illustrative; it will be replaced by engine.cli audit when available.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LabError as exc:
        print(f"sample_audit: error: {exc}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("sample_audit: interrupted", file=sys.stderr)
        sys.exit(130)
