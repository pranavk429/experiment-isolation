# Experiment Isolation Engine

Python 3.9 stdlib package and CLI that finds overlapping Flagsmith experiments,
measures contamination on a deterministic identity sample, isolates colliding
draft experiments with disjoint bucket-trait ranges, and provides a direct-API
rollback command with an honest recreate fallback.

Run everything from the repository root (the folder that contains engine/).

## Demo commands (exact)

    source ~/flagsmith-local/flagsmith.env
    export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"

    # 1. Create two DRAFT experiments that collide on us_mobile.
    python3 seed/demo_seed.py --reset

    # 2. Measure overlap. audit exits 10 on collision, by design (CI gate).
    python3 -m engine.cli audit --samples 100 --workers 4 --out audit.json

    # 3. Build the plan and its approval token.
    python3 -m engine.cli plan --audit audit.json --out plan.json

    # 4. Apply with the exact token from plan.json.
    TOKEN=$(python3 -c "import json; print(json.load(open('plan.json'))['approval_token'])")
    python3 -m engine.cli apply --plan plan.json --approve "$TOKEN" --out apply.json

    # 5. Verify the planned experiments are disjoint.
    python3 -m engine.cli verify --plan plan.json --samples 100 --workers 4 --out verify.json

    # 6. Compact receipt (before/after Jaccard and multi-exposure).
    python3 -m engine.cli receipt --audit audit.json --plan plan.json \
        --verify verify.json --apply apply.json --out receipt.json

    # 7. Rollback. Direct Admin API; no flagsmith api shell-out.
    python3 -m engine.cli rollback --apply apply.json --out rollback.json

    # Offline suite.
    python3 -m pytest tests/engine -q

3-way demo:

    python3 seed/demo_seed.py --experiments 3 --reset
    python3 -m engine.cli audit --samples 100 --workers 4 --out audit.json
    python3 -m engine.cli plan --audit audit.json --out plan.json
    TOKEN=$(python3 -c "import json; print(json.load(open('plan.json'))['approval_token'])")
    python3 -m engine.cli apply --plan plan.json --approve "$TOKEN" --out apply.json
    python3 -m engine.cli verify --plan plan.json --samples 100 --workers 4 --out verify.json
    python3 -m engine.cli receipt --audit audit.json --plan plan.json \
        --verify verify.json --apply apply.json --out receipt.json
    python3 -m engine.cli rollback --apply apply.json --out rollback.json

For a no-op plan (no audience changes), apply requires the literal
--approve noop. A wrong or missing token exits 10.

## Exit codes (exact)

- audit: 10 when verdict is collision; 0 when clear or none; 20 error.
  The JSON artifact is still written on exit 10. A CI gate should treat 10 as
  "do not launch".
- plan: 10 when infeasible; 0 when a feasible plan is written; 20 error.
  Blocked running experiments are reported but do not make a feasible draft
  plan fail.
- apply: 10 on missing/wrong approval, an infeasible plan, a change targeting a
  blocked/running experiment, or any target not status=created; 0 success.
- verify: 10 when pass is false; 0 when true; 20 error.
- rollback: 0 when every experiment was restored/recreated and created segments
  were deleted; 10 when the artifact cannot be rolled back safely; 20 API error.
- receipt: 10 when pass is false; 0 when true; 20 error.

## N-way plan and feasibility

For N colliding draft experiments, ranges are proportional and contiguous:

    lo = floor(i * 100 / N), hi = floor((i + 1) * 100 / N) - 1

- Each segment is flagsmith_experiment_bucket GREATER_THAN_INCLUSIVE lo AND
  LESS_THAN hi+1. The lower bound is omitted when lo is 0. The last range uses
  LESS_THAN 100.
- Legacy single-bound segments are reused only when they match the same
  semantic range: LESS_THAN 50 is [0,49], GREATER_THAN_INCLUSIVE 50 is [50,99].
- bucket_width = 100 // N. feasible is false when bucket_width is below
  --min-bucket-width (default 5) or N exceeds --max-concurrent (default 4).
- Infeasible plan.json: feasible=false, no changes, no token,
  deferred_experiments lists every draft, schedule gives sequential batches.
  plan exits 10; no partial isolation is planned.

