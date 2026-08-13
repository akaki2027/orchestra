#!/usr/bin/env python3
"""Turn the supplied logo into a transparent mark.

The source art is gold on a near-black field. Compositing it with
`mix-blend-mode: screen` does not hide that field — screen is
1-(1-a)(1-b), so a 4% black over an 8% ground lands at 12% and the artwork
sits in a visibly lighter box. Only real alpha removes it.

The key is luminance-based rather than a flat colour match, so the soft edges
of the artwork fade out instead of leaving a hard cut. Gold is preserved at
full opacity; the field goes fully transparent; the transition between them
becomes partial alpha.

Build-time only. Pillow is NOT a runtime dependency and is deliberately absent
from requirements.txt:

    .venv/bin/python -m pip install Pillow
    .venv/bin/python scripts/build_mark.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("This script needs Pillow:  python -m pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "web" / "brand" / "orchestra-logo-source.png"
OUT_DIR = ROOT / "web" / "brand"

# Below FLOOR the pixel is background and goes fully transparent. Above CEILING
# it is artwork and stays opaque. Between them alpha ramps, which is what keeps
# the thin engraved lines from developing a hard black halo.
FLOOR = 26
CEILING = 78


def key_out(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size

    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            # Perceived luminance: the field is neutral-dark, the art is warm-bright.
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if lum <= FLOOR:
                px[x, y] = (r, g, b, 0)
            elif lum < CEILING:
                ramp = (lum - FLOOR) / (CEILING - FLOOR)
                px[x, y] = (r, g, b, int(a * ramp))
    return img


def main() -> int:
    if not SOURCE.exists():
        print(f"Missing source art at {SOURCE}", file=sys.stderr)
        return 1

    keyed = key_out(Image.open(SOURCE))

    # Trim the transparent margin so the mark fills its box and the header and
    # hall can size it by intent rather than around dead padding.
    bbox = keyed.getbbox()
    if bbox:
        keyed = keyed.crop(bbox)

    for name, size in (("orchestra-mark", 320), ("favicon", 64)):
        out = keyed.copy()
        out.thumbnail((size, size), Image.LANCZOS)
        # Square canvas so CSS width/height never distorts the art.
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(out, ((size - out.width) // 2, (size - out.height) // 2))
        canvas.save(OUT_DIR / f"{name}.png", optimize=True)
        if name == "orchestra-mark":
            canvas.save(OUT_DIR / f"{name}.webp", quality=90, method=6)

    print(f"Wrote transparent mark from {SOURCE.name}:")
    for f in ("orchestra-mark.png", "orchestra-mark.webp", "favicon.png"):
        print(f"  {f}  {(OUT_DIR / f).stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
