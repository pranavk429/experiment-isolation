#!/usr/bin/env python3
"""Count tokens in a JSON file and print one integer.

Uses tiktoken (o200k_base, the project's proxy encoding) when it is
installed. Otherwise falls back to ceil(characters / 4), a documented
estimate, not an exact tokenizer count. Errors go to stderr and exit
non-zero.
"""

import json
import math
import sys
from pathlib import Path


def count_tokens(text: str) -> int:
    """Return an exact tiktoken count when available, else a chars/4 estimate."""
    try:
        import tiktoken  # type: ignore

        encoding = tiktoken.get_encoding("o200k_base")
        return len(encoding.encode(text))
    except Exception:
        return math.ceil(len(text) / 4)


def main(argv: list) -> int:
    if len(argv) != 2:
        print("usage: token_count.py <file.json>", file=sys.stderr)
        return 2

    path = Path(argv[1])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    try:
        json.loads(text)
    except ValueError as exc:
        print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    print(count_tokens(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
