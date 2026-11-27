# Experiment Isolation — Live URL Gate

Date: 2026-11-27
Verifier: independent release verifier
Live URL: https://github.com/pranavk429/experiment-isolation
Release commit: 3d18fb74f597688a73e68c03e60d25c33b02e2cf
Published HEAD: ba474d6feb7cb29929e12e85cdf0e59231ab131e
Branch: master

Verdict: **NOT READY TO SUBMIT**

## Summary

The repository is public, the published tree is reachable, both external validators pass, the suite is 93 tests, and the published README/SKILL match the local files byte-for-byte. Two live-artifact gaps prevent a clean gate:

1. The live README and skills/experiment-isolation/SKILL.md do **not contain the repository URL**. The URL exists only in SUBMISSION.md.
2. Two judge-facing docs still say the lab/dashboard is unverified, contradicting the verified README/submission and this gate: docs/judge-qa.md:59 and docs/why-we-win.md:55,65.

These are documentation fixes, not engine failures. Video upload is pending and is not a project blocker.

## Check table

| # | Check | Command | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | Public repo/branch | gh repo view ... --json url,visibility,defaultBranchRef,pushedAt | PUBLIC, master | PUBLIC; master; pushedAt 2026-11-27T07:25:13Z | PASS |
| 2 | Public URL | curl -s -o /dev/null -w '%{http_code}' URL | 200 | 200 | PASS |
| 3 | Local git state | git status --short; git log -1; git remote -v | clean; release; origin | clean at gate start; HEAD ba474d6; 3d18fb7 is parent/release; origin https://github.com/pranavk429/experiment-isolation.git | PASS (HEAD note) |
| 4 | Live README/SKILL match | gh api contents README.md and SKILL.md; diff/hash | identical | SHA-256 identical both files | PASS |
| 5 | Repo URL in live README/SKILL | grep for URL | present | absent in both; only SUBMISSION.md contains it | FAIL |
| 6 | Tracked secrets/media | git ls-files | none | only lab/.env.example (safe template); no .env, .key, state.json, mp4, aiff, mov, webm | PASS (example only) |
| 7 | Tests | pytest tests/engine tests/skill -q | 93 | 93 passed | PASS |
| 8 | Skill validator | Codex + Claude quick_validate.py | valid | both print Skill is valid!; exit 0 | PASS |
| 9 | Docs headline | grep token copy | 121 o200k / 120 cl100k | README/docs/engine use 121/120; internal 107; 429 chars | PASS |
| 10 | 3-way token label | grep 125/124 | stress only | every hit labels 125/124 as 3-way stress, not demo headline | PASS |
| 11 | Docs counts/paths | grep 93/92/54/skill path/under 100 | 93; no stale | 93; no 92/54 or old skill/ path; under-100 only as refused/negated | PASS |
| 12 | SUBMISSION.md | fetch live file | URL + video placeholder | URL present; [PASTE YOUTUBE OR LOOM URL] placeholder; no invented URL | PASS |
| 13 | Lab verified documentation | README/submission | verified | README says reset -> demo -> reset 100% -> 0% -> 100%, HTTP 200, no 409; submission says release gate verified | PASS (README/submission) |
| 14 | File count/large media | live tree; git ls-files | 86; no huge | 86 files; largest 409,373 bytes; no tracked media >1MB | PASS |
| 15 | Video artifact | local video/renders | exists or not | video/renders/final.mp4 exists (14,919,984 bytes); not tracked; YouTube/Loom upload pending | PASS (pending upload) |
| 16 | Lab-unverified conflict | grep judge-qa/why-we-win | consistent | docs/judge-qa.md:59 and docs/why-we-win.md:55,65 still call lab/dashboard unverified | FAIL |
| 17 | Compatibility leftovers | grep compatibility | none | references/troubleshooting.md:49 still says See compatibility in SKILL.md; judge-qa/why-we-win say pending compatibility trim though validator passes | FAIL (minor) |

## Exact publication facts

- URL: https://github.com/pranavk429/experiment-isolation
- Visibility: PUBLIC; default branch: master
- Pushed at: 2026-11-27T07:25:13Z
- Published HEAD: ba474d6feb7cb29929e12e85cdf0e59231ab131e (Record published release metadata)
- Release commit: 3d18fb74f597688a73e68c03e60d25c33b02e2cf (Verified release: Experiment Isolation skill, engine, and self-hosted lab)
- ba474d6 differs from 3d18fb7 only in PACKAGING.md and video/build_final.py.
- Live tree: 86 files. Test suite: 93 passed (55 engine + 38 skill).
- Receipt headline: 121 o200k / 120 cl100k, 429 chars, internal 107; 3-way stress 125/124 only.
- SUBMISSION.md: repo URL plus video placeholder; video/renders/final.mp4 exists locally and is untracked.
- Tracked secret check: only lab/.env.example matches the broad .env regex; no real .env, key, state, or media is tracked.

## Blockers

### MAJOR (documentation) — Repo URL absent from live README and SKILL

The live README and skills/experiment-isolation/SKILL.md match local byte-for-byte, but neither contains https://github.com/pranavk429/experiment-isolation. SUBMISSION.md has it. Add the URL to README (and optionally the skill compatibility/setup text), commit, push, and re-fetch.

### MAJOR (documentation) — Live docs still say the lab is unverified

docs/judge-qa.md:59 says the verifier did not verify the lab or dashboard and the one-command claim is unverified. docs/why-we-win.md:55,65 repeat it and say to label the lab unverified. README and docs/submission.md now document the verified reset -> demo -> reset gate. This is a direct judge-facing contradiction; update the two stale docs and push.

### MINOR — Compatibility leftovers

skills/experiment-isolation/references/troubleshooting.md:49 still says “See compatibility in SKILL.md,” but the field was removed. docs/judge-qa.md:27 and docs/why-we-win.md:53 still say “pending the compatibility trim,” though the validators pass and full SKILL is now 1,550 o200k (body 1,477). Update these phrases.

## Residual risks

- Live README/SKILL URL gap is a publication-quality issue, not an engine failure.
- Lab-unverified text in judge-qa/why-we-win could make a judge doubt Track 3 despite the verified README/submission.
- Video upload is pending; final.mp4 exists locally and is not tracked. Upload is not a project blocker.
- No tracked secrets or large media found; local lab/.env remains mode 600 and ignored.
- The published HEAD includes a metadata-only commit after the release commit; both README/SKILL are identical at both refs.

## Required before submission

1. Add the repo URL to live README and SKILL.
2. Remove/replace the “lab unverified” statements in docs/judge-qa.md and docs/why-we-win.md.
3. Remove the stale “pending compatibility trim” and troubleshooting compatibility reference.
4. Commit and push; re-fetch live README/SKILL and confirm the URL and verified-lab text.
5. Upload the video; then the project is submission-ready.
