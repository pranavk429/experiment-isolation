#!/usr/bin/env python3
"""Build the draft cut from the recorded lab segments and narration.

All inputs are real captures from the lab run in video/work/draft. Captions are
graphics only; they restate numbers visible in the captured output. Nothing is
re-enacted.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VIDEO = Path(__file__).resolve().parent
WORK = VIDEO / "work"
SEG = WORK / "segments"
CAPS = WORK / "captions"
OUT = VIDEO / "renders" / "draft.mp4"
FFMPEG = "ffmpeg"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def still(src: Path, out: Path, seconds: float, caption: Path | None) -> None:
    filters = "scale=1920:1080,setsar=1,fps=30,format=yuv420p"
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-t", f"{seconds}", "-i", str(src)]
    if caption:
        cmd += ["-i", str(caption)]
        filters += "[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        cmd += ["-filter_complex", filters, "-map", "[v]"]
    else:
        cmd += ["-vf", filters]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", "-r", "30", str(out)]
    run(cmd)


def clip(src: Path, out: Path, seconds: float, caption: Path | None) -> None:
    src_seconds = duration(src)
    pad = max(0.0, seconds - src_seconds + 0.6)
    base = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0A0D13,"
        f"setsar=1,fps=30,tpad=stop_mode=clone:stop_duration={pad:.3f},"
        f"trim=duration={seconds:.3f},setpts=PTS-STARTPTS"
    )
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if caption:
        cmd += ["-i", str(caption)]
        filt = f"[0:v]{base}[b];[b][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        cmd += ["-filter_complex", filt, "-map", "[v]"]
    else:
        cmd += ["-vf", base + ",format=yuv420p"]
    cmd += ["-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", "-r", "30", str(out)]
    run(cmd)


def main() -> int:
    SEG.mkdir(parents=True, exist_ok=True)
    for old in SEG.glob("*.mp4"):
        old.unlink()

    specs = [
        ("00-title", "still", VIDEO / "stills" / "title.png", 2.0, None),
        ("01-storefront", "clip", VIDEO / "raw" / "03-storefront.webm", 10.0, CAPS / "caption-storefront.png"),
        ("02-before-top", "clip", VIDEO / "raw" / "07-dashboard-before.webm", 14.0, CAPS / "caption-before.png"),
        ("03-before-panel", "clip", VIDEO / "raw" / "07b-dashboard-before-panel.webm", 14.0, CAPS / "caption-before.png"),
        ("04-intro", "clip", VIDEO / "captures" / "draft-intro.mp4", 9.0, None),
        ("05-architecture", "clip", VIDEO / "captures" / "draft-architecture.mp4", 6.7, None),
        ("06-terminal", "clip", VIDEO / "captures" / "draft-terminal.mp4", 54.0, None),
        ("06b-verify", "clip", VIDEO / "captures" / "draft-verify.mp4", 5.0, None),
        ("07-receipt-hold", "still", WORK / "receipt-frame.png", 6.0, CAPS / "caption-receipt.png"),
        ("08-after-top", "clip", VIDEO / "raw" / "08-dashboard-after.webm", 14.0, CAPS / "caption-after.png"),
        ("09-after-panel", "clip", VIDEO / "raw" / "09-dashboard-after-panel.webm", 14.0, CAPS / "caption-panel.png"),
        ("10-flagsmith", "clip", VIDEO / "raw" / "10-flagsmith-after.webm", 12.0, CAPS / "caption-flagsmith.png"),
        ("99-endcard", "still", VIDEO / "stills" / "endcard.png", 5.0, None),
    ]

    for name, kind, src, seconds, caption in specs:
        if not src.is_file():
            print(f"error: missing {src}", file=sys.stderr)
            return 2
        out = SEG / f"{name}.mp4"
        print(f"{name}: {seconds:.1f}s <- {src.name}")
        if kind == "still":
            still(src, out, seconds, caption)
        else:
            clip(src, out, seconds, caption)

    narration = WORK / "draft" / "narration150.m4a"
    if not narration.is_file():
        print(f"error: missing {narration}", file=sys.stderr)
        return 2

    run([
        str(VIDEO / "assemble.sh"),
        "--clips", str(SEG),
        "--audio", str(narration),
        "--out", str(OUT),
    ])
    print(f"draft: {OUT} ({duration(OUT):.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
