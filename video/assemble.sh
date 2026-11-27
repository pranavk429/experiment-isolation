#!/usr/bin/env bash
# Normalize, order, and concatenate recorded segments into the final MP4.
#
#   video/assemble.sh --clips video/raw --out video/renders/demo.mp4
#   video/assemble.sh --clips video/raw --audio video/raw/narration.m4a \
#       --endcard video/stills/endcard.png --with-endcard
#
# Every segment is scaled/padded to 1920x1080, forced to 30 fps, and stripped of
# audio before concat. A title card is opt-in because docs/demo-script.md says
# the demo opens on the product, not a logo. The end card is opt-in and adds
# 2.5 seconds, so include it only if the cut is under 2:42.

set -euo pipefail

VIDEO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIPS=""
OUT="$VIDEO_DIR/renders/demo.mp4"
AUDIO=""
TITLE_PNG=""
ENDCARD_PNG=""
WITH_TITLE=0
WITH_ENDCARD=0
KEEP_WORK=0
CRF=18

usage() {
  cat <<'EOF'
Usage: video/assemble.sh --clips DIR [options]

  --clips DIR          directory of recorded segments (mp4/mov/mkv/webm), sorted by name
  --out FILE           output MP4 (default video/renders/demo.mp4)
  --audio FILE         narration track; padded to the video length
  --title PNG          title still; used only with --with-title
  --with-title         prepend the title still for 1.0 s
  --endcard PNG        end card still; used only with --with-endcard
  --with-endcard       append the end card for 2.5 s
  --crf N              x264 quality (default 18; lower is larger/better)
  --keep-work          keep the normalized clips and concat list
  -h, --help           this text

Name clips in shot order, e.g. 01-problem.mp4 02-audience.mp4 ... 17-close.mp4.
The script refuses to invent a missing segment; a gap in the story is an error.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 2; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --clips) [ "$#" -ge 2 ] || die "--clips needs a directory"; CLIPS="$2"; shift 2 ;;
    --out) [ "$#" -ge 2 ] || die "--out needs a path"; OUT="$2"; shift 2 ;;
    --audio) [ "$#" -ge 2 ] || die "--audio needs a path"; AUDIO="$2"; shift 2 ;;
    --title) [ "$#" -ge 2 ] || die "--title needs a PNG"; TITLE_PNG="$2"; shift 2 ;;
    --with-title) WITH_TITLE=1; shift ;;
    --endcard) [ "$#" -ge 2 ] || die "--endcard needs a PNG"; ENDCARD_PNG="$2"; shift 2 ;;
    --with-endcard) WITH_ENDCARD=1; shift ;;
    --crf) [ "$#" -ge 2 ] || die "--crf needs a number"; CRF="$2"; shift 2 ;;
    --keep-work) KEEP_WORK=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

[ -n "$CLIPS" ] || { usage >&2; die "--clips DIR is required"; }
[ -d "$CLIPS" ] || die "clips directory not found: $CLIPS"
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg not found; brew install ffmpeg"
command -v ffprobe >/dev/null 2>&1 || die "ffprobe not found; brew install ffmpeg"

if [ "$WITH_TITLE" -eq 1 ]; then
  [ -n "$TITLE_PNG" ] || die "--with-title needs --title PNG"
  [ -f "$TITLE_PNG" ] || die "title still not found: $TITLE_PNG"
fi
if [ "$WITH_ENDCARD" -eq 1 ]; then
  [ -n "$ENDCARD_PNG" ] || die "--with-endcard needs --endcard PNG"
  [ -f "$ENDCARD_PNG" ] || die "end card still not found: $ENDCARD_PNG"
