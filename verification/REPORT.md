# Experiment Isolation — Independent Verification

Date: 2026-11-27
Verifier: independent verifier (no source edits; only this report and /tmp evidence)
Target: local Flagsmith 2.291.0, `~/flagsmith-local/flagsmith.env`, Development environment
Verdict: **NOT READY TO RECORD**

## Executive summary

The happy path works and reproduces the recorded numbers. The 2-way loop moved max Jaccard from 1.0 to 0.0; the 3-way loop produced three contiguous ranges covering 0–99 with max pairwise Jaccard 0.0; 41 engine tests and 24 skill tests pass.

It is not ready because the safety story does not survive a live drill:

1. The documented rollback sequence pauses an experiment and then PATCHes its saved audience. Flagsmith 2.291.0 rejects that with `Cannot change the audience of a paused experiment.` The audience remains changed, `flagsmith api` returns exit 0 on the HTTP 400, and its error text prints the environment key in the request URL.
2. Judge-facing docs say N-way is not implemented and that a collision does not exit 10. The code, tests, and live runs prove the opposite (3-way works; audit exits 10 on collision).
3. `SKILL.md` tells the agent to stop when audit returns `isolated`, a verdict audit never emits, and never says audit exit 10 is the expected collision signal.
4. The receipt is 110/114 tokens under o200k_base and 109/113 under cl100k_base, not under 100 as the acceptance target says.
5. The skill directory is `skill/` while the frontmatter name is `experiment-isolation`; the Agent Skills spec requires the parent directory name to match.

## Environment and method

- Python 3.9.6; repository root executed all commands.
- Source: `source ~/flagsmith-local/flagsmith.env`; Flagsmith CLI v2.0.0; local health 200.
- Baseline: experiments 1–4 running; drafts 20/21 created; segments 2 (`half_users`), 4 (`us_mobile`), 7 (`exp_bucket_a`), 8 (`exp_bucket_b`).
- All mutations were against the local Development environment. The 3-way test used experiments 22/23/24 and segments 34/35/36, then removed them.
- Final state was reset: experiments 1–4 untouched/running; drafts 25/26 created; only segments 2/4/7/8 remain. Synthetic identities persist.

## Check table

