#!/usr/bin/env bash
# Run the experiment-isolation engine CLI from any directory.
# Contains no business logic; all arguments pass through to engine.cli.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

resolve_engine_root() {
  if [[ -n "${EXPERIMENT_ISOLATION_ROOT:-}" ]]; then
    if [[ -f "${EXPERIMENT_ISOLATION_ROOT}/engine/cli.py" ]]; then
      printf '%s\n' "${EXPERIMENT_ISOLATION_ROOT}"
      return 0
    fi
    if [[ -f "${EXPERIMENT_ISOLATION_ROOT}/skills/experiment-isolation/scripts/engine/cli.py" ]]; then
      printf '%s\n' "${EXPERIMENT_ISOLATION_ROOT}/skills/experiment-isolation/scripts"
      return 0
    fi
    return 1
  fi

  if [[ -f "$script_dir/engine/cli.py" ]]; then
    printf '%s\n' "$script_dir"
    return 0
  fi

  local candidate="$script_dir"
  while [[ "$candidate" != "/" ]]; do
    if [[ -f "$candidate/engine/cli.py" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    candidate="$(dirname -- "$candidate")"
  done

  return 1
}

if ! engine_root="$(resolve_engine_root)"; then
  printf 'error: engine package not found; set EXPERIMENT_ISOLATION_ROOT\n' >&2
  exit 20
fi

export PYTHONPATH="$engine_root${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m engine.cli "$@"
