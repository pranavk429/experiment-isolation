# Demo script — Experiment Isolation (2:45)

Hard cap: 3:00. Target: 2:45. Format: 1080p, 16:9, terminal font 18 pt or larger, browser at 110%. Record one clean take.

Why this cut: the demo is 25% of the scorecard and often the only part a judge watches. The problem gets 15 seconds, the working product gets most of the runtime, and the Flagsmith side is visible at 0:30–2:40. All identities are synthetic; say so once.

## Before recording

Start the dashboard host and prepare the terminal so the audit starts from the seeded collision:

```sh
# dashboard host: Flagsmith :8010, storefront :8020, dashboard :8022
bash lab/run.sh

# engine run: local research instance on :8000 (current drafts)
source ~/flagsmith-local/flagsmith.env
export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"
python3 seed/demo_seed.py --experiments 2   # reset state (reset may renumber)
rm -f audit.json plan.json apply.json verify.json receipt.json refused.json
clear
```

Expected state: main-instance current drafts (**58/59** at release; a full reset renumbers), both `status=created`, audience `us_mobile`. The lab seeds its own IDs.

Open three tabs before you start:

1. Flagsmith UI at **:8000**, Experiments list, current drafts visible.
2. The overlap dashboard at **:8022**, reading `audit.json`.
3. This repository's README, for the close.

The engine commands below use the local research instance (`DEV_ENV_KEY`). The lab at :8010 is the separate Track 3 artifact; do not mix the two instances in one run.

Check that no key or token is visible in the terminal prompt, scrollback, or browser. Do not run `env`, `set -x`, or `cat` on the env file.

## 0:00–0:15 — Problem (15 s)

**Screen:** Flagsmith Experiments list at :8000. Current drafts are visible. Hover each audience chip; both name `us_mobile`.

**Say:** "Two experiments, one audience. Every user in both sees two changes, so each result depends on the other. Flagsmith has no mutual exclusion — nothing stops this launch. Teams find it after the data looks wrong."

**Proof on screen:** current drafts, same audience segment name. No title card, no logo.

## 0:15–0:30 — What it is (15 s)

**Screen:** terminal at the repo root, then the README architecture block for two seconds.

**Say:** "Experiment Isolation is a Flagsmith Agent Skill. It audits real enrollment, computes N-way overlap, refuses unsafe launches, and makes audiences disjoint with one human approval. The planner handles up to four concurrent drafts; this run isolates two."

**Proof on screen:** `skills/experiment-isolation/SKILL.md` and the CLI verbs in `engine/`.

## 0:30–1:05 — Audit and overlap matrix (35 s)

**Commands:**

```sh
python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json; echo "audit exit=$?"
jq '{verdict, collisions, overlaps: [.overlaps[] | {a, b, jaccard}]}' audit.json
cp audit.json lab/dashboard/audit.json
```

**Say:** "Audit is read-only. It samples 500 synthetic identities, persists their traits, and reads actual enrollment. Exit 10 is the collision gate, not a crash: both experiments claim the same users."

**Proof on screen:** `audit exit=10`, `verdict: "collision"`, and the measured Jaccard (acceptance target ≥ 0.9). Read the number aloud; do not pre-bake it.

**Cut to dashboard at :8022 and refresh** (the tab reads the file just copied): "The same audit as an N-way matrix. Red means shared users; this is the artifact a team would put in a launch review."

**Proof on screen:** both drafts red, off-diagonal cell at the measured Jaccard, a `collision` badge.

## 1:05–1:25 — Plan and refusal (20 s)

**Commands:**

```sh
python3 -m engine.cli plan --audit audit.json --max-concurrent 4 --min-bucket-width 5 --out plan.json
jq '{approval_token, segments_to_create, audience_changes}' plan.json
python3 -m engine.cli apply --plan plan.json --approve "wrong-token" --out refused.json; echo "exit=$?"
```

