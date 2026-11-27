#!/usr/bin/env python3
"""Generate 1920x1080 transparent caption strips for the draft cut."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
OUT = Path(__file__).resolve().parent / "work" / "captions"
OUT.mkdir(parents=True, exist_ok=True)
SANS = "/System/Library/Fonts/SFNS.ttf"
MONO = "/System/Library/Fonts/SFNSMono.ttf"

CAPTIONS = {
    "storefront": ("SIMULATED TRAFFIC · synthetic identities · local Flagsmith", (139, 153, 172)),
    "before": ("AUDIT · 500 identities · Jaccard 1.00 · 250 / 250 shared", (255, 92, 92)),
    "after": ("VERIFY · 0 shared users · Jaccard 0.00 · pass true", (61, 224, 164)),
    "panel": ("BEFORE 100% → AFTER 0% · 100 points of overlap removed", (61, 224, 164)),
    "receipt": ("RECEIPT FILE · 110 tokens · phase sum 991 · pass true", (103, 200, 255)),
    "flagsmith": ("FLAGSMITH · exp_iso_0_49 / exp_iso_50_99 · both running", (61, 224, 164)),
}


def main() -> int:
    font = ImageFont.truetype(SANS, 25)
    brand = ImageFont.truetype(MONO, 13)
    for name, (text, accent) in CAPTIONS.items():
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 1003, W, H], fill=(7, 10, 15, 236))
        draw.rectangle([0, 1003, W, 1004], fill=(*accent, 110))
        draw.rectangle([64, 1024, 68, 1056], fill=(*accent, 255))
        draw.text((88, 1026), text, font=font, fill=(236, 242, 249, 255))
        label = "EXPERIMENT ISOLATION"
        tw = draw.textlength(label, font=brand)
        draw.text((W - 64 - tw, 1032), label, font=brand, fill=(105, 119, 136, 255))
        path = OUT / f"caption-{name}.png"
        img.save(path)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
