# ToggleWars submission — exact form answers

Copy/paste these. Replace every `TODO` with the recorded value before submitting. Do not submit with a `TODO` in a required field.

## Project details

**Project title (max 120 chars):**

```text
Experiment Isolation: stop overlapping Flagsmith experiments
```

**Tracks:** Track 3 — Build on Open Source Flagsmith; Track 4 — Flagsmith Agent Skills.

**Demo video:** `TODO — public or unlisted YouTube/Loom URL, under 3:00`

**GitHub repository:** `TODO — public repository URL`

**Live demo or deployment:** Local self-hosted lab — `bash lab/run.sh`; Flagsmith :8010, storefront :8020, dashboard :8022. The recorded demo uses current main-instance drafts; the lab seeds its own IDs. No public deployment.

## What did you build, and what problem does it solve?

```text
Experiment Isolation is an Agent Skill, a small Python engine, and a self-hosted lab that prevent overlapping Flagsmith experiments from contaminating each other.

Two or more experiments can target the same audience. Every shared user is then exposed to multiple changes, and no result is clean. Flagsmith 2.291.0 has no mutual-exclusion primitive: an experiment audience holds one segment, and experiments can name the same segment. An audience also cannot change while its rollout is enabled, and a running experiment cannot change its audience at all.

The tool audits actual enrollment from sampled identities, computes N-way Jaccard overlap across all pairs, and returns a collision verdict. Audit exits 10 on collision, by design, and still writes its JSON; above the threshold apply refuses to launch. Otherwise it proposes disjoint audiences using contiguous ranges of a stable 0-99 integer trait, requires an HMAC-bound approval token, and applies through disable-rollout → patch-audience → start (start re-enables). Apply ensures segments (creates missing, reuses existing), resamples to verify zero overlap for the planned drafts, and emits a compact receipt (121 actual tokens for the 2-way demo; 3-way stress test 125) with before/after numbers and a rollback reference. It handles up to four concurrent drafts by default with a minimum bucket width of five; the 3-way stress run used [0,32], [33,65] and [66,99].

The engine is Python 3.9 standard library only. The skill wraps it for coding agents. The lab reproduces the full loop on self-hosted Flagsmith with a seeded storefront and an overlap dashboard. All lab traffic is simulated and labeled.
```

## Which parts of Flagsmith did you use?

Check the boxes that apply:

```text
[x] Flags (experiments are attached to existing feature flags)
[x] Experimentation
[x] Segments
[ ] Remote config
[x] CLI
[x] API
[ ] MCP
[x] Self-hosted
[ ] Cloud
```

**Edge API:** not called directly. Enrollment is edge-compatible because the bucket is a plain integer trait, so SDK or Edge evaluation resolves the same segment without a central lookup. Do not tick an Edge API box unless the form treats "edge-compatible" as use; the honest answer is "not called directly."

**One-line version:** Experiments, segments, feature flags, CLI, API, and self-hosted Flagsmith. Evaluation is edge/SDK-compatible via persisted traits; MCP and Cloud were not used.

## Track 4 — Flagsmith Agent Skills

**What the skill does:**

```text
experiment-isolation takes an agent through the whole job of launching an experiment safely: audit the environment, measure audience overlap, refuse a collision, propose disjoint bucket segments, obtain human approval, apply the audience change, verify zero overlap, and emit a receipt.

It is not a single command. The skill decides when to stop for a person, refuses unsafe states, and leaves a rollback trail.
```

**Start-to-finish workflow:**

1. **Audit.** Discover non-completed experiments in one environment. Sample deterministic identities, persist `country`, `platform`, and `flagsmith_experiment_bucket`, and read `metadata.experiment.in_experiment` for each. No fabricated enrollment. Audit exits 10 on collision; the artifact is still written.
2. **Measure.** Compute N-way overlap and Jaccard across all pairs, with a collision verdict against a threshold (default 0.05).
3. **Refuse or plan.** If overlap is above threshold, stop. If the plan would touch a running experiment, stop: a paused experiment still cannot change audience, so complete/delete and recreate it. Otherwise plan contiguous bucket ranges (2 to 4 drafts, minimum width 5) and an approval token.
4. **Approve.** A human reads `plan.json` and passes its `approval_token` to `apply`.
5. **Apply.** Ensure segments (create missing, reuse existing); for each experiment disable the rollout, patch the audience, and start; start re-enables. Refuse on any failed precondition.
6. **Verify.** Resample with `--workers 2` and require zero N-way overlap for the planned drafts (`after_jaccard == 0.0`).
7. **Receipt.** Emit compact JSON with environment, sample size, before/after, changes, rollback reference, token counts, and pass.

**CLI commands (exact):**

```sh
python3 -m engine.cli audit   --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json
python3 -m engine.cli plan    --audit audit.json --max-concurrent 4 --min-bucket-width 5 --out plan.json
python3 -m engine.cli apply   --plan plan.json --approve "<approval-token>" --out apply.json
python3 -m engine.cli verify  --plan plan.json --samples 500 --workers 2 --out verify.json
python3 -m engine.cli receipt --audit audit.json --plan plan.json --verify verify.json --apply apply.json --out receipt.json
python3 -m engine.cli rollback --apply apply.json
```

