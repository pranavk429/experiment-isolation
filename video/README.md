# Video pipeline — Experiment Isolation

**Status: a draft cut exists; the final cut waits for the verifier.** The draft is `renders/draft.mp4` (2:45.70, 1920×1080 H.264/AAC). See `DRAFT.md` for beats, gaps, and exact commands. It is not verifier-approved and must not be presented as final. `captures/pipeline-test.mp4` remains a labelled 11.8-second placeholder; it is not product footage.

The shot-by-shot plan is `SHOTLIST.md`. The beat structure comes from `../docs/demo-script.md`; the judging rationale is in `../../research/04-winning-craft.md`.

## Tool inventory (checked 27 Nov 2026)

| Tool | State | Evidence | Role |
|---|---|---|---|
| `browse.recording` | **available, tested** | Relay connected (Chrome 0.0.17). Recorded the title page at 1920×1080 (2.03 s) and the live dashboard at 1904×1080 (4.07 s; 16 px scrollbar), both VP8 / 30 fps containers. | Primary browser/tab capture. |
| `browse.emulate` | **available, tested** | Forced a `1920×1080` layout viewport. A page with a visible scrollbar encoded 1904×1080 (16 px scrollbar). | Set the tab size; `assemble.sh` pads the 16 px back. |
| `screencapture` | **present, blocked** | `/usr/sbin/screencapture`. A test returned `could not create image from display`. | Screen/window stills after Screen Recording permission is granted. |
| `ffmpeg` / `ffprobe` | **present** | 8.1 at `/opt/homebrew/bin/ffmpeg`; `libx264` present; AVFoundation lists `Capture screen 0`. | Normalize, concat, mux, transcode. Screen capture still needs permission. |
| `script` | **present, tested** | BSD `/usr/bin/script`; captured a 6-command session and rendered it to 1080p30. | Default terminal capture backend. |
| `asciinema` | **missing** | Not on `PATH`. `brew install asciinema` if wanted. | Preferred terminal capture when installed; not required. |
| `agg` / `terminalizer` / `vhs` | **missing** | None on `PATH`. | Not needed; `render_transcript.py` replaces the cast-to-video step. |
| `brew` | **present** | 7.0.15. | Install `asciinema` or `ffmpeg` if needed. |
| `python3` | **present** | 3.9.6; Pillow 11.3.0; Playwright + Chromium cache present. | Renderer, stills, fallback page recorder. |
| `node` / `npm` | **present** | v24.14.1 / 11.11.0. | Not used by this pipeline. |
| `jq` | **present** | 1.7.1. | The on-camera `jq` projections in the demo script. |
| Chrome-family browser | **present, connected** | `browse.status` shows Chrome (extension 0.0.17) with tabs. The default `/Applications/Google Chrome.app` path was absent, so the running app is installed elsewhere. | Primary browser for `browse.recording`; Playwright Chromium is the fallback. |
| `qlmanage` | present | Renders HTML to a **square** 1920×1920 thumbnail. | Not used; `render_still.py` gives exact 1920×1080. |

**Pipeline tests already run (no product data):**

- Terminal: `record_terminal.sh --demo --render` → 11.83 s, 1920×1080, 30 fps, H.264. Placeholder only.
- Page fallback: `record_page.py` on a local HTML file → 2.87 s, 1920×1080, 30 fps.
- Cast parser: a 3-line synthetic v2 cast → 4.03 s, 1920×1080, 30 fps. Synthetic input, not product data.
- Assembly: two synthetic clips + title + end card + a 3 s tone → 7.53 s, 1920×1080, 30 fps, AAC audio padded to video length.
- Guard: a `--commands` file containing `env` is refused with exit 2 **before** capture opens.
- Browser primary: `browse.recording` + `browse.emulate` recorded the title page at 1920×1080 VP8 (2.03 s) and the live dashboard at 1904×1080 VP8 (4.07 s; 16 px scrollbar). The dashboard frame showed `MEASURED AUDIT`, 2 experiments, 500 samples, 100% before Jaccard, 0% max. Smoke only; the lab is still building.
- Dashboard fallback: `record_page.py` against the same live dashboard → 5.03 s, 1920×1080, same measured state. Smoke only.
- Stills: `stills/title.png` and `stills/endcard.png` render at exactly 1920×1080.
- Engine surface: `python3 -m engine.cli --help` lists `audit plan apply verify receipt`. No audit/apply was run.