| # | Check | Command (abridged) | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | Engine suite | `python3 -m pytest tests/engine -q` | all pass | **41 passed** in 0.10s | PASS |
| 2 | Skill suite | `python3 -m unittest discover -s tests/skill` | all pass | **24 tests, OK**, 2.514s | PASS |
| 3 | Combined suite | `python3 -m pytest tests/engine tests/skill -q` | all pass | **65 passed** in 1.62s | PASS |
| 4 | Seed 2-way idempotent | `python3 seed/demo_seed.py --experiments 2` | 2 drafts, no start | exit 0; 2 reused; 0 created | PASS |
| 5 | Audit 2-way collision | `audit --samples 100 --out /tmp/audit2.json` | exit 10; collision | exit 10; 6 experiments, 15 collision pairs; draft pair 20/21 Jaccard 1.0; multi 0.76; max 6; risk critical | PASS |
| 6 | Plan 2-way | `plan --audit /tmp/audit2.json` | feasible; 2 ranges | exit 0; width 50; [0,49] + [50,99]; reused segments 7/8; blocked running 1–4; token generated | PASS |
| 7 | Wrong token no mutation | `apply --plan /tmp/plan2.json --approve iso-deadbeef` | exit 10; no writes | exit 10; statuses/audiences/segments identical before/after | PASS |
| 8 | Apply 2-way | `apply --plan /tmp/plan2.json --approve <token>` | 2 running; audiences changed | exit 0; 2 running; created 0 / reused 2; audiences [7]/[8]; 2 restore files; 4 rollback commands | PASS |
| 9 | Verify 2-way | `verify --plan /tmp/plan2.json --samples 100` | after 0.0; pass true | exit 0; before 1.0 → after 0.0; max pair 0.0; multi 0.76 → 0.0; enrolled 46/54; pass true | PASS |
| 10 | Receipt 2-way | `receipt ... --apply /tmp/apply2.json` | pass; rollback; token counts | exit 0; pass true; 378 chars; estimate 95; cl100k 109; o200k 110; changes 4 | PASS (with token caveat) |
| 11 | Seed 3-way | `seed/demo_seed.py --experiments 3` | 3 drafts | After cleanup: 3 drafts (22/23/24). First attempt reused running 20/21, created only 1 draft, and stderr still said "not started" | PARTIAL (seed bug) |
| 12 | Audit 3-way | `audit --samples 100 --out /tmp/audit3.json` | exit 10; all draft pairs collide | exit 10; 7 experiments, 21 collisions; draft pairs 1.0/1.0/1.0; multi 0.76; max 7; risk critical | PASS |
| 13 | Infeasible concurrency | `plan --max-concurrent 2` | exit 10; deferred; no partial plan | exit 10; feasible false; deferred [22,23,24]; 0 changes; token null; no segments | PASS |
| 14 | Infeasible width | `plan --min-bucket-width 40` | exit 10; deferred | exit 10; width 33; deferred [22,23,24]; 0 changes; token null | PASS |
| 15 | Plan 3-way ranges | `plan --audit /tmp/audit3.json` | 3 contiguous ranges, no gaps/overlaps | exit 0; [0,32], [33,65], [66,99]; coverage 0–99; width 33; 3 changes; blocked 1–4 | PASS |
| 16 | Plan rerun | same plan command again | same segments, no duplicates | same token and same three segment specs; no API writes | PASS |
| 17 | Apply 3-way | `apply --plan /tmp/plan3.json --approve <token>` | 3 running; 3 segments | exit 0; 3 running; created segments 34/35/36; 3 restore files; 9 rollback entries | PASS |
| 18 | Verify 3-way | `verify --plan /tmp/plan3.json --samples 100` | max pairwise 0; pass true | exit 0; before 1.0 → after 0.0; max pair 0.0; multi 0.76 → 0.0; enrolled 31/35/34; shared 0 in all pairs; unions 66/65/69; pass true | PASS |
| 19 | Receipt 3-way | `receipt ... --apply /tmp/apply3.json` | pass; rollback; token counts | exit 0; pass true; 384 chars; estimate 96; cl100k 113; o200k 114; changes 6 | PASS (with token caveat) |
| 20 | Rerun apply after success | `apply --plan /tmp/plan3.json --approve <token>` | refuse; no mutation | exit 10; experiments still running, audiences 34/35/36, segment set unchanged | PASS |
| 21 | Verify residual overlap | crafted plan for experiments 2/3, both audience 4 | exit 10; overlap detected | exit 10; after 1.0; multi 0.5; enrolled 50/50; pass false | PASS |
| 22 | Audit no collisions | `audit --env "$PROD_ENV_KEY" --samples 10` | exit 0 | exit 0; 0 experiments; verdict none; no sampling | PASS (zero-experiment case) |
| 23 | Sample bounds | `audit --samples 1`, `--samples 5001` | exit 20 | exit 20; clear errors | PASS |
| 24 | HTTP/auth error | `audit --env "$SERVER_ENV_KEY"` | exit 20; sanitized | exit 20; error uses `<env>`, no key shown | PASS |
| 25 | Receipt failure | receipt with passing=false verify | exit 10 | exit 10; after 1.0; pass false | PASS |
| 26 | Apply infeasible plan | `apply --plan plan3-infeasible-conc.json` | exit 10; no writes | exit 10; no apply artifact; no mutation | PASS |
| 27 | No-op apply wrong token | plan from zero-experiment audit; `apply --approve iso-wrong` | exit 10 | **exit 0**, `pass:true`, approval_token_verified false; no mutation | FAIL |
| 28 | Rollback drill | pause exp 22; plan rollout PATCH with restore-22.json | restore audience/rollout; nonzero on failure | **HTTP 400** `Cannot change the audience of a paused experiment.`; audience stayed [34]; `flagsmith api` **exit 0**; stderr printed the environment key in the URL | FAIL |
| 29 | N-way math 2..100 | pure `equal_ranges`/conditions check | full coverage, no overlap | 99 counts checked; no gaps/overlaps; conditions correct | PASS |
| 30 | Skill frontmatter | `quick_validate.py skill` | valid | "Skill is valid!"; name 383-char description; 228-char compatibility; 112 body lines / ~1315 estimate; all six triggers | PASS |
| 31 | Skill name/directory | spec: parent directory == name | match | `skill/SKILL.md` name `experiment-isolation`, parent `skill` | FAIL |
| 32 | Skill commands/flags | inspect SKILL.md vs CLI | all exist | audit/plan/apply/verify/receipt flags exist; `flagsmith api --input`, `-X PATCH`, `evaluate --persist` exist | PASS |
| 33 | Env check / wrapper | `bash skill/scripts/check_env.sh`; `run.sh --help` | no secrets; works | exit 0; values not shown; help works | PASS |
| 34 | Secret scan: files | exact-value scan of six env values across repo and /tmp JSON/stdout/stderr | none | no exact value in repository files or /tmp artifacts | PASS |
| 35 | Secret scan: printed output | same values in command output | none | documented rollback command printed env key in an error URL | FAIL |
| 36 | Final reset | pause/delete test experiments; delete 34/35/36; seed 2 | drafts ready; no extra running/segments | 1–4 running; 25/26 created; segments 2/4/7/8 only; no exp_iso_* segments | PASS |

