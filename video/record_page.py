#!/usr/bin/env python3
"""Record a real browser page with Playwright when the browse relay is offline.

Primary browser capture is browse.recording (see video/README.md). This script is
the fallback for a local page such as the lab dashboard: it records the actual
page, not a mock. It cannot hover Flagsmith UI like a human; use browse.recording
for those shots.

Usage:
    python3 video/record_page.py --url http://localhost:8022/ \
        --out video/raw/07-dashboard.mp4 --seconds 10

The .webm Playwright produces is transcoded to 1920x1080 H.264 when --out ends
in .mp4, so it drops into video/assemble.sh with the other segments.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a page with Playwright.")
    parser.add_argument("--url", required=True, help="page URL to record")
    parser.add_argument("--out", required=True, help="output .mp4 or .webm")
    parser.add_argument("--seconds", type=float, default=8.0, help="total recording seconds (default 8)")
    parser.add_argument("--width", type=int, default=1920, help="viewport width (default 1920)")
    parser.add_argument("--height", type=int, default=1080, help="viewport height (default 1080)")
    parser.add_argument("--reload-at", type=float, default=0.0, help="reload this many seconds in (0 = never)")
    parser.add_argument("--wait-selector", default="", help="wait for this CSS selector before recording")
    parser.add_argument("--settle-ms", type=int, default=1200, help="wait after load before the timed hold")
    return parser.parse_args()


def transcode(source: Path, destination: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found; brew install ffmpeg")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0A0D13,setsar=1,fps=30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(destination),
        ],
        check=True,
    )


def main() -> int:
    args = parse_args()
    if args.seconds <= 0:
        print("error: --seconds must be positive", file=sys.stderr)
        return 2

    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    video_dir = Path(tempfile.mkdtemp(prefix="ei-page-video-"))

    page = None
    context = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                context = browser.new_context(
                    viewport={"width": args.width, "height": args.height},
                    device_scale_factor=1,
                    record_video_dir=str(video_dir),
                    record_video_size={"width": args.width, "height": args.height},
                )
                page = context.new_page()
                page.goto(args.url, wait_until="load", timeout=45000)
                if args.wait_selector:
                    page.wait_for_selector(args.wait_selector, timeout=20000)
                page.wait_for_timeout(args.settle_ms)

                reload_at = args.reload_at
                if reload_at > 0:
                    before = max(0.0, reload_at - args.settle_ms / 1000.0)
                    page.wait_for_timeout(int(before * 1000))
                    page.reload(wait_until="load", timeout=45000)
                    if args.wait_selector:
                        page.wait_for_selector(args.wait_selector, timeout=20000)
                    remaining = max(0.0, args.seconds - reload_at)
                else:
                    remaining = max(0.0, args.seconds - args.settle_ms / 1000.0)

                page.wait_for_timeout(int(remaining * 1000))
                context.close()
                context = None

                if page.video is None:
                    raise RuntimeError("Playwright did not attach a video recorder")
                webm = video_dir / "page.webm"
                page.video.save_as(str(webm))
                page = None

                if output.suffix.lower() == ".mp4":
                    transcode(webm, output)
                else:
                    shutil.copyfile(webm, output)
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
    except Exception as exc:
        print(f"error: could not record {args.url}: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(video_dir, ignore_errors=True)

    if not output.is_file():
        print(f"error: no recording written to {output}", file=sys.stderr)
        return 1

    print(f"wrote {output} ({output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
