# Token count — method and measured values

Track 4 requires a token count for the demo run. This document defines what is counted, records the verified numbers, and leaves only the full harness total to fill after the recorded session.

## Two numbers, one headline

1. **Harness total (headline, TODO).** Input + output tokens reported by the agent harness for the recorded session: system prompt, conversation, tool calls, tool results, retries. This is the form number.
2. **Measured artifacts (supporting, filled).** Tokens in the skill body and the JSON artifacts the agent reads or writes, measured with the helper and `tiktoken` `o200k_base`. Verified subtotal: **2,944 tokens**.

If the harness cannot export usage, say so and report the measured artifacts as a labelled floor. Do not present the floor as the harness total.

## Demo-run boundary

**Included:** the session from the first `audit` command at 0:30 through the receipt at 2:25, plus the `SKILL.md` and any `references/` file loaded before the first command.

**Excluded:** lab startup before recording, Docker image pulls, browser rendering, Flagsmith server logs, human keystrokes, terminal paint, and any file the agent never read. If a command was retried on camera, count both attempts.

## What is counted

| Item | Included? | Why |
|---|---|---|
| `skills/experiment-isolation/SKILL.md` body loaded by the agent | Yes | It is the skill's always-on context cost. |
| `skills/experiment-isolation/references/` files actually opened | Yes | Progressive disclosure only helps if opened files are counted. |
| `audit.json`, `plan.json`, `apply.json`, `verify.json`, `receipt.json`, `rollback.json` as read by the agent | Yes | These are the tool results the model sees. |
| Command stdout/stderr summaries | Yes, harness total only | The agent reads them to decide the next step. |
| Tool-call arguments and model replies | Yes, harness total only | They are part of the harness total. |
| System prompt and conversation history | Yes, harness total only | Real cost, not attributable to the skill alone. |
| Cache-read or cache-write tokens | Report separately | Hiding them overstates efficiency. |
| Flagsmith server logs, Docker pulls, browser paint | No | Not model input. |
| Files present in the repo but never opened | No | They did not enter context. |
| The human's spoken narration | No | Not model tokens. |

The helper is at `skills/experiment-isolation/scripts/token_count.py`. It takes one JSON file and prints one integer, using `o200k_base` when tiktoken is installed and a documented chars/4 estimate otherwise:

```sh
python3 skills/experiment-isolation/scripts/token_count.py receipt.json
```

## Measure the artifacts

```sh
for f in audit.json plan.json apply.json verify.json receipt.json rollback.json; do
  printf '%s ' "$f"
  python3 skills/experiment-isolation/scripts/token_count.py "$f"
done
```

Verified 2-way run:

| Artifact | `o200k_base` tokens |
|---|---:|
| `SKILL.md` body | 1,267 |
| `audit.json` | 240 |
| `plan.json` | 563 |
| `apply.json` | 447 |
| `verify.json` | 139 |
| `receipt.json` | 121 |
| `rollback.json` | 167 |
| **Measured artifacts subtotal** | **2,944** |

The full `SKILL.md` file is 1,401 tokens; the body loaded after frontmatter is 1,267. The 3-way receipt is 125 tokens. The helper's `o200k_base` count is the project proxy, not necessarily the runtime model tokenizer; label it as a proxy.

## Receipt size

```sh
python3 skills/experiment-isolation/scripts/token_count.py receipt.json
```

Verified receipt: **121 tokens** (2-way) and **125** (3-way) under `o200k_base`; **120** and **124** under `cl100k_base`. The internal engine estimate is 108/109. The old 100-token budget is exceeded. Do not claim the receipt meets that budget.

## Harness total

Export the session usage from the harness used for the recording and sum input + output:

- **OpenCode:** the exported session JSON; sum the per-message `tokens.input` and `tokens.output` fields.

Recorded run identity:

```text
Harness: OpenCode general subagent
Model: DeepSeek V4.1 Flash 1017 (provider opencode-go)
Date: 2026-11-27
Commit SHA: not recorded (no git metadata)
Sample size: 500 (2-way); 100 (3-way)
Harness total: TODO
```

If the harness reports cached input separately, record fresh input, cache read, and output. The headline is fresh input + output; cache read is reported in the notes.

## Fill-in table

| Component | Source | `o200k_base` tokens | In harness total? | Notes |
|---|---|---:|---|---|
| `SKILL.md` body | measured | 1,267 | Yes | Full file is 1,401. |
| References opened | measured | — | Yes | Not separately recorded. |
| `audit.json` | measured | 240 | Yes | Compact JSON. |
| `plan.json` | measured | 563 | Yes | Token and rollback reference. |
| `apply.json` | measured | 447 | Yes | Mutation record. |
| `verify.json` | measured | 139 | Yes | Before/after proof. |
| `receipt.json` | measured | 121 / 125 | Yes | 2-way / 3-way; 120/124 cl100k. |
| `rollback.json` | measured | 167 | Yes | 2-way verified rollback. |
| Command summaries | harness | — | Yes | Not separately measured. |
| Tool-call arguments | harness | — | Yes | Not separately measured. |
| Model replies | harness | — | Yes | Not separately measured. |
| System prompt / context | harness | — | Headline only | Not attributable to the skill. |
| Retries | harness | — | Headline only | Count every attempt used. |
| **Measured artifacts subtotal** | sum | **2,944** | — | Excludes harness-only rows and any references. |
| **Harness total (headline)** | harness usage | **TODO** | — | Form number. |
| Cache read | harness | — | No | Report separately. |
| **Receipt only** | measured | **121 / 125** | — | 2-way / 3-way. |

## Reporting template

```text
Demo-run token count: TODO (harness total: input + output)
Measured artifacts subtotal: 2,944 (o200k_base)
Receipt size: 121 (2-way) / 125 (3-way) o200k_base; 120/124 cl100k_base
Harness/model/date: OpenCode general subagent / DeepSeek V4.1 Flash 1017 / 2026-11-27
Cache read: not reported
Method: docs/token-count.md
```

Do not round down, do not omit retries, and do not substitute the receipt size for the demo-run total. The form asks for the demo run; the receipt is a separate check.
