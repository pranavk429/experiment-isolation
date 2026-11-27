#!/usr/bin/env python3
"""Render an HTML still to an exact 1920x1080 PNG with Playwright Chromium.

Usage:
    python3 video/render_still.py video/title.html --out video/stills/title.png
    python3 video/render_still.py video/endcard.html --out video/stills/endcard.png

Why Playwright: qlmanage thumbnails are square and re-pad the page; Chromium
honours the 1920x1080 viewport exactly. This script is only for stills. The
live dashboard is captured with browse.recording (see video/README.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an HTML file to a 1920x1080 PNG.")
    parser.add_argument("html", help="HTML file to render")
    parser.add_argument("--out", required=True, help="output PNG path")
    parser.add_argument("--width", type=int, default=1920, help="viewport width (default 1920)")
    parser.add_argument("--height", type=int, default=1080, help="viewport height (default 1080)")
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="device scale factor (use 2 only for a 2x review copy; final stills stay 1x)",
    )
    parser.add_argument("--wait-ms", type=int, default=350, help="settle time before capture")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.html).expanduser().resolve()
    if not source.is_file():
        print(f"error: HTML file not found: {source}", file=sys.stderr)
        return 2

    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(
                viewport={"width": args.width, "height": args.height},
                device_scale_factor=args.scale,
            )
            page.goto(source.as_uri(), wait_until="load")
            page.wait_for_timeout(args.wait_ms)
            page.screenshot(path=str(output), full_page=False)
            browser.close()
    except Exception as exc:  # Playwright raises several unrelated error types.
        print(f"error: could not render {source}: {exc}", file=sys.stderr)
        print("hint: python3 -m playwright install chromium", file=sys.stderr)
        return 1

    if not output.is_file():
        print(f"error: no PNG written to {output}", file=sys.stderr)
        return 1

    print(f"wrote {output} ({output.stat().st_size:,} bytes, {args.width}x{args.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
