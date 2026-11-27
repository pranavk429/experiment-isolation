# Security Cleanup — Lab Key Material

Date: 2026-11-27
Scope: leaked-key copies in `/tmp` and the `experiment-isolation/` repository. The main `~/flagsmith-local` instance was not touched. No source code was changed; only `lab/.env` was edited, for credential rotation.

## Result

| Item | Status |
|---|---|
| Flagged `/tmp` files | Removed; confirmed absent |
| Other `/tmp` copies | None found |
| Repo matches for leaked values | 0 |
| Lab admin API key | Rotated; old key revoked |
| Running lab | Unaffected (all services healthy) |

## 1. Files removed

| Path | Size | Observed contents | Disposition |
|---|---|---|---|
| `/tmp/lab_envs.json` | 1515 B | Flagsmith environment-list JSON with 3 environment records, each containing a 22-character environment API key | Deleted |
| `/tmp/lab_devkey` | 22 B | One 22-character environment API key; matched the Development key in the JSON above | Deleted |

Both files had mtime 10:19 and were removed with `rm -f`. Neither path exists now, and `lsof` shows no process holding either deleted file open.

No key values were printed, copied into this report, or passed on a command line. Matching was done in-memory.

## 2. /tmp sweep

- A full scan of `/private/tmp` (510 regular files, files up to 50 MB) for the exact values from both flagged files found only those same two paths. No additional copies were present.
- After removal, `/private/tmp` was re-scanned for the current lab's credential values (admin key plus Development and Production environment keys): 0 matches outside `lab/.env`.
- The harness temp directory was included in the sweep.

## 3. Repository scan

- 182 files under `experiment-isolation/` were scanned for the exact leaked values, excluding `.git`, `node_modules`, `__pycache__`, `.venv`, and `venv`.
- Matches: **0**. No trace of the leaked values in source, docs, tests, skills, logs, or verification artifacts.
- The current lab credentials appear only in `lab/.env`, which is gitignored and mode 600.

## 4. Admin key rotation

- Created a replacement organisation master API key through the lab API (`POST /api/v1/organisations/<org>/master-api-keys/`, HTTP 201).
- Verified the new key authenticates (`GET /api/v1/organisations/`, HTTP 200).
- Updated the three matching entries in `lab/.env` — `LAB_ADMIN_API_KEY`, `FLAGSMITH_API_KEY`, and `FLAGSMITH_API_KEY_localhost_8010` — using an atomic replace. File mode remains 600; all 20 expected variables are present and non-empty.
- Revoked the old key with `DELETE /api/v1/organisations/<org>/master-api-keys/<prefix>/` (HTTP 204). One master key remains, and the new key still authenticates (HTTP 200).
- The running lab did not depend on the admin key: Flagsmith, task processor, and Postgres stayed healthy; storefront health and dashboard both returned 200.

## 5. Environment keys

The captured JSON contained **3** environments, while the current lab has **2** (Development and Production), and the captured values do not match the current `lab/.env` environment keys. The captures (10:19) therefore appear to predate the current lab volume (containers and `.env` were created around 11:33–11:37), so the leaked environment keys are stale for this lab and were not rotated. Rotating the live environment keys would also require updating and restarting the storefront, and was unnecessary for the current credentials.

If the captured keys came from the separate `:8000` research instance, that instance was outside this cleanup's scope and was not touched; its owner should verify and rotate there.

## 6. Residual risk

- The deleted files may remain in free disk blocks or local backups; no secure-erase guarantee is claimed on APFS.
- No secret values are recorded in this document or in any repo artifact.
