# Agent Run — experiment-isolation

Date: 2026-11-27
Target: isolated lab only — Flagsmith `http://localhost:8010`, storefront `http://localhost:8020`, dashboard `http://localhost:8022`. The `:8000` research instance and `~/flagsmith-local` were not used.
Artifacts directory: `/private/var/folders/7m/p85t2ft12ts2spdd0cr1t5mh0000gn/T/opencode/experiment-isolation-run` (referred to as `$RUN` below). Raw JSON stayed on disk; this report contains compact fields only.

## Identity

- This was an **OpenCode general subagent** run.
- Runtime model reported by the harness: **DeepSeek V4.1 Flash 1017** (provider `opencode-go`).
- Orchestrator model: not exposed to this run. (Equivalent to "OpenCode general subagent (model not exposed to the run)" for the parent.)
- No source files were edited. Only this report was written under `verification/`.

## Executive result

The skill loop itself worked end to end after the lab baseline was repaired: **audit → plan → apply → verify → receipt → rollback**, with the exact plan token accepted. The measured pair moved from **Jaccard 1.0** to **0.0**; verify returned `pass: true`; receipt returned `pass: true`; rollback returned `pass: true` but reported `live_restore: false` / `requires_recreate: true` because both experiments had been started.

Two non-skill environment problems affected the run:

1. The lab was **not** in the stated clean 100%-collision state at the start.
2. The instructed cleanup command, `bash lab/run.sh`, did **not** restore a clean baseline after a `requires_recreate` rollback; it exited 2 with HTTP 409. A full `reset` + `run.sh` was required.

## Preflight and baseline repair

I first checked the live lab rather than trusting the stated baseline.

| Check | Exact command | Exit | Result |
|---|---|---|---|
| Env check | `FLAGSMITH_ENV_FILE=lab/.env bash skills/experiment-isolation/scripts/check_env.sh` | 0 | env file, Flagsmith CLI v2.0.0, health 200, credentials present |
| CLI help | `python3 -m engine.cli --help` | 0 | audit, plan, apply, verify, receipt, rollback, seed all exist |
| Lab status | `bash lab/run.sh status` | 0 | all services up; dashboard was reading a stale `collision` audit |
| Preflight audit | `python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out "$RUN/audit.json"` | **0** | **clear**; experiments 1 and 2 already `running` on disjoint segments [4] and [5], pair Jaccard 0.0 |

This contradicted the task statement that the lab was in the clean collision state. The lab's own README documents the recovery path, so I ran:

| Command | Exit | Result |
|---|---|---|
| `bash lab/run.sh reset` | 0 | deleted lab volume and generated `.env` |
| `bash lab/run.sh` | 0 | re-bootstrapped and seeded 2 drafts sharing `us_mobile` (segment 1); measured audit exit 10 / collision |

After that repair, the two experiments were:

- `Pricing banner` id 1, status `created`, audience `[1]`
- `Onboarding tip` id 2, status `created`, audience `[1]`

The preflight audit artifact was overwritten by the official audit after the reset; its numbers are recorded above only.

## Skill workflow commands and exit codes

All engine commands were run from the repository root with `source lab/.env` and `export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"`.

| Step | Exact command | Exit | Result |
|---|---|---|---|
| 1. Audit | `python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out "$RUN/audit.json"` | **10** | expected collision signal; JSON written |
| 2. Plan | `python3 -m engine.cli plan --audit "$RUN/audit.json" --out "$RUN/plan.json"` | 0 | feasible, 2 audience changes, width 50 |
| 3. Apply | `TOKEN=$(PLAN_PATH="$RUN/plan.json" python3 -c 'import json,os; print(json.load(open(os.environ["PLAN_PATH"]))["approval_token"])')` then `python3 -m engine.cli apply --plan "$RUN/plan.json" --approve "$TOKEN" --out "$RUN/apply.json"` | 0 | token accepted; 2 segments created; both experiments running |
| 4. Verify | `python3 -m engine.cli verify --plan "$RUN/plan.json" --samples 500 --out "$RUN/verify.json"` | 0 | `pass: true`, pair `isolated` |
| 5. Receipt | `python3 -m engine.cli receipt --audit "$RUN/audit.json" --plan "$RUN/plan.json" --verify "$RUN/verify.json" --out "$RUN/receipt.json"` | 0 | `pass: true`; scope `planned_experiments` |
| 5b. Token count | `python3 skills/experiment-isolation/scripts/token_count.py "$RUN/receipt.json"` | 0 | printed **121** |
| 6. Rollback | `python3 -m engine.cli rollback --apply "$RUN/apply.json" --out "$RUN/rollback.json"` | 0 | `live_restore: false`, `requires_recreate: true` |
| 6b. Post-rollback audit | `python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out "$RUN/post-rollback-audit.json"` | **10** | recreated drafts 3 and 4, both `created`, sharing segment [1], Jaccard 1.0 |

The exact plan token was read from `plan.json` and passed via `$TOKEN`. It was accepted; `apply.json` reports `approval_token_verified: true`. The token itself is not persisted in this report.

## Audit numbers (before)

