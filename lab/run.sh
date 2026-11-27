#!/usr/bin/env bash
# Experiment Isolation Lab — one-command local starter.
#
#   bash lab/run.sh              start everything and print URLs
#   bash lab/run.sh demo         start, then run audit -> plan -> apply -> verify -> receipt
#   bash lab/run.sh audit        regenerate dashboard/audit.json
#   bash lab/run.sh sample       write an explicitly labelled sample audit
#   bash lab/run.sh status       show containers and HTTP health
#   bash lab/run.sh down         stop containers, keep the Postgres volume
#   bash lab/run.sh reset        wipe and rebuild the clean collision baseline
#
# Requires: Docker Compose v2, Python 3.9+, curl.
# The lab uses its own Compose project "isolation-lab" on 8010/8011 and never
# touches an existing Flagsmith stack on 8000/8001.

set -euo pipefail

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$LAB_DIR/.." && pwd)"
COMPOSE_FILE="$LAB_DIR/docker-compose.yml"
PROJECT="isolation-lab"
PYTHON="${PYTHON:-python3}"
API_URL="${LAB_API_URL:-http://localhost:8010}"
STOREFRONT_PORT="${STOREFRONT_PORT:-8020}"
DASHBOARD_PORT="${DASHBOARD_PORT:-8022}"
SAMPLES="${SAMPLES:-500}"
THRESHOLD="${THRESHOLD:-0.05}"
STRICT_AUDIT="${STRICT_AUDIT:-0}"

info() { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

compose() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }

usage() {
  cat <<'USAGE'
Experiment Isolation Lab

  bash lab/run.sh            start Flagsmith, seed drafts, audit, and serve the dashboard
  bash lab/run.sh demo       start, then run the approval-gated audit -> plan -> apply -> verify -> receipt
  bash lab/run.sh audit      regenerate lab/dashboard/audit.json from the running lab
  bash lab/run.sh sample     write an explicitly labelled sample audit
  bash lab/run.sh status     show containers, HTTP health, and the current audit summary
  bash lab/run.sh down       stop containers (keep the Postgres volume)
  bash lab/run.sh reset      wipe and rebuild the clean collision baseline (one command)
  bash lab/run.sh reset --wipe-only
                            wipe the volume, .env, and runtime evidence without rebuilding

Ports: Flagsmith 8010, task processor 8011, storefront 8020, dashboard 8022.
USAGE
}

check_prereqs() {
  command -v docker >/dev/null 2>&1 || fail "Docker is not installed. Install Docker Desktop or Docker Engine with Compose v2."
  docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop, then retry."
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required (docker compose, not docker-compose)."
  command -v curl >/dev/null 2>&1 || fail "curl is required."
  "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' \
    || fail "Python 3.9+ is required (found: $("$PYTHON" --version 2>&1))."
}

port_listening() {
  "$PYTHON" - "$1" <<'PY'
import socket, sys
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.3)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

check_ports() {
  if port_listening 8010; then
    if docker ps --format '{{.Names}}' | grep -qx "$PROJECT-flagsmith-1"; then
      info "Port 8010 is already held by this lab; reusing it."
    else
      fail "Port 8010 is already in use. Stop the other process or change the lab ports."
    fi
  fi
  if port_listening 8011; then
    if docker ps --format '{{.Names}}' | grep -qx "$PROJECT-flagsmith-task-processor-1"; then
      info "Port 8011 is already held by this lab; reusing it."
    else
      fail "Port 8011 is already in use. Stop the other process or change the lab ports."
    fi
  fi
  for port in "$STOREFRONT_PORT" "$DASHBOARD_PORT"; do
    if port_listening "$port"; then
      fail "Port $port is already in use. Stop the process or set STOREFRONT_PORT / DASHBOARD_PORT."
    fi
  done
}