fi
if [ -n "$AUDIO" ] && [ ! -f "$AUDIO" ]; then
  die "audio file not found: $AUDIO"
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/ei-assemble.XXXXXX")"
cleanup() {
  if [ "$KEEP_WORK" -eq 1 ]; then
    printf 'work kept: %s\n' "$WORK"
  else
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT

mkdir -p "$(dirname "$OUT")"

CLIP_FILES=()
while IFS= read -r clip_file; do
  [ -n "$clip_file" ] && CLIP_FILES+=("$clip_file")
done < <(
  find "$CLIPS" -maxdepth 1 -type f \
    \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.webm' \) \
    -print | sort
)

if [ "${#CLIP_FILES[@]}" -eq 0 ]; then
  die "no mp4/mov/mkv/webm segments in $CLIPS"
fi

normalize() {
  local source="$1" destination="$2"
  ffmpeg -y -hide_banner -loglevel error \
    -i "$source" \
    -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0A0D13,setsar=1,fps=30" \
    -c:v libx264 -preset veryfast -crf "$CRF" -pix_fmt yuv420p -an \
    "$destination"
}

still_clip() {
  local source="$1" seconds="$2" destination="$3"
  ffmpeg -y -hide_banner -loglevel error \
    -loop 1 -t "$seconds" -i "$source" \
    -vf "scale=1920:1080,setsar=1,fps=30,format=yuv420p" \
    -c:v libx264 -preset veryfast -crf "$CRF" -pix_fmt yuv420p -an \
    "$destination"
}

CONCAT_LIST="$WORK/concat.txt"
: > "$CONCAT_LIST"
INDEX=0

if [ "$WITH_TITLE" -eq 1 ]; then
  INDEX=$((INDEX + 1))
  still_clip "$TITLE_PNG" 1.0 "$WORK/segment-$(printf '%02d' "$INDEX").mp4"
  printf "file '%s'\n" "$WORK/segment-$(printf '%02d' "$INDEX").mp4" >> "$CONCAT_LIST"
  printf 'prepended title still (1.0 s)\n'
fi

for source in "${CLIP_FILES[@]}"; do
  INDEX=$((INDEX + 1))
  destination="$WORK/segment-$(printf '%02d' "$INDEX").mp4"
  printf 'normalizing %s\n' "$(basename "$source")"
  normalize "$source" "$destination"
  printf "file '%s'\n" "$destination" >> "$CONCAT_LIST"
done

if [ "$WITH_ENDCARD" -eq 1 ]; then
  INDEX=$((INDEX + 1))
  still_clip "$ENDCARD_PNG" 2.5 "$WORK/segment-$(printf '%02d' "$INDEX").mp4"
  printf "file '%s'\n" "$WORK/segment-$(printf '%02d' "$INDEX").mp4" >> "$CONCAT_LIST"
  printf 'appended end card (2.5 s)\n'
fi

SILENT="$WORK/silent.mp4"
printf 'concatenating %s segments\n' "$INDEX"
if ! ffmpeg -y -hide_banner -loglevel error -fflags +genpts -f concat -safe 0 -i "$CONCAT_LIST" -c copy "$SILENT" 2>/dev/null; then
  printf 'stream copy failed; re-encoding the join\n'
  ffmpeg -y -hide_banner -loglevel error -fflags +genpts -f concat -safe 0 -i "$CONCAT_LIST" \
    -c:v libx264 -preset veryfast -crf "$CRF" -pix_fmt yuv420p -an "$SILENT"
fi

if [ -n "$AUDIO" ]; then
  DURATION="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SILENT")"
  printf 'muxing narration and padding to %ss\n' "$DURATION"
  ffmpeg -y -hide_banner -loglevel error \
    -i "$SILENT" -i "$AUDIO" \
    -map 0:v:0 -map 1:a:0 \
    -c:v copy -c:a aac -b:a 192k -af "apad" -t "$DURATION" \
    "$OUT"
else
  cp "$SILENT" "$OUT"
fi

FINAL_DURATION="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")"
BYTES="$(wc -c < "$OUT" | tr -d ' ')"
printf '\nwrote %s (%s bytes, %ss)\n' "$OUT" "$BYTES" "$FINAL_DURATION"
awk -v d="$FINAL_DURATION" 'BEGIN { printf "runtime: %d:%05.2f\n", int(d/60), d - int(d/60)*60 }'

if awk -v d="$FINAL_DURATION" 'BEGIN { exit !(d > 180) }'; then
  printf 'WARNING: over the 3:00 hard cap. Trim before uploading.\n' >&2
elif awk -v d="$FINAL_DURATION" 'BEGIN { exit !(d > 170) }'; then
  printf 'note: over the 2:50 target; still under the 3:00 hard cap.\n'
elif awk -v d="$FINAL_DURATION" 'BEGIN { exit !(d >= 155) }'; then
  printf 'note: within the 2:35–2:50 target.\n'
else
  printf 'note: shorter than 2:35; check that no proof beat was cut.\n'
fi
