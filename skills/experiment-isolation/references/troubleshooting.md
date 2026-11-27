# Troubleshooting

Work from compact JSON artifacts; do not dump raw API payloads. Commands below use `bash scripts/run.sh` (which runs standalone from any installed skill copy and writes `--out` relative to `$PWD`); `python3 -m engine.cli` is equivalent when installed or with `PYTHONPATH`.

## Audit exits 10 / verdict collision

This is the expected collision signal, not an error. `audit.json` is still written; read its compact fields and continue to `plan`. Do not abort or re-run `audit` just because the exit code is 10.

## Audit verdict clear or none

Exit 0 means no collision was found above `--threshold`. Report that and stop; do not `plan` or `apply`. If you expected a collision, check the environment key (`DEV_ENV_KEY` or `FLAGSMITH_ENVIRONMENT_KEY`), verify experiments are non-completed (`created`, `paused`, `running`), verify their audience segments overlap, and increase `--samples`.

## Verify verdict isolated

`isolated` belongs to `verify`, never `audit`. After `apply`, success is exit 0, `pass: true`, every planned experiment `running`, `enrolled > 0`, and every pair with verdict `isolated`. If `pass` is false or any pair is `collision`, stop, run `rollback`, and do not claim isolation.

## "Audience segment N contains a percentage split"

The target segment has a `PERCENTAGE_SPLIT` condition. Remove it and use bucket trait ranges (`GREATER_THAN_INCLUSIVE`, `LESS_THAN`) on `flagsmith_experiment_bucket`. Regenerate the plan; never patch a segment by hand while experiments use it.

## "Cannot change the audience while the rollout is enabled and serving traffic. Disable the rollout first."

The audience patch ran before the rollout was disabled. Always use `apply`; it patches `"enabled": false` first and verifies via read-back. If this appears mid-apply, stop, run `rollback`, regenerate the plan, and retry. Do not manually disable a running experiment.

## "Cannot change the audience of a paused experiment" / running experiment / exit 10

Pausing is not an isolation step; paused audiences are immutable. The only paths are pre-launch isolation or complete/delete + recreate. If a plan note mentions pausing, ignore any pause-to-isolate suggestion. The operator must explicitly decide to complete/delete and recreate; this skill never pauses or patches a running experiment.

## Sample too small, empty enrollment, or overlap unstable

Increase `--samples` (for example `500` to `2000`, max `5000`) and rerun `audit` and `verify`. Rare segments need more samples; report the sample size with every `jaccard`. Note that `audit` generates synthetic traits from `country` (`US`/`GB`) and `platform` (`mobile`/`desktop`); if a composed segment (`exp_iso_<slug>_<lo>_<hi>`) requires traits absent from that matrix, `enrolled` will be `0` and `verify` will fail `pass: false`. If the sample cannot resolve the question, report that honestly instead of claiming isolation.

On local instances, run `verify` with `--workers 2` for stability:

```sh
bash scripts/run.sh verify --plan plan.json --samples 500 --workers 2 --out verify.json
```

## Missing bucket trait / empty segment

Numeric trait rules do not match identities without `flagsmith_experiment_bucket`. Ensure `flagsmith evaluate --persist --json` succeeded and `EdgeAPI` read back matching traits (integer `0-99`), and confirm the segment belongs to the experiment's project. Rerun `audit` to repopulate traits.

## 401 / 403 / connection refused / non-local URL refusal

Run `bash scripts/check_env.sh` with `FLAGSMITH_ENV_FILE=<path>` (for example `FLAGSMITH_ENV_FILE=lab/.env`) or after exporting `FLAGSMITH_API_URL`, `FLAGSMITH_API_KEY_<host>_<port>` (or `FLAGSMITH_API_KEY`), `FLAGSMITH_PROJECT`, and `DEV_ENV_KEY` (or `FLAGSMITH_ENVIRONMENT_KEY`). Confirm Flagsmith responds at `${FLAGSMITH_API_URL}/health`. `Config.load()` refuses non-local hosts unless `ISO_ALLOW_REMOTE=1` is set for a disposable host. Never print API/environment keys in chat or argv, and never switch to Flagsmith Cloud.

## "No module named engine"

Use `bash scripts/run.sh <subcommand> ...` (from `~/.claude/skills/experiment-isolation/scripts/run.sh`, `~/.codex/skills/experiment-isolation/scripts/run.sh`, or `skills/experiment-isolation/scripts/run.sh`), which bundles `scripts/engine/` automatically and keeps `--out` relative to `$PWD`. If you prefer `python3 -m engine.cli ...` directly, install the repo (`pip install -e .`) or add the skill's `scripts/` directory to `PYTHONPATH`.

## Approval token rejected

Pass the exact `approval_token` from the current `plan.json` (or `noop` only for an empty no-op plan). Tokens are HMAC-SHA256 bound to the plan contents and environment; if the plan was regenerated or edited, the token is stale. Re-run `plan` and get fresh human approval—never guess or edit `plan.json`.

## Apply partially failed

Stop immediately. Run rollback against `apply-failure.json` (written in the `--out` directory on mid-apply failure) or `apply.json`, then verify:

```sh
bash scripts/run.sh rollback --apply apply-failure.json --out rollback.json
```

Do not rerun `apply` blindly. If `rollback.json` reports `requires_recreate`, report clearly that the started experiment was deleted and recreated as a draft; do not claim a live in-place rollback.

## Receipt token count looks wrong

The receipt is roughly 100-125 tokens depending on tokenizer; do not claim under 100. `python3 scripts/token_count.py receipt.json` prints one integer (`o200k_base` via `tiktoken` when installed, else `ceil(characters/4)`). Ensure `receipt.json` is compact JSON (no pretty-printing) and generated with `--apply apply.json`.
