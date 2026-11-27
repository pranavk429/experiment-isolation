# Experiment Isolation — Re-verification of the fixed build

Date: 2026-11-27
Verifier: independent verifier (read-only on source; this report and /tmp evidence only)
Target: local Flagsmith 2.291.0, Development environment
Verdict: **NOT READY TO RECORD**

## Executive summary

The engine and skill fixes are real. Tests are **54 engine + 34 skill = 88**. The 2-way loop moved Jaccard **1.0 → 0.0** and multi-exposure **0.76 → 0.0**. The 3-way loop did the same, with contiguous ranges [0,32], [33,65], [66,99]. HMAC approval rejects a public-token rewrite; wrong tokens and no-op wrong tokens exit 10; `--approve noop` is accepted. The new `rollback` command restored a created draft in place and honestly recreated started experiments as new drafts. An apply failure wrote `apply-failure.json` with created segment IDs, and rollback cleaned it up.

The build is **not ready to record because the judge-facing docs still describe the pre-fix build**. Q11 says the rollback drill failed and "do not claim rollback works"; why-we-win says apply does not re-derive the token and quotes 41+24 tests; all receipt copy still says ~110–115 tokens instead of the verified **121/125**; judge-qa still links `skill/scripts/token_count.py`. Those are direct contradictions of the verified fix, not just stale prose.

## Environment and method

- Python 3.9.6; Flagsmith CLI v2.0.0; local health 200.
- Baseline: experiments 1–4 running; drafts 39/40 created; segments 2/4/7/8.
- All mutations local. Test experiments/segments were removed at the end. Final state: 1–4 running, drafts 49/50 created, segments 2/4/7/8 only.
- No source edits. Only `verification/REPORT2.md` was written; all other evidence is in /tmp.

## Check table

