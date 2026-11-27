# Final cut — Experiment Isolation

**Video status: FINAL CUT COMPLETE. Not uploaded.** The required refusal, 121-token, agent-run, and repo-URL beats are present, so this cut is final. The project release gate in `verification/RELEASE.md` still blocks submission (uncommitted tree, public URL 404 at gate time). Do not upload until the repo is public and committed.

| | |
|---|---|
| File | `video/renders/final.mp4` |
| Duration | **2:48.23** (168.233 s), under the 3:00 cap |
| Format | 1920×1080, 30 fps, H.264 High, AAC-LC mono 48 kHz |
| Size | 14,919,984 bytes |
| SHA-256 | `1aaa9627823232d025e7c8288c2016503a1777dc247b396196e9bdfa090b1c1d` |
| Narration | macOS `say -v Samantha -r 145`; 167.04 s script |
| Repo on screen | `https://github.com/pranavk429/experiment-isolation` |

## Beats covered

| Time | Beat | Proof |
|---|---|---|
| 0:00–0:02 | Title card | Product name, tracks, repo URL |
| 0:02–0:10 | Problem | Storefront: two experiments, one audience |
| 0:10–0:22 | Flagsmith shared audience | Both drafts show `us_mobile` at :8010 |
| 0:22–0:42 | Live dashboard before | :8022, 100% collision, 250/250, matrix |
| 0:42–0:58 | What it is | `skills/experiment-isolation/SKILL.md` + CLI + architecture |
| 0:58–1:28 | Audit → plan → refusal → apply | Audit exit `10`, wrong-token exit `10`, approved apply |
| 1:28–1:35 | Verify | 1.00 → 0.00, pass true, 1 pair measured, 0 overlapping |
| 1:35–1:38 | Receipt token line | `token_count.py` prints **121** |
| 1:38–1:47 | Receipt panel | **121 o200k / 120 cl100k**, 429 chars, internal 107 |
| 1:47–2:11 | Live dashboard after | Same-run :8022 recording, 0% + 100→0 panel |
| 2:11–2:25 | Flagsmith disjoint audiences | `exp_iso_0_49` / `exp_iso_50_99`, both running |
| 2:25–2:38 | Agent-run proof | OpenCode subagent log: audit exit 10 → rollback |
| 2:38–2:43 | Rollback truth | `live_restore=false`, `requires_recreate=true` |
| 2:43–2:48 | End card | Repo URL, Track 3/4, pass-safe claims |

## Required proof check

- **Refusal visible:** yes. Audit exit `10` at about `1:01`; wrong-token apply exit `10` at about `1:24–1:25`.
- **121 visible:** yes. Terminal `token_count.py` at `1:35–1:38`; receipt panel at `1:38–1:47`; agent log at `2:25–2:38`. The narration says 121 o200k / 120 cl100k, 429 chars, internal 107.
- **Agent-run proof:** yes. 13-second panel rendered from `verification/AGENT_RUN.md`: audit exit 10, plan, apply, verify 1.0 → 0.0, receipt 121, rollback requires_recreate, 92 tests, skill body 1,477, validators pass.
- **Repo URL:** yes, title and end card, no `OWNER` placeholder.
- **Shared audience:** yes, Flagsmith before clip shows both drafts on `us_mobile`.
- **Rollback honesty:** yes. Agent log and live rollback clip show `requires_recreate=true`; no in-place restore claim.
- **Live dashboard:** before is live :8022; after is the live :8022 server fed the same-run JSON, labelled **SAME-RUN :8022** in the caption because the lab was reset after capture.
- **Token count on screen:** yes, 121; the dashboard evidence panel’s `1,384` is the sum of five phase estimates, not the receipt count. The receipt panel says “Not the harness total · not the phase sum.”

## Exact commands used

### Lab lifecycle

~~~sh
bash lab/run.sh reset
bash lab/run.sh
# ... record ...
bash lab/run.sh reset
bash lab/run.sh
~~~

Lab left clean: 2 drafts on segment 1, dashboard 100% collision, HTTP 200.

### Terminal run

Parent shell (values never printed):

~~~sh
set -a
. lab/.env
set +a
export FLAGSMITH_API_URL="$LAB_API_URL"
export FLAGSMITH_API_KEY_localhost_8010="$LAB_ADMIN_API_KEY"
export FLAGSMITH_API_KEY="$LAB_ADMIN_API_KEY"
export FLAGSMITH_ENVIRONMENT_KEY="$LAB_DEV_ENV_KEY"
export DEV_ENV_KEY="$LAB_DEV_ENV_KEY"
~~~

