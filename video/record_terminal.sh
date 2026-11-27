#!/usr/bin/env bash
# Record a terminal demo take with asciinema when available, else BSD script.
#
#   video/record_terminal.sh --demo
#   video/record_terminal.sh --commands video/commands/demo.txt --render
#
# The runner prints every command with a fixed prompt, executes it, keeps going
# after a non-zero exit (the refusal beat is exit 10), and refuses obviously
# unsafe lines before the capture starts. It never sources an env file itself.
#
# Output: video/captures/terminal-<stamp>.cast   (asciinema)
#         video/captures/terminal-<stamp>.typescript (script)
# Add --render to turn the capture into a 1920x1080 MP4 with render_transcript.py.

set -u

VIDEO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE_DIR="$VIDEO_DIR/captures"
PROMPT_TEXT='experiment-isolation $'

TOOL="auto"
OUT=""
COMMANDS=""
DEMO=0
RENDER=0
CHECK=0
PACE="0.40"
TITLE="Experiment Isolation — local Flagsmith"
BANNER=""
WATERMARK=""
DEMO_COMMANDS=""
SESSION=""
CLEAN=""

usage() {
  cat <<'EOF'
Usage: video/record_terminal.sh (--demo | --commands FILE) [options]

Required (one of):
  --demo                 run labelled placeholder commands; never product data
  --commands FILE        one shell command per line; blank lines and # comments skipped

Options:
  --out PATH             capture path (default video/captures/terminal-<stamp>.<ext>)
  --tool auto|asciinema|script   capture backend (default auto)
  --render               also render the capture to MP4 (1920x1080, 30 fps)
  --check                validate the command file and exit; never executes it
  --pace SECONDS         pause after each command (default 0.40)
  --title TEXT           terminal window title written into the recording
  -h, --help             this text

Safety: the script refuses env/printenv, set -x, history, reads of .env or
flagsmith.env, and echo/printf of API-key variables. It does not source any
environment file and does not run the audit or apply unless they are in FILE.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 2
}

cleanup() {
  [ -n "$SESSION" ] && rm -f "$SESSION"
  [ -n "$CLEAN" ] && rm -f "$CLEAN"
  [ -n "$DEMO_COMMANDS" ] && rm -f "$DEMO_COMMANDS"
}

trap cleanup EXIT

while [ "$#" -gt 0 ]; do
  case "$1" in
    --out)
      [ "$#" -ge 2 ] || die "--out needs a path"
      OUT="$2"
      shift 2
      ;;
    --commands)
      [ "$#" -ge 2 ] || die "--commands needs a file"
      COMMANDS="$2"
      shift 2
      ;;
    --demo)
      DEMO=1
      shift
      ;;
    --tool)
      [ "$#" -ge 2 ] || die "--tool needs auto, asciinema, or script"
      TOOL="$2"
      shift 2
      ;;
    --render)
      RENDER=1
      shift
      ;;
    --check)
      CHECK=1
      shift
      ;;
    --pace)
      [ "$#" -ge 2 ] || die "--pace needs seconds"
      PACE="$2"
      shift 2
      ;;
    --title)
      [ "$#" -ge 2 ] || die "--title needs text"
      TITLE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1 (try --help)"
      ;;
  esac
done

if [ "$DEMO" -eq 1 ] && [ -n "$COMMANDS" ]; then
  die "use either --demo or --commands, not both"
fi
if [ "$DEMO" -eq 0 ] && [ -z "$COMMANDS" ]; then
  usage >&2
  die "provide --demo or --commands FILE"
fi
if ! printf '%s' "$PACE" | grep -Eq '^[0-9]+([.][0-9]+)?$'; then
  die "--pace must be a number, got: $PACE"
fi

case "$TOOL" in
  auto|asciinema|script) ;;
  *) die "--tool must be auto, asciinema, or script" ;;
esac

if [ -z "$COMMANDS" ]; then
  DEMO_COMMANDS="$(mktemp "${TMPDIR:-/tmp}/ei-demo-commands.XXXXXX")"
  cat > "$DEMO_COMMANDS" <<'EOF'
echo "[pipeline-test] placeholder only — this is not product footage"
echo "[pipeline-test] would run: engine.cli audit --samples 500"
printf '[pipeline-test] audit.json: <written by the real run>\n'
sh -c 'echo "[pipeline-test] refusal path: exit 10" >&2; exit 10'
echo "[pipeline-test] capture pipeline works end to end"
printf '{"pipeline_test": true, "product_data": false}\n'
EOF
  COMMANDS="$DEMO_COMMANDS"
  BANNER="PIPELINE TEST — placeholder output, not demo footage"
  WATERMARK="PIPELINE TEST — PLACEHOLDER OUTPUT"