| # | Check | Command (abridged) | Expected | Actual | Pass/fail |
|---|---|---|---|---|---|
| 1 | Engine tests | `pytest tests/engine -q` | 54 pass | **54 passed** | PASS |
| 2 | Skill tests | `unittest discover -s tests/skill` | 34 pass | **34 tests, OK** | PASS |
| 3 | Combined | `pytest tests/engine tests/skill -q` | 88 pass | **88 passed** | PASS |
| 4 | Seed 2-way | `seed/demo_seed.py --experiments 2` | reuse 2 drafts | 39/40 created, 0 new, started false | PASS |
| 5 | Audit 2-way | `audit --samples 100 --workers 4` | exit 10, collision | exit 10; 6 experiments, 15 pairs; draft pair 39/40 1.0; multi 0.76; max 6; critical | PASS |
| 6 | Plan 2-way | `plan --audit ...` | feasible, 2 ranges | exit 0; width 50; [0,49]/[50,99]; segments 7/8 reused; blocked 1–4; HMAC 12 chars | PASS |
| 7 | Wrong token | `apply --approve iso-deadbeef` | exit 10, no writes | exit 10; 39/40 still created [4] | PASS |
| 8 | Edited plan + public token | edit change; recompute `approval_token(..., secret='')`; apply | exit 10 | exit 10; no writes | PASS |
| 9 | No-op tokens | `apply --approve iso-wrong`; `--approve noop` | 10; 0 | 10; 0 | PASS |
| 10 | Apply 2-way | `apply --plan ... --approve <token>` | 2 running | exit 0; 2 running [7]/[8]; 6 steps; created 0 / reused 2; 2 restore files | PASS |
| 11 | Verify 2-way | `verify --samples 100 --workers 4` | 1.0→0.0; pass | exit 0; 1.0→0.0; max pair 0.0; multi 0.76→0.0; 46/54; pass | PASS |
| 12 | Receipt 2-way | `receipt ...` | pass; ≤125 actual | exit 0; pass; 429 chars; estimate 107; **o200k 121; cl100k 120**; changes 4; scope planned | PASS |
| 13 | Rollback started 2-way | `rollback --apply r2-apply.json` | recreate, not live | exit 0; `live_restore=false`, `requires_recreate=true`; new drafts 41/42; old audience [4] | PASS |
| 14 | Rollback created-only | crafted apply artifact after real created-audience change | live restore in place | exit 0; `live_restore=true`, `requires_recreate=false`; 41 restored [4], enabled true | PASS |
| 15 | Seed 3-way reset | `seed --experiments 3 --reset` | 3 drafts | 43/44/45 created; started false | PASS |
| 16 | Audit 3-way | `audit --samples 100` | exit 10, all pairs collide | exit 10; 7 experiments, 21 pairs; all draft pairs 1.0; multi 0.76; max 7 | PASS |
| 17 | Plan 3-way | `plan --audit ...` | 3 contiguous ranges | exit 0; width 33; [0,32], [33,65], [66,99]; 3 new segments; blocked 1–4 | PASS |
| 18 | Apply 3-way | `apply --plan ...` | 3 running | exit 0; 3 running; created segments 61/62/63; 9 steps; 3 restore files | PASS |
| 19 | Verify 3-way | `verify --samples 100 --workers 4` then retry `--workers 2` | 0.0; pass | first attempt **exit 20 timeout**; retry exit 0; 1.0→0.0; 31/35/34; unions 66/65/69; pass | PARTIAL (flake) |
| 20 | Receipt 3-way | `receipt ...` | pass; ≤125 | exit 0; pass; 435 chars; estimate 109; **o200k 125; cl100k 124**; changes 6; scope planned | PASS |
| 21 | Rollback started 3-way | `rollback --apply r3-apply.json` | recreate; delete segments | exit 0; `live_restore=false`, `requires_recreate=true`; new 46/47/48; deleted 61/62/63 | PASS |
| 22 | Apply failure artifact | modified plan to force pre-apply failure | artifact with created IDs | exit 20; `apply-failure.json` has created 67/68/69, 0 applied changes; rollback deleted 3, pass | PASS |
| 23 | Rollback failure artifact | apply artifact with missing restore | exit 10, sanitized | exit 10; pass false; error "no restore state"; no key | PASS |
| 24 | Blocked running target | plan change to running exp 2, recomputed HMAC | exit 10, no writes | exit 10; 2 and 46/47/48 unchanged | PASS |
| 25 | Audit clear/none | `audit --env "$PROD_ENV_KEY"` | exit 0 | exit 0; 0 experiments; verdict none | PASS |
| 26 | HMAC binding | compare stored token to HMAC and public helper | HMAC, not public | stored==HMAC true; stored==public false; public-edit rejected | PASS |
| 27 | Skill parent/validator | `quick_validate.py skills/experiment-isolation` | valid; basename match | valid; parent/name both experiment-isolation | PASS |
| 28 | Skill semantics | inspect SKILL.md/references | audit 10 continue; clear/none stop; isolated only verify | all present | PASS |
| 29 | Skill rollback recipe | inspect SKILL.md/references | engine rollback; no flagsmith api recipe | `engine.cli rollback`; no hand-rolled recipe | PASS |
| 30 | Docs forbidden claims | grep target docs | no pairwise-only/third-raises/at-most-two | none; "under 100" appears only as negated legacy target | PASS |
| 31 | Docs path claims | grep `skill/` | no old path | `docs/judge-qa.md:27` still says `skill/scripts/token_count.py` | FAIL |
| 32 | Docs receipt numbers | compare README/docs to measured | 121/125 actual | README/docs say ~110–115, 110/114, 109–114 | FAIL |
| 33 | Docs rollback/HMAC/tests | inspect judge-qa/why-we-win | reflect fixed build | Q11 says rollback failed; why-we-win says apply does not re-derive token and 41+24 tests; why-we-win says rollback drill failed | FAIL |
| 34 | Docs apply sequence | compare steps | disable/change/start (start enables) | docs say disable/change/re-enable/start; apply has no re-enable step | FAIL |
| 35 | Secret scan repo/new | exact env values in repo/new artifacts | none | none in repo; none in new-run artifacts | PASS |
| 36 | Secret scan /tmp | exact env values in /tmp | none | pre-existing `/tmp/lab_envs.json`, `/tmp/lab_devkey` contain DEV_ENV_KEY/PROD_ENV_KEY/FLAGSMITH_ENVIRONMENT values (10:19, before this run) | FAIL |
| 37 | Final reset | seed 2 --reset; list state | drafts only | 1–4 running; 49/50 created; segments 2/4/7/8 only | PASS |

## Numbers

### 2-way

