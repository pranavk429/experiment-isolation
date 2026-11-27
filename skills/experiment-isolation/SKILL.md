---
name: experiment-isolation
description: Prevent overlapping A/B experiments from contaminating each other. Use before you run another experiment, or when you suspect overlapping experiments, an experiment collision, or audience overlap. Plans mutual exclusion with deterministic bucket segments, applies only with an approval token, verifies zero overlap, and helps you isolate experiments in a local Flagsmith environment.
metadata: {"repository": "https://github.com/pranavk429/experiment-isolation"}
---

# Experiment Isolation

Before you run another experiment, prove its audience is disjoint from experiments already launched, or make it disjoint with explicit human approval. The engine samples identities and computes enrollment; draft enrollment is labeled projected, not measured. This skill only orchestrates the CLI.

## When to use

- Before you run another experiment in one Flagsmith environment.
- Suspected overlapping experiments, experiment collision, or audience overlap.
- You need mutual exclusion without percentage splits.

Do not use this for post-launch analysis, and never to modify running experiments.

## Safety rules

- **Read-only by default.** `audit` and `plan` never change experiments, segments, rollouts, or status. Audit persists traits on synthetic identities for measurement only.
- **Never modify running experiments.** Apply only to pre-launch drafts (`status: created`). Experiments already running or paused are refused with exit 10; the operator must complete/delete and recreate them. Pausing does not free a started experiment, so do not pause or patch it as an isolation step.
- **Approval token required.** `apply` needs the exact approval token (`approval_token` in the current `plan.json`, `iso-<8 hex>`) and an explicit human yes for that plan. Never invent, reuse, or silently edit a token.
- **Roll back after any partial failure.** Use the engine-owned rollback, never a hand-written `flagsmith api` recipe:

  ```sh
  python3 -m engine.cli rollback --apply apply.json --out rollback.json
  ```

  If `rollback.json` reports `requires_recreate`, say the started experiment must be completed/deleted and recreated. Do not claim a live rollback.
- **Local/development only.** Use `$DEV_ENV_KEY`; never production or Cloud. Never print API keys or environment keys. The approval token is a short confirmation string, not a secret, and is safe to display.
- **Disclose synthetic identities.** Samples are synthetic, their traits persist, and measured or projected enrollment is not real traffic. Use a disposable environment for demos.
- Do not bypass the engine with raw `curl` or ad-hoc admin writes. Details: `references/safety.md`.

## Setup

Use the instance you intend; no path is assumed. Require `FLAGSMITH_API_URL`; a host-scoped `FLAGSMITH_API_KEY_<host>_<port>` (or `FLAGSMITH_API_KEY`); `FLAGSMITH_PROJECT`; and `FLAGSMITH_ENVIRONMENT` (lab `.env` may expose `FLAGSMITH_ENVIRONMENT_KEY`). Commands also need `DEV_ENV_KEY` or `--env`.

From the repo root:

```sh
source ~/flagsmith-local/flagsmith.env   # research instance
# source lab/.env                        # self-hosted lab
export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"
bash skills/experiment-isolation/scripts/check_env.sh
```

`check_env.sh` reads exported variables or `FLAGSMITH_ENV_FILE=<path>`; it verifies the CLI and local `/health` without printing secrets.

## Workflow

### 1. Audit (read-only)

```sh
python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json
```

Audit exit 10 = collision: read `audit.json` and continue to plan. If `verdict` is `clear` or `none`, report and stop.

Read only `verdict`, `collisions`, and each overlap's `jaccard`, `shared`, and `verdict`; note each experiment's `basis` (`projected` for drafts, `measured` otherwise). Keep raw JSON on disk; never dump it.

### 2. Plan

```sh
python3 -m engine.cli plan --audit audit.json --out plan.json
```

Plan does read-only GETs, not offline. Exit 10 = infeasible or deferred: report `notes` and stop. If a note suggests pausing, ignore it: paused experiments cannot change audience. The only paths are pre-launch isolation or complete/delete + recreate. Otherwise show the bucket ranges, audience changes, `rollback`, and `approval_token`; ask for explicit approval. Ranges cover 0-99.

### 3. Apply (after approval)

```sh
python3 -m engine.cli apply --plan plan.json --approve "<approval-token>" --out apply.json
```

Use the exact token. Exit 10 = refusal or approval failure: stop and report. Exit 20 = error: stop and roll back if anything changed. Never rerun with an edited plan.

### 4. Verify

```sh
python3 -m engine.cli verify --plan plan.json --samples 500 --workers 2 --out verify.json
```

Use `--workers 2` for stability on the local instance; higher concurrency is optional. Success = exit 0, `pass: true`, and every pair verdict `isolated`. `isolated` is a verify verdict, never an audit verdict. Exit 10 or `pass: false` = residual overlap: stop, roll back, do not claim isolation.

### 5. Receipt

```sh
python3 -m engine.cli receipt --audit audit.json --plan plan.json --apply apply.json --verify verify.json --out receipt.json
```

Pass all four artifacts so the receipt includes audit, plan, apply, and verify token counts. Report only the receipt highlights: before/after verdict, sample size, changes, rollback, and token counts. The receipt is roughly 100-125 tokens depending on tokenizer; do not claim under 100. If you need a number:

```sh
python3 skills/experiment-isolation/scripts/token_count.py receipt.json
```

It prints one integer: tiktoken (`o200k_base`) when installed, otherwise ceil(characters/4).

## Installed-skill wrapper

When copied to `~/.claude/skills/experiment-isolation`, use `scripts/run.sh` with the same arguments:

```sh
skills/experiment-isolation/scripts/run.sh audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json
```

It resolves the repo root from `EXPERIMENT_ISOLATION_ROOT`, script ancestry, or `$PWD`, then delegates to `python3 -m engine.cli "$@"`; no business logic.

## References

- `references/api.md` - endpoints, payloads, audience constraints, bucket rules, enrollment metadata.
- `references/safety.md` - approval, refusal, rollback, synthetic-identity disclosure.
- `references/troubleshooting.md` - verdicts, percentage-split, rollout, sample-size, missing-trait, and install errors.

## Output and exit codes

- Exit 0 success; 20 error. Audit 10 = collision, continue; plan/apply/verify/receipt 10 = stop (rollback after partial apply).
- Read compact fields and the receipt, not raw API payloads. Keep JSON on disk.
- Do not reimplement engine logic; the engine owns it.
