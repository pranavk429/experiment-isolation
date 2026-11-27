# Shot list — Experiment Isolation (target 2:45, hard cap 3:00)

Status: **pipeline only.** No demo footage has been recorded. This list maps every shot to [`docs/demo-script.md`](../docs/demo-script.md). A shot is only recordable when its **Ready** line says READY; everything marked BLOCKED must not be staged or mocked.

Format: 1920x1080, 16:9, 30 fps. Terminal font >= 18 pt; browser at 110%. All identities are synthetic; say it once, on camera.

## Readiness key

| Mark | Meaning |
|---|---|
| **READY** | Asset or command exists and can be captured now. |
| **BLOCKED** | Depends on the local Flagsmith instance, a measured run, the lab, the browser relay, or the final repo URL. Do not substitute sample data. |
| **GATE** | Requires a passing upstream artifact (audit, plan, apply, verify, receipt) from the same run. |

## Capture map

| # | In–out | Screen | Primary capture | Proof on screen | Ready |
|---|---|---|---|---|---|
| S01 | 0:00–0:07 | Flagsmith Experiments list | `browse.recording` tab `ei-flagsmith` | Two seeded experiments, both visible | BROWSER READY: reset to the draft collision and confirm state immediately before |
| S02 | 0:07–0:15 | Same list, audience chips | `browse.recording` (same take) | Both chips name the same segment | BROWSER READY: same as S01 |
| S03 | 0:15–0:22 | Terminal, repo root | `record_terminal.sh` | `skill/SKILL.md` + five CLI verbs | READY (help output is real) |
| S04 | 0:22–0:30 | README architecture block | Terminal / editor | Flagsmith in the data path, not a logo | READY |
| S05 | 0:30–0:43 | Terminal | `record_terminal.sh` | Audit completes; `audit.json` written | BLOCKED: lab is post-apply; reset to the seeded draft collision |
| S06 | 0:43–0:55 | Terminal | Same recording, no cut | `verdict: "collision"`, measured Jaccard >= 0.9 | GATE: S05 |
| S07 | 0:55–1:05 | Lab overlap dashboard | `browse.recording` tab `ei-dashboard` | Both experiments red; off-diagonal cell = measured Jaccard; `collision` badge | LIVE BUT UNFROZEN: measured audit exists; reset to pre-apply and freeze same-run artifacts; must NOT show SAMPLE chip |
| S08 | 1:05–1:15 | Terminal | `record_terminal.sh` | Two bucket rules, `iso-...` token, audience changes | GATE: S05/S06 |
| S09 | 1:15–1:25 | Terminal | Same recording, unedited | Wrong token → `exit=10` + stderr refusal | GATE: S08 |
| S10 | 1:25–1:38 | Terminal | Same recording | Create segments, disable → swap → re-enable, start | GATE: S08 + explicit human approval |
| S11 | 1:38–1:50 | Terminal | Same recording | `apply.json` records the same mutations + rollback | GATE: S10 |
| S12 | 1:50–2:00 | Terminal | Same recording | Verify completes; `pass: true` | GATE: S10/S11 |
| S13 | 2:00–2:10 | Terminal | Same recording | `after_jaccard: 0`, `overlaps: 0` | GATE: S12 |
| S14 | 2:10–2:25 | Terminal | Same recording | Before/after, changes, rollback, measured token count, pass | GATE: S12/S13 |
| S15 | 2:25–2:33 | Flagsmith Experiments | `browse.recording` tab `ei-flagsmith` | `exp_iso_0_49` and `exp_iso_50_99`, both running | GATE: S10 + UI refresh |
| S16 | 2:33–2:40 | Flagsmith identity | `browse.recording` (same tab or new tab) | `flagsmith_experiment_bucket` in persisted traits | GATE: S10 |
| S17 | 2:40–2:45 | End card | `video/endcard.html` → `stills/endcard.png` | Product name, tracks, repo URL | BLOCKED: replace `OWNER`; only after S12 passes |

