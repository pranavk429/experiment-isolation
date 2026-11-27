#!/usr/bin/env python3
"""Build the final 3-minute cut from the recorded lab and verifier evidence."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VIDEO = Path(__file__).resolve().parent
RAW = VIDEO / "raw" / "final"
CAP = VIDEO / "captures" / "final"
WORK = VIDEO / "work" / "final"
CAPS = VIDEO / "work" / "captions-final"
SEG = WORK / "segments"
OUT = VIDEO / "renders" / "final.mp4"
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


def clip(src: Path, out: Path, seconds: float, caption: Path | None, redact: tuple[int, int, int, int] | None = None) -> None:
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
        filt = f"[0:v]{base}[b];[b][1:v]overlay=0:0"
        if redact:
            x, y, w, h = redact
            filt += f",drawbox=x={x}:y={y}:w={w}:h={h}:color=0x070A0F:t=fill"
        filt += ",format=yuv420p[v]"
        cmd += ["-filter_complex", filt, "-map", "[v]"]
    else:
        vf = base
        if redact:
            x, y, w, h = redact
            vf += f",drawbox=x={x}:y={y}:w={w}:h={h}:color=0x070A0F:t=fill"
        cmd += ["-vf", vf + ",format=yuv420p"]
    cmd += ["-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", "-r", "30", str(out)]
    run(cmd)


def main() -> int:
    SEG.mkdir(parents=True, exist_ok=True)
    for old in SEG.glob("*.mp4"):
        old.unlink()

    specs = [
        ("00-title", "still", VIDEO / "stills" / "title.png", 1.5, None),
        ("01-storefront", "clip", RAW / "storefront.webm", 8.0, CAPS / "caption-storefront.png"),
        ("02-flags-before", "clip", RAW / "flagsmith-before.webm", 12.0, CAPS / "caption-flags-before.png"),
        ("03-dash-before", "clip", RAW / "dash-before.webm", 10.0, CAPS / "caption-before.png"),
        ("04-dash-before-panel", "clip", RAW / "dash-before-panel.webm", 10.0, CAPS / "caption-before.png"),
        ("05-intro", "clip", CAP / "intro.mp4", 10.0, CAPS / "caption-skill.png"),
        ("06-architecture", "clip", CAP / "architecture.mp4", 6.0, None),
        ("07-terminal-a", "clip", CAP / "terminal-a.mp4", 30.3, None),
        ("08-terminal-b", "clip", CAP / "terminal-b.mp4", 7.5, None),
        ("09-token", "clip", CAP / "token.mp4", 3.0, CAPS / "caption-token.png"),
        ("10-receipt", "still", WORK / "receipt-panel.png", 9.0, None),
        ("11-dash-after", "clip", RAW / "dash-after.webm", 12.0, CAPS / "caption-after.png"),
        ("12-dash-after-panel", "clip", RAW / "dash-after-panel.webm", 12.0, CAPS / "caption-panel.png"),
        ("13-flags-after", "clip", RAW / "flagsmith-after.webm", 14.0, CAPS / "caption-flags-after.png"),
        ("14-agent-log", "clip", CAP / "agent-log.mp4", 13.0, None),
        ("15-rollback", "clip", CAP / "rollback.mp4", 4.9, CAPS / "caption-rollback.png"),
        ("99-endcard", "still", VIDEO / "stills" / "endcard.png", 5.0, None),
    ]

    redactions = {"03-dash-before": (396, 232, 174, 30)}
    for name, kind, src, seconds, caption in specs:
        if not src.is_file():
            print(f"error: missing {src}", file=sys.stderr)
            return 2
        out = SEG / f"{name}.mp4"
        print(f"{name}: {seconds:.1f}s <- {src.name}")
        if kind == "still":
            still(src, out, seconds, caption)
        else:
            clip(src, out, seconds, caption, redactions.get(name))

    narration = WORK / "narration.m4a"
    if not narration.is_file():
        print(f"error: missing {narration}", file=sys.stderr)
        return 2

    run([
        str(VIDEO / "assemble.sh"),
        "--clips", str(SEG),
        "--audio", str(narration),
        "--out", str(OUT),
    ])
    print(f"final: {OUT} ({duration(OUT):.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