## Numbers

### 2-way (experiments 20/21, sample 100)

| Metric | Before | After |
|---|---|---|
| Max pairwise Jaccard (planned drafts) | 1.0 | 0.0 |
| Multi-exposed rate (all sampled experiments) | 0.76 | 0.0 |
| Enrolled planned experiments | 50 / 50 projected | 46 / 54 measured |
| Environment audits | 6 experiments, 15 collision pairs, max exposure 6, risk critical | verify covers planned pair only |

- Plan: width 50, ranges [0,49] and [50,99], segments 7/8 reused; blocked running 1–4.
- Apply: 2 running; segments created 0, reused 2; 2 restore files; 4 rollback entries.
- Receipt: 378 chars; estimate 95; **cl100k 109; o200k 110**; changes 4; pass true.
- Rerun behavior: plan is read-only and reuses segments; a second apply after success exits 10 with no mutation.

### 3-way (experiments 22/23/24, sample 100)

| Metric | Before | After |
|---|---|---|
| Max pairwise Jaccard | 1.0 (all 3 pairs) | 0.0 (all 3 pairs) |
| Multi-exposed rate | 0.76 | 0.0 |
| Enrolled | 50 / 50 / 50 projected | 31 / 35 / 34 measured |
| Ranges | — | [0,32], [33,65], [66,99] |

- Range coverage: 0–99, no gaps, no overlaps; widths 33/33/34; actual bucket counts 31/35/34, sum 100.
- Verify overlaps: shared 0; unions 66, 65, 69; all Jaccard 0.0.
- Plan: 3 changes; blocked running 1–4; token deterministic across reruns.
- Apply: 3 running; created segments 34/35/36; 3 restore files; 9 rollback entries.
- Receipt: 384 chars; estimate 96; **cl100k 113; o200k 114**; changes 6; pass true.
- Environment still had 21 collision pairs among all 7 experiments after apply. The receipt says `after.verdict: isolated` without saying it is planned-pair scope.

### Test counts

- `pytest tests/engine -q`: **41 passed**.
- `unittest discover -s tests/skill`: **24 tests, OK**.
- Combined: **65 passed**.

## Bugs

### BLOCKER — Rollback cannot restore the audience; failure is silent and leaks the environment key

Files: `engine/plan.py:315-322`, `engine/apply.py:191-207`, `docs/judge-qa.md:55`, `skill/SKILL.md:24-30`.

Reproduction (observed live on experiment 22, then deleted during reset):

1. Create/start a draft via apply.
2. Pause it with `POST /api/v1/environments/{env}/experiments/{id}/pause/`.
3. Run the plan's rollback PATCH with `restore-{id}.json` (old audience [4], current audience [34]).
4. Actual: `HTTP 400: ["Cannot change the audience of a paused experiment."]`. Audience remains [34]. `flagsmith api` exits **0**, so an automation sees success. The CLI error text includes the full environment key in the request URL.

