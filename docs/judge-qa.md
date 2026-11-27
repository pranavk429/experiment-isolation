# Judge Q&A — 14 likely questions, honest answers

These are for live Q&A or the video narration. Where a number is not measured, the answer says so. `TODO` is deliberate: do not improvise a number. Sources are file paths or URLs so a judge can check the claim.

## Q1. Isn't this just Flagsmith audiences? Why a skill?

Audiences are the mechanism; isolation is the invariant Flagsmith does not enforce. In 2.291.0 an experiment audience holds exactly one segment (`MAX_AUDIENCE_SEGMENTS = 1`), and nothing stops two experiments naming the same segment. The API also rejects `PERCENTAGE_SPLIT` inside an audience segment, requires the rollout to be disabled before an audience change, and refuses audience changes on a running experiment ([CONTRACT.md](../CONTRACT.md), verified locally). The skill is the audit → stop → plan → approve → apply → verify → receipt procedure. It is not just segment creation: `plan` allocates contiguous ranges across N colliding drafts (the live 3-way run used [0,32], [33,65], [66,99]), refuses infeasible allocations with exit 10 and no partial writes (traffic-aware feasibility: `--max-concurrent 4`, `--min-bucket-width 5`), and the audit reports multi-exposure (`multi_exposed_rate`, `max_exposure_count`, `risk`) while verify reports `after_multi_exposed_rate`. `audit` exits 10 on collision; that is the expected stop signal, not an error. Delete Flagsmith and there is no enrollment to measure, no audience to change, and no state to verify. If Flagsmith ships native mutual exclusion, this becomes a stopgap; today it is the safe path ([verification/REPORT2.md](../verification/REPORT2.md)).

## Q2. How do you measure overlap without real users?

The current engine builds a deterministic synthetic sample (`iso_0001`…), assigns a stable 0–99 bucket from `sha256(identifier)`, persists `country`, `platform`, and `flagsmith_experiment_bucket` through `flagsmith evaluate --persist`, then reads `metadata.experiment.in_experiment` back from each identity ([engine/sampling.py](../engine/sampling.py), [engine/audit.py](../engine/audit.py)). Draft experiments are projected from their segment rules and labelled `basis: projected`; running experiments are `measured`. So the demo measures a synthetic cohort, not production users. The method would transfer if you replaced `build_sample` with real identifiers from a warehouse or exposure log and persisted the same traits; that adapter is not built (TODO). The receipt reports `sample_size` and the multi-exposure metrics; we do not claim population-level certainty.

## Q3. What happens to already-running experiments?

They are audited and reported, not modified. `plan` only changes experiments with `status: created`; `apply` refuses anything else with exit 10, and `plan.blocked_running` lists every running experiment that overlaps a planned draft ([engine/plan.py](../engine/plan.py), [engine/apply.py](../engine/apply.py)). To isolate a running experiment, use the rollback path: it deletes the started experiment and recreates it as a new draft with the old audience (`live_restore=false`, `requires_recreate=true`); pausing does not allow an audience change ([verification/REPORT2.md](../verification/REPORT2.md)). `verify` and the receipt cover the planned experiments only; remaining environment collisions are reported (18 in the 3-way run, 14 in the 2-way). Scope is pre-launch drafts by design.

## Q4. Why bucket traits instead of percentage splits?

Flagsmith rejects a `PERCENTAGE_SPLIT` condition inside an experiment audience segment: `Audience segment N contains a percentage split` (verified on 2.291.0; [CONTRACT.md](../CONTRACT.md)). A stable integer trait `flagsmith_experiment_bucket` (0–99) with contiguous range conditions is accepted, deterministic per identity, and evaluated by Flagsmith's normal segment engine. The 2-way run used [0,49] and [50,99]; the live 3-way run used [0,32], [33,65], [66,99]. It is also portable to SDK/edge evaluation because it is a plain persisted trait. Trade-offs: the app or warehouse must assign and persist the bucket; the split is approximately uniform, not stratified by country or platform; an identity with no bucket trait falls outside every range; and the split is not exact in small samples ([README.md](../README.md#safety-and-limitations)). Liftover uses the same 0–99 bucket idea to preserve users during migration; we use it to isolate experiments.

## Q5. Does this actually improve experiment validity, or just tidy audiences?

