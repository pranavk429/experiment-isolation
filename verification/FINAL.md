# FINAL — Authoritative token measurement

Date: 2026-11-27 (UTC 06:31)
Target: local Flagsmith `:8000`, Development environment (project 1)
Run: 2-way draft collision pair, skill-default 500 samples, threshold 0.05, verify `--workers 2`
Result: PASS — audit collision (exit 10) → plan → apply → verify isolated (0.0)

## Authoritative number

**121 tokens (tiktoken `o200k_base`) / 120 tokens (`cl100k_base`) for the 2-way `receipt.json` produced with `--apply apply.json`; 429 characters excluding the trailing newline (430 bytes on disk); engine internal estimate 107.**

This is the receipt file only. It is not the harness total, not the sum of the five per-phase estimates, and not the skill-body cost. Passing `--apply` adds `"apply":697` instead of `"apply":0`; it did not cross a token boundary, so the measured receipt remains 121/120.

## Command transcript summary

| # | Command (abridged) | Exit | Result |
|---|---|---:|---|
| 1 | `python3 seed/demo_seed.py --experiments 2` | 0 | Reused drafts 49/50; `created_now=false`, `started=false` |
| 2 | `python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json` | **10** | 6 experiments, 15 collision pairs, sample 500, verdict `collision`; draft pair 49/50 Jaccard 1.0, shared 250/250, multi-exposed 0.76, max exposure 6, risk `critical` |
| 3 | `python3 -m engine.cli plan --audit audit.json --out plan.json` | 0 | `feasible=true`, width 50, ranges [0,49]/[50,99], segments 7/8 reused, blocked running 1–4, token `iso-99625c70`, before Jaccard 1.0 |
| 4 | `python3 -m engine.cli apply --plan plan.json --approve "iso-99625c70" --out apply.json` | 0 | 2 experiments running; 6 steps; segments created 0 / reused 2; `approval_token_verified=true`; `pass=true` |
| 5 | `python3 -m engine.cli verify --plan plan.json --samples 500 --workers 2 --out verify.json` | 0 | before 1.0 → after 0.0; multi 0.76 → 0.0; pair 49/50 `isolated`, shared 0, union 500; enrolled 234/266; `pass=true` |
| 6 | `python3 -m engine.cli receipt --audit audit.json --plan plan.json --apply apply.json --verify verify.json --out receipt.json` | 0 | before `collision` → after `isolated`; `pass=true`; 4 changes; 14 remaining environment collisions; rollback pointer `["restore 49,50"]` |
| 7 | `python3 skills/experiment-isolation/scripts/token_count.py receipt.json` | 0 | **121** |
| 8 | tiktoken 0.12.0 direct, `o200k_base` / `cl100k_base` | 0 | **121 / 120**; 429 chars; internal estimate 107 |
| 9 | `python3 -m pytest tests/engine -q` | 0 | **54 passed** |
| 10 | `python3 -m unittest discover -s tests/skill` | 0 | **38 tests, OK** |
| 11 | `python3 -m pytest tests/engine tests/skill -q` | 0 | **92 passed** |
| 12 | `python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/experiment-isolation` | **1** | **FAIL**: `Unexpected key(s) in SKILL.md frontmatter: compatibility. Allowed properties are: allowed-tools, description, license, metadata, name` |
| 13 | `python3 seed/demo_seed.py --experiments 2 --reset` | 0 | Deleted applied 49/50; created clean drafts **51/52**, `created`, audience [4], `started=false` |
| 14 | `python3 seed/demo_seed.py --experiments 2` (idempotence check) | 0 | Reused 51/52; `created_now=false`, `started=false` |

Raw JSON lives in `/var/folders/7m/p85t2ft12ts2spdd0cr1t5mh0000gn/T/final-measure/` (`audit.json`, `plan.json`, `apply.json`, `verify.json`, `receipt.json`, plus a `receipt-noapply.json` comparison). No generated JSON was written into the repository.

## Exact receipt

```json
{"product":"experiment-isolation","environment":"Development","scope":"planned_experiments","sample_size":500,"before":{"verdict":"collision","max_jaccard":1.0,"multi_exposed_rate":0.76},"after":{"verdict":"isolated","max_jaccard":0.0,"multi_exposed_rate":0.0},"changes":4,"token_count":{"audit":802,"plan":852,"apply":697,"verify":96,"receipt":107},"remaining_environment_collisions":14,"rollback":["restore 49,50"],"pass":true}
```

