# Experiment Isolation Lab

A **one-command, self-hosted Flagsmith starter + developer tool** that makes
overlapping A/B audiences visible before they contaminate a readout.

Two draft experiments deliberately target the same `us_mobile` segment. The lab
measures the overlap, shows a collision matrix, then the isolation workflow
splits the audience with the stable integer trait
`flagsmith_experiment_bucket` (0–49 / 50–99). The dashboard shows the measured
before/after.

This is the Track 3 artefact for **Experiment Isolation**. The same repository
contains the Flagsmith Agent Skill in `skill/` and the CLI engine in `engine/`.

---

## What is in the lab

| Path | Purpose |
|---|---|
| `lab/docker-compose.yml` | Flagsmith + Postgres + task processor, experimentation on, ports 8010/8011 |
| `lab/bootstrap.py` | Admin user, org, project, Development/Production, Postgres warehouse, admin API key |
| `lab/seed/seed.py` | Idempotent two features, two variants, metric, `us_mobile` segment, two draft experiments |
| `lab/storefront/` | Stdlib Python storefront on 8020; evaluates flags through the SDK/edge API with `flagsmith_experiment_bucket` |
| `lab/dashboard/` | Static single-page overlap matrix on 8022; no build step |
| `lab/run.sh` | One command for Compose, bootstrap, seed, audit, servers, URLs |
| `demo/README.md` | Three-minute demo path |

The existing Flagsmith instance on **8000/8001 is never touched**. The lab uses
its own Compose project, network, volume, and ports.

---

## Prerequisites

- Docker with Compose v2 and at least 4 GB allocated to Docker.
- Python **3.9+** (stdlib only; no pip installs).
- Free ports **8010**, **8011**, **8020**, **8022**.
- `curl` (used by the runner's health checks).

Verified against Flagsmith **2.291.0**. The Compose file pulls
`docker.flagsmith.com/flagsmith/flagsmith:latest` like the official starter; the
lab was tested with the image reporting 2.291.0.

---

## One-command run

```bash
cd "experiment-isolation"
bash lab/run.sh
```

On a first run the image pull can take a few minutes. The runner then:

1. Starts the isolated `isolation-lab` Compose project.
2. Waits for `/health/liveness/` and checks `migrate-db` exited 0.
3. Bootstraps the admin, organisation, project, Development/Production, and
   the Postgres warehouse connections.
4. Seeds two 50/50 features, the `Purchase` metric, the `us_mobile` segment,
   and two **draft** experiments with the same audience.
5. Generates `lab/dashboard/audit.json` with `python3 -m engine.cli audit`.
   If the engine CLI is not present yet, it writes a visibly labelled
   **sample** audit instead (see below).
6. Starts the storefront and dashboard and prints every URL.

Rerunning `bash lab/run.sh` is safe after a demo or rollback: it detects active
experiments for the two lab features, pauses/removes conflicting ones (including
`[rollback]` drafts), deletes stale `exp_iso_*` segments, and recreates the two
clean drafts sharing `us_mobile`. No HTTP 409 and no manual reset are required.

### URLs

| Service | URL |
|---|---|
| Flagsmith dashboard / API | http://localhost:8010 |
| Flagsmith task processor | http://localhost:8011 |
| Storefront | http://localhost:8020 |
| Overlap dashboard | http://localhost:8022 |

### Admin login

The admin email is `admin@isolation-lab.local`. The generated password is stored
in `lab/.env` (mode 600, gitignored). Load the credentials without printing
them:

```bash
source lab/.env
echo "$LAB_ADMIN_EMAIL"        # email only
# do not echo $LAB_ADMIN_PASSWORD or $LAB_ADMIN_API_KEY in a demo
```

The same file contains `LAB_DEV_ENV_KEY`, `LAB_ADMIN_API_KEY`,
`FLAGSMITH_API_URL`, `FLAGSMITH_API_KEY_localhost_8010`, and `DEV_ENV_KEY` so
the engine CLI and Flagsmith CLI work against the lab.

---

## What the seed creates

- Features `pricing_banner` and `onboarding_tip`, each with a control value and
  one variant (`urgent` / `short`), 50% allocation.
- Metric `Purchase` (occurrence, direction up).
- Segment `us_mobile`: `country = US AND platform = mobile`.
- Draft experiments **Pricing banner** and **Onboarding tip**, both with a 100%
  rollout and audience `[us_mobile]`.

They are left in `status=created` intentionally. Flagsmith only allows a draft
experiment to change its audience; the isolation workflow needs that. The
engine's audit recognises drafts and reports the overlap as `basis: "projected"`.

To start them early and make live enrollment measurable:

```bash
python3 lab/seed/seed.py --start
```

Running experiments cannot be retargeted without pausing or recreating them.

---

## See the collision

Open **http://localhost:8022** (the runner serves the directory; opening
`index.html` as a `file://` URL will block the dashboard's `fetch` of
`audit.json`). With a fresh lab you should see:

