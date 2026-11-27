# Draft cut — Experiment Isolation

**Status: DRAFT. Not final. Verifier sign-off pending.**

| | |
|---|---|
| File | `video/renders/draft.mp4` |
| Duration | `2:45.70` (165.70 s) |
| Format | 1920×1080, 30 fps, H.264 High, AAC-LC mono 48 kHz |
| Size | 17,748,679 bytes |
| SHA-256 | `3efe23a2df69a45ee55fb2e0d48d008bc93c4265adaceb911843d35347474eec` |
| Recorded | 27 Nov 2026 against the self-hosted lab: Flagsmith `:8010`, storefront `:8020`, dashboard `:8022` |
| Narration | macOS `say`, Samantha, rate 150; 164.803 s |
| Source state | Pre-apply 100% collision, then the real plan → apply → verify → receipt run |

This is a draft assembled from real captures. It is not a claim that the verifier has passed the final run. The raw terminal captures, browser clips, JSON artifacts, narration, and caption frames are under `video/work/`, `video/raw/`, and `video/captures/`.

## Beats covered

| Time | Beat | Visual |
|---|---|---|
| 0:00–0:02 | Title card | `stills/title.png` |
| 0:02–0:12 | Problem: two experiments, one audience | Storefront, `:8020` |
| 0:12–0:26 | Audit verdict on the dashboard | 100% collision, 2 experiments, 500 samples |
| 0:26–0:40 | Pairwise matrix before | 100% / 250 shared of 250 |
| 0:40–0:49 | Skill and CLI surface | `SKILL.md` + five CLI verbs |
| 0:49–0:56 | Architecture | README data-flow block |
| 0:56–1:50 | Audit → plan → refusal → apply | Real terminal take; audit exit 10, wrong-token apply exit 10 |
| 1:50–1:55 | Verify clarification | `pairs_measured: 1`, `overlapping_pairs: 0`, `pass: true` |
| 1:55–2:01 | Receipt hold | Receipt JSON + measured 110-token file count |
| 2:01–2:15 | After dashboard | 0% max Jaccard, isolated |
| 2:15–2:29 | Before → after panel | 100% → 0%, 100 points removed, evidence loaded |
| 2:29–2:41 | Flagsmith experiments | Both running; detail pages show `exp_iso_0_49` / `exp_iso_50_99` |
| 2:41–2:45 | End card | Product name, tracks, repo placeholder |

## Numbers visible in the cut

- Audit: 2 experiments, 1 collision, 500 samples, verdict `collision`, Jaccard `1.0`, 250 shared / 250 union, exit `10`.
- Plan: token `iso-287a08eb`; `exp_iso_0_49` (`LESS_THAN 50`) and `exp_iso_50_99` (`GREATER_THAN_INCLUSIVE 50`); 2 audience changes.
- Wrong-token apply: exit `10`, message “Approval token does not match this plan; nothing was changed”.
- Approved apply: 2 segments created (IDs 4 and 5), both experiments running, `pass: true`; 6 rollback commands in `apply.json`.
- Verify: before `1.0`, after `0.0`, `pass: true`, one pair measured, zero overlapping users; 500 samples.
- Receipt: before `collision`, after `isolated`, 4 changes, `pass: true`. `token_count` phases: audit 209, plan 594, apply 0, verify 95, receipt 93 → 991. The receipt file itself measures **110 tokens** with `token_count.py`.
- Dashboard after: 0% max, 100 → 0, “100 points of overlap removed”. The evidence panel shows the phase sum `991` and one receipt-level rollback reference.
- Flagsmith: both experiments running; audiences `exp_iso_0_49` and `exp_iso_50_99`.

## Refusal and token count

- **Audit refusal:** `audit` exits `10` on the collision. The red `[exit 10]` is visible at about `0:59`.
- **Apply refusal:** wrong-token `apply` exits `10` and says nothing changed. Visible at about `1:27`.
- **Token count:** `token_count.py receipt.json` prints **110**. It is visible in the terminal at about `1:57` and on the receipt caption. The dashboard’s `991` is the sum of the receipt’s per-phase counts, not the file count. Both are real; they measure different things.

## Missing or known gaps

1. **Repo URL is a placeholder.** Title and end card still read `github.com/OWNER/experiment-isolation` with a `PLACEHOLDER` tag. No real repo URL was available. The final cut must replace it.
2. **Verifier sign-off is not in.** This draft uses the lab run; the final cut waits for the verifier.
3. **Repo layout moved mid-record.** The terminal intro and token line show `skill/…`. The repo now uses `skills/experiment-isolation/…`. The token count was re-verified at the new path: 110. Re-record the intro and token line for the final.
4. **No Flagsmith “before” UI shot.** The lab was already post-apply when recording began. The problem beat uses the storefront plus the dashboard’s pre-apply 100% matrix; the Flagsmith clip is after-apply only.
5. **The after dashboard is a video-owned copy.** To avoid writing to `lab/**`, `lab/dashboard/index.html` was copied to `video/work/dashboard-after/` and served on `:8024` with the same-run JSON. The UI is the real dashboard; the data is same-run. The live `:8022` was not edited after apply.
6. **Token metrics are easy to confuse.** `token_count.py` measures the receipt file (110). `receipt.token_count` sums to 991. The harness total required by `docs/token-count.md` was not exported and is **not** claimed.
7. **Demo-script projection mismatch.** `jq '{overlaps: (.overlaps|length)}'` returns `1` because verify lists the one measured pair, even with zero shared users. The added verify clip shows `pairs_measured: 1` and `overlapping_pairs: 0`. Fix the demo script or keep the clarification.
8. **Flagsmith detail holds are short.** The clip shows the experiments list plus both audience detail pages; the audience names are on screen for only a few seconds.
9. **No music.** Narration is TTS; the only silence is a short tail (narration 164.803 s, picture 165.70 s).
10. **Dashboard shows a truncated key prefix.** The ENV chip and `apply.json` show only a truncated environment-key prefix. No full key or token is on screen. Crop if the final policy forbids even prefixes.
11. **Title/end card are still the draft assets.** They are exact 1920×1080, but reuse the placeholder repo and “packaged for upstream contribution” line.
12. **No re-take after the repo path changed.** The terminal content is real but the path in the intro/token command is stale.