| Measure | Value |
|---|---:|
| `token_count.py` (tiktoken `o200k_base`) | **121** |
| tiktoken 0.12.0 `o200k_base` direct | **121** |
| tiktoken 0.12.0 `cl100k_base` direct | **120** |
| Characters, no trailing newline | **429** |
| Bytes on disk (includes trailing newline) | **430** |
| Receipt's internal estimate (`token_count.receipt`) | **107** |
| Sample size | 500 |
| `changes` | 4 |
| `remaining_environment_collisions` | 14 |
| `pass` | true |

The no-`--apply` receipt is 427 chars / 428 bytes and also measures 121 o200k / 120 cl100k; it is not the submission receipt because it reports `apply:0`.

### Standalone artifact sizes (not the receipt count)

| Artifact | Bytes | Chars | o200k | cl100k | Engine estimate embedded in receipt |
|---|---:|---:|---:|---:|---:|
| `audit.json` | 3,209 | 3,208 | 1,106 | 1,103 | 802 |
| `plan.json` | 3,409 | 3,408 | 821 | 796 | 852 |
| `apply.json` | 2,787 | 2,786 | 645 | 631 | 697 |
| `verify.json` | 385 | 384 | 139 | 137 | 96 |
| `receipt.json` | 430 | 429 | **121** | **120** | 107 |

The five engine estimates (802 + 852 + 697 + 96 + 107 = 2,554) are `ceil(compact_chars/4)` values computed when the receipt was built. They are not tiktoken counts and are not the receipt's token count. The five standalone artifacts total 2,832 o200k / 2,787 cl100k. Adding the measured `SKILL.md` body (1,477 o200k / 1,473 cl100k) gives 4,309 / 4,260, excluding any rollback artifact (none was run in this measurement).

## What the receipt count includes and excludes

**Includes** — the entire compact `receipt.json` file as read by `token_count.py`:

- `product`, `environment`, `scope=planned_experiments`, `sample_size=500`
- `before` and `after` verdicts, `max_jaccard`, `multi_exposed_rate`
- `changes=4`
- The `token_count` object with five integer estimates for the audit, plan, apply, verify, and receipt artifacts (`802, 852, 697, 96, 107`)
- `remaining_environment_collisions=14`
- The compact rollback pointer `["restore 49,50"]`
- `pass=true`

**Excludes:**

- The full `audit.json`, `plan.json`, `apply.json`, and `verify.json` contents. They appear only as the five integer estimates above; the receipt does not embed them.
- `SKILL.md` body (1,477 o200k / 1,473 cl100k) and its `references/` files.
- Agent harness/system prompt, conversation history, tool-call arguments, tool results, command stdout/stderr, retries, and human narration.
- Any rollback artifact and the 3-way run (not repeated here).
- The harness total. The submission form's harness total remains `TODO`; the receipt is a separate measured artifact.

## Stale token claims — files and lines

The measured headline is **still 121 / 120**. Lines that quote 121 need no numeric replacement; they are confirmed. The following lines are numerically or factually stale and must change.

### Must change (stale numbers)

| File:line | Current claim | Required |
|---|---|---|
| `docs/token-count.md:52` | `SKILL.md` body = 1,267 | **1,477** |
| `docs/token-count.md:61` | full `SKILL.md` = 1,401; body = 1,267 | **1,611** full / **1,477** body |
| `docs/token-count.md:94` | body 1,267; full file 1,401 | **1,477** / **1,611** |
| `docs/token-count.md:8,59,107,116` | "Verified subtotal: 2,944 tokens" | Recompute. For this run's six artifacts (skill body + audit + plan + apply + verify + receipt) it is **4,309** o200k, excluding rollback; do not patch to 4,309 without matching the chosen run and adding rollback if the table keeps it. |
| `README.md:161` | internal estimate 108/109 | **107** for the 2-way receipt; 3-way not re-measured |
| `docs/judge-qa.md:27` | internal estimate 108–109 | **107** (2-way) |
| `docs/judge-qa.md:75` | "108–109 internal estimate" | **107** (2-way) |
| `docs/why-we-win.md:53` | internal estimate 108–109; 54+34 = 88 tests | **107** (2-way); **92 tests = 54 engine + 38 skill** |
| `docs/token-count.md:69` | internal estimate 108/109 | **107** (2-way) |
| `docs/submission.md:99` | internal estimate 108/109 | **107** (2-way) |
| `CONTRACT.md:184` | "`receipt` is under 100 tokens of JSON" | Not true. Use **121 actual** (`o200k_base`), target **≤125**; keep the "do not claim under 100" warning. |
| `engine/README.md:199,227` | "429 chars, estimate 108" | **429 chars, estimate 107** |
| `video/DRAFT.md:30,43,51,57,60,129,165`; `video/make_captions.py:17` | old receipt = **110** tokens | **121** (out of scope; do not edit video) |
| `verification/REPORT.md:17,41,82,149` | old 110/114 and 109/113 | Historical; superseded by 121/120. Do not reuse. |
| `verification/REPORT2.md:51` | validator PASS | Actual `quick_validate.py` exits 1 on the `compatibility` frontmatter key. |

