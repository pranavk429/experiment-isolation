# ToggleWars Submission — Experiment Isolation

Copy-paste sheet for the WeMakeDevs ToggleWars form. Replace only the demo-video placeholder.

## 1. Form fields → exact answers

**Project title**

```text
Experiment Isolation
```

**Which tracks are you entering?**

```text
Track 3 — Build on Open Source Flagsmith
Track 4 — Flagsmith Agent Skills
```

**GitHub repository**

```text
https://github.com/pranavk429/experiment-isolation
```

**Demo video**

```text
[PASTE YOUTUBE OR LOOM URL]
```

**Live demo or deployment**

```text
self-hosted lab; run bash lab/run.sh
```

**What did you build, and what problem does it solve?**

```text
Experiment Isolation prevents overlapping Flagsmith experiments from contaminating each other. Two experiments can target the same audience; every shared user is exposed to both changes, so neither result is clean. Flagsmith 2.291.0 has no mutual-exclusion primitive: an experiment audience holds one segment, and multiple experiments can name it.

The tool audits actual enrollment, computes N-way Jaccard overlap, and returns a collision verdict. Audit exits 10 on collision. With approval it plans contiguous bucket ranges, creates or reuses segments, disables each rollout, patches the audience, and starts; verify resamples to zero overlap, and a compact receipt records before/after plus rollback. It handles up to four concurrent drafts. A 3-way stress run moved max overlap from 1.0 to 0.0; the 2-way run did the same, and multi-exposure fell from 0.76 to 0.0. The engine is Python 3.9 stdlib only; the skill drives it; the lab reproduces the loop on self-hosted Flagsmith.
```

**Which parts of Flagsmith did you use?**

```text
Experimentation, Segments, Edge API, CLI, Management API, self-hosted Flagsmith
```

**Track 3 answer:** copy section 2 below.

**Track 4 answer:** copy section 3 below. Token count: **121**.

**Feedback:** copy section 4 below.

## 2. Track 3 answer

```text
I ran Flagsmith 2.291.0 self-hosted with Postgres and experimentation enabled through a one-command Docker Compose lab. The lab exposes Flagsmith on :8010, a seeded storefront on :8020, and an overlap dashboard on :8022; bash lab/run.sh starts all three, bootstraps the project, seeds two colliding draft experiments, measures the overlap, and prints every URL. Release gate: reset → demo → reset gave 100% → 0% → 100%, HTTP 200, no 409. The dashboard renders the audit JSON as a 100%-collision matrix before launch.

On top of it, the same Python engine and Agent Skill audit enrollment, plan contiguous bucket ranges, apply approved audiences, and verify the result. The seeded pair moved from Jaccard 1.0 to 0.0; a 3-way stress run also moved 1.0 to 0.0, with multi-exposure 0.76 to 0.0. The suite has 93 tests: 55 engine and 38 skill.

Another developer reuses it by cloning the public repo, running bash lab/run.sh, and opening :8022. lab/README.md documents ports, reset, and cleanup; the engine can also point at any self-hosted instance through FLAGSMITH_API_URL and DEV_ENV_KEY. All lab traffic is simulated and labeled.
```

## 3. Track 4 answer

```text
Experiment Isolation is an Agent Skill that runs the whole job: audit non-completed experiments, measure N-way overlap, plan disjoint bucket ranges, stop for approval, apply, verify zero overlap, and emit a receipt. The demo isolates two drafts; the planner supports four concurrent drafts with minimum width five; a 3-way stress run also hit 0.0.

CLI (all via python3 -m engine.cli):
audit --env "$DEV_ENV_KEY" --samples 500 --out audit.json
plan --audit audit.json --out plan.json
apply --plan plan.json --approve "<token>" --out apply.json
verify --plan plan.json --samples 500 --workers 2 --out verify.json
receipt --audit audit.json --plan plan.json --verify verify.json --apply apply.json --out receipt.json
rollback --apply apply.json

Safety: audit exits 10 on collision; apply re-derives the HMAC token and rejects edited plans; only drafts change; apply disables the rollout, patches the audience, starts. Rollback restores created-only in place and recreates started experiments as drafts with old audience; failures sanitize keys/URLs and write an artifact.

Tested with an OpenCode general subagent using SKILL.md, no human intervention beyond the plan token. The 2-way receipt is 121 tokens o200k (120 cl100k), receipt only; harness/context excluded. Tests: 93.
```

## 4. Feedback

```text
Strengths: experimentation is scriptable end to end. Experiments, audiences, segments, and start are real API resources; the CLI keeps admin credentials out of argv; Edge/SDK evaluation plus persisted traits makes bucket splits portable; self-hosted Compose runs a full instance locally without Cloud.

Limitations: Flagsmith has no native mutual exclusion or experiment layers, so experiments can silently share an audience. An audience is limited to one segment, cannot change while the rollout is enabled, and cannot change on a running experiment; pausing does not unlock it, so a started experiment must be completed and recreated. A native audience-conflict check, experiment layers, or pause-and-retarget would remove most of the need for this tool. Clearer typed rollout errors would help agents recover.
```

## 5. Pre-submit checklist

- [ ] Repository is public: open https://github.com/pranavk429/experiment-isolation in a logged-out browser; README shows setup and Flagsmith usage.
- [ ] Demo video is public or unlisted and under 3:00; the placeholder above is replaced.
- [ ] Track 3 and Track 4 are both selected.
- [ ] Token count entered as **121** (2-way receipt, o200k_base; receipt only).
- [ ] All links tested logged out: repository, video, and any lab instructions.
- [ ] Lab is described as local, not publicly deployed: `bash lab/run.sh` on :8010/:8020/:8022.
- [ ] No keys or `.env` files are committed; Flagsmith calls use environment credentials.
- [ ] The Track 3 and Track 4 answers still match the repository state.