- Verdict: **Audiences collide**
- Max Jaccard: **100%**
- Matrix cell E1/E2: **100%**, shared 250 / union 250
- Both experiment cards marked **draft**, sharing segment 1
- Before → after: 100% before, after not measured yet

The storefront at http://localhost:8020 evaluates the same two flags for a
synthetic identity. Try `demo-us-mobile-001`, `demo-gb-mobile-002`, or
`demo-us-desktop-003`. Each response includes the stable bucket:

```bash
curl -s "http://localhost:8020/api/evaluate?identifier=demo-us-mobile-001&country=US&platform=mobile" | python3 -m json.tool
```

The public API never returns keys. The synthetic identity's traits are persisted
in the local Flagsmith database, which is expected.

---

## Run the isolation workflow (before → after)

The runner has an explicit local demo command:

```bash
bash lab/run.sh demo
```

It runs `audit → plan → apply (with the plan's approval token) → verify →
receipt` against the lab, then leaves the server-rendered dashboard showing:

- Hero: **Audiences isolated**, 0% max Jaccard
- Matrix: the **before snapshot** (100%), clearly labelled
- Before → after: **100% → 0%**, 100 points removed
- Evidence: `receipt.json` loaded, pass true, changes 4, rollback steps

Prefer the individual commands? Use the exact engine contract:

```bash
source lab/.env

python3 -m engine.cli audit \
  --env "$LAB_DEV_ENV_KEY" --samples 500 --threshold 0.05 \
  --out lab/dashboard/audit.json

python3 -m engine.cli plan \
  --audit lab/dashboard/audit.json --out lab/dashboard/plan.json

TOKEN=$(python3 -c 'import json; print(json.load(open("lab/dashboard/plan.json"))["approval_token"])')
python3 -m engine.cli apply \
  --plan lab/dashboard/plan.json --approve "$TOKEN" \
  --out lab/dashboard/apply.json

python3 -m engine.cli verify \
  --plan lab/dashboard/plan.json --samples 500 \
  --out lab/dashboard/verify.json

python3 -m engine.cli receipt \
  --audit lab/dashboard/audit.json --plan lab/dashboard/plan.json \
  --verify lab/dashboard/verify.json --out lab/dashboard/receipt.json
```

Refresh http://localhost:8022 after the loop. The dashboard reads
`receipt.json` and `verify.json` from its own directory; no build step.

> The demo is explicitly local and destructive to the **lab** state only. It
> creates the bucket segments, disables/changes/re-enables the draft audiences,
> starts the experiments, and writes rollback commands into `apply.json`.

To return to the initial collision for a repeat demo, use the one-command
reset (it wipes the volume and rebuilds the clean baseline):

```bash
bash lab/run.sh reset
```

