# Judging map — ToggleWars scorecard to artifacts and demo timestamps

Use this to check that every claim has an artifact and a moment on screen. Timestamps refer to [demo-script.md](demo-script.md). `TODO` means the evidence is not recorded yet; do not claim it in the video.

## General scorecard

| Scorecard line | What the judge is asking | Concrete artifact | Demo timestamp | How to verify |
|---|---|---|---|---|
| **Use of Flagsmith** | Is Flagsmith core, or decorative? Delete it and does the project still behave the same? | `engine/` calls experiments, segments, identities, rollout and start; `lab/docker-compose.yml` runs self-hosted Flagsmith; `skills/experiment-isolation/scripts/` wraps the engine. | 0:30 audit reads enrollment; 1:25 apply cycles the rollout; 2:25 UI shows disjoint audiences. | Delete Flagsmith and there is no enrollment to measure, no audience to change, no state to verify. Run `audit` against the lab. |
| **Impact** | Would a developer or team actually use it? | README problem section; refusal path; receipt with rollback reference. | 0:00–0:15 problem; 1:05–1:25 refusal; 2:10–2:25 receipt. | The receipt is designed to paste into a launch review or PR. The tool fits an existing Flagsmith workflow without a new dashboard account. |
| **Creativity** | New idea, or a familiar idea somewhere new? | N-way bucket-segment isolation (`plan.json`), measured before/after, approval token; 3-way stress verified. | 0:50 matrix; 1:05 plan; 1:50 verify. | Mutual exclusion for experiments is not a Flagsmith primitive. The implementation uses ordinary segments and traits, so it is portable. |
| **Demo video** | Does it show the problem, the product, and Flagsmith clearly? | `docs/demo-script.md`; `docs/assets/hero-before-after.gif` (TODO). | Whole video, problem at 0:00, Flagsmith side at 2:25. | 15 s problem, working product 0:30–2:25, Flagsmith UI 2:25–2:40. Demo is 25% of the scorecard. |

## Track 3 — Build on Open Source Flagsmith

| Criterion | Artifact | Demo timestamp | How to verify |
|---|---|---|---|
| **Self-hosted Flagsmith** | `bash lab/run.sh`: self-hosted Flagsmith :8010, storefront :8020, dashboard :8022, Postgres, experimentation enabled. | 0:50 dashboard; 2:25 Flagsmith UI. | `bash lab/run.sh`; no Cloud account. |
| **Integrations and plugins** | Seeded storefront, overlap dashboard, engine running against the same API. | 0:30–1:05. | Lab README one-command path; dashboard reads `audit.json`. |
| **Developer tools** | `engine/cli.py` core verbs; `skills/experiment-isolation/` wrappers; compact JSON output. | 0:30–2:25. | `python3 -m engine.cli --help`; `pytest`. |
| **Easy for others to reuse** | README setup, `lab/README.md`, environment-key instructions, cleanup note. | Close, 2:40. | Clean clone + `bash lab/run.sh`; no maintainer path required. |
| **Honest scope** | "Simulated traffic" label in README, lab, and video. | 0:15 or 2:25. | Synthetic identities are stated, not implied as real users. |

## Track 4 — Flagsmith Agent Skills

| Criterion | Artifact | Demo timestamp | How to verify |
|---|---|---|---|
| **Completes the whole job** | `skills/experiment-isolation/SKILL.md` workflow; five CLI commands from audit to receipt; 2-way demo and 3-way stress loops verified. | 0:30–2:25. | Run the five commands in order; audit exits 10 on collision, `apply` changes state, `verify` confirms zero overlap across the planned drafts. |
| **Token efficiency** | Compact JSON only; 2-way demo receipt 121 tokens `o200k_base` / 120 `cl100k_base`, 429 chars, internal 107; 3-way stress 125/124 is not the headline; `docs/token-count.md`. | 2:10–2:25. | Measure with the helper; demo verified 121. |
| **Creative use of the CLI** | `flagsmith evaluate --persist` for enrollment; `flagsmith api` for experiment/segment admin calls; identity metadata read-back. | 0:30 audit; 1:25 apply. | The key never enters `argv`; no raw experiment payload is dumped into context. |
| **Safety around production changes** | Read-only audit; audit collision exit 10; HMAC re-derived by apply; running-experiment refusal; engine rollback. Created-only restores in place (`live_restore=true`); started experiments are recreated as drafts (`requires_recreate=true`); failures sanitize keys/URLs and write an artifact. | 1:05–1:25 refusal; 1:25 apply; 2:10 receipt. | Wrong token or edited plan + public token exits 10; undo with `python3 -m engine.cli rollback --apply apply.json`. |
| **Agent/model tested** | OpenCode general subagent, DeepSeek V4.1 Flash 1017 (`opencode-go`), 2026-11-27, in `docs/submission.md`. | N/A | Recorded for the verified run. |
| **Token count for demo run** | `TODO`: full harness total in `docs/submission.md` and `token-count.md`; 2-way receipt 121 already measured. | 2:10 receipt beat. | Required by the form; only the harness total is outstanding. |
| **Upstream fit** | Agent Skills layout; `SKILL.md` frontmatter; progressive disclosure; no upstream merge claim. | Close. | `tests/skill` covers frontmatter and triggers; say "packaged for contribution." |

## Submission mechanics

| Requirement | Where it is covered | Status |
|---|---|---|
| Public GitHub repo | `TODO` URL | TODO |
| README with setup and how Flagsmith was used | This repo's `README.md`, "Setup and run" and "How Flagsmith is used" | Done |
| Short demo video, public or unlisted, under 3:00 | `docs/demo-script.md`, 2:45 target | TODO record |
| Track 4 harness total | `docs/token-count.md`, `docs/submission.md` | TODO measure |
| Track 4 agent/model tested | `docs/submission.md` | Done |
| No secrets committed | `.gitignore`, env-only keys, `flagsmith api` | Verify before push |
| Lab runs from a clean clone | `bash lab/run.sh`, `lab/README.md` | Verified: `reset → demo → reset` = 100% → 0% → 100%, HTTP 200, no 409 |

## Evidence gaps (do not paper over)

| Claim | Current state | What closes it |
|---|---|---|
| Sample size actually measured | 500 | `audit.json.sample_size` from the 2-way run. |
| Before Jaccard | 1.0 | `audit.json.overlaps[].jaccard`. |
| After Jaccard | 0.0 | `verify.json.after_jaccard`. |
| Receipt size | 121 (2-way demo); 125 (3-way stress) | `token_count.py`; o200k 121/120 cl100k. |
| Demo-run token total | TODO | Export harness usage and sum input + output. |
| Tests passing | 93 (55 engine + 38 skill) | `pytest tests/engine tests/skill -q`. |
| Demo video | TODO | Record the 2:45 cut and upload. |

If a judge asks for a number and the table says `TODO`, say it is not recorded yet. Do not estimate it on camera.
