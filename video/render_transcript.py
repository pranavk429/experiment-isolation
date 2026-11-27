#!/usr/bin/env python3
"""Render a terminal capture to a 1920x1080 MP4.

Inputs:
  * asciinema v2 .cast (real event timing)
  * BSD/macOS 'script' .typescript (fixed per-line timing)

This exists because asciinema and agg are not installed on this machine. It is a
renderer for a real captured session, not a way to invent one. Long gaps are
capped so a slow command does not become dead air; the README says to cut waits,
not proof, in the edit.

Usage:
    python3 video/render_transcript.py video/captures/take.typescript \
        --out video/captures/take.mp4
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1920
HEIGHT = 1080
PROMPT = "experiment-isolation $"
LINE_HEIGHT = 42
MARGIN_X = 72
TEXT_TOP = 142
TEXT_BOTTOM = HEIGHT - 86
MAX_ROWS = (TEXT_BOTTOM - TEXT_TOP) // LINE_HEIGHT

BG = (10, 13, 19)
HEADER = (13, 18, 25)
LINE = (29, 39, 52)
INK = (235, 242, 250)
SOFT = (198, 210, 225)
DIM = (112, 126, 143)
CYAN = (103, 200, 255)
RED = (255, 92, 92)
GREEN = (61, 224, 164)
AMBER = (255, 196, 87)
JSON_INK = (169, 199, 232)

ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_ESC = re.compile(r"\x1b[@-_]")


def strip_ansi(text: str) -> str:
    text = ANSI_OSC.sub("", text)
    text = ANSI_CSI.sub("", text)
    text = ANSI_ESC.sub("", text)
    return text


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def apply_controls(text: str) -> str:
    """Apply backspaces and drop terminal control bytes, keeping tabs readable."""
    out: List[str] = []
    for char in text:
        if char == "\x08":
            if out:
                out.pop()
        elif char == "\t":
            out.append("    ")
        elif char in ("\x00", "\x04", "\x07"):
            continue
        elif char >= " " or char == "\n":
            out.append(char)
    return "".join(out)


def collapse_blank_lines(lines: Sequence[Tuple[str, float]]) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    for text, hold in lines:
        if text == "" and out and out[-1][0] == "":
            continue
        out.append((text, hold))
    while out and out[0][0] == "":
        out.pop(0)
    while out and out[-1][0] == "":
        out.pop()
    return out


def load_typescript(path: Path, base_delay: float) -> List[Tuple[str, float]]:
    raw = path.read_bytes().decode("utf-8", "replace")
    raw = strip_ansi(raw).replace("\r\n", "\n")

    lines: List[str] = []
    for chunk in raw.split("\n"):
        if chunk.startswith("Script started on") or chunk.startswith("Script done on"):
            continue
        # A bare carriage return means the line was redrawn; keep the final state.
        chunk = chunk.split("\r")[-1]
        lines.append(apply_controls(chunk).rstrip())

    timed: List[Tuple[str, float]] = []
    for text in lines:
        if text.startswith(PROMPT):
            hold = base_delay * 2.2
        elif text == "":
            hold = 0.16
        elif text.lstrip().startswith(("{", "}", '"')):
            hold = base_delay * 1.15
        else:
            hold = base_delay
        timed.append((text, clamp(hold, 0.12, 1.6)))

    return collapse_blank_lines(timed)


def load_cast(path: Path, min_hold: float, max_hold: float) -> List[Tuple[str, float]]:
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not raw_lines:
        raise ValueError("cast file is empty")

    try:
        header = json.loads(raw_lines[0])
    except json.JSONDecodeError as exc:
        raise ValueError(f"cast header is not JSON: {exc}") from exc
    if header.get("version") != 2:
        print(f"warning: unexpected cast version {header.get('version')!r}; trying v2 parsing", file=sys.stderr)

    line_events: List[Tuple[str, float]] = []
    buffer = ""
    cr_pending = False
    last_time = 0.0

    for raw in raw_lines[1:]:
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, list) or len(event) < 3 or event[1] != "o":
            continue
        try:
            timestamp = float(event[0])
        except (TypeError, ValueError):
            continue
        last_time = timestamp
        data = strip_ansi(str(event[2]))

        for char in data:
            if char == "\n":
                # CRLF is a line ending; a CR followed by text is a redraw.
                line_events.append((apply_controls(buffer).rstrip(), timestamp))
                buffer = ""
                cr_pending = False
            elif char == "\r":
                cr_pending = True
            else:
                if cr_pending:
                    buffer = ""
                    cr_pending = False
                if char == "\x08":
                    buffer = buffer[:-1]
                elif char == "\t":
                    buffer += "    "
                elif char in ("\x00", "\x04", "\x07"):
                    continue
                elif char >= " ":
                    buffer += char

    if buffer.strip():
        line_events.append((apply_controls(buffer).rstrip(), last_time))

    timed: List[Tuple[str, float]] = []
    for index, (text, timestamp) in enumerate(line_events):
        next_time = line_events[index + 1][1] if index + 1 < len(line_events) else timestamp + 1.5
        hold = clamp(next_time - timestamp, min_hold, max_hold)
        timed.append((text, hold))

    return collapse_blank_lines(timed)


def font_path(mono: bool) -> str:
    candidates = (
        [
            "/System/Library/Fonts/SFNSMono.ttf",
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Supplemental/Menlo.ttc",
        ]
        if mono
        else [
            "/System/Library/Fonts/SFNS.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("no system font found (tried SF Mono, Menlo, SF Pro)")


def load_font(size: int, mono: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path(mono), size)


class TerminalRenderer:
    def __init__(self, title: str, footer: str, watermark: str, font_size: int) -> None:
        self.title = title
        self.footer = footer
        self.watermark = watermark
        self.mono = load_font(font_size, mono=True)
        self.mono_small = load_font(17, mono=True)
        self.title_font = load_font(20, mono=False)
        self.footer_font = load_font(16, mono=False)
        self.measure_draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        self.max_width = WIDTH - 2 * MARGIN_X
        self.prompt_width = self.measure(PROMPT + " ")

    def measure(self, text: str) -> float:
        return self.measure_draw.textlength(text, font=self.mono)

    def wrap(self, text: str, width: float) -> List[str]:
        if text == "":
            return [""]
        if width <= self.measure("m"):
            width = self.max_width

        words = text.split(" ")
        rows: List[str] = []
        current = ""

        for word in words:
            candidate = word if current == "" else current + " " + word
            if self.measure(candidate) <= width:
                current = candidate
                continue

            if current:
                rows.append(current)
                current = ""

            if self.measure(word) <= width:
                current = word
                continue

            # A single token longer than the row: hard-split it by character.
            piece = ""
            for char in word:
                if self.measure(piece + char) <= width:
                    piece += char
                else:
                    if piece:
                        rows.append(piece)
                    piece = char
            current = piece

        if current or not rows:
            rows.append(current)
        return rows

    def color_for(self, text: str) -> Tuple[int, int, int]:
        stripped = text.strip()
        if "[exit " in text or re.search(r"exit=([1-9][0-9]*)", text):
            return RED
        if stripped.startswith(("{", "}", '"')) or stripped.startswith("["):
            return JSON_INK
        return SOFT

    def layout_line(self, text: str) -> List[Tuple[List[Tuple[str, Tuple[int, int, int]]], float]]:
        if text.startswith(PROMPT):
            rest = text[len(PROMPT):].lstrip()
            available = self.max_width - self.prompt_width
            chunks = self.wrap(rest, available)
            rows: List[Tuple[List[Tuple[str, Tuple[int, int, int]]], float]] = []
            for index, chunk in enumerate(chunks):
                if index == 0:
                    rows.append(([(PROMPT + " ", CYAN), (chunk, INK)], 0.0))
                else:
                    rows.append(([(chunk, INK)], self.prompt_width))
            return rows

        if text == "":
            return [([("", SOFT)], 0.0)]

        leading = len(text) - len(text.lstrip(" "))
        indent = min(self.measure(" " * leading), 160.0)
        body = text.lstrip(" ")
        chunks = self.wrap(body, self.max_width - indent)
        color = self.color_for(text)
        return [([(chunk, color)], indent) for chunk in chunks]

    def draw_frame(self, rows: Sequence[Tuple[List[Tuple[str, Tuple[int, int, int]]], float]], elapsed: float) -> Image.Image:
        image = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(image)

        draw.rectangle([0, 0, WIDTH, 78], fill=HEADER)
        draw.line([0, 78, WIDTH, 78], fill=LINE)
        for index, color in enumerate((RED, AMBER, GREEN)):
            x = 48 + index * 24
            draw.ellipse([x, 34, x + 10, 44], fill=color)

        draw.text((130, 28), self.title, font=self.title_font, fill=SOFT)

        if self.watermark:
            text_width = draw.textlength(self.watermark, font=self.mono_small)
            box_right = WIDTH - 48
            box_left = box_right - text_width - 26
            draw.rounded_rectangle(
                [box_left, 23, box_right, 55],
                radius=6,
                fill=(38, 31, 14),
                outline=(96, 74, 28),
            )
            draw.text((box_left + 13, 31), self.watermark, font=self.mono_small, fill=AMBER)
        else:
            right = "captured terminal · synthetic identities"
            right_width = draw.textlength(right, font=self.footer_font)
            draw.text((WIDTH - 48 - right_width, 31), right, font=self.footer_font, fill=DIM)

        visible = list(rows)[-MAX_ROWS:]
        y = TEXT_TOP
        for segments, indent in visible:
            x = MARGIN_X + indent
            for segment, color in segments:
                if segment:
                    draw.text((x, y), segment, font=self.mono, fill=color)
                    x += draw.textlength(segment, font=self.mono)
            y += LINE_HEIGHT

        draw.line([MARGIN_X, HEIGHT - 64, WIDTH - MARGIN_X, HEIGHT - 64], fill=LINE)
        draw.text((MARGIN_X, HEIGHT - 47), self.footer, font=self.footer_font, fill=DIM)

        minutes, seconds = divmod(int(elapsed), 60)
        stamp = f"{minutes:02d}:{seconds:02d}"
        stamp_width = draw.textlength(stamp, font=self.footer_font)
        draw.text((WIDTH - MARGIN_X - stamp_width, HEIGHT - 47), stamp, font=self.footer_font, fill=DIM)

        if len(rows) > MAX_ROWS:
            hint = "later output"
            hint_width = draw.textlength(hint, font=self.mono_small)
            draw.text((WIDTH - MARGIN_X - hint_width, 96), hint, font=self.mono_small, fill=(58, 70, 86))

        return image


def ffmpeg_path() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found (brew install ffmpeg)")
    return found


def render_video(frames: Sequence[Tuple[Path, float]], output: Path, fps: int) -> None:
    if not frames:
        raise ValueError("no frames to render")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        list_path = Path(handle.name)

        def quote(value: Path) -> str:
            return str(value).replace("'", "'\\''")

        for image_path, duration in frames:
            handle.write(f"file '{quote(image_path)}'\n")
            handle.write(f"duration {duration:.3f}\n")
        # Concat needs the final image listed twice so its duration is honoured.
        handle.write(f"file '{quote(frames[-1][0])}'\n")
        handle.write("duration 1.600\n")

    try:
        subprocess.run(
            [
                ffmpeg_path(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-vf",
                f"fps={fps},format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
        )
    finally:
        list_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a terminal capture to a 1920x1080 MP4.")
    parser.add_argument("capture", help=".cast or .typescript file")
    parser.add_argument("--out", required=True, help="output MP4 path")
    parser.add_argument("--title", default="experiment-isolation — terminal", help="header title")
    parser.add_argument("--footer", default="Experiment Isolation · local Flagsmith", help="footer text")
    parser.add_argument(
        "--watermark",
        default="",
        help="amber header label, e.g. PIPELINE TEST — PLACEHOLDER OUTPUT",
    )
    parser.add_argument("--font-size", type=int, default=30, help="terminal font size (default 30)")
    parser.add_argument("--line-delay", type=float, default=0.46, help="seconds per line for .typescript")
    parser.add_argument("--min-hold", type=float, default=0.28, help="minimum per-line hold for .cast")
    parser.add_argument("--max-hold", type=float, default=2.40, help="maximum per-line hold for .cast")
    parser.add_argument("--fps", type=int, default=30, help="output frame rate (default 30)")
    parser.add_argument("--keep-frames", action="store_true", help="keep the temporary PNG frames")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capture = Path(args.capture).expanduser().resolve()
    if not capture.is_file():
        print(f"error: capture not found: {capture}", file=sys.stderr)
        return 2

    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        if capture.suffix.lower() == ".cast":
            lines = load_cast(capture, min_hold=args.min_hold, max_hold=args.max_hold)
        else:
            lines = load_typescript(capture, base_delay=args.line_delay)
    except Exception as exc:
        print(f"error: could not parse {capture}: {exc}", file=sys.stderr)
        return 1

    if not lines:
        print(f"error: no terminal lines in {capture}", file=sys.stderr)
        return 1

    renderer = TerminalRenderer(args.title, args.footer, args.watermark, args.font_size)
    row_states: List[Tuple[List[Tuple[List[Tuple[str, Tuple[int, int, int]]], float]], float, float]] = []
    all_rows: List[Tuple[List[Tuple[str, Tuple[int, int, int]]], float]] = []
    elapsed = 0.0

    for text, hold in lines:
        all_rows.extend(renderer.layout_line(text))
        elapsed += hold
        row_states.append((list(all_rows), hold, elapsed))

    frame_dir = Path(tempfile.mkdtemp(prefix="ei-transcript-"))
    frame_files: List[Tuple[Path, float]] = []

    try:
        for index, (rows, hold, stamp) in enumerate(row_states):
            image = renderer.draw_frame(rows, stamp)
            frame_path = frame_dir / f"frame_{index:05d}.png"
            image.save(frame_path, "PNG", optimize=True)
            frame_files.append((frame_path, hold))

        print(f"rendering {len(frame_files)} frames ({elapsed:.1f}s) -> {output}")
        render_video(frame_files, output, args.fps)
    except subprocess.CalledProcessError as exc:
        print(f"error: ffmpeg failed with exit {exc.returncode}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if args.keep_frames:
            print(f"frames kept in {frame_dir}")
        else:
            shutil.rmtree(frame_dir, ignore_errors=True)

    if not output.is_file():
        print(f"error: no MP4 written to {output}", file=sys.stderr)
        return 1

    print(f"wrote {output} ({output.stat().st_size:,} bytes, {WIDTH}x{HEIGHT}, {args.fps} fps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
