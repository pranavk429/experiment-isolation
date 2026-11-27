"""Package shim forwarding ``engine`` imports to the canonical skill scripts."""

from __future__ import annotations

from pathlib import Path

_CANONICAL = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "experiment-isolation"
    / "scripts"
    / "engine"
)
__path__ = [str(_CANONICAL)]
__version__ = "0.1.0"
