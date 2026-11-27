# Experiment Isolation — build contract

This is the single source of truth for all build agents. Read it fully before writing code.

## Product

**Experiment Isolation** is a Flagsmith Agent Skill that prevents overlapping A/B experiments from contaminating each other.

One-liner: *Before you launch another experiment, prove its audience does not overlap with experiments already running — or make it disjoint, with human approval.*

It must:
1. Discover non-completed experiments in one Flagsmith environment.
2. Sample identities and measure actual experiment enrollment.
3. Compute pairwise audience overlap and a collision verdict.
4. Refuse to launch when overlap exceeds a threshold.
5. Design disjoint audiences using a stable integer trait `flagsmith_experiment_bucket` (0–99) split into ranges.
6. Apply with explicit approval: disable rollout → set audience segment → re-enable → start.
7. Verify overlap is 0% after the change.
8. Emit a compact JSON receipt with before/after overlap, sample size, changes, rollback commands, and token counts.

Track 4 is the primary submission. The same repo also contains a self-hosted **Experiment Isolation Lab** for Track 3 (Docker Compose + seeded storefront + overlap dashboard).

## Non-negotiable constraints (verified on local Flagsmith 2.291.0)

- `MAX_AUDIENCE_SEGMENTS = 1`: an experiment audience can contain exactly one segment.
- An audience segment **must not contain a PERCENTAGE_SPLIT condition**. The API returns: "Audience segment N contains a percentage split".
- Audience changes require disabling the rollout first: "Cannot change the audience while the rollout is enabled and serving traffic. Disable the rollout first."
- A running experiment cannot change its audience. The skill must refuse to modify running experiments unless the operator explicitly pauses and accepts a restart.
- Enrollment is exposed per identity at `metadata.experiment.in_experiment` when traits are persisted.
- Disjoint segments must use trait rules, e.g. `flagsmith_experiment_bucket LESS_THAN 50` and `GREATER_THAN_INCLUSIVE 50`.
- Experiment create payload:
  `{"feature":<id>,"name":"...","hypothesis":"...","metrics":[{"metric":<id>,"expected_direction":"increase"}],"experiment_rollout":{"enabled":true,"rollout_percentage":100,"feature_state_value":{"type":"string","value":"control"},"multivariate_feature_state_values":[{"multivariate_feature_option":<variant id>,"percentage_allocation":50}],"audience":{"match":"any","segment_ids":[<segment id>]}}}`
- Rollout patch: `PATCH /api/v1/environments/{env_key}/experiments/{id}/rollout/` with the same rollout object, `enabled:false` while changing the audience.
- Start: `POST /api/v1/environments/{env_key}/experiments/{id}/start/`.
- Admin API calls need the CLI's credentials; use `flagsmith api <path>` so the key never enters argv.

## Local Flagsmith instance

```sh
source ~/flagsmith-local/flagsmith.env
export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"
```

Available variables: `FLAGSMITH_API_URL`, `FLAGSMITH_API_KEY_localhost_8000`, `FLAGSMITH_PROJECT`, `FLAGSMITH_ORGANISATION`, `DEV_ENV_KEY`, `PROD_ENV_KEY`, `SERVER_ENV_KEY`, `ADMIN_TOKEN`.

Rules:
- Never print or commit a key/token.
- Do not delete the existing features/experiments/segments created during research.
- Use only the local instance, never Cloud.
- The dashboard is `http://localhost:8000`.

## Repository layout and ownership

Root: `/Users/pranav1296/toggle win for sure/experiment-isolation`

| Path | Owner | Contents |
|---|---|---|
| `engine/**` | Engine agent | Python package + CLI, stdlib only (Python 3.9) |
| `tests/engine/**` | Engine agent | pytest/unittest tests |
| `seed/demo_seed.py` | Engine agent | creates two draft collision experiments for the demo |
| `skill/**` | Skill agent | SKILL.md, references/, scripts/ wrappers |
| `tests/skill/**` | Skill agent | frontmatter/trigger/contract tests |
| `lab/**` | Lab agent | Docker Compose, storefront, dashboard, seed reuse |
| `demo/**` | Lab agent | runnable demo assets |
| `README.md`, `docs/**` | Docs agent | submission README, demo script, form answers |
| `verification/**` | Verifier | only evidence and bug reports; do not modify other files |

No agent may edit another owner's files. If a cross-cutting fix is needed, write it in your own report and tell the orchestrator.

## Engine CLI contract (must be implemented exactly)

All commands print a compact human summary to stderr and machine JSON to stdout (or to `--out`). Exit codes: 0 = success, 10 = refusal/needs approval, 20 = error.

```sh
python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json
python3 -m engine.cli plan --audit audit.json --out plan.json
python3 -m engine.cli apply --plan plan.json --approve "<approval-token>" --out apply.json
python3 -m engine.cli verify --plan plan.json --samples 500 --out verify.json
python3 -m engine.cli receipt --audit audit.json --plan plan.json --verify verify.json --out receipt.json
```

### audit.json (minimum schema)