**One-pass rule:** record S05–S14 in a single terminal take. The only intended failure is S09. Browser shots are B-roll captured separately and cut in; that is editing, not re-enactment.

---

## S01 — Problem, wide (0:00–0:07)

- **Before capture:** the lab is currently post-apply (isolated audiences). Reset to the seeded draft collision first; if the chips do not name the same segment, stop. Then `browse.emulate` the tab to 1920×1080; `browse.recording` returns a 1920×1080 VP8 file (1904 with a scrollbar), otherwise it is the window size.
- **Visual:** Flagsmith **Experiments** list at 110% zoom. Both seeded experiments visible without scrolling. Cursor still.
- **Action:** none. Hold the list.
- **Proof:** two experiment names, both marked running/draft as seeded, same environment.
- **Fallback:** If the list is empty, run `python3 seed/demo_seed.py` and reload. If the page will not load, stop; do not use a mock. Re-record this shot after the instance is healthy.
- **Edit:** no title card, no logo, no fade-in. Start on the product.

## S02 — Same audience (0:07–0:15)

- **Visual:** Hover each audience chip in turn; the tooltip/segment name is identical.
- **Action:** hover experiment A audience, pause 1.5 s; hover experiment B audience, pause 2 s.
- **Proof:** both chips resolve to the same segment (the seeded shared audience). Do not say the name if it contains a key or token.
- **Fallback:** If hover is unreliable, click into each experiment's Audience tab so the segment name is pinned on screen. If the audience is not shared, the seed is wrong: stop and fix the seed, then re-record S01–S02.

## S03 — What it is (0:15–0:22)

- **Visual:** Terminal at repo root. Show the skill file and the CLI surface.
- **Commands:**
  ```sh
  ls -l skill/SKILL.md
  python3 -m engine.cli --help
  ```
- **Proof:** `skill/SKILL.md` exists; help lists `audit plan apply verify receipt`.
- **Fallback:** If the engine import fails, show `sed -n '1,40p' skill/SKILL.md` and the five verbs from `docs/demo-script.md`; do not claim a working CLI.
- **Edit:** 7 seconds maximum. Cut the shell prompt setup.

## S04 — Architecture (0:22–0:30)

- **Visual:** README architecture block, large enough to read.
- **Command:**
  ```sh
  sed -n '/^## Architecture/,/^## /p' README.md | head -28
  ```
- **Proof:** the diagram shows agent → skill/CLI → Flagsmith API → experiments/segments/identities.
- **Fallback:** Open the same block in an editor with 20 pt font. Do not scroll past it; hold for 2 seconds after the last line.

## S05 — Audit (0:30–0:43)

- **Before capture:** at report time the lab has a completed run (`receipt.json`, 10:47) and the dashboard reads "Audiences isolated". Reset to the seeded **draft collision** first; do not run this audit against an already-isolated state. The audit must produce a collision on camera for the story to be true.
- **Visual:** Terminal. Run the read-only audit.
- **Command:**
  ```sh
  python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json
  ```
- **Proof:** command completes, stderr summary names the environment/sample size, `audit.json` is written. No mutation.
- **Edit:** If the audit runs longer than the 35 s beat, keep the command line and the final verdict and cut the wait in post. Never speed-ramp a measured number.
- **Fallback:** If Flagsmith is unreachable, stop. Do not substitute `audit.sample.json` — the dashboard labels it SAMPLE, and a judge will see that. Re-record after the instance health check passes and the seed still shows the shared audience.

## S06 — Measured verdict (0:43–0:55)

- **Visual:** Same terminal, no cut.
- **Command:**
  ```sh
  jq '{verdict, collisions, overlaps: [.overlaps[] | {a, b, jaccard}]}' audit.json
  ```
- **Proof:** `verdict: "collision"`; Jaccard is the measured value (acceptance target >= 0.9). Read the number on screen aloud; never pre-bake it.
- **Fallback:** If `jq` is missing, use `python3 -m json.tool audit.json | head -40` and point at the same fields. Do not edit the JSON.

## S07 — Dashboard matrix (0:55–1:05)

