# Safety rules

## Scope: pre-launch only

This skill is a pre-launch gate. Audit any environment, but apply only to experiments that have not started (`status: created`). A running or paused experiment's audience is immutable here. If apply sees running or paused, it must exit 10 and tell the operator to complete/delete and recreate the experiment. The only paths are pre-launch isolation or complete/delete + recreate; never pause as an isolation step.

## Read-only default

- `audit` is read-only for experiment configuration: discovery, sampling, persisted synthetic traits, enrollment reads. No experiment, segment, rollout, or status writes.
- `plan` performs read-only GETs against Flagsmith; it is not offline.
- Only `apply` writes configuration, and only after a human approves the exact plan.
- `rollback` writes only to restore the applied experiment state; `verify` is read-only for configuration except synthetic evaluation.
- Do not use raw `curl`, direct HTTP, or ad-hoc `flagsmith api` PATCH/POST calls to "fix" a result. If the engine refuses, report it.

## Approval token

- `plan.json.approval_token` has the form `iso-<8 lowercase hex>`. It is a short confirmation string, not a credential, and is safe to display in the approval step.
- Pass it with `--approve` exactly; do not commit it.
- If the token is missing, stale, or apply exits 10, stop and ask the operator to review the plan. Regenerate the plan after any audit or plan change; never edit `plan.json` or reuse a token across plans.
- Approval must cover this plan's audience changes and rollback, not a general "go ahead".

## Never modify running experiments

- Running or paused experiments are refused by design; the API also refuses audience changes while running or paused.
- Pausing is not a valid isolation step. Complete/delete the experiment and recreate it, or use a new draft.
- Do not manually disable a running rollout to get around a refusal.
- Do not touch experiments outside the plan's `audience_changes`.
- Do not delete features, metrics, experiments, or pre-existing segments.

## Rollback

- Keep the plan and apply artifacts before attempting rollback.
- If apply fails after any write, stop and run the engine-owned rollback:

  ```sh
  python3 -m engine.cli rollback --apply apply.json --out rollback.json
  ```

- Read `rollback.json`. If it reports `requires_recreate`, report that the started experiment must be completed/deleted and recreated; do not claim a live restore.
- Never hand-roll a `flagsmith api` PATCH/DELETE rollback recipe, and never pause before an audience restore.
- If rollback itself fails, report exact experiment IDs and stop.

## Environment and secrets

- Local/development only. Use `$DEV_ENV_KEY`; never `$PROD_ENV_KEY`, Cloud, or an unknown environment.
- Never print or commit API keys, admin tokens, environment keys, or env-file contents. The approval token is not an API key and is safe to display. Use `scripts/check_env.sh`; it reports presence only.
- Use `flagsmith api` for discovery only; keys must stay out of argv. Do not add auth headers to commands or logs.

## Synthetic identities

- Samples are synthetic identities generated from a trait matrix, not real users. Say so in every demo and receipt narrative.
- Draft enrollment is projected from segment rules; running enrollment is measured. Label both as synthetic and neither as production traffic.
- Their traits persist in the environment. Use a disposable environment where possible; clean up identities only with an explicit operator decision.

## Token discipline

- Read compact JSON fields and the receipt, not raw API payloads.
- If a response is large, keep it on disk and extract only the needed keys. Never paste full experiment or identity JSON into chat.
- The receipt is roughly 100-125 tokens depending on tokenizer; do not claim under 100. Use `scripts/token_count.py` for a single token number.
