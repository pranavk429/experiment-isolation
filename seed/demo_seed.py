#!/usr/bin/env python3
"""Idempotently seed draft collision experiments in a Flagsmith environment."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "experiment-isolation" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from engine.seed import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
