# Troubleshooting

Work from the compact JSON; do not dump raw API payloads.

## Audit exits 10 / verdict collision

This is the expected collision signal, not an error. `audit.json` is still written; read it and continue to `plan`. Do not abort or re-run audit just because the exit code is 10.

## Audit verdict clear or none

Exit 0 means no collision was found. Report that and stop; do not plan or apply. If you expected a collision, check the environment key, that experiments are non-completed, that their audience segments overlap, and that the sample size is large enough.

## Verify verdict isolated

`isolated` belongs to `verify`, not `audit`. After apply, success is exit 0, `pass: true`, and every pair with verdict `isolated`. If `pass` is false or any pair is `collision`, stop, run rollback, and do not claim isolation.

## "Audience segment N contains a percentage split"

The target segment has a `PERCENTAGE_SPLIT` condition. Remove it and use bucket trait ranges (`LESS_THAN`, `GREATER_THAN_INCLUSIVE`) on `flagsmith_experiment_bucket`. Regenerate the plan; never patch a segment by hand while experiments use it.

## "Cannot change the audience while the rollout is enabled and serving traffic. Disable the rollout first."

The audience patch ran before the rollout was disabled. Use `apply`; it patches `enabled:false` first. If this appears mid-apply, stop and run rollback, regenerate the plan, and retry. Do not manually disable a running experiment.

## "Cannot change the audience of a paused experiment" / running experiment / exit 10

Pausing is not an isolation step; paused audiences are immutable. The only paths are pre-launch isolation or complete/delete + recreate. If a plan note suggests pausing, ignore it. The operator must explicitly accept the recreation; the skill never pauses or patches a running experiment.

## Sample too small or overlap unstable

Increase `--samples` (for example 500 to 2000) and rerun audit and verify. Rare segments need more samples; report the sample size with every jaccard. If the sample cannot resolve the question, say so rather than claiming isolation.

On the local instance, run verify with `--workers 2` for stability; higher concurrency is optional:

```sh
python3 -m engine.cli verify --plan plan.json --samples 500 --workers 2 --out verify.json
```

## Missing bucket trait / empty segment

Numeric trait rules do not match identities without `flagsmith_experiment_bucket`. Ensure the engine persisted the trait for every sampled identity. Re-run audit to repopulate; check that the value is an integer 0-99 and that the segment belongs to the experiment's project.

## 401 / 403 / connection refused

Run `bash skills/experiment-isolation/scripts/check_env.sh` with `FLAGSMITH_ENV_FILE=<path>` or after sourcing your instance env file (`~/flagsmith-local/flagsmith.env` for research, `lab/.env` for the lab); confirm local Flagsmith is up at the health URL. Never paste an API or environment key into chat or argv. The approval token is safe to display. Do not switch to Cloud.

## "No module named engine" / wrapper cannot find repo root

Run from the repository root or set `EXPERIMENT_ISOLATION_ROOT` to it. The wrapper needs the `engine/` package; copying the skill to `~/.claude/skills/` does not copy the engine. See `compatibility` in SKILL.md.

## Approval token rejected

Use the exact token from the current `plan.json`. If the plan was regenerated or edited, the token is stale. Get a new plan and fresh human approval; do not guess or brute-force.

## Apply partially failed

Stop. Run `python3 -m engine.cli rollback --apply apply.json --out rollback.json`, then verify. Do not rerun apply blindly. If rollback reports `requires_recreate`, say the started experiment must be completed/deleted and recreated; do not claim a live rollback.

## Receipt token count looks wrong

The receipt is roughly 100-125 tokens depending on tokenizer; do not claim under 100. `scripts/token_count.py` uses tiktoken when installed, otherwise ceil(characters/4). Ensure the receipt is compact JSON, not pretty-printed.
