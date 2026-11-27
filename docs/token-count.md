# Token count — method and authoritative values

Track 4 requires a token count for the demo run. The headline is the 2-way demo receipt: **121 tokens under `o200k_base` / 120 under `cl100k_base`**, 429 characters, internal engine estimate 107. Only the full harness total remains to be filled after the recorded session.

## Headline

| Measure | Value |
|---|---:|
| 2-way demo receipt, `o200k_base` | **121** |
| 2-way demo receipt, `cl100k_base` | **120** |
| Receipt characters (no trailing newline) | **429** |
| Receipt internal estimate (`token_count.receipt`) | **107** |
| 3-way stress-test receipt | 125 / 124 — **not the demo headline** |

The receipt includes its summary plus five integer artifact estimates (audit 802, plan 852, apply 697, verify 96, receipt 107). It does **not** include the full artifacts, the skill body, or harness context. The five estimates sum to 2,554 and are `ceil(chars/4)` values, not tiktoken counts.

## What is counted

| Item | Included? | Why |
|---|---|---|
| `skills/experiment-isolation/SKILL.md` body | Separate | Always-on skill context; measured below. |
| `audit.json`, `plan.json`, `apply.json`, `verify.json`, `receipt.json` as read by the agent | Separate | Tool results the model sees. |
| Command stdout/stderr summaries | Harness total only | The agent reads them to decide the next step. |
| Tool-call arguments and model replies | Harness total only | Part of the harness total. |
| System prompt and conversation history | Harness total only | Real cost, not attributable to the skill. |
| Cache-read or cache-write tokens | Report separately | Hiding them overstates efficiency. |
| Flagsmith server logs, Docker pulls, browser paint | No | Not model input. |
| Files present in the repo but never opened | No | They did not enter context. |

The receipt itself is the compact JSON file read by `token_count.py`; it does not embed the full upstream artifacts.

## Measure the receipt

The helper is at `skills/experiment-isolation/scripts/token_count.py`. It takes one JSON file and prints one integer, using `o200k_base` when tiktoken is installed and a documented chars/4 estimate otherwise:

```sh
python3 skills/experiment-isolation/scripts/token_count.py receipt.json
# 121
```

The 2-way demo receipt was produced with `--apply apply.json`. Dropping `--apply` reports `"apply":0`; it does not change the measured 121/120 at these sizes.

## Standalone artifact sizes

Authoritative 2-way measurement (500 samples, `--workers 2` verify):

| Artifact | Bytes | `o200k_base` | `cl100k_base` | Receipt estimate |
|---|---:|---:|---:|---:|
| `audit.json` | 3,209 | 1,106 | 1,103 | 802 |
| `plan.json` | 3,409 | 821 | 796 | 852 |
| `apply.json` | 2,787 | 645 | 631 | 697 |
| `verify.json` | 385 | 139 | 137 | 96 |
| `receipt.json` | 430 | **121** | **120** | 107 |
| **Five artifacts** | — | **2,832** | **2,787** | 2,554 |

The skill body is **1,477 `o200k_base`** after the portability fix (full `SKILL.md` 1,550; both external validators pass). Adding it to the five standalone artifacts gives **4,309 `o200k_base`** / **4,260 `cl100k_base`**, excluding a rollback artifact (none was run in this measurement).

The tracked **2,944** subtotal is the pre-portability figure (1,267 body plus a rollback artifact); the current measured sum is **4,309**. If the skill body changes, re-measure and update both numbers.

## Harness total

Export the session usage from the harness used for the recording and sum input + output. For OpenCode, export the session JSON and sum the per-message `tokens.input` and `tokens.output` fields.

Recorded run identity:

```text
Harness: OpenCode general subagent
Model: DeepSeek V4.1 Flash 1017 (provider opencode-go)
Date: 2026-11-27
Commit SHA: not recorded (no git metadata)
Sample size: 500 (2-way); 100 (3-way stress)
Harness total: TODO
```

If the harness reports cached input separately, record fresh input, cache read, and output. The headline is fresh input + output; cache read is reported in the notes.

## Fill-in table

| Component | Source | `o200k_base` | In harness total? | Notes |
|---|---|---:|---|---|
| `SKILL.md` body | measured | 1,477 | Separate | Full file 1,550. |
| `audit.json` | measured | 1,106 | Separate | Full artifact. |
| `plan.json` | measured | 821 | Separate | Full artifact. |
| `apply.json` | measured | 645 | Separate | Full artifact. |
| `verify.json` | measured | 139 | Separate | Full artifact. |
| `receipt.json` | measured | 121 | Separate | Demo headline; 120 cl100k. |
| Rollback artifact | — | — | — | Not run in this measurement. |
| Command summaries | harness | — | Yes | Not separately measured. |
| Tool-call arguments | harness | — | Yes | Not separately measured. |
| Model replies | harness | — | Yes | Not separately measured. |
| System prompt / context | harness | — | Headline only | Not attributable to the skill. |
| Retries | harness | — | Headline only | Count every attempt used. |
| **Skill + five artifacts** | sum | **4,309** | — | Excludes harness-only rows and rollback. |
| **Harness total (headline)** | harness usage | **TODO** | — | Form number. |
| Cache read | harness | — | No | Report separately. |

## Reporting template

```text
Demo-run receipt: 121 o200k_base / 120 cl100k_base (429 chars; internal 107)
3-way stress receipt: 125 / 124 (not the demo headline)
Skill body + five artifacts: 4,309 o200k_base (skill body 1,477; full 1,550)
Harness total: TODO (input + output)
Harness/model/date: OpenCode general subagent / DeepSeek V4.1 Flash 1017 / 2026-11-27
Cache read: not reported
Method: docs/token-count.md
```

Do not substitute the receipt size for the harness total. The form asks for the demo run; the receipt is a separate check.
