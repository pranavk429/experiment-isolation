"""Small shared helpers: JSON IO, env parsing, errors, secret redaction."""

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
    tmp = target.with_name(f"{target.name}.tmp")
    tmp.write_text(f"{compact_json(value)}\n", encoding="utf-8")
    tmp.replace(target)


def read_json(path: str) -> Dict[str, Any]:
    """Read a JSON object from *path* with a clear error."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise EngineError(f"JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EngineError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EngineError(f"Expected a JSON object in {path}")
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
        sys.stdout.write(f"{compact_json(payload)}\n")
        location = "stdout"
    sys.stderr.write(f"{summary.rstrip()} -> {location}\n")


def key_prefix(key: str, length: int = 4) -> str:
    """Return a short, non-secret prefix for display."""
    return key[:length] if key else ""


def sanitize_text(text: str, *secrets: str, limit: int = 400) -> str:
    """Strip secret strings, collapse whitespace, and clamp output length."""
    clean = text
    for secret in secrets:
        if secret:
            clean = clean.replace(secret, "<redacted>")
    return " ".join(clean.split())[:limit]


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse export KEY=value lines from *path* without mutating os.environ."""
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if name:
            values[name] = value
    return values
