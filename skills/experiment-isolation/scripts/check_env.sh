#!/usr/bin/env bash
# Verify local Flagsmith prerequisites without printing secret values.
# Usage:
#   source ~/flagsmith-local/flagsmith.env && bash check_env.sh
#   FLAGSMITH_ENV_FILE=lab/.env bash check_env.sh
set -u

failed=0

if [[ -n "${FLAGSMITH_ENV_FILE:-}" ]]; then
  if [[ -f "$FLAGSMITH_ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    if source "$FLAGSMITH_ENV_FILE"; then
      printf 'ok: sourced env file %s\n' "$FLAGSMITH_ENV_FILE"
    else
      printf 'FAIL: could not source env file %s\n' "$FLAGSMITH_ENV_FILE" >&2
      failed=1
    fi
  else
    printf 'FAIL: env file not found: %s\n' "$FLAGSMITH_ENV_FILE" >&2
    failed=1
  fi
elif [[ -n "${FLAGSMITH_API_URL:-}" ]]; then
  printf 'ok: using exported Flagsmith variables\n'
else
  printf 'FAIL: set FLAGSMITH_ENV_FILE (for example lab/.env) or source an env file first\n' >&2
  failed=1
fi

export PATH="$HOME/.cache/fstools/node_modules/.bin:$PATH"

if command -v flagsmith >/dev/null 2>&1; then
  version="$(flagsmith --version 2>&1 | head -n 1)"
  printf 'ok: flagsmith CLI %s\n' "$version"
else
  printf 'FAIL: flagsmith CLI not found (checked PATH and ~/.cache/fstools/node_modules/.bin)\n' >&2
  failed=1
fi

if [[ -n "${FLAGSMITH_API_URL:-}" ]]; then
  base="${FLAGSMITH_API_URL%/}"
  if command -v curl >/dev/null 2>&1; then
    code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$base/health" 2>/dev/null || true)"
    if [[ "$code" == 2* ]]; then
      printf 'ok: local API health HTTP %s\n' "$code"
    else
      printf 'FAIL: local API health returned HTTP %s\n' "${code:-000}" >&2
      failed=1
    fi
  else
    printf 'FAIL: curl not found; cannot check API health\n' >&2
    failed=1
  fi
else
  printf 'FAIL: FLAGSMITH_API_URL is not set\n' >&2
  failed=1
fi

missing=0
for name in FLAGSMITH_API_URL FLAGSMITH_PROJECT DEV_ENV_KEY; do
  if [[ -z "${!name:-}" ]]; then
    printf 'FAIL: %s is not set\n' "$name" >&2
    missing=1
  fi
done
if [[ -z "${FLAGSMITH_ENVIRONMENT:-${FLAGSMITH_ENVIRONMENT_KEY:-}}" ]]; then
  printf 'FAIL: FLAGSMITH_ENVIRONMENT is not set (FLAGSMITH_ENVIRONMENT_KEY accepted)\n' >&2
  missing=1
fi
if [[ "$missing" -ne 0 ]]; then
  failed=1
fi

expected_key=""
if [[ -n "${FLAGSMITH_API_URL:-}" ]] && command -v python3 >/dev/null 2>&1; then
  expected_key="$(python3 - "$FLAGSMITH_API_URL" <<'PY'
import sys
import urllib.parse

parsed = urllib.parse.urlparse(sys.argv[1])
host = (parsed.hostname or "").replace(".", "_")
port = parsed.port or (443 if parsed.scheme == "https" else 80)
print("FLAGSMITH_API_KEY_%s_%s" % (host, port))
PY
)" || expected_key=""
fi

if [[ -n "${FLAGSMITH_API_KEY:-}" ]]; then
  printf 'ok: Flagsmith API credential present (value not shown)\n'
elif [[ -n "$expected_key" ]] && [[ -n "${!expected_key:-}" ]]; then
  printf 'ok: Flagsmith API credential present (value not shown)\n'
else
  if [[ -n "$expected_key" ]]; then
    printf 'FAIL: missing %s or FLAGSMITH_API_KEY\n' "$expected_key" >&2
  else
    printf 'FAIL: no host-scoped API key or FLAGSMITH_API_KEY\n' >&2
  fi
  failed=1
fi

exit "$failed"