Impact: the receipt/plan rollback story and the "every change has a rollback command" demo line are false for audience changes. `_rollback` also swallows every exception, so a partial apply leaves a paused experiment on the new audience with no recorded failure. The failure path has no unit test for this.

Suggested fix: add an engine-owned `rollback` command that calls AdminAPI directly and raises on non-2xx; do not pause before attempting an audience restore; determine a valid restore sequence or state plainly that a started experiment must be recreated; sanitize URLs/errors; write a failure artifact containing created segment IDs; add a live rollback test. Do not rely on `flagsmith api` exit codes.

### BLOCKER — Judge-facing docs contradict the implemented N-way behavior and audit exit code

Files: `docs/judge-qa.md:67`, `docs/judge-qa.md:73`, `docs/why-we-win.md:49`, `docs/why-we-win.md:63`, `docs/why-we-win.md:74`.

- Docs: "planner supports at most two draft experiments; a third raises an error; N-way ... not implemented"; "At most two draft experiments"; "N-way → Two draft experiments today."
- Actual: `equal_ranges` supports N; the live 3-way loop created 3 segments, started 3 experiments, and verify returned max pairwise 0.0. `tests/engine/test_engine.py` has 3-way tests. `engine/README.md` documents N-way.
- Docs: "a collision alone produces a verdict and a plan, not an exit 10." Actual: `audit` returns exit 10 on collision (`engine/cli.py:101`), the contract/task expect it, and the live audit did it.

Impact: a judge reading the Q&A/why-we-win gets a false scope and false exit-code claim. This is especially damaging because those documents are explicitly the "say exactly" material.

Suggested fix: rewrite Q14 for 3-way support and the default `--max-concurrent 4`/`--min-bucket-width 5` limits; remove the "third raises" sentence; update the five sentences; correct why-we-win line 49 and the "must not claim" list to say audit exit 10 is expected on collision.

### MAJOR — SKILL.md tells the agent to stop on a verdict audit never emits and omits audit exit 10

Files: `skill/SKILL.md:56`, `skill/references/troubleshooting.md` ("verdict: isolated").

Audit verdicts are `collision`, `clear`, or `none`; `isolated` is a verify verdict. The workflow says: "If `verdict` is `isolated`, report that and stop." An agent will not stop on a real clear/none audit and may over-run; conversely, the skill never tells the agent that audit exit 10 on collision is expected and should lead to plan, not abort.

Fix: say "If verdict is clear or none, report and stop"; document "audit exit 10 = collision, continue to plan after reading the artifact." Add a skill test for both strings.

### MAJOR — Receipt misses the under-100-token acceptance target under real tokenizers

Files: `README.md:162`, `docs/judge-qa.md:27`, `engine/receipt.py:63`.

- Internal estimate: 95 (2-way), 96 (3-way).
- Actual: 109/110 (cl100k/o200k) for 2-way; 113/114 for 3-way.
- `README.md` calls "receipt under 100 JSON tokens" an acceptance target; CONTRACT acceptance test 6 says under 100. The recorded engine README already shows 109/113 cl100k, so the claim is knowingly over the target.

Fix: shrink the receipt (shorter keys/rollback string), or change the acceptance target and all copy to "under 125 actual / ~96 estimate" and stop saying "under 100 tokens" without qualification.

### MAJOR — Apply does not re-derive the approval token, so an edited plan + matching token is accepted

Files: `engine/apply.py:244-249`, `engine/plan.py:84`.

Apply compares `--approve` to `plan["approval_token"]`. It never recomputes the hash from `environment/threshold/segments/audience_changes`. The token is deterministic and not secret; anyone who edits a plan can call `approval_token()` and pass the result. The docs' "approval is structural / editing changes the token" is true only for accidental edits that leave the stored token stale.

Fix: recompute the expected token inside apply from the plan content and compare; include project/environment/restore in the binding; document that the token is a confirmation string, not a signature. Add a test that mutates a change without updating the token (already) and one that mutates both (currently accepted).