wait_for_api() {
  local deadline=$((SECONDS + 240))
  printf 'Waiting for Flagsmith at %s ' "$API_URL"
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS --max-time 3 "$API_URL/health/liveness/" >/dev/null 2>&1; then
      printf ' ready\n'
      return 0
    fi
    printf '.'
    sleep 2
  done
  printf '\n'
  warn "Flagsmith did not become healthy. Recent logs:"
  compose logs --tail=40 migrate-db flagsmith >&2 || true
  fail "API health check failed after 240s."
}

check_migrate() {
  local ps
  ps="$(compose ps -a --format json 2>/dev/null || true)"
  if printf '%s' "$ps" | grep '"Service":"migrate-db"' | grep -q '"ExitCode":0'; then
    info "Database migration: migrate-db exited 0."
  else
    warn "migrate-db did not report exit code 0. Check: docker compose -p $PROJECT -f lab/docker-compose.yml ps -a"
  fi
}

source_env() {
  [ -f "$LAB_DIR/.env" ] || fail "lab/.env is missing. Run: python3 lab/bootstrap.py"
  # shellcheck disable=SC1090
  set -a
  . "$LAB_DIR/.env"
  set +a
  API_URL="${LAB_API_URL:-$API_URL}"
  [ -n "${LAB_DEV_ENV_KEY:-}" ] || fail "LAB_DEV_ENV_KEY is missing from lab/.env. Re-run bootstrap."
  [ -n "${LAB_ADMIN_API_KEY:-}" ] || fail "LAB_ADMIN_API_KEY is missing from lab/.env. Re-run bootstrap."
}

run_bootstrap() {
  info "Bootstrapping admin, organisation, project, environments, warehouse, and API key."
  "$PYTHON" "$LAB_DIR/bootstrap.py" --api-url "$API_URL"
}

run_seed() {
  info "Converging the lab to two drafts with the shared us_mobile audience."
  if ! "$PYTHON" "$LAB_DIR/seed/seed.py" --api-url "$API_URL"; then
    fail "Could not converge the lab experiments. Run: bash lab/run.sh reset"
  fi
}

clear_evidence() {
  rm -f "$LAB_DIR/dashboard/plan.json" "$LAB_DIR/dashboard/apply.json" \
    "$LAB_DIR/dashboard/verify.json" "$LAB_DIR/dashboard/receipt.json" \
    "$LAB_DIR"/dashboard/restore-*.json
}

write_sample_audit() {
  local reason="${1:-engine.cli is not available in this checkout}"
  "$PYTHON" "$LAB_DIR/seed/sample_audit.py" \
    --out "$LAB_DIR/dashboard/audit.json" \
    --threshold "$THRESHOLD" \
    --reason "$reason"
}

audit_is_valid() {
  AUDIT_PATH="$LAB_DIR/dashboard/audit.json" "$PYTHON" -c '
import json, os
path = os.environ["AUDIT_PATH"]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
assert isinstance(data.get("experiments"), list), "experiments must be a list"
assert isinstance(data.get("overlaps"), list), "overlaps must be a list"
' >/dev/null 2>&1
}