| Field | Value |
|---|---|
| Environment | Development (id 1, key prefix `QvJc`) |
| Sample size / threshold | 500 / 0.05 |
| Verdict | `collision` |
| Experiments | 1 `Pricing banner` `created`, audience [1], `basis: projected`, enrolled 250 |
|  | 2 `Onboarding tip` `created`, audience [1], `basis: projected`, enrolled 250 |
| Pair 1↔2 | shared 250, union 250, **Jaccard 1.0**, a_rate 0.5, b_rate 0.5, verdict `collision` |
| Collisions | `[[1, 2]]` (1 pair) |
| Multi-exposure | rate 0.5, max exposure count 2, risk `critical` |
| Percentage split in audience | false for both experiments |
| Sample traits | `country`, `platform`, `flagsmith_experiment_bucket` |

Both experiments were drafts, so enrollment is correctly labeled **projected**, not measured traffic.

## Plan numbers

| Field | Value |
|---|---|
| Feasible | `true` |
| Bucket width | 50 |
| Ranges | `[0, 49]` (`exp_iso_0_49`, `LESS_THAN 50`) and `[50, 99]` (`exp_iso_50_99`, `GREATER_THAN_INCLUSIVE 50` + `LESS_THAN 100`) |
| Coverage | contiguous 0–99, no gap |
| Audience changes | 2: experiment 1 [1] → [exp_iso_0_49 (0–49)]; experiment 2 [1] → [exp_iso_50_99 (50–99)] |
| Blocked running | none |
| Deferred | none |
| Notes field | `running experiments are reported but not changed; pause or recreate them before changing their audience` |
| Rollback | `python3 -m engine.cli rollback --apply apply.json --out rollback.json`, then delete segments by name |
| Approval token | generated (8 hex, `iso-…`); shown during the approval step and read from the plan for apply |

Plan exited 0, not 10, so it was feasible.

## Apply numbers

| Field | Value |
|---|---|
| Exit / pass | 0 / `true` |
| Approval token verified | `true` |
| Segments created | ids 4 (`exp_iso_0_49`) and 5 (`exp_iso_50_99`) |
| Segments reused | 0 |
| Changes | 2: experiment 1 → [4], experiment 2 → [5], both verified |
| Steps | 6: disable rollout, patch audience, start — for each experiment |
| Restore files | `restore-1.json`, `restore-2.json` |

## Verify numbers (after)

| Field | Value |
|---|---|
| Exit / pass | 0 / `true` |
| Sample size | 500 (fresh sample) |
| Before Jaccard | 1.0 |
| After Jaccard | **0.0** |
| Max pairwise Jaccard | 0.0 |
| Before multi-exposure rate | 0.5 |
| After multi-exposure rate | **0.0** |
| Pair 1↔2 | shared 0, union 500, Jaccard 0.0, verdict **`isolated`** |
| Enrolled / status | 234 (`running`), 266 (`running`) |

Every planned pair was `isolated`; `isolated` is a verify verdict, not an audit verdict.

## Receipt numbers

| Field | Value |
|---|---|
| Exit / pass | 0 / `true` |
| Product / environment | `experiment-isolation` / Development |
| Scope | **`planned_experiments`** |
| Sample size | 500 |
| Before | `collision`, max Jaccard 1.0, multi-exposed 0.5 |
| After | `isolated`, max Jaccard 0.0, multi-exposed 0.0 |
| Changes | 4 (2 audience changes × 2) |
| Token counts inside receipt | audit 209, plan 548, apply **0**, verify 95, receipt 106 (engine estimates) |
| Actual helper token count | **121** (tiktoken `o200k_base` installed) |
| Receipt file size | 424 bytes |
| Remaining environment collisions | **0** |
| Rollback field | `["restore 1,2"]` (a pointer, not a runnable command) |

Scope and remaining collisions are explicit in the receipt: the claim is limited to the planned experiments, and the audit had no other collision pairs to leave behind.

## Rollback outcome

`rollback` exited 0 with `pass: true`, but it did **not** restore in place:

- `live_restore: false`
- `requires_recreate: true`
- actions: 2 `recreated_draft` entries
  - experiment 2 (`running`) → new draft **3**; audience [5] → [1]
  - experiment 1 (`running`) → new draft **4**; audience [4] → [1]
- segments deleted: 4 (`exp_iso_0_49`) and 5 (`exp_iso_50_99`)

Post-rollback audit confirmed two `created` drafts named `Onboarding tip [rollback]` (3) and `Pricing banner [rollback]` (4), both on segment [1], Jaccard 1.0 / collision. This is recreation, not a live restore; the report does not claim otherwise.

## Cleanup and final lab state

The instructed cleanup, `bash lab/run.sh`, was attempted first:

| Command | Exit | Result |
|---|---|---|
| `bash lab/run.sh` | **2** | seed failed: `POST /environments/<env>/experiments/ -> HTTP 409: An active experiment already exists for this feature.` The recreated `[rollback]` drafts still own the features. `run.sh` aborted before regenerating the audit, so the dashboard remained stale and still named deleted experiments 1 and 2. |
| `bash lab/run.sh reset` | 0 | removed volume/.env |
| `bash lab/run.sh` | 0 | clean rebuild: drafts 1 and 2, both `created`, both audience [1], measured audit exit 10 / collision |
| `bash lab/run.sh status` | 0 | Flagsmith, storefront, dashboard up; audit `2 experiments, verdict=collision, source=engine` |