### MAJOR — Demo and receipt claims do not match apply output

Files: `README.md:30`, `README.md:170-172`, `docs/demo-script.md:89-91`, `docs/submission.md:69,93`, `engine/receipt.py:26-31`.

- 2-way apply: `segments created=0 reused=2`, because segments 7/8 already existed. The demo says "creates both segments" and "creates the segments."
- Apply stderr summary is only: `apply: 2 experiment(s) running, segments created=0 reused=2, pass=True`; it does not list the disable → change → re-enable → start cycle. `apply.json` has final changes but no step log.
- Receipt `rollback` is one sentence: `restore 20,21 from plan.restore`; it does not repeat the plan's four commands, despite the README saying it does.

Fix: change narration to "ensures the segments (creates or reuses)", add a `steps` array to apply output if the demo needs the cycle on screen, and either put the actual rollback commands in the receipt or stop claiming it repeats them.

### MAJOR — "Pause, re-run plan/apply" guidance is wrong; paused audiences are immutable

Files: `engine/plan.py:168-169`, `README.md` limitations, `docs/judge-qa.md:15` (ambiguous).

The blocked-running note says "pause experiment, re-run plan/apply/verify, then restart." Live check: after pause, PATCHing the audience returns `Cannot change the audience of a paused experiment`; apply also refuses any status other than `created`. Pausing alone cannot free the experiment for isolation. The operator must complete/delete and recreate it (or use a new experiment).

Fix: change the note and docs to "complete/delete and recreate"; do not suggest pause as an isolation step. Add a live or fake API test for paused audience PATCH failure.

### MAJOR — Plan rollback omits segment deletion; partial apply loses created segment IDs

Files: `engine/plan.py:315-322`, `engine/apply.py:345-353`.

For 3-way, `plan.rollback` had 6 experiment commands and no segment deletes; `apply.rollback` had 9 because it learned IDs 34–36 at runtime. If apply fails after creating segments but before success, the exception message has only "Apply failed after N experiment(s)" and no created-segment list; the operator has no artifact to delete them. Docs Q11 says "created segments are recorded for deletion," which is false on failure.

Fix: include planned segment names and, on failure, write an apply-failure JSON with created IDs and the rollback state; add a partial-failure test.

### MINOR — No-op apply accepts a wrong or missing token

File: `engine/apply.py:221-232`.

A plan with `audience_changes: []` returns `pass:true`, `approval_token_verified:false` before token validation. Live: no-op plan + `--approve iso-wrong` exited 0. No mutation, but it violates the unqualified "apply needs the exact token" claim in SKILL.md/README.

Fix: require the token before the no-op return, or define an explicit `noop` approval path and document it.

### MINOR — Receipt's "isolated" is pair-scoped but unlabeled

File: `engine/receipt.py:45-51`.

After the 3-way apply, the audit had 21 collision pairs across 7 experiments; verify passed for the 3 planned experiments only, and the receipt says `after.verdict: isolated` with no scope or remaining-collision count. This can be read as environment-wide isolation. The docs Q13 admits verify is pair-specific, but the artifact does not.

Fix: add `scope: planned_experiments` and `remaining_environment_collisions` (or equivalent) to the receipt; or change the verdict to `planned_pair_isolated`.

### MINOR — Skill directory/name mismatch against the Agent Skills spec

File: `skill/SKILL.md:2`.

Spec: "Must match the parent directory name." In-repo parent is `skill`, name is `experiment-isolation`. The install instructions copy it to `~/.claude/skills/experiment-isolation`, so the installed copy is valid, but a validator run on the repository fails the spec rule. `quick_validate.py` does not enforce this rule, so its PASS is not sufficient.

Fix: package as `experiment-isolation/SKILL.md` (or add a build/rename step and a test that asserts the parent basename).

### MINOR — Seed reuses running experiments and reports "not started"

File: `engine/seed.py:99-111,218`.

The first `seed --experiments 3` on a state where 20/21 were running reused them, created only one new draft, and printed "not started" even though `started:true`. The demo seed is supposed to leave drafts. This made a reset necessary before the N-way run.

