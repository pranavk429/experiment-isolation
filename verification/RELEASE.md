# Experiment Isolation — Final Release Gate

Date: 2026-11-27
Verifier: independent release verifier
Verdict: **NOT READY FOR SUBMISSION**

## Summary

The engine, skill, and lab behavior pass the requested release drills: **92 tests**, external skill validators pass, the 2-way demo produces **121 o200k / 120 cl100k**, and the lab goes **100% collision -> 0.0 -> 100% collision** with HTTP 200 throughout.

The project is not release-safe yet:

1. The verified build is not committed. HEAD is the initial commit, the working tree has 20 modified and 10 untracked files, and there is no remote. The submitted GitHub URL returns 404 logged out.
2. video/work/final/flagsmith-state.json (ignored, 147,914 bytes) contains the lab admin token and environment keys.
3. Several judge-facing docs still say the lab is unverified even though this gate ran reset -> demo -> reset successfully. engine/plan.py still emits "pause or recreate", which contradicts verified pause semantics.

## Check table

| # | Check | Command (abridged) | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | Full tests | pytest tests/engine tests/skill -q | 92 | 92 passed (54 engine + 38 skill) | PASS |
| 2 | Codex validator | quick_validate.py skills/experiment-isolation | valid | Skill is valid! exit 0 | PASS |
| 3 | Claude validator | quick_validate.py skills/experiment-isolation | valid | Skill is valid! exit 0 | PASS |
| 4 | Compatibility | inspect frontmatter | absent/short | absent | PASS |
| 5 | Seed 2-way | seed/demo_seed.py --experiments 2 | reuse | reused 51/52; started false | PASS |
| 6 | Audit 2-way | audit --samples 500 --workers 2 | exit 10 | exit 10; 6 experiments, 15 pairs; drafts 51/52 1.0, 250/250; multi 0.76; max 6; critical | PASS |
| 7 | Plan 2-way | plan --audit ... | feasible | width 50; [0,49]/[50,99]; segments 7/8; blocked 1-4 | PASS |
| 8 | Apply 2-way | apply --plan ... --approve token | 2 running | 2 running [7]/[8]; 6 steps; created 0 / reused 2 | PASS |
| 9 | Verify 2-way | verify --samples 500 --workers 2 | 1.0 -> 0.0 | 1.0 -> 0.0; multi 0.76 -> 0.0; 234/266; pass | PASS |
| 10 | Receipt 2-way | receipt --apply apply.json | 121/120, 429 chars, 107 | 121 o200k / 120 cl100k; 429 chars; internal 107; changes 4; scope planned; remaining 14 | PASS |
| 11 | Lab reset 1 | bash lab/run.sh reset | collision, no 409 | exit 0; 2 drafts segment 1; 1.0, 250/250; no 409 | PASS |
| 12 | Dashboard before | browser :8022 | 100% collision | Audiences collide; 100%; 250/250 | PASS |
| 13 | Lab demo | bash lab/run.sh demo | 1.0 -> 0.0 | verify 1.0 -> 0.0, pass; receipt pass; 234/266 | PASS |
| 14 | Dashboard after | browser reload | 0% isolated | Audiences isolated; before -> after 100% -> 0% | PASS |
| 15 | Lab reset 2 | bash lab/run.sh reset | collision, no 409 | exit 0; collision; receipt/verify removed; no 409 | PASS |
| 16 | Lab HTTP | curl storefront/dashboard | 200/200 | 200/200; Flagsmith health 200 | PASS |
| 17 | Docs banned claims | grep target docs | no stale phrases | no ~110, 110 tokens, 88 tests, pairwise only, third raises, rollback drill failed, apply does not re-derive, old skill/ path | PASS |
| 18 | 121/120 headline | grep token copy | 2-way headline | README/docs/engine/skill use 121/120 or 100-125 | PASS |
| 19 | 125/124 label | grep 125 | 3-way stress only | every hit labels 125/124 as 3-way stress | PASS |
| 20 | Historical 1,267 | grep 1,267 | no current claim | only explicitly labeled pre-portability line; current sum 4,309 | PASS (historical) |
| 21 | Full SKILL size | inspect token-count | current size | docs say full 1,611 pending trim; actual full 1,550 (body 1,477) | FAIL (stale) |
| 22 | Compatibility reference | grep compatibility | none | references/troubleshooting.md:49 still says See compatibility in SKILL.md | FAIL |
| 23 | Lab verified docs | grep unverified | lab verified | docs/judge-qa.md:59 and docs/why-we-win.md:55,65 say lab/dashboard unverified | FAIL |
| 24 | Demo IDs | grep 49/50 | match current/generic | README/demo-script/submission hard-code 49/50; current drafts 58/59 | FAIL (stale) |
| 25 | Secret scan repo/new | exact values both env files | none outside lab/.env | no secret values in repo outside lab/.env; no /tmp copies; no new output leak | PASS |
| 26 | Secret scan ignored files | exact values in tree | none | video/work/final/flagsmith-state.json contains LAB_ADMIN_TOKEN, DEV_ENV_KEY, FLAGSMITH_ENVIRONMENT_KEY, LAB_DEV_ENV_KEY | FAIL |
| 27 | .env tracked | git ls-files | none except example | only lab/.env.example tracked; lab/.env mode 600 and ignored | PASS |
| 28 | Git working tree | git status --short | clean | 20 modified, 10 untracked | FAIL |
| 29 | Git public repo | git remote; curl URL | public | no remote; HEAD 723dc2e initial; GitHub URL 404 logged out | FAIL |
| 30 | File count/large files | git ls-files; sizes | no huge tracked | 74 tracked; none >1MB; ignored renders 17MB/captures 16MB; .gitignore covers | PASS |
| 31 | Partial artifact | 3-way plan missing third restore | artifact with created IDs | exit 20; apply-failure.json created 79/80/81; changes 55/56 running, 57 applying; steps 6 | PASS |
| 32 | Partial error count | inspect failure output | accurate | says after 3 experiment(s) though only 2 started; third unchanged | FAIL (minor) |
| 33 | Plan pause note | inspect plan.notes | no unsafe pause advice | plan.notes says pause or recreate before changing audience | FAIL |
| 34 | Admin/Edge docs | inspect README/submission | match code | admin calls use flagsmith api claim is false; Edge API not called directly claim conflicts with EdgeAPI and root SUBMISSION | FAIL (minor) |
| 35 | Main final state | list experiments/segments | drafts only | 1-4 running; 58/59 created; segments 2/4/7/8 | PASS |
| 36 | Lab final state | audit + HTTP | clean collision | 1/2 created segment 1; 1.0, 250/250; dashboard 100%; HTTP 200 | PASS |