## Files

| Path | What it is |
|---|---|
| `SHOTLIST.md` | Every shot mapped to the 0:00–2:45 script: visual, command, proof, fallback, readiness. |
| `record_terminal.sh` | Captures a command sequence with asciinema or BSD `script`; guard blocks secret/verbose lines. |
| `render_transcript.py` | Renders a `.cast` or `.typescript` to a 1920×1080 MP4 with a clean terminal frame. |
| `record_page.py` | Playwright fallback that records a real local page when `browse.recording` is unavailable. |
| `assemble.sh` | Normalizes clips to 1080p30, concatenates in name order, pads/muxes narration. |
| `render_still.py` | Renders an HTML still at exactly 1920×1080 with Playwright Chromium. |
| `title.html` / `stills/title.png` | Title/thumbnail card. Opt-in pre-roll only; the script opens cold. |
| `endcard.html` / `stills/endcard.png` | Close card with product name, claim, track labels, repo URL placeholder. |
| `commands/demo.template.txt` | The S03–S14 terminal lines. Copy to `demo.txt` after the engine is verified. |
| `raw/` | Recorded segments go here, named `01-problem.webm` … `17-close.mp4`. |
| `captures/` | Terminal captures and the labelled pipeline test. |
| `DRAFT.md` | Draft report: duration, beats, gaps, exact commands, and token-count caveats. |
| `renders/draft.mp4` | Draft cut, 2:45.70. Not final. |

## 1. Preflight

### 1.1 One instance per run

The demo script uses the local research instance (`http://localhost:8000`). The lab uses its own Flagsmith on `:8010`, storefront on `:8020`, and dashboard on `:8022`. Pick one and do not mix:

