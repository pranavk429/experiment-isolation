# Packaging checklist

Prepared for submission on 2026-11-27. This repo is local only: no remote, push, or publish has been performed.

## Repository setup

- [x] Git repository initialized at `experiment-isolation/`
- [x] Author identity resolved from existing Git config (name `Pranav`); no global config changed
- [x] Single initial commit: `Experiment Isolation: agent skill, engine, and self-hosted lab`
- [x] Working tree clean after commit

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
- [x] Scanned all text files; values were never printed
- [x] 0 secret-type values (API keys, tokens, passwords, environment keys) in tracked files
- [x] Secret-type hits occur only in ignored `lab/.env`
- [x] Other matches were non-secret values only (local API URLs, project/organization names, admin email)

## Large files (>5 MB)

All are generated media and are ignored, so none are committed:

| Size | Path |
|---|---|
| 17 MB | `video/renders/draft.mp4` |
| 6.9 MB | `video/captures/draft-terminal.mp4` |
| 6.9 MB | `video/work/draft/narration150.aiff` |
| 6.4 MB | `video/work/segments/06-terminal.mp4` |
| 5.7 MB | `video/work/draft/narration.aiff` |

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

- 74 tracked files, approximately 1.4 MiB of source (excluding `.git`)
- No ignored secrets, generated JSON, caches, or large media included

## Pending publish (NOT run)

```sh
gh repo create pranavk429/experiment-isolation --public --source . --remote origin --push
```

Run from the repository root only after final human review. This command creates the public remote, adds `origin`, and pushes the commit.