## Exact numbers

Engine 2-way (main :8000, sample 500): audit 6 experiments, 15 pairs; drafts 51/52 1.0, shared 250, union 250; multi 0.76; max 6; risk critical; exit 10. Plan width 50, [0,49]/[50,99], segments 7/8 reused, HMAC token, blocked 1-4. Apply 2 running, 6 steps, created 0 / reused 2. Verify 1.0 -> 0.0, multi 0.76 -> 0.0, enrolled 234/266, pass. Receipt 429 chars, internal 107, 121 o200k / 120 cl100k, changes 4, scope planned_experiments, remaining 14.

Lab: reset 1 clean 2 drafts on segment 1, dashboard 100%, 250/250, no 409. Demo verify 1.0 -> 0.0, receipt pass, dashboard before -> after 100% -> 0%, 234/266. Reset 2 collision again; receipt/verify removed; no 409. Storefront/dashboard/Flagsmith all HTTP 200.

Partial apply: drafts 55/56/57; created segments 79/80/81. Failure artifact pass=false, created IDs 79/80/81, changes 55/56 running, 57 applying, steps only 55/56. Error says after 3 despite 2 started. Cleanup deleted 79/80/81; final main 58/59.

Skill: SKILL body 1,477 o200k / 1,473 cl100k; full 1,550 / 1,546; 116 body lines. Both external validators pass; compatibility absent.

## Bugs

### BLOCKER — Uncommitted tree, no remote, public URL 404

git status: 20 modified, 10 untracked. git log -1: 723dc2e initial commit. No remote. https://github.com/pranavk429/experiment-isolation returns 404 logged out. The verified HMAC, rollback, docs, and packaging changes are absent from HEAD. Commit all intended files, create/configure the public repo, push, verify logged out, rerun the gate.

### BLOCKER — Ignored video state file contains live lab credentials

