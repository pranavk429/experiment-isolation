# Flagsmith API reference

Verified against local Flagsmith 2.291.0. Base URL: `${FLAGSMITH_API_URL}`. The bundled engine separates CLI evaluation from direct HTTP calls:

- **CLI (`sampling.py`):** Synthetic trait persistence and Flagsmith evaluation run `flagsmith evaluate --identity <id> --persist --json --trait ...`.
- **Stdlib HTTP (`api.py`):** `AdminAPI` (`Authorization: Api-Key`) and `EdgeAPI` (`X-Environment-Key`) use Python `urllib.request` for strict HTTP status checks, pagination, and read-back verification. Credentials never enter `argv`, files, or chat. The engine never calls `flagsmith api`.

This page is for review and debugging.

## Discovery and endpoints

| Purpose | Endpoint |
|---|---|
| List / resolve projects | `GET /api/v1/projects/` |
| Environment detail | `GET /api/v1/environments/{env_key}/` |
| List experiments | `GET /api/v1/environments/{env_key}/experiments/` |
| Experiment detail | `GET /api/v1/environments/{env_key}/experiments/{id}/` |
| List segments | `GET /api/v1/projects/{project_pk}/segments/` |
| Segment detail / create / delete | `GET/POST/DELETE /api/v1/projects/{project_pk}/segments/{id}/` |
| Identity flags and traits (`EdgeAPI`) | `GET /api/v1/identities/?identifier=<urlencoded>` |

`audit` inspects all non-completed experiments (`created`, `paused`, `running`), not only running ones. It emits compact fields only (including `basis`, `enrolled`, and `audience_has_percentage_split`). Do not print raw experiment or identity payloads.

`plan` performs read-only `AdminAPI` GETs for the project, segments, and rollout snapshots; it makes no writes and is not offline.

## Audience constraints

- `audience.segment_ids` has `maxItems: 1`; use one segment per experiment.
- No condition in that segment may use `PERCENTAGE_SPLIT`. The server rejects it with `Audience segment N contains a percentage split`.
- Disable the rollout before changing the audience, or the server rejects it with `Cannot change the audience while the rollout is enabled and serving traffic. Disable the rollout first.`
- A running or paused experiment cannot change its audience. Apply only to pre-launch drafts (`status: created`); pause is not an isolation step.
- Variant `percentage_allocation` is fine; it splits variants inside the enrolled audience, not the audience itself.

## Experiment payloads

Create (the engine supplies real IDs from the audit; never invent them):

```json
{"feature":3,"name":"Pricing banner","hypothesis":"Urgent banner increases purchase.","metrics":[{"metric":1,"expected_direction":"increase"}],"experiment_rollout":{"enabled":true,"rollout_percentage":100,"feature_state_value":{"type":"string","value":"control"},"multivariate_feature_state_values":[{"multivariate_feature_option":2,"percentage_allocation":50}],"audience":{"match":"any","segment_ids":[4]}}}
```

`audience.match` is `any` (or `all`); with one segment they are equivalent.

Rollout patch: `PATCH /api/v1/environments/{env_key}/experiments/{id}/rollout/`

```json
{"enabled":false,"rollout_percentage":100,"feature_state_value":{"type":"string","value":"control"},"multivariate_feature_state_values":[{"multivariate_feature_option":2,"percentage_allocation":50}],"audience":{"match":"any","segment_ids":[7]}}
```

`apply` disables first (`"enabled": false`), patches the audience, verifies both via read-back GETs, then calls `POST .../start/` (which re-enables the rollout and moves status to `running`). Do not pause as an isolation step; a paused audience is immutable. Complete with `POST .../complete/`.

## Bucket and composed targeting segments

Create segments via `POST /api/v1/projects/{project_pk}/segments/`.

Untargeted bucket segment (`exp_iso_<lo>_<hi>`, e.g. `exp_iso_0_49`):

```json
{"name":"exp_iso_0_49","project":1,"rules":[{"type":"ALL","rules":[],"conditions":[{"operator":"LESS_THAN","property":"flagsmith_experiment_bucket","value":"50"}]}]}
```