Final dashboard confirmation (browser, `http://localhost:8022/`, HTTP 200):

- Heading: **"Audiences collide"**
- Pairwise matrix: **E1/E2 = 100%, 250 / 250**
- Two experiments in scope: Pricing banner and Onboarding tip
- No before/after evidence remains after reset, which is expected for the clean baseline.

Final `lab/dashboard/audit.json`:

- verdict `collision`
- 2 experiments, 1 collision pair, sample 500
- 1 `Pricing banner` `created` audience [1]; 2 `Onboarding tip` `created` audience [1]
- pair Jaccard 1.0, shared 250, verdict `collision`

## Token counts

Measured with tiktoken `o200k_base` (the helper's exact path; tiktoken is installed):

| Object | Tokens | Basis |
|---|---|---|
| SKILL.md body (after frontmatter) | **1,267** | tiktoken, 5,328 chars |
| Full SKILL.md | 1,401 | tiktoken, 6,025 chars |
| Receipt | **121** | `token_count.py`, 424 bytes |
| audit.json | 240 | helper |
| plan.json | 563 | helper |
| apply.json | 447 | helper |
| verify.json | 139 | helper |
| rollback.json | 167 | helper |
| Sum of measured artifacts (excluding post-rollback audit) | 1,677 | helper counts |

The receipt's own `token_count.receipt` is 106, an internal estimate; the helper's actual count is 121. The 121 figure fits the skill's documented "roughly 100–125" range and is not under 100. **Harness total is not exposed to this subagent**, so no full-session token total can be measured here.

## Findings and doc mismatches

1. **Lab baseline was wrong (environment, blocking).** The stated clean 100%-collision state was actually two running, disjoint experiments (segments 4 and 5) with a stale dashboard audit. Preflight audit exited 0 / `clear`. Without the lab-specific reset, a literal reading of the skill ("clear or none: report and stop") would end the run and never exercise plan/apply/verify. I used the lab's documented `reset` + `run.sh` to restore the intended baseline. This is environment drift, not an engine result.

2. **SKILL.md setup targets the wrong instance for this lab (skill doc issue).** Setup says `source ~/flagsmith-local/flagsmith.env`; the lab's file is `lab/.env` on `:8010`. `check_env.sh` defaults to `~/flagsmith-local/flagsmith.env` and only honors a different file through `FLAGSMITH_ENV_FILE`, which SKILL.md never mentions. A user following the skill verbatim in this repo would source the `:8000` research instance or fail, not run against the isolated lab.

3. **Plan note contradicts the safety rule (engine message).** `plan.notes` says "pause or recreate them before changing their audience." SKILL.md and `references/safety.md` say pausing does not free a started experiment and must never be used as an isolation step. `blocked_running` was empty in this run, so no action depended on it, but the artifact gives unsafe guidance.

4. **SKILL.md's receipt command omits optional `--apply` (workflow/doc issue).** The skill's command produces `receipt.token_count.apply = 0` and a rollback field of `["restore 1,2"]` rather than the engine-owned command. `README.md`'s sample receipt command includes `--apply apply.json`. If apply token accounting or actionable rollback text is expected, the skill command is incomplete.

5. **The prescribed cleanup command is insufficient after `requires_recreate` (task/lab issue).** `bash lab/run.sh` exited 2 with HTTP 409 because the recreated `[rollback]` drafts still own the features. Only `bash lab/run.sh reset` followed by `bash lab/run.sh` restored the clean two-draft collision. The dashboard was also stale until the reset regenerated `audit.json`.

6. **"Never print keys or tokens" vs "show approval_token" is ambiguous (skill contradiction).** Safety says never print keys or tokens; the Plan workflow says show the `approval_token`. I displayed the token in the approval step and did not persist it in this report. Treating the approval token as an operator-facing confirmation string (not a credential) seems intended, but the text should say so.

7. **No missing subcommands or flags were found.** `audit`, `plan`, `apply`, `verify`, `receipt`, and `rollback` all exist with the flags used. `receipt --apply` exists and is optional; the skill simply omits it. `check_env.sh` works when `FLAGSMITH_ENV_FILE` is set.

## Human intervention

- The skill loop ran without further human interaction after the plan was authorized. The orchestrator's task message explicitly instructed apply with the plan's approval token; that is the only approval surface used. No interactive confirmation was requested or possible in this subagent run.
- The baseline repair (`reset`) and final cleanup (`reset` + `run.sh`) were environment/lab operations outside the skill's five commands. They were needed because the lab did not match its stated starting state and because the specified cleanup command failed after rollback recreation.

## Disclosure

All sampled identities are synthetic; their traits persist in the lab database. Draft enrollment is projected from segment rules; verify enrollment is measured on the synthetic sample. None of these numbers is real production traffic.