~~~sh
python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out video/work/final/audit.json
jq '{verdict, collisions, overlaps: [.overlaps[] | {a, b, jaccard}]}' video/work/final/audit.json
python3 -m engine.cli plan --audit video/work/final/audit.json --max-concurrent 4 --min-bucket-width 5 --out video/work/final/plan.json
jq '{approval_token, segments_to_create: [.segments_to_create[] | {name, operator, value}], audience_changes: [.audience_changes[] | {experiment, from_segment_ids, to_segment}]}' video/work/final/plan.json
python3 -m engine.cli apply --plan video/work/final/plan.json --approve "wrong-token" --out video/work/final/refused.json; echo "exit=$?"
TOKEN=$(jq -r .approval_token video/work/final/plan.json)
python3 -m engine.cli apply --plan video/work/final/plan.json --approve "$TOKEN" --out video/work/final/apply.json
python3 -m engine.cli verify --plan video/work/final/plan.json --samples 500 --workers 2 --out video/work/final/verify.json
jq '{before_jaccard, after_jaccard, pass, pairs_measured: (.overlaps | length), overlapping_pairs: ([.overlaps[] | select(.jaccard > 0)] | length)}' video/work/final/verify.json
python3 -m engine.cli receipt --audit video/work/final/audit.json --plan video/work/final/plan.json --verify video/work/final/verify.json --apply video/work/final/apply.json --out video/work/final/receipt.json
printf 'receipt tokens: '; python3 skills/experiment-isolation/scripts/token_count.py video/work/final/receipt.json
~~~

Recorded with:

~~~sh
./video/record_terminal.sh --commands video/commands/final-lab.txt --out video/captures/final/terminal.typescript --pace 0.45
python3 video/render_transcript.py video/captures/final/terminal.typescript --out video/captures/final/terminal.mp4 --line-delay 0.38
~~~

The final cut uses `terminal-a.mp4` (0–30.3 s) and `terminal-b.mp4` (31.0–38.5 s); the full apply JSON line was removed to keep its `key_prefix` out of frame.

### After capture and rollback

The lab was reset externally mid-session; the after UI was re-applied once and captured, then rolled back:

~~~sh
python3 -m engine.cli rollback --apply video/work/reapply/apply.json --out video/work/reapply/rollback.json
jq '{pass, live_restore, requires_recreate, actions}' video/work/reapply/rollback.json
~~~

Output: `actions=2; live_restore=False; requires_recreate=True; segments_deleted=2; pass=True`.

### Browser and Flagsmith

- Before dashboard: `browse.emulate` 1920×1080, `browse.recording` 8 s on `http://localhost:8022/`.
- Before/after Flagsmith: Playwright Chromium, logged-in storage state, 1920×1080; recorded the experiments list and both detail pages. State file deleted after use.
- After dashboard: same-run `audit/plan/apply/verify/receipt` JSON copied to `lab/dashboard/`, live :8022 refreshed, recorded top and panel, then reset.

### Narration and build

~~~sh
say -v Samantha -r 145 -o video/work/final/narration.aiff -f video/work/final/narration.txt
ffmpeg -y -i video/work/final/narration.aiff -c:a aac -b:a 192k -ar 48000 video/work/final/narration.m4a
python3 video/make_captions_final.py
python3 video/build_final.py
~~~

## Security remediation

- Deleted `video/work/final/flagsmith-state.json` (lab admin token + env keys).
- Scanned **234 files** under `video/` against exact values from `lab/.env` and `~/flagsmith-local/flagsmith.env`: **0 matches**. No `*state*.json` remains.
- Removed the full apply JSON from the terminal cut, eliminating the `key_prefix` frame.
- Masked the dashboard’s ENV chip in the before shot; visually checked terminal, dashboard, receipt, Flagsmith, agent, rollback, title, and end-card frames. No full key or token is visible.
- The final MP4 contains zero credentials. Per RELEASE.md, rotate the lab admin token if that state file was ever shared beyond this machine.
- RELEASE.md also notes the public repo was 404 at gate time; the displayed URL must be live before upload.

## Known caveats (not missing beats)

1. The after dashboard is a **same-run recording** on the live :8022 server, labelled in the caption; the lab was reset after capture, so :8022 now shows the clean 100% baseline.
2. An external reset occurred mid-session; the after Flagsmith UI was re-applied once to capture the bucket audiences. Values are deterministic and match the recorded run.
3. The receipt panel uses the authoritative verifier receipt from `verification/FINAL.md` (121 o200k / 120 cl100k, 429 chars, internal 107). The independent lab re-run receipt also measured 121/120 but 425 chars/internal 106; the 121 token count is consistent. The panel is labelled “Final verifier artifact.”
4. The dashboard evidence panel shows `1,384`, the sum of that run’s five phase estimates; it is not the receipt count. The receipt panel and narration state 121 explicitly.
5. Harness total is not exposed and is not claimed.
6. The repo URL is displayed; the public URL was 404 at the release gate and must be made live before uploading. No upload was performed.

## Verdict

Final video cut complete: **2:48.23**, refusal, 121, agent-run proof, and repo URL all visible. Project release gate still requires committing/publishing the repo and rotating any exposed lab token.
