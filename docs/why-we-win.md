# Why we win — a candid comparison

Snapshot: 2026-11-27. The six strongest Track 4 entries we inspected — [Liftover](https://github.com/YashasviThakur/liftover), [PR #120](https://github.com/Flagsmith/flagsmith-cli/pull/120), [GAVEL](https://github.com/RAK2315/gavel), [FlagMedic](https://github.com/Class-now/flagmedic), [DoNotMix](https://github.com/dorakingx/donotmix), and [flagsmith-experiment-closeout](https://github.com/calebjohndan-hoop/flagsmith-experiment-closeout) — are strong. [Early Access](https://github.com/vivekyarra/early-access) is a credible seventh. None is weak. They answer different questions, and one question is still open in the public sample.

## The position

**Experiment Isolation owns pre-launch audience assignment:** before another experiment starts, prove it does not share users with the experiments already planned or running; if it does, stop and show the collision; if a human approves, allocate contiguous, disjoint bucket ranges across all colliding drafts; re-sample to verify the planned experiments are disjoint; leave a receipt that states its scope.

We do not own post-hoc validity, instrumentation, migration, rollback rehearsal, code-level flag interactions, or per-customer access. Those are different layers, and the strongest entries own them well.

## What each incumbent owns — and does not

| Entry | Owns | Does not own | Layer |
|---|---|---|---|
| **Flagsmith audiences** (platform) | Segment rules, one audience per experiment, rollout, evaluation. | Conflict detection, bucket reservation, verification, a receipt. | Primitive; no mutual exclusion. |
| **[Liftover](https://github.com/YashasviThakur/liftover)** | Inventory, plan, apply, vendor-SDK parity on 4,000 users, production token, rollback, cutover PR. | Experiment enrollment or mutual exclusion; its 0–99 bucket note is for migration parity. | Migration; before Flagsmith is the source of truth. |
| **[PR #120](https://github.com/Flagsmith/flagsmith-cli/pull/120)** | Clone a test environment, probe both assignments, replay a captured item, verify cleanup. | Experiment audiences; it decides when a handler can be retired. | Retirement and rollback rehearsal. |
| **[GAVEL](https://github.com/RAK2315/gavel)** | Post-hoc SRM/sample/winner gate, named approval, the `complete/` decision write. | Who enters each experiment; no segment or audience writes. | Measurement and decision. |
| **[FlagMedic](https://github.com/Class-now/flagmedic)** | Instrumentation bugs traced to code lines, fix proposal, approved ship. | Cross-experiment contamination or audience design. | Exposure data quality. |
| **[closeout](https://github.com/calebjohndan-hoop/flagsmith-experiment-closeout)** | Verdict, SRM fallback, ship, live verify, cleanup, decision record. | Pre-launch audience design; starts after the run. | Decision and cleanup. |
| **[DoNotMix](https://github.com/dorakingx/donotmix)** | Covering arrays, AST hypergraph, delta debugging, approval, re-verify. | Statistical interference between audiences; it tests code under flag states. | Code behavior under flag combinations. |
| **[Early Access](https://github.com/vivekyarra/early-access)** | Per-customer grant, verify, expire, revoke, rollback. | Experiment-level mutual exclusion. | Per-customer access. |

## The layer map

| Stage | Question | Strongest owner |
|---|---|---|
| Before Flagsmith | How do we migrate without changing users? | Liftover |
| Design and launch | **Who is allowed into which experiment?** | **Experiment Isolation** — open in the public sample |
| Exposure | Are exposures and conversions recorded correctly? | FlagMedic |
| Analysis and decision | Is the result real, and what do we ship? | GAVEL, closeout |
| Code under flag states | Does the app work when flags combine? | DoNotMix |
| Retirement | When can the old handler go? | PR #120 |
| Per-customer access | Who gets this feature early? | Early Access |

## Why contamination is a different failure mode

- **An assignment bug, not a statistics bug.** GAVEL and closeout can refuse a winner or compute SRM, but SRM is a split-ratio check. It does not know a second experiment is feeding the same users. A perfectly balanced 50/50 experiment can still be contaminated by a co-running experiment.
- **Upstream of instrumentation.** FlagMedic can prove exposures are counted correctly and still leave two or more experiments sharing users. Correct counters do not make treatment arms independent.
- **Not a code-interaction bug.** DoNotMix can find a real bug when flags A and B are both on. It cannot find that experiments A and B share 100% of users. A code path can be correct and the experiment still confounded.
- **Not migration, retirement, or access.** Those change where flags live, when code can go, or who gets a feature early. None decides which experiments may co-run.

## Six reasons this can win

1. **Open lane, real sponsor gap.** Scorecard: Use of Flagsmith, Creativity. Pattern: the sponsor product does real work, and the loop is narrow. No public entry in the 190-repo event sweep does experiment mutual exclusion as of 2026-11-27 ([research/05](../../research/05-competitor-recon.md), [research/07](../../research/07-decision.md)). Flagsmith 2.291.0 has no mutual-exclusion primitive: one segment per audience, no `PERCENTAGE_SPLIT` inside an audience segment, no audience change while the rollout is enabled, and none on a running experiment ([CONTRACT.md](../CONTRACT.md)). Caveat: this is a public-sample claim, not proof no hidden entry exists.

2. **One narrow loop, five verbs, N-way inside it.** Scorecard: Impact and whole-job completion. Pattern: a narrow end-to-end loop beats a feature catalog. `audit` (exit 10 on collision, the expected signal) → `plan` (2+ colliding drafts; contiguous ranges; defaults `--max-concurrent 4`, `--min-bucket-width 5`) → `apply` → `verify` → `receipt`. The independent verifier's live 3-way run used [0,32], [33,65], [66,99], created 3 segments, started 3 experiments, and verify returned max pairwise 0.0; infeasible plans exit 10 with no partial writes ([engine/README.md](../engine/README.md), [verification/REPORT2.md](../verification/REPORT2.md)).

3. **The stop-and-ask is the demo.** Scorecard: Demo, 25%. Pattern: the unhappy path is a centerpiece. `audit` exits 10 on collision — that is the expected stop signal, not an error. `plan` then shows the disjoint ranges; `apply` with a wrong token on a plan with changes exits 10 with zero writes; a running experiment is refused rather than restarted. Use the exit-10 audit signal on camera ([demo-script.md](demo-script.md), [engine/cli.py](../engine/cli.py), [engine/apply.py](../engine/apply.py)).

4. **Approval is HMAC-bound, not just a typed yes.** Track 4 production safety. Pattern: human approval and bounded authority. `apply` re-derives an HMAC approval token from the plan content with the admin key and rejects an edited plan even when the public helper token is recomputed; the live verifier confirmed the rejection ([engine/apply.py](../engine/apply.py), [verification/REPORT2.md](../verification/REPORT2.md)). The token is truncated to 8 hex characters (32-bit) and is a confirmation token, not a signature: an admin-key holder can forge it. Review `plan.json` as a whole.

5. **The claim is measured, not asserted.** Pattern: concrete measurements. Track 4 token efficiency. The independent verifier recorded max pairwise Jaccard 1.0 → 0.0 for both the 2-way and 3-way runs, multi-exposed rate 0.76 → 0.0 ([verification/REPORT2.md](../verification/REPORT2.md)). The final measurement records 93 tests passing (55 engine + 38 skill) and the authoritative 2-way receipt at 121 o200k / 120 cl100k, 429 characters, internal estimate 107 ([verification/FINAL.md](../verification/FINAL.md)). The receipt includes five artifact estimates and excludes the full artifacts, the skill body (1,477 o200k, pending the compatibility trim), and the harness total. The 3-way 125 / 124 is a stress-test figure only, not the submitted 2-way number. The demo-run harness total, video, and final submission fields remain `TODO` ([judging-map.md](judging-map.md), [token-count.md](token-count.md)).

6. **Reusable packaging and double-entry.** Patterns: code plus a live artifact, documentation, reusable open-source packaging. Track 3 criteria. The repo contains [skills/experiment-isolation/](../skills/experiment-isolation/), a Python 3.9 stdlib engine, and a Docker Compose lab with a seeded storefront and an overlap dashboard. The lab is designed as the reproducible demo environment for Track 4, not a second product, but the verifier did not verify the lab or dashboard this pass ([README.md](../README.md), [CONTRACT.md](../CONTRACT.md)).

## Five risks that could lose it

| Risk | Why it could lose | Mitigation |
|---|---|---|
| **"Just audiences" / native-feature risk** | A judge can say audiences already exist; if Flagsmith ships native mutual exclusion, the skill is obsolete. | Point at N-way allocation across 2+ colliding drafts, traffic-aware feasibility (minimum bucket width and concurrency cap), and multi-exposure metrics (`multi_exposed_rate`, `max_exposure_count`, `risk`), not just segment creation. Say "stopgap, packaged for upstream contribution." |
| **Synthetic sample** | Demo identities are synthetic; measured overlap is not production overlap. A sharp judge will ask. | Label `projected` versus `measured`; report `sample_size`, `enrolled`, `shared`, `union`, and the multi-exposure metrics. Build or document a real-identifier adapter (TODO). Treat a clear verdict as "not proven," not "safe." |
| **Planned-experiment scope and running experiments** | N-way works within feasibility limits, but `verify` and the receipt cover only the planned experiments; the 3-way receipt reports 18 remaining environment collision pairs (14 in the 2-way). Running experiments are audited, not changed. Rollback is verified, but a started experiment is deleted and recreated as a new draft with the old audience (`live_restore=false`, `requires_recreate=true`); only a created-only draft restores in place (`live_restore=true`). | State the scope and remaining-collision count on screen. For a running experiment, use the rollback/recreate path; never suggest pause. Say "started experiments are recreated, not restored in place"; call out the delete-before-create residual risk. |
| **Incumbent gravity** | GAVEL, FlagMedic, and closeout are more complete post-launch products; judges may reward "ships a winner" over "prevents a bad launch." | Frame this as a layer, not a competitor. Add a handoff line: isolate → run → GAVEL/closeout. Do not attack the other entries. Make the 15-second hook the cost of contamination. |
| **Evidence gaps** | Rollback is verified but not transactional: a started experiment is deleted before the replacement draft is created, so a create failure could lose the original. The partial-apply path is unit-tested only; one 3-way verify timed out at `--workers 4` and passed on retry at `--workers 2`. The demo video, harness token total, lab one-command run, and final submission fields are still `TODO`. | Record the demo with a retry or lower worker count. Fill [judging-map.md](judging-map.md) and [token-count.md](token-count.md). Label the lab unverified until it runs from a clean clone. Note the started-experiment delete-before-create caveat and the unit-tested-only partial path. |

## What we must not claim

- "No one else does this" → "No public entry in the 190-repo event sweep as of 2026-11-27."
- "Merged upstream" → "Packaged for upstream contribution." No public official skills repo exists at the names checked.
- "Real users" → "Synthetic identities; simulated traffic."
- "Fixes experiment validity" → "Removes one assignment-level threat; does not fix instrumentation or statistics."
- "Environment-wide isolation" → "planned-experiment scope only; the receipt reports 18 remaining collisions in the 3-way run and 14 in the 2-way."
- "Pause to isolate" → "pausing does not allow audience changes; use the rollback/recreate path for a started experiment."
- "The HMAC token is a signature" → "it is a truncated 32-bit confirmation token; an admin-key holder can forge it."

## Bottom line

The top six are strong. We do not beat them at their layer. We win if a judge sees the layer difference and the demo proves the pre-launch invariant end to end: collision signal, N-way allocation, planned experiments made disjoint with approval, zero pairwise and multi-exposure re-measured, and a receipt that states its planned-experiment scope and remaining collisions. Rollback is verified, with one honest limit: a started experiment is deleted and recreated as a new draft, not restored in place.
