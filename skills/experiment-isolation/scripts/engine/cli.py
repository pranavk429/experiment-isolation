"""Command line interface for Experiment Isolation."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

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
    sanitize_text,
)
from .verify import run_verify


def _add_isolation_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register audit, plan, apply, and verify subcommands."""
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
    verify.add_argument("--sample-prefix", default="iso", help="identity prefix (default: iso)")
    verify.add_argument("--out", help="write verify JSON here")
    verify.add_argument("--cleanup", action="store_true")
    verify.add_argument("--env", help="environment key (defaults to DEV_ENV_KEY)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m engine.cli",
        description="Discover overlapping Flagsmith experiments and isolate draft audiences.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_isolation_subparsers(subparsers)

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
    summary = (
        f"audit: {len(report['experiments'])} experiment(s), "
        f"{len(report['collisions'])} collision(s), "
        f"sample={report['sample_size']}, verdict={report['verdict']}"
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
    summary = (
        f"plan: feasible={plan.get('feasible')}, {changes} audience change(s), "
        f"width={plan.get('bucket_width')}, token={plan.get('approval_token') or 'none'}, "
        f"before_jaccard={plan.get('before_jaccard')}"
    )
    emit(plan, args.out, summary)
    return EXIT_OK if plan.get("feasible") else EXIT_REFUSED


def _apply(args: argparse.Namespace) -> int:
    plan = read_json(args.plan)
    config = Config.load(args.env)
    result = run_apply(
        config, plan, args.approve or "", out_dir=_out_dir(args.out) or str(Path.cwd())
    )
    segments = result.get("segments") or {}
    summary = (
        f"apply: {len(result.get('changes') or [])} experiment(s) running; "
        f"steps={len(result.get('steps') or [])}; "
        f"segments created={len(segments.get('created') or [])} "
        f"reused={len(segments.get('reused') or [])}; pass={result.get('pass')}"
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
        sample_prefix=args.sample_prefix,
    )
    summary = (
        f"verify: before={result.get('before_jaccard')} "
        f"after={result.get('after_jaccard')} "
        f"pass={result.get('pass')} sample={result.get('sample_size')}"
    )
    emit(result, args.out, summary)
    return EXIT_OK if result.get("pass") else EXIT_REFUSED


def _receipt(args: argparse.Namespace) -> int:
    audit = read_json(args.audit)
    plan = read_json(args.plan)
    verify = read_json(args.verify)
    apply_result = read_json(args.apply_file) if args.apply_file else None
    receipt = build_receipt(audit, plan, verify, apply_result)
    summary = (
        f"receipt: before={receipt['before']['verdict']} "
        f"after={receipt['after']['verdict']} pass={receipt['pass']}"
    )
    emit(receipt, args.out, summary)
    return EXIT_OK if receipt.get("pass") else EXIT_REFUSED


def _rollback(args: argparse.Namespace) -> int:
    apply_result = read_json(args.apply_file)
    plan = read_json(args.plan) if args.plan else None
    config = Config.load(args.env)
    result = run_rollback(config, apply_result, plan)
    summary = (
        f"rollback: actions={len(result.get('experiments') or [])}; "
        f"live_restore={result.get('live_restore')}; "
        f"requires_recreate={result.get('requires_recreate')}; "
        f"segments_deleted={len(result.get('segments_deleted') or [])}; "
        f"pass={result.get('pass')}"
    )
    emit(result, args.out, summary)
    return EXIT_OK if result.get("pass") else EXIT_REFUSED


def _seed(args: argparse.Namespace) -> int:
    result = run_seed(count=args.experiments, reset=args.reset)
    statuses = ", ".join(
        f"{row['id']}={row.get('status')}" for row in result.get("experiments") or []
    )
    sys.stdout.write(f"{compact_json(result)}\n")
    sys.stderr.write(f"seed: statuses={statuses}; started={result.get('started')}\n")
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
        sys.stdout.write(f"{compact_json({'error': str(exc), 'exit_code': EXIT_REFUSED})}\n")
        sys.stderr.write(f"refused: {exc}\n")
        return EXIT_REFUSED
    except (ConfigError, EngineError) as exc:
        sys.stdout.write(f"{compact_json({'error': str(exc), 'exit_code': EXIT_ERROR})}\n")
        sys.stderr.write(f"error: {exc}\n")
        return EXIT_ERROR
    except Exception as exc:  # no traceback escapes the exit-code contract
        secrets = [
            secret
            for name, secret in os.environ.items()
            if secret
            and (
                name.endswith("ENV_KEY")
                or name.startswith("FLAGSMITH_API_KEY")
                or name == "ADMIN_TOKEN"
            )
        ]
        message = sanitize_text(f"{type(exc).__name__}: {exc}", *secrets)
        sys.stdout.write(f"{compact_json({'error': message, 'exit_code': EXIT_ERROR})}\n")
        sys.stderr.write(f"error: {message}\n")
        return EXIT_ERROR
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
