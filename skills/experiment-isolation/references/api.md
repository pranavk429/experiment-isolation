# Flagsmith API reference

Verified against local Flagsmith 2.291.0. Base URL: `${FLAGSMITH_API_URL}`. Read-only discovery uses `flagsmith api <path>`; engine-owned writes call AdminAPI directly, so credentials never enter argv, files, or chat. This page is for review and debugging.

## Discovery

| Purpose | Endpoint |
|---|---|
| List experiments | `GET /api/v1/environments/{env_key}/experiments/` |
| Experiment detail | `GET /api/v1/environments/{env_key}/experiments/{id}/` |
| List segments | `GET /api/v1/projects/{project_pk}/segments/` |
| Identity flags | `GET /api/v1/identities/?identifier=<urlencoded>` |
| Projects | `GET /api/v1/projects/` |

The audit lists all non-completed experiments (`created`, `paused`, `running`), not only running ones. It reports compact fields only (the contract fields plus `basis`, `enrolled`, and `audience_has_percentage_split`). Do not print raw experiment or identity payloads.

Plan performs read-only GETs for project, segments, and rollout snapshots; it makes no writes.

## Audience constraints

- `audience.segment_ids` has `maxItems: 1`; exactly one segment per experiment.
- No condition in that segment may use `PERCENTAGE_SPLIT`. The server rejects it with `Audience segment N contains a percentage split`.
- Disable the rollout before changing the audience, or the server rejects it with `Cannot change the audience while the rollout is enabled and serving traffic. Disable the rollout first.`
- A running or paused experiment cannot change its audience. Apply only to pre-launch experiments; pause is not an isolation step.
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

Disable first, patch the audience, then re-enable with the same body and `"enabled": true`. Start with `POST .../start/`; complete with `POST .../complete/`. Do not pause as an isolation step; a paused audience is immutable.

## Bucket segments

Create one segment per range: `POST /api/v1/projects/{project_pk}/segments/`

```json
{"name":"exp_iso_0_49","rules":[{"type":"ALL","conditions":[{"operator":"LESS_THAN","property":"flagsmith_experiment_bucket","value":"50"}]}]}
```

- Request and response use the field name `property`; use that spelling consistently.
- Two-way split: `LESS_THAN 50` = buckets 0-49; `GREATER_THAN_INCLUSIVE 50` = 50-99.
- For N planned experiments, create N contiguous ranges over 0-99. A 3-way plan uses `[0,32]`, `[33,65]`, `[66,99]`; keep widths balanced and cover 99 exactly.
- `flagsmith_experiment_bucket` is an integer string 0-99 derived from `sha256(identifier)[0:8] % 100`; it is stable, not random per evaluation.
- Never use `PERCENTAGE_SPLIT` or a key-hash condition as a substitute.
- A missing trait does not satisfy numeric conditions. Persist the trait on every sampled identity first.
- Segment IDs referenced by an experiment audience must belong to the same project.

## Enrollment metadata

Persist traits, then read back:

```sh
flagsmith evaluate <feature> --identity <id> --trait country=US --trait platform=mobile --trait flagsmith_experiment_bucket=<0-99> --persist --json
flagsmith api "api/v1/identities/?identifier=<urlencoded-id>"
```

Count measured enrollment only from `flags[].metadata.experiment.in_experiment == true` for the experiment's feature. Absent metadata is not evidence of enrollment and must not be fabricated. Flagsmith does not report this for drafts; the engine labels draft enrollment `projected` from segment rules. After apply/start, `verify` recomputes it as measured. Do not present projected counts as traffic.

## Rollback and cleanup

Rollback is engine-owned. Use:

```sh
python3 -m engine.cli rollback --apply apply.json --out rollback.json
```

Read `rollback.json`. If it reports `requires_recreate`, the started experiment must be completed/deleted and recreated; do not claim a live rollback. Never hand-roll a `flagsmith api` PATCH/DELETE recipe to restore audiences or segments.

Synthetic sampled identities remain; use a disposable environment for demos.
