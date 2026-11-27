# Packaging checklist

Prepared and published on 2026-11-27. The public repository contains source and documentation only; generated video media remains local and is not uploaded.

## Repository setup

- [x] Git repository initialized at `experiment-isolation/`
- [x] Author identity resolved from existing Git config (name `Pranav`); no global config changed
- [x] Initial commit: `723dc2e5a9ece16ef0f519997394abcc531976d1`
- [x] Verified release commit: `3d18fb74f597688a73e68c03e60d25c33b02e2cf` (`Verified release: Experiment Isolation skill, engine, and self-hosted lab`)
- [x] Published `master`; working tree clean after the packaging metadata commit

## Ignore rules (`.gitignore` + nested ignores)

- [x] Secrets: `.env`, `*.key`, `*.pem`
- [x] Dependencies/caches: `node_modules/`, `venv/`, `.venv/`, `__pycache__/`, `.pytest_cache/`
- [x] Generated evidence: `audit.json`, `plan.json`, `apply.json`, `verify.json`, `receipt.json`, `restore-*.json`, `apply-failure.json`
- [x] Lab: `lab/.env`, `lab/audit.json`, `lab/dashboard/audit.json` (plus all generated dashboard JSON via depth-independent patterns)
- [x] Rendered video: `video/renders/*.mp4`, `*.mkv`, `*.webm`
- [x] Nested `lab/.gitignore` covers runtime logs, PIDs, seed state, generated dashboard JSON
- [x] Nested `video/.gitignore` covers `raw/`, `captures/`, `renders/`, and `work/`

## Secret scan

- [x] Extracted 15 distinct non-placeholder values from `~/flagsmith-local/flagsmith.env` and `lab/.env`
- [x] Scanned every staged blob, including binaries; values were never printed
- [x] 0 secret-type values (API keys, tokens, passwords, environment keys) in tracked files
- [x] Secret-type hits occur only in ignored `lab/.env`
- [x] Other matches were non-secret values only (local API URLs, project/organization names, admin email)

## Large files (>5 MB)

All are generated media and are ignored, so none are committed:

| Size | Path |
|---|---|
| 17 MB | `video/renders/draft.mp4` |
| 14 MB | `video/renders/final.mp4` |
| 7.0 MB | `video/work/final/narration.aiff` |
| 6.9 MB | `video/captures/draft-terminal.mp4` |
| 6.9 MB | `video/work/draft/narration150.aiff` |
| 6.5 MB | `video/captures/final/terminal.mp4` |
| 6.4 MB | `video/work/segments/06-terminal.mp4` |
| 5.7 MB | `video/work/draft/narration.aiff` |

The final cut (`video/renders/final.mp4`) is deliberately not uploaded.

## Required content

- [x] `LICENSE`
- [x] `README.md`
- [x] `CONTRACT.md`
- [x] Skill at the new path: `skills/experiment-isolation/SKILL.md`
- [x] `engine/` (stdlib Python package + CLI)
- [x] `lab/` (Docker Compose, storefront, dashboard, seed)
- [x] `tests/` (`tests/engine`, `tests/skill`)
- [x] `docs/`
- [x] `seed/demo_seed.py`, `demo/`, `verification/`, `video/` sources

## Commit contents

- 86 tracked files, approximately 1.42 MiB of source (excluding `.git`)
- No ignored secrets, generated JSON, caches, or video media included
- The final video is deliberately not uploaded

## Published

- [x] Public URL: https://github.com/pranavk429/experiment-isolation
- [x] Visibility: `PUBLIC`
- [x] Default branch: `master`
- [x] Release commit: `3d18fb74f597688a73e68c03e60d25c33b02e2cf`
- [x] HTTP status: `200`
- [x] Video media: not uploaded (ignored by `video/.gitignore`)

Publish command used:

```sh
gh repo create pranavk429/experiment-isolation --public --source . --remote origin --push
```