## Contamination impact

audit reports multi_exposed_rate (identities in 2+ experiments),
max_exposure_count, and risk:
- none: rate 0
- low: rate <= 0.05
- elevated: rate <= 0.25 and max < 3
- critical: rate > 0.25 or max_exposure_count >= 3

verify reports max_pairwise_jaccard, after_jaccard, and
after_multi_exposed_rate for the planned experiments. pass requires zero
pairwise overlap, zero multi-exposure, all running and all non-empty. The
receipt carries scope=planned_experiments and
remaining_environment_collisions, and before/after rates.

## Blocked running experiments

plan.blocked_running lists every running experiment that overlaps a planned
draft, with experiment_id, reason, and a pause_isolate_restart note. The note is
deliberately NOT "pause and re-run": Flagsmith 2.291.0 rejects audience changes
on paused experiments too. The note says complete/delete and recreate with a
disjoint range. apply never modifies blocked experiments; a change targeting one
exits 10 before any write.

## Rollback (direct API, honest fallback)

rollback reads --apply apply.json (or apply-failure.json) and, if needed,
--plan plan.json. It uses AdminAPI with urllib and never calls flagsmith api.

- status=created: PATCH rollout enabled=false with the old audience, then PATCH
  the restore rollout (enabled as captured). This is a live in-place restore.
- status=running or paused: Flagsmith rejects audience changes. The command
  pauses if needed, deletes the started experiment, and creates a new DRAFT
  with the original feature, metrics, variant allocation, and old audience.
  The result says live_restore=false and requires_recreate=true. It never
  claims an in-place rollback.
- status=completed: creates a new draft on the freed feature; does not claim a
  live restore.
- Created segment IDs from apply.json are deleted only after every experiment
  restore/recreate succeeds.
- If apply fails partway, it writes apply-failure.json beside apply.json (or in
  the current directory) with pass=false, the error, created/reused segment IDs,
  applied changes (including an in-progress change), steps, restore state, and
  the rollback command.

## Approval token binding

plan computes iso-<8 hex> as an HMAC-SHA256 over the plan content: environment,
project, threshold, segment ranges, audience changes, and restore snapshots.
The HMAC key is the local admin key; the token is a confirmation token, not a
public signature. apply recomputes the token from the plan content and requires
both --approve and plan.approval_token to match. Editing a change (even if you
recompute the public no-secret helper) is rejected. An operator with the admin
key can still forge a token; this is not a secret-sharing scheme.

## Seed behavior

seed creates only created (draft) experiments. If an active experiment for a
seed feature is running or paused, seed refuses with a clear message and exits
20 unless --reset is passed. --reset deletes all managed seed experiments
(running ones are paused first), then creates the requested 2 or 3 drafts.
stderr lists the actual experiment statuses.

## Configuration and credentials

The engine loads ~/flagsmith-local/flagsmith.env if variables are not already
set. It uses FLAGSMITH_API_URL (localhost/127.0.0.1 unless ISO_ALLOW_REMOTE=1),
FLAGSMITH_API_KEY_localhost_8000, DEV_ENV_KEY (or --env), and FLAGSMITH_PROJECT.

Admin calls use Authorization: Api-Key. Identity reads use X-Environment-Key.
Trait persistence shells out to the flagsmith v2 CLI with evaluate --persist.
The admin key is never placed in argv, JSON, stderr, or an error message. API
errors replace the environment key with <env> and the admin key with <redacted>.

## Safety model

- audit and plan are read-only. apply and rollback are the mutating commands.
- apply requires the recomputed HMAC token before any write.
- apply refuses any experiment that is not status=created.
- audience segments containing PERCENTAGE_SPLIT are rejected by plan/apply.
- every mutation is read back; steps are recorded in apply.json.
- segment creation is idempotent by semantic range, then by name.
- seed is idempotent for drafts; running/paused seed experiments require --reset.
- synthetic malformed metadata raises EngineError and exits 20.

## Measurement

The sample is deterministic: identity iso_0001..iso_N, a 10-entry trait cycle
(50% US/mobile, 30% GB/mobile, 20% US/desktop), and
flagsmith_experiment_bucket = int(sha256(identifier)[0:8], 16) % 100.