video/work/final/flagsmith-state.json (ignored by video/.gitignore:6; 147,914 bytes) contains exact LAB_ADMIN_TOKEN, DEV_ENV_KEY, FLAGSMITH_ENVIRONMENT_KEY, LAB_DEV_ENV_KEY values (not printed here). Remove it, rotate the lab admin token if exposed, and rescan before recording or packaging.

### MAJOR — Docs say lab/dashboard is unverified

docs/judge-qa.md:59 and docs/why-we-win.md:55,65 still say the verifier did not verify the lab, one-command run is TODO, and label the lab unverified. This gate ran reset -> demo -> reset successfully. Update to cite this gate.

### MAJOR — plan.notes recommends pausing

engine/plan.py:352 emits: running experiments are reported but not changed; pause or recreate them before changing their audience. Paused audiences are immutable; apply refuses paused. SKILL.md says ignore such a note, but the artifact gives unsafe guidance. Change to complete/delete and recreate.

### MAJOR — Stale full SKILL size and compatibility reference

docs/token-count.md:56,81 and docs/judge-qa.md:27, docs/why-we-win.md:53 say full SKILL 1,611 and pending compatibility trim; actual full is 1,550 (body 1,477). skills/experiment-isolation/references/troubleshooting.md:49 still says See compatibility in SKILL.md, but the field was removed for validator compliance. The 1,267 line is explicitly historical and acceptable.

### MAJOR — Hard-coded demo IDs

README.md:74, docs/demo-script.md:15,18,27,37,41 and docs/submission.md:19 expect drafts 49/50. Current final drafts are 58/59; the demo script itself says a full reset renumbers. Update to read current IDs or say the two created drafts.

### MINOR — Partial-apply error count overstates applied work

The live artifact correctly records 55/56 running and 57 applying, but the human error says after 3 experiment(s) when only two have steps. Count applied changes, not applied plus current_change.

### MINOR — Admin/Edge API descriptions conflict

README.md:43 and docs/submission.md:93 say admin calls use flagsmith api; engine writes use AdminAPI with headers. docs/submission.md:49 says Edge API is not called directly, while engine/api.py EdgeAPI reads /api/v1/identities/ with X-Environment-Key; root SUBMISSION.md:49 ticks Edge API. Pick one accurate form answer.

### MINOR — FINAL.md is stale

verification/FINAL.md records validator exit 1 for the removed compatibility field; both external validators now exit 0. It also records final drafts 51/52; current reset is 58/59. Mark historical or refresh.

## Residual risks

- Public repo, commit, push, and logged-out URL check are outstanding.
- Live lab credentials remain in video/work/final/flagsmith-state.json.
- Partial-apply failure is live-tested only before the first audience patch; the one-running-plus-one-applying path is unit-tested only.
- Started-experiment rollback deletes before recreating; a create failure loses the original.
- 3-way verify previously flaked once at --workers 4; the release-required 2-way verify at --workers 2 passed. Keep --workers 2 for recording.
- HMAC token is truncated to 32 bits; an admin-key holder can forge it.
- Receipt scope is planned_experiments with 14 remaining environment collisions; do not narrate environment-wide isolation.
- Synthetic, unstratified buckets: 250/250 and 234/266 are cohort expectations, not 50/50 guarantees.
- No tracked file >1MB; ignored video renders/captures total about 33MB and are correctly ignored but not part of the repo.
- Lab plain run.sh after a rollback-recreate sequence was not re-exercised this gate; reset -> demo -> reset passed.

## Final state

Main :8000: experiments 1-4 running; drafts 58 (Express checkout) and 59 (Discount badge) created, audience segment 4, not started; segments 2/4/7/8 only. Lab :8010/:8020/:8022: clean collision baseline; experiments 1/2 created on segment 1; audit 1.0, 250/250; dashboard 100%; storefront/dashboard HTTP 200. No test experiments 39-57 or test segments 61-81 remain; partial segments 79/80/81 were deleted. lab/.env remains local, mode 600, ignored; /tmp contains no exact secret values after CLEANUP. Only verification/RELEASE.md was written; no code or docs were edited.

## Release recommendation

Do not submit yet. The functional build passes its release drills, but a submission would still ship an uncommitted tree with no public remote and live credentials in an ignored video-work file. Commit and push the intended tree, remove/rotate the captured credentials, update the stale lab-unverified/size/ID statements, and fix the plan note. Then only the video upload and harness-total field remain.
