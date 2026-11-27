---
name: experiment-isolation
description: Prevent overlapping A/B experiments from contaminating each other. Use before you run another experiment, or when you suspect overlapping experiments, an experiment collision, or audience overlap. Plans mutual exclusion with deterministic bucket segments, applies only with an approval token, verifies zero overlap, and helps you isolate experiments in a local Flagsmith environment.
metadata: {"repository": "https://github.com/pranavk429/experiment-isolation"}
---

# Experiment Isolation

Prove an experiment's audience is disjoint from active tests before launch, or isolate colliding drafts with human approval. The engine samples synthetic identities, evaluates flags, computes overlap, and labels draft enrollment `projected` (`measured` for started tests).

## When to use

- Before running another experiment, on suspected overlapping experiments, experiment collision, or audience overlap, or for mutual exclusion without `PERCENTAGE_SPLIT`.
- Not for post-launch analysis or modifying running/paused experiments.

## Safety rules

- **Read-only by default.** `audit` and `plan` never mutate experiments, segments, rollouts, or status (`audit` persists synthetic traits only).
- **Never modify running experiments.** Apply touches `status: created` drafts only; running/paused tests exit 10. Ignore pause-to-isolate suggestions—paused audiences are immutable; the only paths are pre-launch isolation or complete/delete + recreate.
- **Approval token.** `apply` requires exact `approval_token` (`iso-<8 hex>`) from `plan.json` and human approval; it is a confirmation string (safe to display), never invent/edit/reuse tokens.
- **Engine rollback.** Never hand-write `flagsmith api` or `curl`/HTTP recipes; run `python3 -m engine.cli rollback --apply apply.json --out rollback.json` (or `bash scripts/run.sh rollback ...`). If `rollback.json` reports `requires_recreate`, report the started test was deleted and recreated as a draft—never claim live rollback.
- **Local/disposable & secrets.** Use `DEV_ENV_KEY` or `FLAGSMITH_ENVIRONMENT_KEY`, never production/Cloud (`ISO_ALLOW_REMOTE=1` for disposable hosts only). Never print API keys or environment keys.
- **Synthetic & JSON rules.** Samples are synthetic, traits persist, and projected/measured counts are not real traffic. Keep raw JSON on disk; never dump payloads (`references/safety.md`).

## Setup and execution

`bash scripts/run.sh <subcommand> ...` runs standalone from an installed skill dir and writes `--out` to `$PWD`. With `pip install -e .`, `PYTHONPATH=skills/experiment-isolation/scripts`, or from repo root, `python3 -m engine.cli ...` also works.

Env vars (exported or `FLAGSMITH_ENV_FILE=<path>`, e.g., `lab/.env`): `FLAGSMITH_API_URL`, `FLAGSMITH_API_KEY_<host>_<port>` or `FLAGSMITH_API_KEY`, `FLAGSMITH_PROJECT`, `DEV_ENV_KEY` or `FLAGSMITH_ENVIRONMENT_KEY`. Check CLI and `/health`: `bash scripts/check_env.sh` (presence only).

**CLI vs. HTTP:** Evaluation uses `flagsmith evaluate --persist --json`; `AdminAPI` and `EdgeAPI` use stdlib HTTP for status checks and read-back verification (never `flagsmith api`).

## Workflow

### 1. Audit (read-only)

```sh
bash scripts/run.sh audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json
```

Exit 10 = collision: read `verdict`, `collisions`, `jaccard`/`shared`/`verdict`, and `basis` (`projected` drafts, `measured` otherwise), then continue to `plan`. `clear`/`none` (exit 0) -> report and stop.

### 2. Plan (read-only GETs)

```sh
bash scripts/run.sh plan --audit audit.json --out plan.json
```

Read-only GETs (not offline). Exit 10 = infeasible/deferred: report `notes` and stop. Shared non-empty segment targeting (e.g., `us_mobile`) composes with `flagsmith_experiment_bucket` (`exp_iso_<segment>_<lo>_<hi>`) to preserve audience targeting. Show 0-99 ranges, audience changes, `rollback`, and `approval_token`; get approval.

### 3. Apply (after approval)

```sh
bash scripts/run.sh apply --plan plan.json --approve "<approval-token>" --out apply.json
```

Exact token required. Exit 10 = refusal/approval failure -> stop. Exit 20 = error -> stop and roll back if changed. Never rerun an edited plan.

### 4. Verify

```sh
bash scripts/run.sh verify --plan plan.json --samples 500 --workers 2 --out verify.json
```

Use `--workers 2` locally. By default `verify` re-evaluates the paired 500-identity cohort (`iso_0001..iso_0500`) against live flags; pass `--sample-prefix` for a fresh uncached prefix. Success = exit 0, `pass: true`, every pair `isolated` (verify verdict, never an audit verdict). Exit 10 or `pass: false` = residual overlap -> stop, roll back, do not claim isolation.

### 5. Receipt

```sh
bash scripts/run.sh receipt --audit audit.json --plan plan.json --apply apply.json --verify verify.json --out receipt.json
```

Pass all four artifacts for audit/plan/apply/verify token counts; report highlights only. Receipt is roughly 100-125 tokens (do not claim under 100); `python3 scripts/token_count.py receipt.json` prints one integer (`o200k_base` or `ceil(chars/4)`).

## Exit codes & references

- Exit `0` success; `20` error; audit `10` = collision (continue); other `10` = stop (roll back after partial apply). Never reimplement engine logic.
- `references/api.md`, `references/safety.md`, `references/troubleshooting.md`.