## Exact commands used

### Environment (parent shell; values never printed)

~~~sh
cd "/Users/pranav1296/toggle win for sure/experiment-isolation"
set -a
. lab/.env
set +a
export FLAGSMITH_API_URL="$LAB_API_URL"
export FLAGSMITH_API_KEY_localhost_8010="$LAB_ADMIN_API_KEY"
export FLAGSMITH_API_KEY="$LAB_ADMIN_API_KEY"
export FLAGSMITH_ENVIRONMENT_KEY="$LAB_DEV_ENV_KEY"
export DEV_ENV_KEY="$LAB_DEV_ENV_KEY"
~~~

### Terminal take

Command file: `video/commands/draft-lab.txt`.

~~~sh
python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out video/work/draft/audit.json
jq '{verdict, collisions, overlaps: [.overlaps[] | {a, b, jaccard}]}' video/work/draft/audit.json
python3 -m engine.cli plan --audit video/work/draft/audit.json --out video/work/draft/plan.json
jq '{approval_token, segments_to_create: [.segments_to_create[] | {name, operator, value}], audience_changes: [.audience_changes[] | {experiment, from_segment_ids, to_segment}]}' video/work/draft/plan.json
python3 -m engine.cli apply --plan video/work/draft/plan.json --approve "wrong-token" --out video/work/draft/refused.json; echo "exit=$?"
TOKEN=$(jq -r .approval_token video/work/draft/plan.json)
python3 -m engine.cli apply --plan video/work/draft/plan.json --approve "$TOKEN" --out video/work/draft/apply.json
cat video/work/draft/apply.json
python3 -m engine.cli verify --plan video/work/draft/plan.json --samples 500 --out video/work/draft/verify.json
jq '{before_jaccard, after_jaccard, pass, overlaps: (.overlaps | length)}' video/work/draft/verify.json
python3 -m engine.cli receipt --audit video/work/draft/audit.json --plan video/work/draft/plan.json --verify video/work/draft/verify.json --out video/work/draft/receipt.json
jq '{token_count, pass}' video/work/draft/receipt.json
printf 'receipt tokens: '; python3 skill/scripts/token_count.py video/work/draft/receipt.json
~~~

Recorded with:

~~~sh
./video/record_terminal.sh --commands video/commands/draft-lab.txt --out video/captures/draft-terminal.typescript --render --pace 0.5
~~~

The audit command returned 10; the recorder kept going and printed `[exit 10]`. The wrong-token apply also returned 10. No command was edited.

### Verify clarification

~~~sh
jq '{before_jaccard, after_jaccard, pass, pairs_measured: (.overlaps | length), overlapping_pairs: ([.overlaps[] | select(.jaccard > 0)] | length)}' video/work/draft/verify.json
~~~

Recorded to `video/captures/draft-verify.mp4`.

### Intro, architecture, token re-check

~~~sh
ls -l skill/SKILL.md
python3 -m engine.cli --help | head -14
sed -n '/^## Architecture/,/^## 3-minute/p' README.md | head -16

# Re-check at the current path:
python3 skills/experiment-isolation/scripts/token_count.py video/work/draft/receipt.json
# 110
~~~

### Browser captures

Before dashboard: tab `ei-dash-before` at `http://localhost:8022/`, `browse.emulate` viewport 1920×1080, then `browse.recording` start/stop for 10 s.

After dashboard: `video/work/dashboard-after/` contains a copy of `lab/dashboard/index.html` plus same-run `audit/plan/apply/verify/receipt` JSON, served on `:8024`; tab `ei-dash-after`, same emulate/recording flow, 12 s top + 10 s scrolled panel.

Storefront: tab `ei-storefront` at `http://localhost:8020/`, 10 s.

Flagsmith: Playwright Chromium with a temporary logged-in storage state, viewport 1920×1080, recording the experiments list → Pricing banner detail → Onboarding tip detail. The storage state was deleted after recording.

### Narration and build

~~~sh
say -v Samantha -r 150 -o video/work/draft/narration150.aiff -f video/work/draft/narration.txt
ffmpeg -y -i video/work/draft/narration150.aiff -c:a aac -b:a 192k -ar 48000 video/work/draft/narration150.m4a
python3 video/make_captions.py
python3 video/build_draft.py
~~~

## Verification of the file

~~~text
ffprobe: duration 165.700000, 1920x1080, 30/1, h264 High, aac LC 48 kHz mono
volumedetect: mean -16.3 dB, max -1.5 dB
blackdetect: no segments >= 0.6 s
narration: 164.803 s; picture 165.700 s
~~~

## Next steps for the final cut

1. Get verifier sign-off on the same receipt; do not reuse this draft as final.
2. Replace `OWNER` in `video/title.html` and `video/endcard.html`, re-render, rebuild.
3. Re-record the intro and token line with `skills/experiment-isolation/…`.
4. Decide the token headline: receipt file 110 vs phase sum 991 vs harness total (not captured). Follow `docs/token-count.md`.
5. If the final needs the Flagsmith before state, reset the lab and capture both shared audiences before apply.
6. Consider a quiet music bed or a tighter end hold; the current cut has a 0.9 s picture tail after narration.
7. Re-run the 12-item checklist and only then publish.