Fix: if an active experiment for the feature is running/paused, refuse with a clear message or require an explicit `--reset`; make the stderr summary reflect statuses.

### MINOR — Reference docs drift

- `skill/references/api.md:9` says list experiments with `?status=running`; audit lists all non-completed (including created/paused).
- `skill/references/api.md:51` says responses serialize `property_`; observed responses use `property`.
- `skill/references/api.md:53` says the current plan uses two ranges; live 3-way uses three.
- `skill/references/safety.md:10` says plan is "offline"; it performs Admin API GETs (read-only, not offline).

These are review/debugging docs, not runtime, but they are cited by the skill.

### MINOR — Malformed experiment metadata can escape the exit-code contract

File: `engine/sampling.py:198` (`int(experiment.get("id"))`).

A flag metadata object without an experiment id raises `TypeError`, which is not one of the caught `EngineError` types in `engine/cli.py`; the process would exit 1 with a traceback rather than the documented 20. No live occurrence; noted from code inspection.

Fix: validate the metadata and raise `EngineError("malformed experiment metadata")`.

## Secret scan

Method: read the six key/token values from `~/flagsmith-local/flagsmith.env` in memory (ADMIN_TOKEN, DEV_ENV_KEY, PROD_ENV_KEY, SERVER_ENV_KEY, FLAGSMITH_API_KEY_localhost_8000, FLAGSMITH_ENVIRONMENT), searched all text files in the repo and the /tmp JSON/stdout/stderr artifacts, and reported only variable names and paths. No values were printed in this report.

- Repository files: **no exact secret values found**.
- /tmp artifacts: **no exact secret values found**.
- Engine output/errors: env key replaced with `<env>` in the 403 path; admin key not observed.
- **Printed-output failure:** the documented rollback command printed the environment key in the request URL on HTTP 400. The same plan strings put `$DEV_ENV_KEY` in argv, contradicting the README claim that "secrets are never ... passed in argv." The admin API key itself was not observed in argv or output.
- `skill/scripts/check_env.sh` live output showed only variable names/presence, no values.

## Residual risks

- No successful live partial-failure drill; the attempted rollback drill failed before the partial-apply path. The failure path is untested.
- No lab/dashboard/video verification in this pass; README's video and results table remain TODO. The lab's one-command claim is unverified.
- The sample is synthetic and not stratified; a 50/30/20 matrix plus SHA buckets gives 46/54 and 31/35/34 splits. A clear verdict is "not proven," not population-safe.
- Verify/receipt cover the planned experiments only; pre-existing running collisions remain (15 pairs in the 2-way audit, 21 in the 3-way audit). The receipt does not say this.
- External `flagsmith api` returns 0 on HTTP 4xx; any future automation that trusts its exit code is unsafe.
- The engine has no confidence interval/power calculation; the threshold is policy.
- Malformed API data can still produce an uncaught traceback (see minor bug).
- Final demo IDs are 25/26, not the engine README's recorded 20/21; docs recording the run must use the new IDs or reset to the recorded state.

## Final reset state

Changed only local demo state, not source:

- Deleted experiments 20/21 (the 2-way pair started during verification) and 22/23/24 (the 3-way test) after pausing them. Deleted test segments 34/35/36.
- Pre-existing experiments 1–4 remain running and untouched.
- Drafts 25 (`Express checkout`) and 26 (`Discount badge`) are `created`, audience segment 4, not started.
- Kept pre-existing segments 2, 4, 7, 8. `free_shipping` (feature 8) remains with no active experiment after the 3-way cleanup.
- Synthetic `iso_*` identities remain (documented behavior; no cleanup run).
- No generated audit/plan/apply/verify/receipt/restore files were left in the repository root; evidence is under /tmp.
- No edits to engine/, skill/, lab/, docs/, README.md, seed/, tests/, or video/.

## Recommendation

Do not record the demo as "safe with rollback" until the rollback path is fixed and drilled live. The core happy-path loop is real and reproducible; the remaining work is claim integrity, skill instructions, receipt size, packaging, and an honest rollback story.