It removes one specific threat: cross-experiment treatment contamination when the same users are enrolled in two or more experiments. The independent verifier recorded max pairwise Jaccard 1.0 → 0.0 for both the 2-way and 3-way runs, and multi-exposed rate 0.76 → 0.0 ([verification/REPORT2.md](../verification/REPORT2.md)). It does not fix instrumentation ([FlagMedic](https://github.com/Class-now/flagmedic)), sample-ratio mismatch or winner selection ([GAVEL](https://github.com/RAK2315/gavel), [closeout](https://github.com/calebjohndan-hoop/flagsmith-experiment-closeout)), peeking, multiple comparisons, or guardrail metrics. If by "validity" you mean "are the statistics correct," no: this makes assignment disjoint, and the rest of the validity stack is other tools' job. If you mean "can two changes be attributed separately," this removes one assignment-level reason they cannot.

## Q6. What is the token count and what does it include?

The measured demo-run harness number is TODO — do not quote one until it is recorded. The receipt's actual counts are 121 o200k / 120 cl100k for the 2-way and 125 / 124 for the 3-way; the internal estimate is 108–109. Report those exact numbers; state the acceptance target as ≤125 actual ([verification/REPORT2.md](../verification/REPORT2.md)). [token-count.md](token-count.md) defines the harness number: input + output for the 0:30–2:25 session, including `SKILL.md`, any references opened, the five JSON artifacts, command summaries, tool-call arguments, model replies, and retries; the system prompt and history are in the harness total only. The supporting number is the `o200k_base` model-visible subtotal. The receipt's own `token_count` fields use `estimate_tokens` = ceil(characters/4); `skills/experiment-isolation/scripts/token_count.py` uses tiktoken when installed. Report harness, model, date, commit, and sample size; report cached input separately. Do not substitute receipt size for the demo total.

## Q7. Is this merged upstream?

No. It is packaged for contribution to the official Flagsmith skills repo. As of 2026-11-27, no public official skills repo existed at the names checked, and PR #120 is the first community PR in the CLI skills discussion (#67) ([research/05](../../research/05-competitor-recon.md), [research/06](../../research/06-synthesis.md)). The event says winning skills get merged; that is a promise, not current status. Say "packaged for upstream contribution," never "merged." The repo makes no upstream merge claim ([README.md](../README.md), [submission.md](submission.md)).

## Q8. Why should this be a skill rather than a product feature?

Long term, a native feature is the right fix: experiment layers or first-class mutual exclusion belong in Flagsmith. A skill is the right contribution now because the missing piece is a procedure and a refusal policy, not a new API. Today's safe path is a multi-step sequence — choose ranges, one segment per audience, no percentage split, disable the rollout, change the audience, start (which re-enables serving), re-sample — and an agent can get it wrong at any step. The skill encodes the sequence, the N-way allocation and feasibility checks, the approval token, and the stop conditions without waiting for a platform release. The feedback section asks Flagsmith for the native primitive ([submission.md](submission.md#feedback)), which is the honest long-term answer.

## Q9. How is this different from GAVEL / FlagMedic / closeout / DoNotMix / Liftover?

| Entry | What it does | Why it is not this |
|---|---|---|
| [GAVEL](https://github.com/RAK2315/gavel) | Post-hoc referee: refuses a missing or broken SRM, too few exposures, or a losing experiment; proposes a winner; a named person approves; completes via `complete/`. | It decides after the experiment has run. It does not design or change the pre-launch experiment audience, and it does not detect two experiments sharing users. |
| [FlagMedic](https://github.com/Class-now/flagmedic) | Post-launch instrumentation: traces missing exposures, `trackEvent` name mismatches, SRM, and buffered-event loss to code lines; proposes a fix; approved ship. | Correct counters do not make two experiments independent. It fixes the measurement, not the assignment. |
| [closeout](https://github.com/calebjohndan-hoop/flagsmith-experiment-closeout) | Post-experiment verdict, SRM fallback, human-approved ship, live verify, cleanup plan, decision record. | It starts when an experiment has data. It does not design or verify disjoint audiences before launch. |
| [DoNotMix](https://github.com/dorakingx/donotmix) | Code-level combinatorial testing: covering arrays, AST hypergraph, delta debugging, approval, re-verify. | It tests whether the app works when flags combine, not whether two experiments assign the same users. A code path can be correct and the experiment still confounded. |
| [Liftover](https://github.com/YashasviThakur/liftover) | Vendor → Flagsmith migration: inventory, plan, apply, vendor-SDK parity, production token, rollback, cutover PR. | It moves flags into Flagsmith. It mentions the 0–99 bucket trait for preserving users during migration, not for isolating two experiments. |

Also adjacent: [PR #120](https://github.com/Flagsmith/flagsmith-cli/pull/120) rehearses handler retirement; [Early Access](https://github.com/vivekyarra/early-access) manages per-customer grants. All are complementary. In the public sample we inspected, ours is the only one that plans N-way disjoint experiment ranges, refuses infeasible allocations, and measures multi-exposure before launch.

## Q10. What happens when the sample is wrong or too small?

The verdict is only as good as the sample. The engine builds a fixed 50/30/20 matrix, not a random draw from your population, so "wrong" can mean unrepresentative; it reports `sample_size`, per-experiment `enrolled` and `a_rate`, raw `shared`/`union`, and the multi-exposure metrics `multi_exposed_rate`, `max_exposure_count`, and `risk` so thin or concentrated cells are visible ([engine/audit.py](../engine/audit.py)). `--samples` must be at least 2 and is capped at 5000; default 500. There is no confidence interval or power calculation yet (TODO). A 5% Jaccard threshold on 500 identities is a policy, not a significance test. Mitigation: use a larger sample, a staging or disposable environment, and real identifiers with the same traits; treat a small-sample "clear" as "not proven," not "safe." If the trait distribution is wrong, the overlap estimate is biased; the tool does not reweight.

## Q11. What is the rollback story?

`plan` captures a restore payload per experiment before any write (`plan.restore`), and `apply` writes `restore-<id>.json` beside `apply.json` when `--out` is given ([engine/plan.py](../engine/plan.py), [engine/apply.py](../engine/apply.py)). The engine's `rollback` command is verified live ([verification/REPORT2.md](../verification/REPORT2.md)). For a created-only draft, rollback restores the old audience in place (`live_restore=true`, `requires_recreate=false`). For a started experiment, Flagsmith cannot change the audience in place, so rollback deletes it and creates a new draft with the old audience (`live_restore=false`, `requires_recreate=true`). An apply failure writes `apply-failure.json` with created segment IDs; rollback cleans them up; failures sanitize keys and URLs. Residual risk: the started-experiment path deletes before creating the replacement, so a create failure could lose the original, and the partial-apply path is unit-tested only. Do not claim in-place restore for started experiments.

## Q12. Why Track 3 too?

The same repo contains a self-hosted lab, not a second product: Flagsmith 2.291.0 + Postgres + experimentation through Docker Compose on local ports 8010/8011, a seeded storefront with two colliding experiments, and a single-page overlap dashboard (`lab/`, [CONTRACT.md](../CONTRACT.md)). It is designed for one command (`bash lab/run.sh`) and satisfies Track 3's self-hosted, integration/developer-tool, and reuse criteria; it doubles as the demo environment for Track 4. The verifier did not verify the lab or dashboard this pass, so the one-command claim is unverified; the lab falls back to a clearly labeled sample audit if the engine CLI fails, and that fallback must never be presented as measured ([verification/REPORT2.md](../verification/REPORT2.md)). Multi-track submission is allowed; a project can win only one track ([research/06](../../research/06-synthesis.md)).

## Q13. Isn't the 0% after true by construction?

Partly, yes. The allocated ranges are disjoint by definition, so 0 is the expected result. `verify` is an integration test, not a discovery: it checks the audience actually changed, the traits persisted, all planned experiments are running and non-empty, and both max pairwise overlap and multi-exposure are zero ([engine/verify.py](../engine/verify.py)). The useful number is the before — the collision you did not know about; for drafts it is projected, and it becomes measured once the experiments run. In the verifier's 3-way run, the planned trio reached 0.0 and multi-exposure 0.0, but the receipt reports 18 remaining environment collision pairs (14 in the 2-way). So the after is planned-experiment scope, and the remaining collisions are reported, not eliminated. If verify returns nonzero, something is wrong with the segment, the trait, or the audience; we do not hand-wave it.

## Q14. What about more than two experiments, or experiments that must share an audience?

N-way is implemented. The live 3-way run used [0,32], [33,65], [66,99], created 3 segments, started 3 experiments, and verify returned max pairwise 0.0 ([verification/REPORT2.md](../verification/REPORT2.md)). Defaults are `--max-concurrent 4` and `--min-bucket-width 5`; an infeasible plan exits 10 with no partial writes (for example, `--max-concurrent 2` or `--min-bucket-width 40`). If experiments genuinely must share a population, they should run sequentially or use a deliberate layer or holdout design; the tool should not silently allow contamination. That is a product decision for a human, not something to auto-approve.

## Sentences to say exactly

- "It is packaged for upstream contribution, not merged."
- "The demo cohort is synthetic; the real-identifier adapter is TODO."
- "N-way is live: the 3-way run used [0,32], [33,65], [66,99] and verified max pairwise 0.0."
- "It isolates the planned experiments; the receipt reports the remaining environment collisions (18 in 3-way, 14 in 2-way)."
- "Receipts are roughly 120–125 actual tokens; 108–109 internal estimate."
- "Rollback is verified; started experiments are recreated as new drafts, not restored in place."
- "Apply re-derives the HMAC; recomputing the public token is rejected."
- "`audit` exit 10 on collision is the expected stop signal."
