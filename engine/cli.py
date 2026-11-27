"""Command line interface for Experiment Isolation."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .apply import run_apply
from .audit import run_audit
from .config import Config
from .plan import build_plan
from .receipt import build_receipt
from .rollback import run_rollback
from .seed import run_seed
from .util import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_REFUSED,
    ConfigError,
    EngineError,
    Refusal,
    compact_json,
    emit,
    read_json,
)
from .verify import run_verify


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m engine.cli",
        description="Discover overlapping Flagsmith experiments and isolate draft audiences.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="measure experiment audience overlap")
    audit.add_argument("--env", help="environment key (defaults to DEV_ENV_KEY)")
    audit.add_argument("--samples", type=int, default=500)
    audit.add_argument("--threshold", type=float, default=0.05)
    audit.add_argument("--workers", type=int, default=4)
    audit.add_argument("--out", help="write audit JSON here")
    audit.add_argument("--cleanup", action="store_true", help="delete synthetic identities after")

    plan = subparsers.add_parser("plan", help="plan disjoint bucket audiences")
    plan.add_argument("--audit", required=True)
    plan.add_argument("--out", help="write plan JSON here")
    plan.add_argument("--env", help="environment key (defaults to DEV_ENV_KEY)")
    plan.add_argument("--max-concurrent", type=int, default=4)
    plan.add_argument("--min-bucket-width", type=int, default=5)

    apply_parser = subparsers.add_parser("apply", help="apply a plan with its approval token")
    apply_parser.add_argument("--plan", required=True)
    apply_parser.add_argument("--approve", help="exact approval token from plan.json")
    apply_parser.add_argument("--out", help="write apply JSON here")
    apply_parser.add_argument("--env", help="environment key (defaults to DEV_ENV_KEY)")

    verify = subparsers.add_parser("verify", help="resample and prove isolation")
    verify.add_argument("--plan", required=True)
    verify.add_argument("--samples", type=int, default=500)
    verify.add_argument("--workers", type=int, default=4)
    verify.add_argument("--out", help="write verify JSON here")
    verify.add_argument("--cleanup", action="store_true")
    verify.add_argument("--env", help="environment key (defaults to DEV_ENV_KEY)")

    receipt = subparsers.add_parser("receipt", help="combine artifacts into a receipt")
    receipt.add_argument("--audit", required=True)
    receipt.add_argument("--plan", required=True)
    receipt.add_argument("--verify", required=True)
    receipt.add_argument("--apply", dest="apply_file", help="optional apply.json")
    receipt.add_argument("--out", help="write receipt JSON here")

    rollback = subparsers.add_parser("rollback", help="restore or recreate applied drafts")
    rollback.add_argument("--apply", dest="apply_file", required=True)
    rollback.add_argument("--plan", help="optional plan.json for restore state")
    rollback.add_argument("--out", help="write rollback JSON here")
    rollback.add_argument("--env", help="environment key (defaults to DEV_ENV_KEY)")

    seed = subparsers.add_parser("seed", help="create the two draft collision experiments")
    seed.add_argument("--experiments", type=int, default=2, choices=(2, 3))
    seed.add_argument("--reset", action="store_true")
    return parser


def _out_dir(out: Optional[str]) -> Optional[str]:
    if not out:
        return None
    parent = Path(out).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    return str(parent)


def _audit(args: argparse.Namespace) -> int:
    config = Config.load(args.env)
    report = run_audit(
        config,
        samples=args.samples,
        threshold=args.threshold,
        workers=args.workers,
        cleanup=args.cleanup,
    )
    summary = "audit: %d experiment(s), %d collision(s), sample=%d, verdict=%s" % (
        len(report["experiments"]),
        len(report["collisions"]),
        report["sample_size"],
        report["verdict"],
    )
    emit(report, args.out, summary)
    return EXIT_REFUSED if report.get("verdict") == "collision" else EXIT_OK


def _plan(args: argparse.Namespace) -> int:
    audit = read_json(args.audit)
    config = Config.load(args.env) if args.env else None
    plan = build_plan(
        audit,
        config=config,
        max_concurrent=args.max_concurrent,
        min_bucket_width=args.min_bucket_width,
    )
    changes = len(plan.get("audience_changes") or [])
    summary = "plan: feasible=%s, %d audience change(s), width=%s, token=%s, before_jaccard=%s" % (
        plan.get("feasible"),
        changes,
        plan.get("bucket_width"),
        plan.get("approval_token") or "none",
        plan.get("before_jaccard"),
    )
    emit(plan, args.out, summary)
    return EXIT_OK if plan.get("feasible") else EXIT_REFUSED


def _apply(args: argparse.Namespace) -> int:
    plan = read_json(args.plan)
    config = Config.load(args.env)
    result = run_apply(
        config, plan, args.approve or "", out_dir=_out_dir(args.out) or str(Path.cwd())
    )
    summary = (
        "apply: %d experiment(s) running; steps=%d; segments created=%d reused=%d; pass=%s"
        % (
            len(result.get("changes") or []),
            len(result.get("steps") or []),
            len((result.get("segments") or {}).get("created") or []),
            len((result.get("segments") or {}).get("reused") or []),
            result.get("pass"),
        )
    )
    emit(result, args.out, summary)
    return EXIT_OK if result.get("pass") else EXIT_REFUSED


def _verify(args: argparse.Namespace) -> int:
    plan = read_json(args.plan)
    config = Config.load(args.env)
    result = run_verify(
        config,
        plan,
        samples=args.samples,
        workers=args.workers,
        cleanup=args.cleanup,
    )
    summary = "verify: before=%s after=%s pass=%s sample=%d" % (
        result.get("before_jaccard"),
        result.get("after_jaccard"),
        result.get("pass"),
        result.get("sample_size"),
    )
    if args.out:
        from .util import write_json

        write_json(args.out, result)
        sys.stderr.write(summary + " -> " + args.out + "\n")
    else:
        sys.stdout.write(compact_json(result) + "\n")
        sys.stderr.write(summary + " -> stdout\n")
    return EXIT_OK if result.get("pass") else EXIT_REFUSED


def _receipt(args: argparse.Namespace) -> int:
    audit = read_json(args.audit)
    plan = read_json(args.plan)
    verify = read_json(args.verify)
    apply_result = read_json(args.apply_file) if args.apply_file else None
    receipt = build_receipt(audit, plan, verify, apply_result)
    summary = "receipt: before=%s after=%s pass=%s" % (
        receipt["before"]["verdict"],
        receipt["after"]["verdict"],
        receipt["pass"],
    )
    emit(receipt, args.out, summary)
    return EXIT_OK if receipt.get("pass") else EXIT_REFUSED


def _rollback(args: argparse.Namespace) -> int:
    apply_result = read_json(args.apply_file)
    plan = read_json(args.plan) if args.plan else None
    config = Config.load(args.env)
    result = run_rollback(config, apply_result, plan)
    summary = (
        "rollback: actions=%d; live_restore=%s; requires_recreate=%s; "
        "segments_deleted=%d; pass=%s"
        % (
            len(result.get("experiments") or []),
            result.get("live_restore"),
            result.get("requires_recreate"),
            len(result.get("segments_deleted") or []),
            result.get("pass"),
        )
    )
    emit(result, args.out, summary)
    return EXIT_OK if result.get("pass") else EXIT_REFUSED


def _seed(args: argparse.Namespace) -> int:
    result = run_seed(count=args.experiments, reset=args.reset)
    statuses = ", ".join(
        "%s=%s" % (row["id"], row.get("status")) for row in result.get("experiments") or []
    )
    sys.stdout.write(compact_json(result) + "\n")
    sys.stderr.write("seed: statuses=%s; started=%s\n" % (statuses, result.get("started")))
    return EXIT_OK


COMMANDS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "audit": _audit,
    "plan": _plan,
    "apply": _apply,
    "verify": _verify,
    "receipt": _receipt,
    "rollback": _rollback,
    "seed": _seed,
}


def main(argv: Optional[list] = None) -> int:
    """Parse arguments, dispatch, and map errors to exit codes 0/10/20."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except Refusal as exc:
        sys.stdout.write(compact_json({"error": str(exc), "exit_code": EXIT_REFUSED}) + "\n")
        sys.stderr.write("refused: %s\n" % exc)
        return EXIT_REFUSED
    except ConfigError as exc:
        sys.stdout.write(compact_json({"error": str(exc), "exit_code": EXIT_ERROR}) + "\n")
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR
    except EngineError as exc:
        sys.stdout.write(compact_json({"error": str(exc), "exit_code": EXIT_ERROR}) + "\n")
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_ERROR
    except Exception as exc:  # no traceback escapes the exit-code contract
        message = "%s: %s" % (type(exc).__name__, exc)
        for name, secret in os.environ.items():
            if secret and (
                name.endswith("ENV_KEY")
                or name.startswith("FLAGSMITH_API_KEY")
                or name == "ADMIN_TOKEN"
            ):
                message = message.replace(secret, "<redacted>")
        sys.stdout.write(
            compact_json({"error": message[:400], "exit_code": EXIT_ERROR}) + "\n"
        )
        sys.stderr.write("error: %s\n" % message[:400])
        return EXIT_ERROR
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