**Say:** "Plan proposes two trait ranges for two drafts — below 50 and 50-plus — plus an HMAC-bound token; apply re-derives it. The same planner handles N drafts up to four. Nothing has changed yet. A wrong token exits 10 and mutates nothing. Running experiments are refused; pausing does not unlock the audience, so complete/delete and recreate."

**Proof on screen:** two segment rules, an `iso-...` token, `exit=10`, and a stderr refusal line. Do not edit the failure. This is the safety beat.

## 1:25–1:50 — Approve and apply (25 s)

**Commands:**

```sh
TOKEN=$(jq -r .approval_token plan.json)
python3 -m engine.cli apply --plan plan.json --approve "$TOKEN" --out apply.json
cat apply.json
```

**Say:** "With the plan's token, apply ensures the segments — creating missing ones, reusing existing ones — disables the rollout, patches each audience, and starts; start re-enables. Rollback is engine-owned: `engine.cli rollback --apply apply.json`."

**Proof on screen:** stderr shows the running count and `segments created=… reused=…`; `apply.json` records the audience changes. The verified 2-way run reused both segments; the 3-way stress run created three. Keep this under 25 seconds.

## 1:50–2:10 — Verify (20 s)

**Commands:**

```sh
python3 -m engine.cli verify --plan plan.json --samples 500 --workers 2 --out verify.json
jq '{before_jaccard, after_jaccard, pass, overlaps: (.overlaps | length)}' verify.json
```

**Say:** "Verify resamples from scratch. Before was the measured collision; after is zero overlap for the planned pair, pass true. This is the number the plan promised, measured again rather than assumed."

**Proof on screen:** `after_jaccard: 0`, `pass: true`, `overlaps: 0`. If the number is not zero, stop and fix the build; do not talk over it.

## 2:10–2:25 — Receipt (15 s)

**Commands:**

```sh
python3 -m engine.cli receipt --audit audit.json --plan plan.json --verify verify.json --apply apply.json --out receipt.json
cat receipt.json
```

**Say:** "The receipt is the handoff: before and after, changes, rollback reference, token counts, pass. It is 121 actual tokens for this 2-way demo (120 cl100k; 429 chars; internal 107); the 3-way stress test is 125/124. Undo with `rollback --apply`; created-only restores in place, started experiments are recreated as drafts."

**Proof on screen:** before/after verdicts, `changes`, rollback reference, `token_count`, `pass: true`. Do not execute rollback before the final UI shot.

## 2:25–2:40 — Flagsmith side (15 s)

**Screen:** Flagsmith UI at :8000, Experiments. Open each experiment and show the audience.

**Say:** "In Flagsmith, both experiments are live with disjoint audiences: bucket below 50 and 50-plus. The bucket is a persisted trait, so SDK and edge evaluation resolve the same split without a server call."

**Proof on screen:** the two bucket audiences (below 50 / 50-plus), both running. Then open one identity and show `flagsmith_experiment_bucket` in its traits. This is the clearest "Flagsmith is doing the work" shot; do not skip it.

## 2:40–2:45 — Close (5 s)

**Screen:** README links bar.

**Say:** "Repo, skill, and one-command lab are in the description. The skill is packaged for upstream contribution."

**Proof on screen:** repository URL and the Track 3 / Track 4 links.

## Recording notes

- Do not show keys, tokens from the environment file, or the inside of `~/flagsmith-local/flagsmith.env`.
- Do not claim real users. All demo traffic is simulated; the identities are synthetic.
- Do not claim the skill is merged upstream. Say "packaged for upstream contribution."
- Rollback is verified: created-only restores in place; started experiments are recreated as drafts. Failures sanitize keys/URLs and write an artifact.
- Verify uses `--workers 2`; 4 workers timed out once.
- If a command is slow, cut the wait, not the proof. Show the command and the final line.
- If the dashboard needs a refresh to read the copied `audit.json`, refresh it on camera and say so; do not show a stale matrix.
- Keep the cursor still while JSON is on screen. Judges need to read the verdict, not follow the pointer.
- Record at 0:30–2:40 in one pass if possible. The refusal is the only failure in the video.