`bash lab/run.sh` is also a convergence command. If a previous demo or rollback
left **running** experiments, `[rollback]` drafts, or `exp_iso_*` segments, the
seed pauses/removes the conflicting experiments, removes the stale bucket
segments, and recreates the two clean drafts sharing `us_mobile`. That is why
rerunning it does not hit the HTTP 409 "active experiment already exists"
error. The exact repeatable cycle is:

```bash
bash lab/run.sh reset          # collision baseline
bash lab/run.sh demo           # isolated + receipt
bash lab/run.sh                # converge back to collision without wiping
bash lab/run.sh reset          # or wipe + rebuild in one command
```

---

## Expected `audit.json` shape

The dashboard only needs the engine contract's minimum shape:

```json
{
  "environment": {"id": 1, "name": "Development", "key_prefix": "Qr5e"},
  "sample_size": 500,
  "threshold": 0.05,
  "experiments": [
    {"id": 1, "name": "Pricing banner", "feature": "pricing_banner",
     "status": "created", "audience_segment_ids": [1], "rollout_percentage": 100}
  ],
  "overlaps": [
    {"a": 1, "b": 2, "shared": 250, "union": 250, "jaccard": 1.0,
     "a_rate": 0.5, "b_rate": 0.5, "verdict": "collision"}
  ],
  "collisions": [[1, 2]],
  "verdict": "collision",
  "sample_traits": ["country", "platform", "flagsmith_experiment_bucket"]
}
```

The current engine also adds `project_id`, `enrolled`, and `basis`, and may
report `verdict: "clear"` for an isolated audit. The dashboard treats `clear`
as `isolated` and ignores unknown fields. Optional evidence files:

- `verify.json`: `before_jaccard`, `after_jaccard`, `pass`, `overlaps`.
- `receipt.json`: `before`, `after`, `changes`, `token_count`, `rollback`, `pass`.

### If the engine CLI is not ready

`lab/run.sh` degrades gracefully:

- `engine.cli` missing or the audit fails → writes
  `lab/dashboard/audit.json` from `lab/seed/seed_state.json` with
  `_meta.source = "sample"` and a visible **SAMPLE DATA** chip.
- Engine **exit code 10** (refusal / needs approval) is treated as a successful
  audit when it wrote valid JSON. That is the expected verdict for a collision;
  only exit 20 or invalid JSON triggers the sample fallback.
- `STRICT_AUDIT=1 bash lab/run.sh` disables the fallback and fails instead.
- `bash lab/run.sh sample` regenerates the sample on demand.
- `lab/dashboard/audit.sample.json` is a committed fixture for a dashboard-only
  dry run; serve it as `audit.json` or copy it into place.

---

## Reuse the lab

The intended reuse is a starter, not a one-off demo:

1. Copy `lab/` into a project.
2. Change `name:` in `docker-compose.yml` and the four host ports if needed.
3. Run `bash lab/run.sh`. Bootstrap and seed are idempotent by name.
4. Point the dashboard at any producer's `audit.json`; it only needs the shape
   above. No bundler or server-side code is required.
5. Use `lab/bootstrap.py --api-url http://host:port` for another local Flagsmith
   instance. The sequence follows the official coding-agent guide:
   `/auth/users/` → `/organisations/` → `/projects/` → `/environments/` →
   `/warehouse-connections/` → `/master-api-keys/`.

`lab/seed/seed.py` is self-contained and idempotent. At build time
`seed/demo_seed.py` delegates to `engine.seed`, which hardcodes metric 1,
segment 4, and the research feature names; it therefore targets the existing
research instance rather than a fresh lab. The lab keeps its own seed and does
not require the engine seed. The engine's audit remains the producer of the
measured/projected file.

Configuration knobs:

| Variable | Default | Meaning |
|---|---|---|
| `LAB_API_URL` | `http://localhost:8010` | Flagsmith host |
| `STOREFRONT_PORT` | `8020` | Storefront |
| `DASHBOARD_PORT` | `8022` | Static dashboard |
| `SAMPLES` | `500` | Audit sample size |
| `THRESHOLD` | `0.05` | Max allowed Jaccard |
| `STRICT_AUDIT` | `0` | Set to 1 to forbid the sample fallback |

