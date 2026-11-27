#!/usr/bin/env bash
# Run the experiment-isolation engine CLI from any install location.
# Contains no business logic; all arguments pass through to engine.cli.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

find_repo_root() {
  local candidate

  if [[ -n "${EXPERIMENT_ISOLATION_ROOT:-}" ]]; then
    if [[ -f "${EXPERIMENT_ISOLATION_ROOT}/engine/cli.py" ]]; then
      printf '%s\n' "${EXPERIMENT_ISOLATION_ROOT}"
      return 0
    fi
    return 1
  fi

  candidate="$script_dir"
  while [[ "$candidate" != "/" ]]; do
    if [[ -f "$candidate/engine/cli.py" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    candidate="$(dirname -- "$candidate")"
  done

  candidate="$PWD"
  if [[ -f "$candidate/engine/cli.py" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  return 1
}

if ! repo_root="$(find_repo_root)"; then
  printf 'error: engine package not found; set EXPERIMENT_ISOLATION_ROOT to the repo root\n' >&2
  exit 20
fi

cd -- "$repo_root"
exec python3 -m engine.cli "$@"