Running experiments are measured from metadata.experiment.in_experiment on the
Edge identity payload. Drafts are labelled basis=projected and use segment rules
plus rollout percentage. Malformed metadata is an EngineError, not a traceback.

## Limitations

- An experiment audience can contain only one segment.
- Running/paused experiments cannot change audience; they must be completed or
  deleted and recreated. Rollback uses that recreate fallback and reports it.
- At most --max-concurrent drafts fit in one plan, and every range must be at
  least --min-bucket-width buckets.
- Existing running collisions remain; the receipt is scoped to planned
  experiments and reports remaining_environment_collisions.
- Synthetic identities remain. Use --cleanup or a disposable environment.
- Local-instance only by default.

## Receipt size

The receipt exceeds the old 100-token target; the stated ceiling is <=125 actual
tokens. The engine's own estimate is ceil(characters/4).
- Authoritative 2-way receipt: 429 chars, 121 o200k / 120 cl100k (engine estimate 107).
- 3-way stress-test receipt: 435 chars, 125 o200k / 124 cl100k (engine estimate 109).
Both include scope=planned_experiments, remaining_environment_collisions,
before/after Jaccard, before/after multi-exposed rates, changes, per-command
token-count estimates, one compact rollback pointer, and pass. Full rollback
commands live in plan.json/apply.json.

## Files

- cli.py: commands and exit codes
- audit.py: discovery, enrollment, Jaccard, multi-exposure risk
- plan.py: N-way ranges, feasibility, HMAC token, blocked running, rollback
- apply.py: token recompute, steps, segment ensure, failure artifact
- rollback.py: direct-API restore and recreate fallback
- verify.py: max pairwise Jaccard and after multi-exposure
- receipt.py: compact scoped receipt
- sampling.py: deterministic sample, CLI persistence, metadata validation
- segments.py: rule evaluation and semantic range matching
- seed.py: 2/3 draft seed with --reset guard
- api.py, config.py, util.py: local HTTP, env loading, JSON helpers

## Recorded verification (2026-11-27)

2-way, sample=100 (experiments 27/28, then rolled back and reset):
- audit: 6 experiments, 15 collision pairs, draft pair Jaccard 1.0,
  multi 0.76, max 6, risk critical.
- plan: feasible, width 50, reused segments 7/8, token iso-936dad73.
- apply: 2 running, 6 steps, segments created 0 / reused 2.
- verify: 1.0 -> 0.0, multi 0.76 -> 0.0, pass true, enrolled 46/54.
- receipt: 429 chars, estimate 107, cl100k 120, o200k 121, pass true.
- rollback: both started experiments recreated as drafts (29/30),
  live_restore=false, requires_recreate=true, segments_deleted 0.

3-way, sample=100 (experiments 31/32/33, then rolled back and reset):
- audit: 7 experiments, 21 pairs, all draft pairs 1.0, multi 0.76, max 7.
- plan: feasible, width 33, ranges [0,32], [33,65], [66,99],
  token iso-2b939f9d.
- apply: 3 running, 9 steps, created segments 46/47/48.
- verify: max pairwise 0.0, multi 0.76 -> 0.0, pass true,
  enrolled 31/35/34.
- receipt (stress test): 435 chars, estimate 109, cl100k 124, o200k 125, pass true.
- rollback: 3 started experiments recreated as drafts (34/35/36),
  live_restore=false, segments_deleted [46/47/48].

Other live paths:
- wrong token: exit 10, no mutation.
- blocked running target: exit 10, no mutation.
- infeasible plan (--max-concurrent 2): exit 10, deferred [34,35,36], no changes.
- no-op plan wrong token: exit 10; --approve noop: exit 0.
- created-draft rollback drill: after disabling the current audience and
  patching the changed audience while disabled, the rollback restored [4] and
  enabled=true in place; live_restore=true, requires_recreate=false.

Offline suite: 54 passed.

Final reset state: drafts 39/40 created, not started; pre-existing experiments
1-4 running; segments 2/4/7/8 only; no exp_iso_* segments.