The Storefront and dashboard bind to `127.0.0.1`. Docker publishes 8010/8011
on the host; do not expose them beyond your machine with the default secrets.

---

## Safety and teardown

- **Local only.** The Compose file uses default development secrets, a local
  Postgres volume, and the Flagsmith-database warehouse. It is not a production
  deployment. Change every secret before exposing it.
- **No secrets in git.** `lab/.env` is mode 600 and ignored; `lab/.gitignore`
  also ignores runtime evidence. Bootstrap never prints a key.
- **Explicit approval.** `apply` only runs with the plan's approval token.
  `bash lab/run.sh` does not apply changes; `bash lab/run.sh demo` does, and is
  clearly labelled. The engine refuses unsafe running-experiment changes.
- **Synthetic identities persist** in the local database. `reset` deletes them
  with the volume.
- **Destructive reset** removes the lab volume, `.env`, seed state, and runtime
  audit/evidence files, then **rebuilds the clean two-draft baseline** so one
  command recovers the demo. Add `--wipe-only` to leave it stopped and empty.
  The committed `audit.sample.json` is untouched.

```bash
bash lab/run.sh down                 # stop, keep the Postgres volume and .env
bash lab/run.sh reset                # wipe + rebuild clean collision baseline
bash lab/run.sh reset --wipe-only    # wipe and leave it stopped
```

Logs:

```bash
docker compose -p isolation-lab -f lab/docker-compose.yml ps -a
docker compose -p isolation-lab -f lab/docker-compose.yml logs --tail=80 migrate-db flagsmith
tail -n 40 lab/.storefront.log lab/.dashboard.log
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Port 8010/8011 is already in use` | Another stack is on the port. Stop it; the existing 8000/8001 instance is intentionally untouched. |
| `Docker is not running` | Start Docker Desktop. Allocate at least 4 GB. |
| Health check times out | `docker compose ... logs --tail=80 migrate-db flagsmith`. Check Docker memory. |
| Warehouse status is not `connected` | Ensure `EXPERIMENTATION_ENABLED=true` and `USE_POSTGRES_FOR_ANALYTICS=true`; recreate with `reset`. |
| `Flagsmith already has users` and no `.env` | Restore `lab/.env` or `bash lab/run.sh reset` for a fresh lab. |
| Dashboard says `SAMPLE DATA` | The engine CLI is missing or the audit failed. Run `bash lab/run.sh audit`; see `lab/.audit.err`. |
| Dashboard has no before/after | Run `plan`, `apply`, `verify`, `receipt` (or `bash lab/run.sh demo`); refresh the page. |
| Experiments are running and cannot be retargeted | Rerun `bash lab/run.sh` (it pauses/removes and recreates clean drafts), or `bash lab/run.sh reset` for a full wipe + rebuild. |
| `HTTP 409` / "active experiment already exists" | Rerun `bash lab/run.sh`; the seed repairs rollback/running leftovers. If it still fails, `bash lab/run.sh reset`. |

---

## Track 3 mapping

- **Self-hosted Flagsmith:** real Compose stack with Postgres, task processor,
  experimentation, and the Postgres warehouse connection.
- **Integrations and developer tools:** idempotent bootstrap/seed, edge-evaluated
  storefront, pairwise overlap dashboard, one-command runner, documented JSON
  contract.
- **Easy reuse:** isolated Compose project, configurable ports, stdlib-only
  scripts, static dashboard with no build step, and a sample fallback so the
  UI is usable before the engine lands.

Limitations, stated honestly: this is a local playground, not a production
deployment; the storefront is synthetic traffic; the dashboard is a static reader
of JSON produced by the engine, not a statistics package; the Flagsmith-database
warehouse mode is for evaluation, not load testing.