- **Before the take:** copy the measured audit into the dashboard directory: `cp audit.json lab/dashboard/audit.json`, then refresh. The dashboard fetches `audit.json` from its own directory and cannot see the repo-root file. For this shot, hold `lab/dashboard/verify.json` and `receipt.json` aside (restore after) so the dashboard shows the pre-apply collision state, not "Audiences isolated".
- **Visual:** Pre-opened lab overlap dashboard at `http://localhost:8022/`. Both experiments red off-diagonal; the cell shows the measured Jaccard; `collision` badge.
- **Capture:** `browse.recording` on tab `ei-dashboard`; 8–10 s; cursor still.
- **Proof:** the matrix value equals S06's Jaccard. The dashboard must **not** display the SAMPLE chip. If it does, the audit is not measured; stop. The ENV chip shows only a truncated key prefix; never show a full key.
- **Fallback:** Refresh once on camera and say "refreshing the dashboard so it reads the audit we just wrote." If the fetch still fails, confirm `lab/dashboard/audit.json` is the copy from **this** run (or, only when recording the lab instance, run `bash lab/run.sh audit`). Never show a stale matrix or a second instance's audit.

## S08 — Plan (1:05–1:15)

- **Visual:** Terminal.
- **Commands:**
  ```sh
  python3 -m engine.cli plan --audit audit.json --out plan.json
  jq '{approval_token, segments_to_create, audience_changes}' plan.json
  ```
- **Proof:** two segments — `exp_iso_0_49` (`LESS_THAN 50`) and `exp_iso_50_99` (`GREATER_THAN_INCLUSIVE 50`) — an `iso-...` approval token, and both audience changes. Nothing has mutated.
- **Fallback:** If the plan shows no audience changes because experiments are running, stop: the demo must use draft experiments that can be changed. Fix the seed; do not narrate around it.

## S09 — Refusal (1:15–1:25)

- **Visual:** Terminal. Keep this failure unedited.
- **Command:**
  ```sh
  python3 -m engine.cli apply --plan plan.json --approve "wrong-token" --out refused.json; echo "exit=$?"
  ```