The skill is a thin wrapper: `skills/experiment-isolation/SKILL.md` explains when to call each command, and its `scripts/` shells out to the same engine. No business logic is duplicated.

**Production safety:**

- Audit is read-only by default and exits 10 on collision, by design; the JSON artifact is still written.
- `apply` re-derives the HMAC approval token from plan content; an edited plan with a recomputed public token is rejected. Missing or wrong tokens exit 10 with no mutation.
- Overlap above threshold is a refusal, not a warning.
- Running experiments are refused; pausing does not unlock the audience, so complete/delete and recreate.
- Undo is engine-owned: `python3 -m engine.cli rollback --apply apply.json`. Created-only restores in place (`live_restore=true`); a started experiment is recreated as a draft with its old audience (`requires_recreate=true`); failures sanitize keys/URLs and write an artifact. Do not use `flagsmith api` rollback recipes.
- Admin calls use `flagsmith api <path>`, so the key never enters `argv`; secrets come from the environment and are never printed or committed.
- The documented order is enforced: disable rollout, patch audience, start (start re-enables).
- The demo runs against local self-hosted Flagsmith only.

**Agent/model tested:** OpenCode general subagent, **DeepSeek V4.1 Flash 1017** (provider `opencode-go`), 2026-11-27. The skill needs only a shell and the Flagsmith CLI.

**Token count for the demo run:** `TODO — harness total` (not exposed to the subagent). The measured 2-way demo receipt is 121 tokens `o200k_base` / 120 `cl100k_base`, 429 chars, internal 107. The 3-way stress test is 125/124, not the demo headline. Tests: 93 passed (55 engine + 38 skill). Method and include/exclude rules are in [token-count.md](token-count.md).

**Upstream status:** packaged for contribution to the official Flagsmith skills repository. It is not merged upstream, and the submission does not claim it is.

## Track 3 — Build on Open Source Flagsmith

**How you built on self-hosted Flagsmith:**

```text
The lab runs self-hosted Flagsmith (verified 2.291.0) with Postgres and experimentation enabled through Docker Compose: Flagsmith :8010, storefront :8020, dashboard :8022. It uses its own Compose project so it does not clash with an existing instance. No Cloud project is involved.

On top of it we built a seeded storefront with two features and two colliding experiments, a single-page overlap dashboard that reads the engine's audit JSON, and one command — `bash lab/run.sh` — that starts everything and recreates the collision. The release gate verified `reset → demo → reset`: 100% → 0% → 100% collision, HTTP 200 on storefront and dashboard, no 409. The same engine can audit any self-hosted environment; the lab is the reproducible proof.
```

**What you built:**

```text
A reusable experiment-isolation toolkit: a stdlib CLI that measures N-way overlap and applies N-way bucket-segment audiences, an Agent Skill that drives it, a storefront that generates enrollment, and an overlap dashboard. The dashboard turns audit.json into a before/after matrix a team can read in a launch review.
```

**How another developer reuses it:**

```sh
git clone <TODO-public-repo-url> experiment-isolation
cd experiment-isolation
bash lab/run.sh
```

Then open Flagsmith at :8010, the storefront at :8020, and the dashboard at :8022; the runner seeds the collision and prints every URL. Point the engine at the lab's environment key. `lab/README.md` has the port table, the demo command, and the cleanup note. To use it against an existing self-hosted instance instead, export `FLAGSMITH_API_URL`, the server-side key, and `DEV_ENV_KEY`; no code change is needed. All lab traffic is simulated; synthetic identities remain in the environment, so use a disposable environment.

## Feedback

```text
What I liked: experimentation is scriptable end to end. The API exposes experiments, rollouts, audiences and start as real resources; the CLI's api command keeps admin credentials out of argv; segments plus traits are a clean way to express an audience; and the self-hosted Docker Compose path got a working instance running locally without a Cloud account.

What I would improve: there is no mutual exclusion or experiment-layer concept. Two experiments can share an audience, and nothing warns you. An audience is limited to one segment, cannot be changed while the rollout is enabled, and cannot be changed at all on a running experiment; a percentage split is rejected inside an audience segment. Each of these is reasonable alone, but together they make safe re-targeting a manual disable-change-start dance. A native audience-conflict check, experiment layers, or a first-class "pause without losing enrollment" operation would remove most of the need for this tool. Clearer typed errors on the rollout endpoints would also help agents recover without guessing.
```

## Submission checklist

- [ ] Project title, tracks, video URL, repo URL filled.
- [ ] Video is public or unlisted and under 3:00.
- [ ] README has setup steps and a "How Flagsmith is used" section.
- [ ] Track 4 token count is a measured number, not a placeholder.
- [x] Track 4 agent/model field is filled.
- [ ] No key, token, or `.env` file is committed.
- [ ] Lab runs from a clean clone with one command.
- [ ] `pytest` passes and the recorded numbers in the README match the run.