Composed segment (`exp_iso_<slug>_<lo>_<hi>`, e.g. `exp_iso_us_mobile_0_49`) when colliding drafts share non-empty base targeting (for example `us_mobile`):

```json
{"name":"exp_iso_us_mobile_0_49","project":1,"rules":[{"type":"ALL","rules":[],"conditions":[{"operator":"EQUAL","property":"country","value":"US"},{"operator":"EQUAL","property":"platform","value":"mobile"},{"operator":"LESS_THAN","property":"flagsmith_experiment_bucket","value":"50"}]}]}
```

- Request and response use the field name `property`; use that spelling consistently.
- When drafts already target base segment rules (e.g., `country=US`, `platform=mobile`), `plan` extracts those non-bucket rules and composes them under `ALL` with the bucket range `[lo, hi]`, so non-target users are never widened into the experiment. Nested or multi-branch base rules are preserved under `"rules"` inside the top-level `ALL` group.
- For N planned experiments in a collision component, `plan` creates N contiguous inclusive ranges over 0-99: 2-way uses `[0,49]` (`LESS_THAN 50`) and `[50,99]` (`GREATER_THAN_INCLUSIVE 50`, `LESS_THAN 100`); 3-way uses `[0,32]`, `[33,65]`, `[66,99]`. Ranges keep widths balanced and cover 0-99 exactly.
- `apply` reuses an existing project segment when its canonical base rules and 0-99 bucket coverage semantically match `[lo, hi]`.
- `flagsmith_experiment_bucket` is an integer string 0-99 derived from `int(sha256(identifier)[0:8], 16) % 100`; it is stable across runs, not random per evaluation.
- Never use `PERCENTAGE_SPLIT` or a key-hash condition as a substitute.
- A missing trait does not satisfy numeric conditions. Persist the trait on every sampled identity first.
- Segment IDs referenced by an experiment audience must belong to the same project.

## Enrollment metadata

`sampling.py` skips CLI invocation when `EdgeAPI` confirms all expected traits already match, otherwise persists traits and triggers evaluation via the Flagsmith CLI, then reads back via `EdgeAPI`:

```sh
flagsmith evaluate --identity <id> --persist --json --trait country=US --trait platform=mobile --trait flagsmith_experiment_bucket=<0-99>
```

Read-back uses `EdgeAPI` (`GET /api/v1/identities/?identifier=<urlencoded-id>` with `X-Environment-Key`).

Count measured enrollment only from `flags[].metadata.experiment.in_experiment == true` for the experiment's feature. Absent metadata is not evidence of enrollment and must not be fabricated. Flagsmith does not report this for drafts (`status: created`); `audit` labels draft enrollment `projected` from segment rules and `rollout_percentage`. After `apply` starts them, `verify` recomputes enrollment as `measured`. Do not present projected counts as live traffic.

## Rollback and cleanup

Rollback is engine-owned (`scripts/run.sh` works standalone from any installed skill copy; `python3 -m engine.cli` works when installed or with `PYTHONPATH`):

```sh
bash scripts/run.sh rollback --apply apply.json --out rollback.json
# or: python3 -m engine.cli rollback --apply apply.json --out rollback.json
```

Read `rollback.json`:
- If a target experiment is still `status: created`, `rollback` restores its original audience and rollout state in place (`live_restore: true`, `requires_recreate: false`).
- If a target experiment is already `running` or `paused` (e.g., started during `apply`), Flagsmith forbids editing its audience in place: `rollback` pauses if running, deletes it, and creates a new draft (`[rollback]`) with the prior audience (`live_restore: false`, `requires_recreate: true`, `new_experiment_id`). Report this honestly; never claim a live in-place rollback.
- Newly created segments are deleted only if all experiment rollbacks succeed.

Never hand-roll a `flagsmith api` or `curl` PATCH/DELETE recipe to restore audiences or segments. Synthetic sampled identities persist unless `--cleanup` is passed to `audit` or `verify`; use a disposable environment for demos.