```json
{
  "environment": {"id": 1, "name": "Development", "key_prefix": "QUcE"},
  "sample_size": 500,
  "threshold": 0.05,
  "experiments": [
    {"id": 2, "name": "Pricing banner", "feature": "pricing_banner", "status": "running", "audience_segment_ids": [4], "rollout_percentage": 100},
    {"id": 3, "name": "Onboarding tip", "feature": "onboarding_tip", "status": "running", "audience_segment_ids": [4], "rollout_percentage": 100}
  ],
  "overlaps": [
    {"a": 2, "b": 3, "shared": 500, "union": 500, "jaccard": 1.0, "a_rate": 1.0, "b_rate": 1.0, "verdict": "collision"}
  ],
  "collisions": [[2, 3]],
  "verdict": "collision",
  "sample_traits": ["country", "platform", "flagsmith_experiment_bucket"]
}
```

### plan.json (minimum schema)

```json
{
  "threshold": 0.05,
  "segments_to_create": [
    {"name": "exp_iso_0_49", "trait": "flagsmith_experiment_bucket", "operator": "LESS_THAN", "value": "50"},
    {"name": "exp_iso_50_99", "trait": "flagsmith_experiment_bucket", "operator": "GREATER_THAN_INCLUSIVE", "value": "50"}
  ],
  "audience_changes": [
    {"experiment_id": 2, "from_segment_ids": [4], "to_segment_ids": [7], "requires_rollout_disable": true},
    {"experiment_id": 3, "from_segment_ids": [4], "to_segment_ids": [8], "requires_rollout_disable": true}
  ],
  "approval_token": "iso-<8 hex>",
  "rollback": [
    "flagsmith api api/v1/environments/$DEV_ENV_KEY/experiments/2/rollout/ -X PATCH --input restore-2.json",
    "delete created segments 7 and 8"
  ],
  "notes": ["running experiments must be paused or recreated before their audience can change"]
}
```

### verify.json

```json
{"sample_size": 500, "before_jaccard": 1.0, "after_jaccard": 0.0, "pass": true, "overlaps": []}
```

### receipt.json

```json
{
  "product": "experiment-isolation",
  "environment": "Development",
  "sample_size": 500,
  "before": {"verdict": "collision", "max_jaccard": 1.0},
  "after": {"verdict": "isolated", "max_jaccard": 0.0},
  "changes": 4,
  "token_count": {"audit": 0, "plan": 0, "apply": 0, "verify": 0, "receipt": 0},
  "rollback": ["..."],
  "pass": true
}
```

## Sampling requirements

- Build a deterministic sample of synthetic identities from a trait matrix. Default population: 50% US/mobile, 30% GB/mobile, 20% US/desktop.
- Each identity gets a stable `flagsmith_experiment_bucket` = int(sha256(identifier)[0:8], 16) % 100.
- Persist traits with `flagsmith evaluate <feature> --identity <id> --trait ... --persist --json`, then read `GET /api/v1/identities/?identifier=...` and inspect `metadata.experiment.in_experiment`.
- Do not fabricate enrollment; measure it.
- Cleanup: document that synthetic identities remain in the environment; provide a `--cleanup` note or use a disposable environment.

## Skill requirements (Track 4)

- `skill/SKILL.md` frontmatter: `name: experiment-isolation`, description <= 1024 chars with trigger phrases ("run another experiment", "overlapping experiments", "mutual exclusion", "experiment collision", "isolate experiments").
- Body < 500 lines, target ~1.2k tokens; progressive disclosure via `references/`.
- `skill/scripts/` wrappers call the engine CLI; no business logic duplication.
- Safety: audit is read-only by default; apply requires the plan's approval token; running experiments are refused; include rollback.
- Token efficiency: read only compact JSON, never raw experiment payloads; include a token-count helper.

## Lab requirements (Track 3)

- `lab/docker-compose.yml`: Flagsmith + Postgres + experimentation enabled, local ports 8010/8011 to avoid clashing with the existing instance.
- `lab/storefront/`: a tiny app (Python stdlib or Flask; prefer stdlib to avoid deps) with two features and experiment enrollment; serves a page and an API.
- `lab/dashboard/`: a single-page HTML/JS overlap matrix reading an audit JSON; no build step.
- `lab/seed/`: creates the two colliding draft experiments using `seed/demo_seed.py`.
- One-command demo in `lab/README.md`.

## Docs requirements

- Root `README.md`: problem, what it does, 3-minute demo path, setup, how Flagsmith is used, token count, test commands, limitations, license.
- `docs/demo-script.md`: 0:00–2:45 beat-by-beat.
- `docs/submission.md`: exact answers for the Track 4 form (what the skill does, CLI commands, safety, agent/model tested, token count) and Track 3 form.
- Do not overclaim; label simulated traffic.

## Acceptance tests

1. `python3 -m pytest tests/engine -q` passes.
2. `audit` against the local instance produces at least two experiments and a collision with jaccard >= 0.9.
3. `plan` produces two bucket segments and audience changes.
4. `apply --approve <token>` creates the segments, disables/changes/re-enables audiences, starts the experiments.
5. `verify` reports after_jaccard == 0.0 and pass true.
6. `receipt` is <=125 actual tokens under `o200k_base` (measured 121) and includes a rollback pointer.
7. `skill/SKILL.md` validates against the Agent Skills frontmatter rules.
8. The lab starts with one command and shows the overlap matrix.

## Quality bar

- Type hints, docstrings, explicit error handling, no secrets in logs.
- Stdlib only for the engine (urllib, json, subprocess, hashlib, argparse).
- No destructive commands against production; local only.
- Every command must be idempotent or refuse safely.

## Reporting

Return under 200 words: files created, commands run, test results, blockers. Do not paste large logs.