generate_audit() {
  if (cd "$ROOT_DIR" && "$PYTHON" -c 'import engine.cli' >/dev/null 2>&1); then
    info "Generating a measured audit with engine.cli (samples=$SAMPLES, threshold=$THRESHOLD)."
    rm -f "$LAB_DIR/dashboard/audit.json"
    local status=0
    set +e
    (
      cd "$ROOT_DIR"
      FLAGSMITH_API_URL="$API_URL" \
      FLAGSMITH_API_KEY_localhost_8010="$LAB_ADMIN_API_KEY" \
      FLAGSMITH_API_KEY="$LAB_ADMIN_API_KEY" \
      FLAGSMITH_ENVIRONMENT_KEY="$LAB_DEV_ENV_KEY" \
      "$PYTHON" -m engine.cli audit \
        --env "$LAB_DEV_ENV_KEY" \
        --samples "$SAMPLES" \
        --threshold "$THRESHOLD" \
        --out "$LAB_DIR/dashboard/audit.json"
    ) 2>"$LAB_DIR/.audit.err"
    status=$?
    set -e
    # Exit 0 = success; exit 10 = refusal/needs approval. For an audit, 10 is
    # the expected "collision found" verdict, not a tool failure.
    if { [ "$status" -eq 0 ] || [ "$status" -eq 10 ]; } && audit_is_valid; then
      if [ "$status" -eq 10 ]; then
        info "Measured audit written; verdict requires action (engine exit 10)."
      else
        info "Measured audit written to lab/dashboard/audit.json."
      fi
      return 0
    fi
    warn "engine.cli audit failed (exit $status). Last lines:"
    tail -n 8 "$LAB_DIR/.audit.err" >&2 || true
    if [ "$STRICT_AUDIT" = "1" ]; then
      fail "STRICT_AUDIT=1 and the measured audit failed; not falling back to sample data."
    fi
    write_sample_audit "engine.cli audit failed; see lab/.audit.err"
  else
    warn "engine.cli is not available yet; writing an explicitly labelled sample audit."
    write_sample_audit "engine.cli is not available in this checkout"
  fi
}

