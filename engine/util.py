"""Small shared helpers: JSON IO, errors, token estimates, output."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Optional

EXIT_OK = 0
EXIT_REFUSED = 10
EXIT_ERROR = 20


class EngineError(RuntimeError):
    """Base error for all engine failures."""


class Refusal(EngineError):
    """The operation is unsafe or lacks approval; exit code 10."""


class ConfigError(EngineError):
    """Configuration is missing or invalid; exit code 20."""


def compact_json(value: Any) -> str:
    """Serialize compactly, without whitespace or a trailing newline."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def write_json(path: str, value: Any) -> None:
    """Write compact JSON atomically to *path*."""
    target = Path(path)
    if target.parent and str(target.parent) not in ("", "."):
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(compact_json(value) + "\n", encoding="utf-8")
    tmp.replace(target)


def read_json(path: str) -> Dict[str, Any]:
    """Read a JSON object from *path* with a clear error."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise EngineError("JSON file not found: %s" % path) from exc
    except json.JSONDecodeError as exc:
        raise EngineError("Invalid JSON in %s: %s" % (path, exc)) from exc
    if not isinstance(value, dict):
        raise EngineError("Expected a JSON object in %s" % path)
    return value


def estimate_tokens(value: Any) -> int:
    """Rough token count for compact JSON: four characters per token."""
    return int(math.ceil(len(compact_json(value)) / 4.0))


def emit(payload: Dict[str, Any], out: Optional[str], summary: str) -> None:
    """Write machine JSON to *out* or stdout; human summary to stderr."""
    if out:
        write_json(out, payload)
        location = out
    else:
        sys.stdout.write(compact_json(payload) + "\n")
        location = "stdout"
    sys.stderr.write(summary.rstrip() + " -> " + location + "\n")


def key_prefix(key: str, length: int = 4) -> str:
    """Return a short, non-secret prefix for display."""
    return key[:length] if key else ""
