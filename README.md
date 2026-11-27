# Experiment Isolation

**Outcome:** a Flagsmith Agent Skill that proves which experiments share users, refuses to launch the unsafe ones, and makes their audiences disjoint with one approved change — then verifies the result and emits a receipt.

**Links:** Repository: https://github.com/pranavk429/experiment-isolation · Demo video: `TODO — add public YouTube/Loom URL` · [Lab](lab/) · [Track 3 answers](docs/submission.md#track-3--build-on-open-source-flagsmith) · [Track 4 answers](docs/submission.md#track-4--flagsmith-agent-skills) · [Demo script](docs/demo-script.md) · [Judging map](docs/judging-map.md)

> **What it is:** an audit-and-apply loop for Flagsmith experiments, packaged as an Agent Skill and a stdlib CLI.
>
> **Does it work:** the run proves it: `pytest` passes, `apply` ensures segments and patches audiences, `verify` reports `after_jaccard: 0.0`, and `receipt.pass` is `true`. Recorded values are in [Results](#results-and-evidence); only the harness total is `TODO`.
>
> **Verify it:** run the five commands in [Setup and run](#setup-and-run), or watch the 2:45 demo.

**Hero proof (to record):** `docs/assets/hero-before-after.gif` — 6 s, 1280×720. Left: red overlap matrix before, cell at the measured Jaccard, label `collision`. Right: green matrix after `apply` + `verify`, measured Jaccard, receipt footer `"pass": true`. Caption: "Seeded demo data; values from Results." Record after it passes.

<!-- TODO: add docs/assets/hero-before-after.gif and replace this comment with the image embed. -->

## Problem

Run two or more experiments on the same users and every result is contaminated. A user in both the pricing-banner and onboarding-tip tests sees both changes; lift attributed to one may come from the other. It compounds with each test.

Flagsmith 2.291.0 has no native mutual exclusion. An experiment audience holds one segment (`MAX_AUDIENCE_SEGMENTS = 1`), and two experiments can name the same one. Audience segments cannot use `PERCENTAGE_SPLIT`, audiences cannot change while the rollout is enabled, and running experiments cannot change audiences. Teams find the overlap after the numbers look strange.

## What it does

1. **Audit** — read-only. Lists non-completed experiments, samples identities, persists traits via the Flagsmith CLI, and reads enrollment from `metadata.experiment.in_experiment`. Exits `10` on collision (the expected gate signal) and still writes JSON; `0` is clear/none.
2. **N-way overlap matrix** — every experiment pair's `shared`, `union`, `jaccard`, enrollment rates, multi-exposure rate, and a `collision` verdict against a threshold (default `0.05`).
3. **Refuse** — `apply` exits `10` when overlap exceeds the threshold, the approval token is missing or wrong, or an experiment is not a draft. No mutation on refusal.
4. **N-way bucket-segment isolation** — contiguous ranges over `flagsmith_experiment_bucket` (0–99), up to `--max-concurrent 4` drafts by default and at least `--min-bucket-width 5` buckets each. Two-way uses `[0,49]`/`[50,99]`; the 3-way stress run used `[0,32]`/`[33,65]`/`[66,99]`.
5. **Approve** — the plan carries an HMAC-bound token; `apply` re-derives it and rejects an edited plan with a recomputed public token. Undo with `python3 -m engine.cli rollback --apply apply.json`.
6. **Apply** — ensures segments (create/reuse), disables the rollout, patches the audience, and starts; start re-enables.
7. **Verify** — resamples, recomputes N-way overlap for planned drafts, and requires `after_jaccard == 0.0`.
8. **Receipt** — compact JSON (121 tokens for the 2-way demo; 3-way stress 125; `o200k_base`): sample size, before/after, changes, rollback reference, token counts, `pass`.

## How Flagsmith is used

| Mechanism | What the project does with it |
|---|---|
| **Experiments** | Discovers experiments, seeds them, patches the rollout, and starts via `POST /api/v1/environments/{env_key}/experiments/{id}/start/`. |
| **Audiences** | Reads and replaces each experiment's `{match, segment_ids}` audience. Respects one segment per audience and disables the rollout before every audience change. |
| **Segments** | Creates trait-rule segments for the bucket ranges. No percentage-split condition is ever placed in an audience segment. |
| **Identities and traits** | Persists `country`, `platform`, and `flagsmith_experiment_bucket`; reads enrollment from `GET /api/v1/identities/?identifier=...`; nothing fabricated. |
| **Edge/SDK enrollment** | The bucket is a plain trait, so SDK/Edge evaluation resolves the same segment without a server lookup. The demo reads identity metadata after `evaluate --persist`; it does not call a hosted Edge API. |
| **CLI** | `flagsmith evaluate ... --persist --json` for enrollment; `flagsmith api <path>` for admin calls so the key never enters `argv`. |
| **API** | Raw REST for experiment create/rollout/start and segment create, because those payloads are not fully covered by CLI verbs. |
| **Self-hosted** | The lab runs self-hosted Flagsmith (verified 2.291.0) with Postgres and experimentation on `:8010`, storefront `:8020`, dashboard `:8022`. |

Flagsmith is load-bearing: delete it and there is no enrollment, audience, or state to verify.

## Architecture and data flow

```text
Agent (Claude Code / Codex)
  reads skills/experiment-isolation/SKILL.md, calls its scripts/ wrappers
        |
        v
engine/ (Python 3.9 stdlib: urllib, json, subprocess, hashlib, argparse)
        |  flagsmith evaluate --persist     |  flagsmith api <path>
        v                                  v
Self-hosted Flagsmith API  <---- experiments, segments, identities, rollout
        |
        +--> audit.json --> plan.json --(approval token)--> apply.json
                                   |                            |
                                   +--> verify.json --> receipt.json
                                                          |
             lab/dashboard (overlap matrix) <--------------+
```

Summary to stderr, JSON to stdout or `--out`. Exit codes: `0` clear/success, `10` collision/infeasible/refusal/approval, `20` error. Audit writes JSON on `10`; `apply` and `rollback` mutate.

## 3-minute demo path

Beat sheet: [docs/demo-script.md](docs/demo-script.md); ~15 seconds on the problem, most on the product.

1. **0:00–0:15 — Problem.** Current main-instance drafts, one audience; lab IDs differ.
2. **0:15–0:30.** Skill + engine + lab; audit, refuse, isolate, verify, receipt.
3. **0:30–1:05 — Audit and matrix.** Run `audit`; show `exit=10` (collision is the gate signal), then the red N-way matrix.
4. **1:05–1:25 — Plan and refusal.** Show the bucket segments and approval token; run `apply` with a wrong token, show `exit=10`, no changes.
5. **1:25–1:50 — Approve and apply.** Run `apply` with the HMAC token; show segments created/reused, then disable → patch → start.
6. **1:50–2:10 — Verify.** Resample; show `after_jaccard: 0`, `pass: true`, zero overlaps.
7. **2:10–2:25 — Receipt.** Show before/after, changes, `rollback --apply`, and the 121-token receipt.
8. **2:25–2:45 — Flagsmith side and close.** Both experiments live with disjoint audiences; bucket trait visible on an identity; repo links.

## Setup and run

### Prerequisites

- Python 3.9+ (engine has no third-party dependencies).
- Docker with Compose v2 for the lab.
- The Flagsmith CLI on `PATH` (see the [Flagsmith CLI docs](https://docs.flagsmith.com/integrating-with-flagsmith/CLI)).
- `jq` for the demo output.

### Engine

```sh
git clone https://github.com/pranavk429/experiment-isolation
cd experiment-isolation
python3 -m engine.cli --help
```

Against any self-hosted Flagsmith instance, export the URL, a server-side key, and the environment key. The key never enters the repo or `argv`:

```sh
export FLAGSMITH_API_URL="http://localhost:8010"
export FLAGSMITH_API_KEY="<server-side key>"
export DEV_ENV_KEY="<environment key>"
```

Reset the demo drafts, then run:

```sh
python3 seed/demo_seed.py --experiments 2   # reset demo state

python3 -m engine.cli audit   --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json
python3 -m engine.cli plan    --audit audit.json --max-concurrent 4 --min-bucket-width 5 --out plan.json
python3 -m engine.cli apply   --plan plan.json --approve "<token from plan.json>" --out apply.json
python3 -m engine.cli verify  --plan plan.json --samples 500 --workers 2 --out verify.json
python3 -m engine.cli receipt --audit audit.json --plan plan.json --verify verify.json --apply apply.json --out receipt.json
python3 -m engine.cli rollback --apply apply.json   # undo, if needed
```

Lab is portable; build used `~/flagsmith-local`.

### Skill install

Agent Skills layout (`SKILL.md`, `references/`, `scripts/`):

```sh
# Claude Code
mkdir -p ~/.claude/skills
cp -R skills/experiment-isolation ~/.claude/skills/

# Codex
mkdir -p ~/.codex/skills
cp -R skills/experiment-isolation ~/.codex/skills/
```

Then ask: "Run another experiment on US mobile — check it does not overlap the pricing test first." The skill is packaged for contribution to the official Flagsmith skills repo; it is not merged upstream.

### Lab (one command)

```sh
bash lab/run.sh
```

Starts Flagsmith `:8010`, storefront `:8020`, dashboard `:8022`. Gate: `reset → demo → reset` = 100% → 0% → 100%, HTTP 200, no 409.

## Results and evidence

Values from `FINAL.md` (2-way) and `REPORT2.md` (3-way stress); harness total is TODO.

| Evidence | Value | Source |
|---|---|---|
| Sample size requested / measured | `500` / `500` | `audit.json.sample_size` |
| Before: max N-way Jaccard (all pairs) | `1.0` | `audit.json.overlaps[].jaccard` |
| After: max N-way Jaccard (all pairs) | `0.0` | `verify.json.after_jaccard` |
| After: `verify.pass` | `true` | `verify.json.pass` |
| Receipt JSON size | `121` (2-way demo); `125` (3-way stress only) | [docs/token-count.md](docs/token-count.md) |
| Demo-run total tokens | `TODO` | [docs/token-count.md](docs/token-count.md) |
| Segments created / reused, 2-way verified | `0 / 2` | verification/FINAL.md |
| Segments created / reused, 3-way stress | `3 / 0` | verification/REPORT2.md |
| Tests passing | `93` passed (55+38) | `pytest` output |

**Verified results:** before Jaccard 1.0, `after_jaccard == 0.0`, `verify.pass == true`. Receipt is 121 tokens for the 2-way demo (120 `cl100k_base`; 429 chars; internal 107); 125/124 is 3-way stress only.

## Safety and limitations

**Safety**

- Audit/plan are read-only; `apply`/`rollback` mutate; `apply` needs the token.
- Audit exits `10` on collision; apply exits `10` on missing/wrong token, overlap, or a non-draft experiment.
- Undo with `python3 -m engine.cli rollback --apply apply.json`: created-only restores in place; a started experiment is recreated as a draft with its old audience. Failures sanitize keys/URLs and write an artifact. Do not use `flagsmith api` recipes.
- Self-hosted only; no Cloud keys. Secrets never enter `argv`, logs, or the repo; admin calls use `flagsmith api`.
- Audience changes follow: disable rollout → patch audience → start (start re-enables).

**Limitations**

- Overlap is sampled, not exhaustive; the verdict depends on sample size and traits. 500 is a default, not a guarantee.
- The bucket is a deterministic hash split, approximately uniform but not stratified by country or platform. A 50/50 allocation is not exact in small samples.
- A running experiment cannot change its audience, and pausing does not unlock it. The tool refuses; complete/delete and recreate the experiment.
- An audience holds one segment, so isolation uses the bucket trait; compose other targeting inside the segment.
- It measures isolation, not results; it does not replace Flagsmith's Bayesian analysis or pick a winner.
- Lab traffic is simulated; synthetic identities persist. Use a disposable environment; see `lab/README.md`.
- Packaged for upstream contribution, not merged.

## Tests

```sh
python3 -m pytest tests/engine tests/skill -q
```

Expected: `93` passed (55+38). Engine tests cover sampling, Jaccard, refusal, apply, verify, receipt, rollback; skill tests cover frontmatter, triggers, CLI.

## Repository map

| Path | Contents |
|---|---|
| `engine/` | Python 3.9 stdlib CLI: `audit`, `plan`, `apply`, `verify`, `receipt`, `rollback`. |
| `skills/experiment-isolation/` | `SKILL.md`, `references/`, `scripts/` wrappers for coding agents. |
| `lab/` | `bash lab/run.sh`: Flagsmith `:8010`, storefront `:8020`, dashboard `:8022`. |
| `seed/` | `demo_seed.py`: two colliding experiments for the demo. |
| `tests/` | Engine and skill contract tests. |
| `docs/` | Demo script, form answers, judging map, token-count method. |
| `demo/` | Runnable demo assets. |
| `verification/` | Recorded evidence and bug reports. |
| `CONTRACT.md` | Build contract, schemas, and acceptance tests. |

## License and acknowledgments

MIT License — see [LICENSE](LICENSE).

Built for ToggleWars 2026. Thanks to Flagsmith for the platform, API, CLI, and self-hosting docs; WeMakeDevs for the event; and the Agent Skills specification. Demo data is synthetic; lab traffic is simulated.