- Audit: 6 experiments, 15 collision pairs, draft pair 39/40 Jaccard 1.0, multi 0.76, max exposure 6, risk critical.
- Plan: width 50, [0,49] + [50,99]; segments 7/8 reused; blocked 1–4.
- Apply: 2 running, 6 steps (disable, patch, start ×2), created 0 / reused 2.
- Verify: 1.0 → 0.0; multi 0.76 → 0.0; enrolled 46/54; pass true.
- Receipt: 429 chars, estimate 107, **o200k 121**, **cl100k 120**, changes 4, scope `planned_experiments`, remaining environment collisions 14.
- Rollback: started pair recreated as drafts 41/42, `live_restore=false`, `requires_recreate=true`, segments deleted 0.

### 3-way

- Audit: 7 experiments, 21 collision pairs, all three draft pairs 1.0, multi 0.76, max 7, risk critical.
- Plan: width 33, [0,32], [33,65], [66,99]; 3 new segments; blocked 1–4.
- Apply: 3 running, 9 steps, created segments 61/62/63.
- Verify: retry after one timeout; 1.0 → 0.0; multi 0.76 → 0.0; enrolled 31/35/34; unions 66/65/69; pass true.
- Receipt: 435 chars, estimate 109, **o200k 125**, **cl100k 124**, changes 6, scope `planned_experiments`, remaining environment collisions 18.
- Rollback: 3 started experiments recreated as drafts 46/47/48; `live_restore=false`, `requires_recreate=true`; deleted segments 61/62/63.
- Created-only drill: 41 changed to [7] while created, then engine rollback restored [4] enabled true; `live_restore=true`, `requires_recreate=false`.
- Failure artifact: created 67/68/69; 0 applied changes because the failure was caught in pre-apply validation; rollback deleted all three. Partial-applied artifact is covered by unit tests, not a live drill.

### HMAC / approval

- Plan token equals HMAC with the admin key; it differs from `approval_token(..., secret='')`.
- Editing a change and using the public helper token: exit 10, no writes.
- Wrong token: exit 10. No-op wrong token: exit 10. `--approve noop`: exit 0.
- Blocked running target with a correctly recomputed HMAC: exit 10, no writes.

## Bugs and claim mismatches

### BLOCKER — Judge-facing docs still describe the pre-fix build

Files: `docs/judge-qa.md:55,75,76`; `docs/why-we-win.md:51,53,63,65,75`.

The docs say the live rollback drill failed, `_rollback` swallows exceptions, and "do not claim rollback works." The fixed engine has `rollback.py`, and the live drills passed both started and created-only cases. `why-we-win.md:51` says apply does not re-derive the token; `apply._expected_token` does. `why-we-win.md:53` says 41 engine + 24 skill tests; actual is 54 + 34.

Impact: the Q&A script and "sentences to say exactly" would tell the presenter to deny a working feature and understate approval strength. A judge checking the code will see the contradiction. Fix: rewrite Q11, the why-we-win approval/evidence rows, the five sentences, and the "what we must not claim" list against this re-verification.

### MAJOR — Receipt copy still quotes the old 110–115 numbers

Files: `README.md:32,80,155,161`; `docs/submission.md:28,99`; `docs/judging-map.md:29,55`; `docs/token-count.md:65,74,108,117,124`; `docs/demo-script.md:119`; `docs/judge-qa.md:27,75`.

Measured: **121 o200k / 120 cl100k** for 2-way and **125 / 124** for 3-way. The engine README and skill references are correct ("<=125", "100-125"); the main docs are not. "Under 100" now appears only as a negated legacy target, so that specific claim is fixed, but the actual numbers are stale.

Fix: replace every 110–115/110/114/109–114 reference with 120/121 and 124/125, and state the o200k/cl100k distinction.

### MAJOR — Old `skill/` path remains in judge-qa

File: `docs/judge-qa.md:27`.

It still says `skill/scripts/token_count.py`; the skill is now `skills/experiment-isolation/scripts/token_count.py`. All other target docs use the new path; this one link is stale.

Fix: update the path and search the docs for any remaining `skill/` single-directory references.

### MINOR — Docs claim an explicit re-enable step that apply does not record

Files: `README.md:30,78,171`; `docs/submission.md:28,69,94`; `docs/demo-script.md:93`; `skills/experiment-isolation/references/api.md:43`.

