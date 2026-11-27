# Safety rules

## Scope: pre-launch only

This skill is a pre-launch gate. Audit any local or disposable environment, but apply only to experiments that have not started (`status: created`). A running or paused experiment's audience is immutable here. If `apply` sees `running` or `paused`, it exits 10 and refuses changes; the operator must complete/delete and recreate the experiment. The only paths are pre-launch isolation or complete/delete + recreate; never pause as an isolation step.

## Read-only default

- `audit` is read-only for experiment configuration: discovery, sampling, persisted synthetic traits, and enrollment reads. No experiment, segment, rollout, or status writes.
- `plan` performs read-only `AdminAPI` GETs against Flagsmith; it is not offline.
- Only `apply` mutates audiences/segments/statuses, and only after explicit human approval of the exact plan.
- `verify` is read-only for experiment configuration (only synthetic identity trait persistence/evaluation when needed, plus optional `--cleanup`).
- `rollback` writes only to restore or recreate the applied experiment state and delete segments created by `apply`.
- Do not use raw `curl`, ad-hoc HTTP, or `flagsmith api` PATCH/POST/DELETE calls to bypass engine checks or "fix" a result. If the engine refuses, stop and report.

## Approval token

- `plan.json.approval_token` has the form `iso-<8 lowercase hex>`, HMAC-SHA256 bound to the environment, project, threshold, planned segments (including composed base rules), audience changes, and restore snapshots. It is a short confirmation string, not a credential, and is safe to display in the approval step.
- Pass it with `--approve` exactly; do not commit it.
- If the token is missing, stale, or `apply` exits 10, stop and ask the operator to review the plan. Regenerate the plan after any audit or experiment change; never edit `plan.json` or reuse a token across plans.
- Approval must cover this plan's bucket ranges, audience changes (including preserved base targeting), and rollback plan, not a general "go ahead".

## Never modify running experiments

- Running or paused experiments are refused by design; the Flagsmith API also rejects audience changes while running or paused.
- Pausing is not a valid isolation step. Complete/delete the experiment and recreate it, or isolate new drafts pre-launch.
- Do not manually disable a running rollout to work around a refusal.
- Do not touch experiments outside the plan's `audience_changes`.
- Do not delete features, metrics, experiments, or pre-existing segments.

## Rollback

- Keep `plan.json`, `apply.json` (or `apply-failure.json`), and `restore-<id>.json` before attempting rollback.
- If `apply` fails after any write (exit 20) or `verify` finds residual overlap (exit 10 / `pass: false`), stop and run the engine-owned rollback:

  ```sh
  python3 -m engine.cli rollback --apply apply.json --out rollback.json
  # or from any standalone skill copy:
  bash scripts/run.sh rollback --apply apply.json --out rollback.json
  ```

- Read `rollback.json`. If it reports `requires_recreate`, tell the user the started experiment was deleted and recreated as a draft (`[rollback]`); do not claim an in-place live restore.
- Never hand-roll a `flagsmith api` or `curl` PATCH/DELETE rollback recipe, and never pause as an isolation step.
- If rollback itself fails, report exact experiment IDs and stop.

## Environment and secrets

- Local/disposable only (`localhost`, `127.0.0.1`, `::1`; `ISO_ALLOW_REMOTE=1` only for a disposable host). Use `DEV_ENV_KEY` or `FLAGSMITH_ENVIRONMENT_KEY` (or `FLAGSMITH_ENVIRONMENT`); never production keys, Flagsmith Cloud, or an unknown environment.
- Never print or commit API keys (`FLAGSMITH_API_KEY`, `FLAGSMITH_API_KEY_<host>_<port>`), environment keys, or env-file contents. The approval token is not an API key and is safe to display. Use `bash scripts/check_env.sh`; it reports presence only.
- The engine uses `flagsmith evaluate --persist --json` for synthetic trait persistence/evaluation and Python stdlib HTTP (`AdminAPI` with `Authorization: Api-Key`, `EdgeAPI` with `X-Environment-Key`) for API calls—keys stay out of `argv`, logs, and sanitized errors. Never add auth headers to shell commands or chat output.

## Synthetic identities

- Samples are synthetic identities (`iso_0001`..) generated from a fixed trait matrix, not real users. Disclose this in every demo and receipt narrative.
- Draft enrollment is `projected` from segment rules; running/paused enrollment is `measured` from Flagsmith metadata. Label both as synthetic and neither as production traffic.
- Synthetic traits persist in the environment unless cleaned up (`--cleanup` on `audit`/`verify`). Use a disposable environment where possible; clean up identities only intentionally.

## Token discipline

- Read compact JSON fields and the receipt, not raw API payloads.
- Keep large artifacts on disk and extract only the needed keys. Never paste full experiment or identity JSON into chat.
- The receipt is roughly 100-125 tokens depending on tokenizer; do not claim under 100. Use `python3 scripts/token_count.py receipt.json` for a single integer token count.
