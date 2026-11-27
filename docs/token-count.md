# Token Counting Methodology

`skills/experiment-isolation/scripts/token_count.py` provides deterministic token accounting for JSON artifacts produced by the isolation workflow.

## How `token_count.py` Counts Tokens

- **CLI helper (`token_count.py <file.json>`):** Validates JSON syntax and prints one integer. When `tiktoken` is installed, it encodes the exact file text using `o200k_base`; when `tiktoken` is absent, it falls back to `ceil(len(text) / 4)`.
- **In-engine estimate (`util.estimate_tokens`):** Keeps the core `engine` package dependency-free by computing `ceil(len(compact_json(value)) / 4)` for each artifact inside `receipt.json`'s `token_count` block (`audit`, `plan`, `apply`, `verify`, `receipt`).

```sh
python3 skills/experiment-isolation/scripts/token_count.py receipt.json
```

## Measured Values

Verified with `tiktoken` (`o200k_base` and `cl100k_base`) against Flagsmith `2.291.0`:

| Artifact / Scope | `o200k_base` | `cl100k_base` | Engine `ceil(chars/4)` | Notes |
|---|---:|---:|---:|---|
| `SKILL.md` body (after frontmatter) | `1,210` | `1,212` | `1,211` | `78` total lines (`4,841` body chars) |
| `SKILL.md` full file | `1,304` | `1,306` | `1,339` | `5,353` full chars |
| 2-way `receipt.json` (with `--apply`) | `121` | `120` | `106` | `426` bytes; workflow artifact estimates sum `1,563` |
| 3-way `receipt.json` (with `--apply`) | `123` | `122` | `107` | `429` bytes; workflow artifact estimates sum `2,186` |

## Three Distinct Token Scopes

1. **Skill context (`SKILL.md` body):** Only the Markdown body after the YAML frontmatter loads when the skill activates (`1,210` `o200k_base` tokens). Reference files (`references/api.md`, `safety.md`, `troubleshooting.md`) load on demand only when troubleshooting or checking API/safety details.
2. **Compact receipt (`receipt.json`):** Targets `<= 125` tokens (`121` `o200k_base` / `120` `cl100k_base` measured for a 2-way isolated run with `--apply`). Contains compact verdict deltas (`before`/`after` Jaccard and multi-exposure rate), change count, rollback hint, and the five `ceil(chars/4)` artifact estimates—never raw API payloads.
3. **Workflow artifacts vs. harness session total:**
   - **Workflow artifacts:** Full `audit.json`, `plan.json`, `apply.json`, `verify.json`, and `receipt.json` files remain on disk; agents inspect only compact summary keys (`verdict`, `collisions`, `approval_token`, `pass`) and the final receipt.
   - **Harness session total:** The complete `input + output` token usage exported from the agent harness for a recorded run (with cache-read tokens reported separately). Never substitute the `receipt.json` count for the harness session total.

## What Is Included vs. Excluded

| Item | Compact Receipt | Workflow Footprint | Harness Session Total |
|---|:---:|:---:|:---:|
| Receipt summary + 5 integer estimates | Included | Included | Included |
| `SKILL.md` body (on activation) | Excluded | Included | Included |
| Full artifact JSON / CLI stderr summaries read by model | Excluded | Only read fields | Included |
| System prompt, tool call arguments, model replies, retries | Excluded | Excluded | Included |
| Cache-read / cache-write tokens | Excluded | Excluded | Report separately |
| Unopened repo files, Flagsmith logs, Docker builds, browser UI | Excluded | Excluded | Excluded |