The apply artifact steps are `disable_rollout`, `patch_audience`, `start` (6 steps for 2 experiments, 9 for 3). There is no `enable_rollout` step; `start` leaves the rollout enabled. The docs' "disable → change → re-enable → start" describes a different sequence than the engine emits.

Fix: say "disable → change audience → start (start re-enables the rollout)" or add an explicit re-enable step and test it.

### MINOR — One 3-way verify timed out under the documented worker count

Command: `verify --samples 100 --workers 4` → exit 20, "Flagsmith identity request timed out or failed: timed out"; retry with `--workers 2` passed. The 2-way verify with workers 4 passed. This is a local-environment flake, but the demo commands use `--workers 4`.

Fix: lower the default/demo worker count, add retry/backoff around identity reads, or document the retry. Re-run the 3-way verify more than once before recording.

### MINOR — Live failure artifact had zero applied changes; partial path is only unit-tested

The live failure artifact correctly contained created segment IDs 67/68/69 and was cleaned up by rollback, but it had `changes: []` because validation failed before the first experiment. Unit tests cover a partial failure with one running change and one "applying" change; a live partial drill remains unrecorded.

Fix: record a live partial-apply failure or state that the partial path is unit-tested only.

### MAJOR (security hygiene) — Pre-existing /tmp files contain environment keys

`/tmp/lab_envs.json` and `/tmp/lab_devkey` contain exact `DEV_ENV_KEY`/`PROD_ENV_KEY`/`FLAGSMITH_ENVIRONMENT` values (timestamps 10:19, before this 11:xx run). The repository and all new-run artifacts are clean, and no new command printed a key. These files are outside the repo but in the working environment; screen-sharing or shell history could expose them.

Fix: delete/rotate the lab temp files before recording and add a preflight check that scans /tmp for env values. Do not print the values here.

## Secret scan

Method: read the six env values in memory from `~/flagsmith-local/flagsmith.env`; scanned repository text files and /tmp JSON/stdout/stderr artifacts; reported only variable names/paths. No values are printed in this report.

- Repository: **no exact env values**.
- New-run artifacts (/tmp/r2*, r3*, rf*): **no exact env values**.
- New stdout/stderr: no key; apply-failure and rollback-failure errors sanitized.
- Existing /tmp lab artifacts: **2 files contain exact env values** (DEV_ENV_KEY, PROD_ENV_KEY, and FLAGSMITH_ENVIRONMENT); pre-existing, not created by this run.
- Admin API key was not observed in repo, new artifacts, or printed output.

## Residual risks

- Stale docs are the main readiness blocker; the engine and skill behavior are verified, but the Q&A/why-we-win/receipt copy would misstate the build.
- 3-way verify flaked once at 4 workers; retry at 2 passed. Demo reliability is not yet proven under repeated runs.
- Partial-apply failure artifact is unit-tested, not live-tested.
- Rollback deletes a started experiment before creating the replacement draft; a create failure would lose the original. The result reports failure, but there is no transactional recovery.
- HMAC token is truncated to 8 hex characters (32-bit) and is a confirmation token, not a signature; an admin-key holder can forge it.
- Receipt scope is correct (`planned_experiments` plus remaining collisions), but 14 (2-way) / 18 (3-way) environment collision pairs remain; do not narrate environment-wide isolation.
- Synthetic sample is unstratified; 31/35/34 and 46/54 splits are hash noise, not 50/50 guarantees.
- Lab/dashboard not exercised this pass; the one-command lab claim remains unverified.
- Existing /tmp lab key files should be removed/rotated before any recording.

## Final state

- Pre-existing experiments 1–4 remain running and untouched.
- Drafts **49 (Express checkout)** and **50 (Discount badge)** are `created`, audience segment 4, not started.
- Segments: only 2 (`half_users`), 4 (`us_mobile`), 7 (`exp_bucket_a`), 8 (`exp_bucket_b`).
- All verification experiments 39–48 and test segments 61–69 were removed.
- Synthetic `iso_*` identities remain (documented behavior; no cleanup run).
- No generated apply/audit/plan/verify/receipt/restore/rollback files in the repo root; evidence is under /tmp.

## Recommendation

Fix the stale judge-facing docs before recording. The functional build passes the requested drills; the remaining work is documentation integrity (rollback/HMAC/test counts, 121/125 receipt numbers, old `skill/` path), a repeatable 3-way verify, and cleanup of the pre-existing /tmp key files.