- **Proof:** stderr refusal and `exit=10`; `refused.json` is written or the command explicitly writes nothing (match the engine's actual contract). No segment is created.
- **Fallback:** If it exits 0, **stop the recording** — this is a real bug, not a bad take. Fix the token check, rerun the unit tests, then re-record from S05. Never stage a fake error.

## S10 — Approved apply (1:25–1:38)

- **Visual:** Terminal.
- **Commands:**
  ```sh
  TOKEN=$(jq -r .approval_token plan.json)
  python3 -m engine.cli apply --plan plan.json --approve "$TOKEN" --out apply.json
  ```
- **Proof:** stderr summary shows segment creation, rollout disable, audience swap, re-enable, start — in that order. `apply.json` exists.
- **Safety:** The approval is the on-camera human gate. Do not echo `$TOKEN`; the recorded command line shows the literal `$TOKEN`, never its value.
- **Fallback:** If apply fails midway, run the plan's rollback commands before retrying. Do not edit `apply.json`; a partial apply is a stop-the-demo event.

## S11 — Apply record (1:38–1:50)

- **Visual:** Terminal.
- **Command:**
  ```sh
  jq '{changes, experiments: [.changes[]? | {experiment_id, action}]}' apply.json
  ```
  (Use the engine's actual `apply.json` field names; adjust only the `jq` projection, not the file.)
- **Proof:** the JSON names the same mutations as the stderr summary and includes rollback commands.
- **Fallback:** `cat apply.json` at 18 pt and hold. Do not summarize a file you have not shown.

## S12 — Verify (1:50–2:00)

- **Visual:** Terminal.
- **Command:**
  ```sh
  python3 -m engine.cli verify --plan plan.json --samples 500 --out verify.json
  ```
- **Proof:** fresh sample, completion, `verify.json` written.
- **Fallback:** If verify needs the plan's audit path and cannot find it, stop and fix the invocation. Do not point it at a different run's artifacts.

## S13 — After overlap (2:00–2:10)

- **Visual:** Terminal.
- **Command:**
  ```sh
  jq '{before_jaccard, after_jaccard, pass, overlaps: (.overlaps | length)}' verify.json
  ```
- **Proof:** `after_jaccard: 0`, `pass: true`, `overlaps: 0`. If the number is not zero, stop and fix the build; do not talk over it.
- **Fallback:** None. A non-zero after-overlap is a failed demo, not an editing problem.

## S14 — Receipt (2:10–2:25)

- **Visual:** Terminal.
- **Commands:**
  ```sh
  python3 -m engine.cli receipt --audit audit.json --plan plan.json --verify verify.json --out receipt.json
  cat receipt.json
  ```
- **Proof:** before/after verdicts, `changes`, rollback list, `token_count`, `pass: true`. The token count must be the measured value from `docs/token-count.md`; do not say a number that was not measured.
- **Fallback:** If `receipt` is not implemented yet, this shot is not recordable. Do not hand-write a receipt for the video.

## S15 — Flagsmith experiments (2:25–2:33)

- **Visual:** Flagsmith Experiments list. Open each experiment's Audience panel.
- **Proof:** experiment one audience `exp_iso_0_49`; experiment two `exp_iso_50_99`; both running. This is the clearest "Flagsmith is doing the work" shot.
- **Fallback:** If the UI is slow, cut the wait, not the proof. Reload once; if the audience still shows the old segment, apply did not land — stop and rerun S12.

## S16 — Persisted bucket trait (2:33–2:40)

- **Visual:** Flagsmith identity detail for one sampled identity.
- **Proof:** `flagsmith_experiment_bucket` with an integer value in its traits; the value explains which segment the identity matches.
- **Fallback:** If the identity search is slow, pre-open the identity page before the take and cut to it. Do not type a different identifier than the one the audit sampled.

## S17 — Close (2:40–2:45)

- **Visual:** `video/endcard.html` (rendered to `stills/endcard.png`). Repo URL, both track labels.
- **Action:** replace `OWNER` in the HTML with the real GitHub org/user before rendering. Hold 2.5 s.
- **Proof:** repository URL is readable for the full hold; Track 3 and Track 4 labels are visible.
- **Fallback:** If the end card cannot be rendered in time, hold the README links bar for 2.5 s. The URL must still be readable.
- **Edit:** hard stop at 2:45; trim the last frame rather than adding music tail.

---

## Pre-flight (do before any take)

1. `source ~/flagsmith-local/flagsmith.env` in the recording shell only; never `cat` it, never `env`, never `set -x`.
2. `export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"`.
3. Reset to the seeded draft collision (`python3 seed/demo_seed.py`, or a fresh lab volume if the run is already applied); confirm two draft experiments share one audience. Do not assume seed resets a completed run.
4. `rm -f audit.json plan.json apply.json verify.json receipt.json refused.json`.
5. Confirm `lab/dashboard/audit.json` is from this run; for S07, hold `verify.json`/`receipt.json` aside so the dashboard shows the pre-apply collision. No SAMPLE chip.
6. `browse.status` must report a connected browser (it did at test time). If `paired-offline`, fix before browser shots. Run `browse.emulate` at 1920×1080 before recording; otherwise `browse.recording` captures the window size (the first smoke take was 1700×902). A visible scrollbar can encode 1904×1080; `assemble.sh` pads it.
7. Terminal: 18 pt+ font, 1920x1080 window, no key in the prompt or scrollback. Browser: 110%.
8. Run `video/record_terminal.sh --demo` once to confirm capture and render; delete the placeholder output afterwards.

## Honesty rules

- Do not record `audit.sample.json`, a hand-edited receipt, or a fabricated dashboard state.
- Do not show a key, token, or the inside of `flagsmith.env`.
- Do not say "zero" until `verify.json` shows zero in the same run.
- Do not claim the skill is merged upstream; say "packaged for upstream contribution."
- The only failure in the video is S09. Any other failure is a stop-and-fix.