### Confirmed — 121 / 120, no numeric change

The 121 component on these lines is confirmed. Where the same line also contains 108/109 or 125, those components are covered in the stale table above or the 3-way note below.

- `README.md:32,80,155`
- `docs/judging-map.md:29,33,55`
- `docs/token-count.md:57,69,100,110,117`
- `docs/demo-script.md:119`
- `docs/submission.md:28,99`
- `docs/judge-qa.md:27`
- `docs/why-we-win.md:53`
- `engine/README.md:199,227`

### 125 / 124 (3-way) — not re-measured

These lines refer to the 3-way run. Do not change 125 to 121; re-measure a 3-way receipt if the submission will quote it. If only the 2-way number is submitted, label 125/124 as 3-way-only or drop it.

- `README.md:32,155,161`
- `docs/token-count.md:61,69,100,110,117`
- `docs/judging-map.md:29,33,55`
- `docs/judge-qa.md:27`
- `docs/why-we-win.md:53`
- `docs/demo-script.md:119`
- `docs/submission.md:28,99`
- `engine/README.md:200,238`

### Skill text — accurate, optional tightening

- `skills/experiment-isolation/SKILL.md:92`, `references/safety.md:59`, `references/troubleshooting.md:61` say "roughly 100-125 tokens" and "do not claim under 100". Both are true at 121. No mandatory change; if desired, add "measured 121 (o200k) / 120 (cl100k)".
- `docs/demo-script.md:3` contains "110%" (browser zoom), not a token claim; ignore.

## Tests and validator

| Check | Result |
|---|---|
| Engine tests `pytest tests/engine -q` | **54 passed** |
| Skill tests `unittest discover -s tests/skill` | **38 tests, OK** |
| Combined `pytest tests/engine tests/skill -q` | **92 passed** |
| External skill validator `quick_validate.py skills/experiment-isolation` | **exit 1** — `compatibility` is not an allowed frontmatter key (allowed: `allowed-tools, description, license, metadata, name`) |

The project's own skill contract tests (38) pass, including the required `compatibility` field, apply-inclusive receipt command, token-claim honesty, and rollback recipe. The installed Codex skill-creator validator rejects that field. This is a schema mismatch between the skill and the validator, not a test failure; no edit was made to `SKILL.md`.

## Final state (after reset)

| Item | State |
|---|---|
| Experiments 1–4 | **running**, unchanged: 1 `[]` 100%; 2 `[4]` 100%; 3 `[4]` 100%; 4 `[7]` 100% |
| Drafts | **51 Express checkout**, **52 Discount badge** — `created`, audience `[4]` (`us_mobile`), rollout 100%, not started |
| Segments | Exactly 4: **2** `half_users`, **4** `us_mobile`, **7** `exp_bucket_a`, **8** `exp_bucket_b` |
| Extra segments from this run | **None.** Plan/apply reused 7/8; `segments.created=[]`, `segments.reused=[7,8]`. Reset created none. |
| Experiments 49/50 | Deleted by the reset; replaced by 51/52. Docs that hard-code 49/50 are ID-stale: `README.md:74`; `docs/demo-script.md:15,18,27,37,41`. Generalize to "two drafts" or update to 51/52. |
| Synthetic identities | Remain (audit/verify persisted traits); documented behavior, not a segment or experiment. |
| Repository writes | Only this `verification/FINAL.md`. Raw artifacts are in the temp directory above. |

## Bottom line

**Authoritative submission number: 121 tokens under `o200k_base` (120 under `cl100k_base`) for the 2-way receipt with `--apply`; 429 characters, internal estimate 107. Use 121, not 110, 115, or 125; 125/124 is the separate 3-way figure and was not re-measured here.**