wait_for_http() {
  local url="$1" label="$2" timeout="$3" deadline=$((SECONDS + $3))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

stop_servers() {
  local pidfile pid
  for pidfile in .storefront.pid .dashboard.pid; do
    if [ -f "$LAB_DIR/$pidfile" ]; then
      pid="$(cat "$LAB_DIR/$pidfile" 2>/dev/null || true)"
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        sleep 1
      fi
      rm -f "$LAB_DIR/$pidfile"
    fi
  done
}

start_servers() {
  stop_servers
  info "Starting storefront on :$STOREFRONT_PORT and dashboard on :$DASHBOARD_PORT."
  nohup "$PYTHON" "$LAB_DIR/storefront/app.py" --port "$STOREFRONT_PORT" --api-url "$API_URL" \
    >>"$LAB_DIR/.storefront.log" 2>&1 &
  echo $! >"$LAB_DIR/.storefront.pid"
  nohup "$PYTHON" -m http.server "$DASHBOARD_PORT" --bind 127.0.0.1 --directory "$LAB_DIR/dashboard" \
    >>"$LAB_DIR/.dashboard.log" 2>&1 &
  echo $! >"$LAB_DIR/.dashboard.pid"

  if ! wait_for_http "http://localhost:$STOREFRONT_PORT/api/health" storefront 20; then
    tail -n 15 "$LAB_DIR/.storefront.log" >&2 || true
    fail "Storefront failed to start on :$STOREFRONT_PORT (see lab/.storefront.log)."
  fi
  if ! wait_for_http "http://localhost:$DASHBOARD_PORT/" dashboard 15; then
    tail -n 15 "$LAB_DIR/.dashboard.log" >&2 || true
    fail "Dashboard failed to start on :$DASHBOARD_PORT (see lab/.dashboard.log)."
  fi
}

print_summary() {
  local verdict source email summary
  verdict="?"
  source="unknown"
  summary="$(AUDIT_PATH="$LAB_DIR/dashboard/audit.json" RECEIPT_PATH="$LAB_DIR/dashboard/receipt.json" VERIFY_PATH="$LAB_DIR/dashboard/verify.json" "$PYTHON" -c '
import json, os

def read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None

verdict = "?"
source = "unknown"
audit = read(os.environ["AUDIT_PATH"])
if audit:
    verdict = audit.get("verdict", "?")
    source = (audit.get("_meta") or {}).get("source", "engine")
receipt = read(os.environ["RECEIPT_PATH"])
verify = read(os.environ["VERIFY_PATH"])
if receipt and isinstance(receipt.get("after"), dict):
    verdict = receipt["after"].get("verdict", verdict)
    source = "receipt.json (after)"
elif verify:
    verdict = "isolated" if verify.get("pass") else "collision"
    source = "verify.json (after)"
if verdict == "clear":
    verdict = "isolated"
print(verdict + "	" + source)
')"
  IFS="$(printf '	')" read -r verdict source <<< "$summary"
  email="$(grep -E '^export LAB_ADMIN_EMAIL=' "$LAB_DIR/.env" | head -n 1 | cut -d= -f2- || true)"
  echo
  echo "Experiment Isolation Lab is running."
  echo "  Flagsmith dashboard:  http://localhost:8010"
  echo "  Storefront:           http://localhost:$STOREFRONT_PORT"
  echo "  Overlap dashboard:    http://localhost:$DASHBOARD_PORT"
  echo "  Task processor:       http://localhost:8011"
  echo "  Audit JSON:           $LAB_DIR/dashboard/audit.json"
  echo "  Admin login:          ${email:-admin@isolation-lab.local} (password in lab/.env)"
  echo "  Load credentials:     source lab/.env"
  echo "  Verdict:              $verdict"
  echo "  Audit source:         $source"
  if [ "$source" = "sample" ]; then
    echo
    echo "  NOTE: the dashboard is showing a labelled SAMPLE audit because the measured audit was unavailable or failed."
    echo "  Retry with: bash lab/run.sh audit  (see lab/.audit.err for the last error)"
  fi
  echo
  echo "  Teardown (keep data): bash lab/run.sh down"
  echo "  Teardown (delete):    bash lab/run.sh reset"
}

cmd_up() {
  check_prereqs
  stop_servers
  check_ports
  info "Starting Compose project '$PROJECT' (ports 8010/8011)."
  compose up -d || fail "docker compose up failed. Check: docker compose -p $PROJECT -f lab/docker-compose.yml ps -a"
  wait_for_api
  check_migrate
  run_bootstrap
  run_seed
  source_env
  clear_evidence
  generate_audit
  start_servers
  print_summary
}

cmd_audit() {
  check_prereqs
  source_env
  generate_audit
  if [ -f "$LAB_DIR/dashboard/audit.json" ]; then
    info "Audit ready: $LAB_DIR/dashboard/audit.json"
  fi
}

cmd_demo() {
  if ! (cd "$ROOT_DIR" && "$PYTHON" -c 'import engine.cli' >/dev/null 2>&1); then
    fail "demo requires engine.cli. Run 'bash lab/run.sh' to start the lab with the sample fallback."
  fi
  cmd_up
  source_env
  info "Running the approval-gated isolation cycle (local lab only)."
  local plan="$LAB_DIR/dashboard/plan.json"
  local apply="$LAB_DIR/dashboard/apply.json"
  local verify="$LAB_DIR/dashboard/verify.json"
  local receipt="$LAB_DIR/dashboard/receipt.json"

  (
    cd "$ROOT_DIR"
    "$PYTHON" -m engine.cli plan --audit "$LAB_DIR/dashboard/audit.json" --out "$plan"
  ) || fail "engine.cli plan failed. Run 'bash lab/run.sh audit' and check lab/dashboard/audit.json."

  local token
  token="$(PLAN_PATH="$plan" "$PYTHON" -c 'import json, os; print(json.load(open(os.environ["PLAN_PATH"], encoding="utf-8"))["approval_token"])')" \
    || fail "plan.json did not contain an approval_token."

  (
    cd "$ROOT_DIR"
    "$PYTHON" -m engine.cli apply --plan "$plan" --approve "$token" --out "$apply"
  ) || fail "engine.cli apply failed. The lab is unchanged; inspect plan.json."
  (
    cd "$ROOT_DIR"
    "$PYTHON" -m engine.cli verify --plan "$plan" --samples "$SAMPLES" --out "$verify"
  ) || fail "engine.cli verify failed. Inspect lab/dashboard/verify.json."
  (
    cd "$ROOT_DIR"
    "$PYTHON" -m engine.cli receipt --audit "$LAB_DIR/dashboard/audit.json" --plan "$plan" --verify "$verify" --out "$receipt"
  ) || fail "engine.cli receipt failed."

  info "Full cycle complete. Refresh http://localhost:$DASHBOARD_PORT to see before/after."
  print_summary
}

cmd_sample() {
  clear_evidence
  write_sample_audit "manual sample regeneration"
  info "Sample audit ready: $LAB_DIR/dashboard/audit.json"
}

cmd_status() {
  check_prereqs
  compose ps || true
  echo
  for pair in "Flagsmith:$API_URL/health/liveness/" "Storefront:http://localhost:$STOREFRONT_PORT/api/health" "Dashboard:http://localhost:$DASHBOARD_PORT/"; do
    label="${pair%%:*}"
    url="${pair#*:}"
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      echo "$label: up ($url)"
    else
      echo "$label: down ($url)"
    fi
  done
  if [ -f "$LAB_DIR/dashboard/audit.json" ]; then
    AUDIT_PATH="$LAB_DIR/dashboard/audit.json" RECEIPT_PATH="$LAB_DIR/dashboard/receipt.json" VERIFY_PATH="$LAB_DIR/dashboard/verify.json" "$PYTHON" -c '
import json, os

def read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None

data = read(os.environ["AUDIT_PATH"]) or {}
verdict = data.get("verdict", "?")
source = (data.get("_meta") or {}).get("source", "engine")
receipt = read(os.environ["RECEIPT_PATH"])
verify = read(os.environ["VERIFY_PATH"])
if receipt and isinstance(receipt.get("after"), dict):
    verdict = receipt["after"].get("verdict", verdict)
    source = "receipt.json (after)"
elif verify:
    verdict = "isolated" if verify.get("pass") else "collision"
    source = "verify.json (after)"
if verdict == "clear":
    verdict = "isolated"
print("Audit: %s experiments, verdict=%s, source=%s" % (
    len(data.get("experiments") or []), verdict, source,
))
'
  else
    echo "Audit: missing"
  fi
}

cmd_down() {
  stop_servers
  check_prereqs
  info "Stopping Compose project '$PROJECT' (Postgres volume preserved)."
  compose down
  info "Stopped. Start again with: bash lab/run.sh"
}

cmd_reset() {
  local rebuild=1
  if [ "${2:-}" = "--wipe-only" ]; then
    rebuild=0
  fi
  stop_servers
  check_prereqs
  warn "This deletes the lab Postgres volume, generated lab/.env, and runtime audit files."
  compose down -v || fail "Could not remove the lab Compose project; check Docker and retry."
  rm -f "$LAB_DIR/.env" "$LAB_DIR/.storefront.pid" "$LAB_DIR/.dashboard.pid" \
    "$LAB_DIR/.storefront.log" "$LAB_DIR/.dashboard.log" "$LAB_DIR/.audit.err" \
    "$LAB_DIR/seed/seed_state.json" \
    "$LAB_DIR/dashboard/audit.json" "$LAB_DIR/dashboard/plan.json" \
    "$LAB_DIR/dashboard/apply.json" "$LAB_DIR/dashboard/verify.json" \
    "$LAB_DIR/dashboard/receipt.json" "$LAB_DIR"/dashboard/restore-*.json
  if [ "$rebuild" -eq 0 ]; then
    info "Lab wiped. Start again with: bash lab/run.sh"
    return 0
  fi
  info "Lab wiped. Rebuilding the clean two-draft collision baseline."
  cmd_up
}

case "${1:-up}" in
  up) cmd_up ;;
  demo) cmd_demo ;;
  audit) cmd_audit ;;
  sample) cmd_sample ;;
  status) cmd_status ;;
  down|stop) cmd_down ;;
  reset) cmd_reset ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