else
  case "$COMMANDS" in
    /*) ;;
    *) COMMANDS="$PWD/$COMMANDS" ;;
  esac
  [ -f "$COMMANDS" ] || die "commands file not found: $COMMANDS"
fi

# Pre-scan: refuse before opening the capture, so a blocked line is never
# recorded and a refusal cannot leave a half-take.
CLEAN="$(mktemp "${TMPDIR:-/tmp}/ei-clean-commands.XXXXXX")"
line_no=0
while IFS= read -r raw || [ -n "$raw" ]; do
  line_no=$((line_no + 1))
  line="$(printf '%s' "$raw" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [ -z "$line" ] && continue
  case "$line" in
    \#*) continue ;;
  esac

  blocked=0
  if printf '%s' "$line" | grep -Eq '(^|[;&|][[:space:]]*)(env|printenv)([[:space:]]|$)'; then
    blocked=1
  fi
  if printf '%s' "$line" | grep -Eq 'set[[:space:]]+-[[:alnum:]]*x'; then
    blocked=1
  fi
  if printf '%s' "$line" | grep -Eq '(cat|less|more|head|tail|sed|awk|grep)[[:space:]].*(flagsmith[.]env|(^|[[:space:]/])[.]env([[:space:]]|$))'; then
    blocked=1
  fi
  if printf '%s' "$line" | grep -Eq '(echo|printf)[[:space:]].*(FLAGSMITH_API_KEY|ADMIN_TOKEN)'; then
    blocked=1
  fi
  if printf '%s' "$line" | grep -Eq '(^|[;&|][[:space:]]*)(history)([[:space:]]|$)'; then
    blocked=1
  fi

  if [ "$blocked" -eq 1 ]; then
    die "refusing commands line $line_no (secret/verbose-shell pattern): $line"
  fi
  printf '%s\n' "$line" >> "$CLEAN"
done < "$COMMANDS"

if [ ! -s "$CLEAN" ]; then
  die "no runnable commands in $COMMANDS"
fi

if [ "$CHECK" -eq 1 ]; then
  printf 'check OK: %s runnable commands, no blocked patterns\n' "$(wc -l < "$CLEAN" | tr -d ' ')"
  exit 0
fi

if [ "$TOOL" = "auto" ]; then
  if command -v asciinema >/dev/null 2>&1; then
    TOOL="asciinema"
  else
    TOOL="script"
  fi
fi

if [ "$TOOL" = "asciinema" ]; then
  command -v asciinema >/dev/null 2>&1 || die "asciinema not found; brew install asciinema (or use --tool script)"
else
  command -v script >/dev/null 2>&1 || die "script not found; run on macOS/BSD or install util-linux"
fi

if [ -z "$OUT" ]; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  if [ "$DEMO" -eq 1 ]; then
    prefix="pipeline-test"
  else
    prefix="terminal-$stamp"
  fi
  if [ "$TOOL" = "asciinema" ]; then
    OUT="$CAPTURE_DIR/$prefix.cast"
  else
    OUT="$CAPTURE_DIR/$prefix.typescript"
  fi
fi

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"

SESSION="$(mktemp "${TMPDIR:-/tmp}/ei-session.XXXXXX")"
{
  printf '#!/bin/bash\n'
  printf 'export TERM=xterm-256color\n'
  printf "export PS1='%s '\n" "$PROMPT_TEXT"
  printf 'unset HISTFILE\n'
  printf 'printf "\\033[2J\\033[H"\n'
  if [ -n "$BANNER" ]; then
    printf 'printf "\\033[1;33m%%s\\033[0m\\n\\n" %q\n' "$BANNER"
  fi
  printf 'while IFS= read -r line; do\n'
  printf '  printf "\\n\\033[1;36m%%s\\033[0m \\033[1;37m%%s\\033[0m\\n" %q "$line"\n' "$PROMPT_TEXT"
  printf '  eval "$line"\n'
  printf '  rc=$?\n'
  printf '  if [ "$rc" -ne 0 ]; then printf "\\033[1;31m[exit %%s]\\033[0m\\n" "$rc"; fi\n'
  printf '  sleep %q\n' "$PACE"
  printf 'done < %q\n' "$CLEAN"
  printf 'printf "\\n\\033[2m[recording stopped]\\033[0m\\n"\n'
  printf 'sleep 0.7\n'
} > "$SESSION"
chmod +x "$SESSION"

printf 'tool:  %s\n' "$TOOL"
printf 'file:  %s\n' "$OUT"
printf 'title: %s\n' "$TITLE"
printf 'lines: %s\n' "$(wc -l < "$CLEAN" | tr -d ' ')"
if [ -n "$BANNER" ]; then
  printf 'mode:  PIPELINE TEST (placeholder output)\n'
fi
printf '\n'

if [ "$TOOL" = "asciinema" ]; then
  asciinema rec --overwrite --title "$TITLE" --command "/bin/bash $(printf '%q' "$SESSION")" "$OUT"
else
  script -q "$OUT" /bin/bash "$SESSION"
fi

if [ ! -s "$OUT" ]; then
  die "capture is empty: $OUT"
fi

bytes="$(wc -c < "$OUT" | tr -d ' ')"
lines="$(wc -l < "$OUT" | tr -d ' ')"
printf '\ncaptured %s bytes, %s records/lines: %s\n' "$bytes" "$lines" "$OUT"

if [ "$RENDER" -eq 1 ]; then
  command -v python3 >/dev/null 2>&1 || die "python3 not found; cannot render"
  mp4="${OUT%.*}.mp4"
  if [ -n "$WATERMARK" ]; then
    python3 "$VIDEO_DIR/render_transcript.py" "$OUT" --out "$mp4" --title "$TITLE" --watermark "$WATERMARK"
  else
    python3 "$VIDEO_DIR/render_transcript.py" "$OUT" --out "$mp4" --title "$TITLE"
  fi
  printf 'video: %s\n' "$mp4"
fi