**Research instance (the demo script's default):**

~~~sh
source "$HOME/flagsmith-local/flagsmith.env"
export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"
python3 seed/demo_seed.py
rm -f audit.json plan.json apply.json verify.json receipt.json refused.json
# second terminal: dashboard-only static host; skip if :8022 is already served
python3 -m http.server 8022 --bind 127.0.0.1 --directory lab/dashboard
~~~

**Lab instance:**

~~~sh
bash lab/run.sh                 # Flagsmith :8010, storefront :8020, dashboard :8022
source lab/.env
export DEV_ENV_KEY="$LAB_DEV_ENV_KEY"
~~~

If you use the lab, the dashboard already owns the measured `lab/dashboard/audit.json` and `lab/run.sh` generates it. If you use the research instance, the dashboard still serves `lab/dashboard/`, so copy the measured audit there before shot S07 (see 3.3).

### 1.2 Permissions and relay

- **Screen Recording:** `screencapture` failed with `could not create image from display`. Open **System Settings → Privacy & Security → Screen Recording**, enable Terminal (and the app hosting the agent), then quit and reopen Terminal. Re-test with `screencapture -x /tmp/screen-test.png`. Until then, only tab capture and terminal capture work.
- **Browse relay:** `browse.status` reported a connected Chrome at test time. If it drops to `paired-offline`, open the paired browser with the browse extension and follow its `nextStep`; do not retry-loop a disconnected relay.
- **Zoom:** browser at 110%; terminal font 18 pt or larger. The transcript renderer uses 30 px SF Mono, which is readable at 1080p.
- **Secrets:** never run `env`, `set -x`, `history`, or `cat` on an env file in the recording shell. The recorder refuses those patterns, but it cannot protect a key you paste into a command.

### 1.3 Product readiness gate

Do not record S05–S16 until all of these are true:

1. `python3 -m pytest tests/engine -q` passes.
2. Two draft experiments share one audience after `python3 seed/demo_seed.py`.
3. `audit` returns `verdict: "collision"` with measured Jaccard ≥ 0.9.
4. `plan` returns the two bucket segments and an `iso-…` token.
5. Wrong-token `apply` exits 10 and writes no change.
6. Approved `apply` creates the segments and cycles the rollouts.
7. `verify` returns `after_jaccard: 0.0` and `pass: true`.
8. `receipt` returns `pass: true` and a measured `token_count`.
9. The dashboard shows the measured audit, **not** the SAMPLE chip.

## 2. Record the terminal

### 2.1 Test the capture path (safe now)

~~~sh
cd "$HOME/toggle win for sure/experiment-isolation"
./video/record_terminal.sh --demo --render
~~~

This writes `video/captures/pipeline-test.typescript` and `pipeline-test.mp4`. The amber header says **PIPELINE TEST — PLACEHOLDER OUTPUT**. It is not demo footage; delete it before publishing if you do not want the artifact in the repo.

### 2.2 Record the real take

Copy the template after the product gate passes, then edit only the `jq` projections if the engine's field names differ. Validate it first without executing anything:

~~~sh
cp video/commands/demo.template.txt video/commands/demo.txt
./video/record_terminal.sh --commands video/commands/demo.txt --check
source "$HOME/flagsmith-local/flagsmith.env"
export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"
./video/record_terminal.sh --commands video/commands/demo.txt --render
~~~

The parent shell is sourced **before** the recorder starts, so the `source` line never appears on camera and keys never enter the capture. The child shell inherits `DEV_ENV_KEY` and the CLI path.

What the runner does:

- Prints `experiment-isolation $ <command>` for every line, then executes it.
- Keeps going on a non-zero exit and prints `[exit N]` in red. The wrong-token refusal is supposed to exit 10.
- Prints the literal `"$TOKEN"`, never its expanded value.
- Refuses `env`, `printenv`, `set -x`, `history`, reads of `.env`/`flagsmith.env`, and `echo`/`printf` of `FLAGSMITH_API_KEY` or `ADMIN_TOKEN` **before** the capture opens.
- Uses asciinema when installed; otherwise BSD `script`. Force with `--tool script`. Output is `.cast` or `.typescript`.
- The asciinema branch is **not exercised on this machine** (binary missing). The `script` path is tested end to end; if you install asciinema, run `--demo --tool asciinema` once before the real take.

Install asciinema only if you want real event timing and a portable cast:

~~~sh
brew install asciinema
~~~

### 2.3 If you need to re-render only

~~~sh
python3 video/render_transcript.py video/captures/take.typescript \
  --out video/captures/take.mp4
~~~

Useful options: `--line-delay 0.46` for `script` pacing, `--max-hold 2.4` to cap a slow command's gap, `--watermark` for a test, `--keep-frames` to inspect PNGs. The renderer is not a screen recording; it redraws the captured lines. That is why the header says it is a captured terminal, not a desktop capture.

## 3. Record the browser with browse.recording

### 3.1 Confirm the relay and open the tab

`browse.status` must show a connected browser. Then open or reuse a named tab:

~~~js
const tab = await tools.browse.tabs({
  action: "new",
  id: "ei-dashboard",
  url: "http://localhost:8022/",
  allowedOrigins: ["http://localhost:8022"],
  keepOpen: true,
});
// tab.tab is the handle every other call takes
~~~

Force the tab to 1920×1080 before recording:

~~~js
await tools.browse.emulate({
  tab: tab.tab,
  viewport: { width: 1920, height: 1080, deviceScaleFactor: 1 },
});
~~~

Without this, the file is whatever the browser window is (the first smoke take was 1700×902). `browse.recording` does not resize the page. A visible scrollbar can reduce the encoded width to 1904 for a 1920 layout; `assemble.sh` pads it back to 1920×1080.

Use `http://localhost:8000` for the research Flagsmith UI, or `http://localhost:8010` for the lab Flagsmith. Use `ei-flagsmith` as the tab id. Keep the tab open for S01/S02 and S15/S16 so you do not reload between shots.

### 3.2 Start and stop

~~~js
await tools.browse.recording({
  action: "start",
  tab: tab.tab,
  path: "ei-dashboard-07.webm",
  frameRate: 30,
  quality: 92,
  maxDurationMs: 120000,
});

// reload or hold the matrix here; do not touch the page during the proof beat

const result = await tools.browse.recording({ action: "stop", tab: tab.tab });
// result = { path, bytes, durationMs, width, height, frameCount, quality }
~~~

The recording size is the tab's device resolution. `browse.emulate` sets the layout viewport; a visible scrollbar can reduce the encoded width by 16 px (the dashboard smoke was 1904×1080). `assemble.sh` pads it back to 1920×1080. Reset with `viewport: "reset"` when done. The tool caps at 30 fps but only emits changed frames: the static title-page take reported ~5.9 source fps, the dashboard ~6.1. A held matrix is fine; inspect a scroll/hover clip before trusting it, and use the Playwright fallback or screen capture if it looks choppy.

A **relative** `path` is always accepted and lands in browse's private folder. An absolute path must be inside browse's file roots; if it is refused, use a relative name. `stop` returns the actual `path`. Copy it into the ordered raw folder:

~~~sh
cp "<result.path>" video/raw/07-dashboard.webm
~~~

The recording is a CDP screencast of the tab: it captures the page, not the browser chrome or the desktop cursor. For a hover proof, prefer a pinned audience panel over a tooltip that may not show a pointer.

### 3.3 Dashboard before S07

The dashboard fetches `audit.json` from **its own directory** (`lab/dashboard/`), not from the repo root. After the audit, copy the measured file before refreshing:

~~~sh
cp audit.json lab/dashboard/audit.json
~~~

Refresh once on camera and say so. The dashboard must not show the SAMPLE chip. If it does, the file is a sample or the fetch failed; stop and fix it. For S07, hold `lab/dashboard/verify.json` and `receipt.json` aside (restore after) so the dashboard shows the pre-apply collision state, not "Audiences isolated". Do not record a stale matrix.

### 3.4 Fallback A — Playwright records the real page

If the relay is offline but the dashboard is up, `record_page.py` records the actual page with Playwright:

~~~sh
python3 video/record_page.py \
  --url http://localhost:8022/ \
  --out video/raw/07-dashboard.mp4 \
  --seconds 10 \
  --reload-at 4
~~~

Both a 5 s Playwright take and a 4 s `browse.recording` take captured the live dashboard in its measured state: no SAMPLE chip, 2 experiments, 500 samples, 100% before Jaccard, 0% max. The lab is still building; re-check the audit and receipt immediately before a real take. These are scripted holds, not human hover. They are honest for the matrix; do not use them to claim an interaction that did not happen. Playwright cannot reach the research Flagsmith UI's hover states as naturally as the user's browser; prefer `browse.recording` for S01/S02/S15/S16.

### 3.5 Fallback B — whole-screen ffmpeg capture

Only after Screen Recording is granted:

~~~sh
ffmpeg -y -f avfoundation -framerate 30 -i "Capture screen 0" \
  -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p \
  video/raw/screen-01.mp4
~~~

Press `q` to stop. Crop in post if the window does not fill the frame. This captures the desktop, so hide notifications and anything with a key. `assemble.sh` will scale/pad it to 1080p.

## 4. Flagsmith UI shots (S01/S02, S15/S16)

- Same `browse.recording` flow with tab `ei-flagsmith`. Start on the **Experiments** list; keep both seeded experiments visible without scrolling.
- Hover each audience chip for S02, or click into the Audience panel so the shared segment name is pinned. Proof is the identical segment, not the hover animation.
- For S15, open each experiment's Audience panel: `exp_iso_0_49` and `exp_iso_50_99`, both running.
- For S16, open one sampled identity and show `flagsmith_experiment_bucket` in its traits. Use an identifier the audit actually sampled.
- Hide or crop key columns. Never show project API keys, environment keys, or the inside of `flagsmith.env`.
- If the UI is slow, cut the wait in the edit, not the proof. Do not speed-ramp a number.

## 5. Narration

Record narration separately (QuickTime Player, or `ffmpeg` with the microphone) against the 2:45 script. Do not try to narrate live over a terminal take; the typing and waits will drift.

~~~sh
# example only: list the microphone device first
ffmpeg -f avfoundation -list_devices true -i ""
~~~

Keep the narration file at `video/raw/narration.m4a`. `assemble.sh` pads it to the video length with `apad` so a short read does not cut the picture. If the read is longer than the picture, trim the script, not the proof.

## 6. Render the stills

Replace `OWNER` in both HTML files with the real GitHub org/user **before** rendering. The placeholder is intentionally obvious on screen.

~~~sh
python3 video/render_still.py video/title.html   --out video/stills/title.png
python3 video/render_still.py video/endcard.html --out video/stills/endcard.png
~~~

Both are exactly 1920×1080. The title card is for the thumbnail/poster; the demo script opens cold on the problem, so do not insert a 1-second logo unless the cut is comfortably under 2:45. The end card is the S17 close or a 2.5-second append.

## 7. Assemble

Name segments in shot order in `video/raw/`: `01-problem.webm`, `02-audience.webm`, `03-skill.mp4`, … `17-close.mp4`. The script sorts by filename.

~~~sh
./video/assemble.sh \
  --clips video/raw \
  --audio video/raw/narration.m4a \
  --endcard video/stills/endcard.png --with-endcard \
  --out video/renders/demo.mp4
~~~

What it does: normalizes every clip to 1920×1080, 30 fps, H.264, yuv420p, no audio; concatenates in order; pads/muxes the narration; prints the final duration and warns over 3:00. Add `--title video/stills/title.png --with-title` only if you want the 1-second pre-roll. `--keep-work` keeps the normalized clips.

### 7.1 Manual ffmpeg fallback

If you do not use the script, the equivalent steps are:

~~~sh
mkdir -p video/work
ffmpeg -y -i video/raw/01-problem.webm \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -an video/work/01.mp4

for f in video/work/*.mp4; do printf "file '%s'\n" "$f"; done > video/work/concat.txt
ffmpeg -y -f concat -safe 0 -i video/work/concat.txt -c copy video/work/silent.mp4

DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 video/work/silent.mp4)
ffmpeg -y -i video/work/silent.mp4 -i video/raw/narration.m4a \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -af apad -t "$DURATION" \
  video/renders/demo.mp4
~~~

Add title/end-card stills with `-loop 1 -t 1.0` / `-t 2.5` and the same normalize filter before the concat list.

### 7.2 If ffmpeg is missing

`brew install ffmpeg`. If Homebrew/network is unavailable, use QuickTime Player screen recording plus iMovie, or the platform editor; `assemble.sh` and `render_transcript.py` will not run. Do not upload a 4:3 or 720p cut because a tool was missing.

## 8. Runtime and edit rules

Target **2:45**, hard cap **3:00**.

| Beat | Target in | Target out | Seconds |
|---|---|---|---|
| Problem | 0:00 | 0:15 | 15 |
| What it is | 0:15 | 0:30 | 15 |
| Audit + matrix | 0:30 | 1:05 | 35 |
| Plan + refusal | 1:05 | 1:25 | 20 |
| Approve + apply | 1:25 | 1:50 | 25 |
| Verify | 1:50 | 2:10 | 20 |
| Receipt | 2:10 | 2:25 | 15 |
| Flagsmith side | 2:25 | 2:40 | 15 |
| Close | 2:40 | 2:45 | 5 |

Rules:

- Record S05–S14 in one terminal take. The only intended failure is the wrong-token refusal.
- Browser shots are B-roll captured separately and cut in. That is editing, not re-enactment.
- Cut waits, not proof. Keep the command line and the final line; cut the spinner.
- Do not pre-bake or narrate a number you have not seen. The measured Jaccard and token count must come from the same run.
- If `after_jaccard` is not 0, stop and fix the build. Do not talk over it.
- Hard stop at 2:45; trim the tail rather than adding a music outro.

## 9. Final checklist

- [ ] **Repo link visible** at the close; `OWNER` replaced in both HTML files and on screen.
- [ ] **Token count visible**: receipt `token_count` from the measured run; no guessed number.
- [ ] **Refusal beat**: wrong-token `apply` exits `10` on camera, unedited; no mutation.
- [ ] **Before/after overlap**: `before_jaccard` and `after_jaccard: 0` from the same run; S13 shows `pass: true` and `overlaps: 0`.
- [ ] **Flagsmith dashboard**: experiments list, both audiences (`exp_iso_0_49` / `exp_iso_50_99`), both running, and one identity's `flagsmith_experiment_bucket`.
- [ ] **Dashboard measured**: no SAMPLE chip; `audit.json` copied into `lab/dashboard/` and refreshed on camera.
- [ ] **No secrets**: no full key, token, `flagsmith.env` contents, `env` output, or full key column in frame. The dashboard ENV chip shows only a truncated key prefix; crop it if even that is too much.
- [ ] **Synthetic identities** stated once; no claim of real users.
- [ ] **No fabricated footage**: every clip is a recorded run; placeholder renders are deleted or clearly labelled.
- [ ] **Runtime** 2:45–3:00; 1920×1080, 16:9, 30 fps; audio synced.
- [ ] **Title/end card** placeholders replaced; end card held long enough to read the URL.
- [ ] **Video URL** added to the root README by the docs owner (this pipeline only owns `video/`).

## 10. Blockers and exact next steps

**Blockers right now:**

1. **The dashboard is live but not frozen.** At report time (10:46–10:47), `lab/dashboard/audit.json`, `apply.json` and `receipt.json` exist and the dashboard is up; a smoke capture showed `MEASURED AUDIT`, 2 experiments, 500 samples, 100% before Jaccard, 0% max. The lab is still building: confirm the artifacts are from the same run and freeze them before S07/S15/S16. Do not use the smoke capture.
2. **The lab is post-apply.** At report time, `receipt.json` exists and the dashboard headline is "Audiences isolated". S05/S07 need the seeded draft collision **before** apply: reset the demo to draft, confirm `audit` reports collision, and make sure `verify.json`/`receipt.json` are absent from `lab/dashboard/` for the S07 take.
3. **No verified run by this pipeline.** Audit/plan/apply/verify/receipt were not run here; S05–S14 remain gated. Do not record them from a prior or sample audit.
4. **Screen Recording denied.** `screencapture` cannot read the display; grant permission and restart Terminal before any screen fallback.
5. **One instance, confirmed seed.** Research Flagsmith (:8000) and lab Flagsmith (:8010) are both up. Pick one, confirm the two draft experiments share an audience immediately before S01/S02, and do not mix artifacts.
6. **Repo URL placeholder.** `OWNER` must be replaced before stills are rendered.
7. **Dashboard path mismatch.** The demo writes `audit.json` at the repo root; the dashboard reads `lab/dashboard/audit.json`. Copy the measured file before S07.
8. **Token count unmeasured.** Wait for `receipt.json`; never quote a target.
9. **No narration or final edit.** The pipeline is ready; the performance is not.

**Once the engine and lab land:**

1. Run `pytest tests/engine -q`; fix failures before touching the camera.
2. Reset to the seeded draft collision on one instance; run `audit`; confirm `verdict: "collision"` and Jaccard ≥ 0.9.
3. Copy `audit.json` to `lab/dashboard/audit.json`; confirm no SAMPLE chip and hold `verify.json`/`receipt.json` out of the dashboard for the S07 take.
4. Copy the template to `demo.txt`; record S03–S14 in one take; check the refusal is exit 10.
5. Confirm `browse.status` connected; `browse.emulate` 1920×1080; record S01/S02/S07/S15/S16; check no keys are in frame.
6. Confirm S13/S14 numbers; render stills with the real repo URL.
7. Record narration; assemble; check runtime and audio sync.
8. Run the checklist above; only then add the video URL to the root README.

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `browse.status` says `paired-offline` | Open the paired browser and the browse extension. Wait for it to reconnect; do not retry-loop. |
| `screencapture` says `could not create image from display` | Grant Screen Recording to Terminal/the agent host, then restart it. |
| `asciinema` not found | Expected. The recorder falls back to `script`; or `brew install asciinema`. |
| `script` output starts with `^D^H^H` or clear codes | Expected. `render_transcript.py` strips control bytes; do not hand-edit the typescript. |
| Dashboard shows SAMPLE | The audit is not measured or the copy is stale. Run the audit, copy to `lab/dashboard/audit.json`, refresh. |
| `ffmpeg` concat reports non-monotonic DTS | `assemble.sh` re-encodes the join; for a manual join, normalize every clip to the same fps/size first. |
| `mapfile: command not found` | Run the scripts with `/bin/bash` or the current Bash; `assemble.sh` is Bash 3.2-compatible. |
| `record_page.py` event-loop error | Fixed in this version; make sure `playwright` and its Chromium cache are installed (`python3 -m playwright install chromium`). |
| Playwright MP4 is 2.9 s for a 3 s request | The settle time is subtracted from the timed hold. Increase `--seconds` or lower `--settle-ms`. |

---

**Do not claim a video exists until `video/renders/demo.mp4` is a real assembled cut and the checklist passes.** This directory is the recording pipeline, not the deliverable.
