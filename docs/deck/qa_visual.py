"""Pixel-level QA on the rendered slides (stdlib + Pillow only).

I cannot look at the PNGs myself, so this measures what a human reviewer would
judge by eye:

  * effective resolution of every placed screenshot (px per inch on the slide),
    which decides whether UI text stays legible on a projector;
  * the largest empty horizontal band inside the content area (wasted space or
    broken visual balance);
  * ink coverage per slide, to catch a slide that is nearly blank or overloaded;
  * contrast ratio of every text colour against its background;
  * ink bleeding into the outer safety ring of the canvas.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

EMU = 914400.0
DECK = Path(sys.argv[1] if len(sys.argv) > 1 else "aeza_umirhack_defense.pptx")
RENDER = Path("render") / DECK.stem


def inch(v) -> float:
    return v / EMU


def srgb(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(rgb) -> float:
    r, g, b = (srgb(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    prs = Presentation(DECK)
    sw, sh = inch(prs.slide_width), inch(prs.slide_height)
    issues: list[str] = []
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    print(f"=== {DECK.name} · {len(prs.slides._sldIdLst)} slides · {sw:.2f}x{sh:.2f}in")

    print("\n-- screenshot legibility (want >= 110 px/in) --")
    for idx, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                continue
            try:
                iw, ih = Image.open(io.BytesIO(shape.image.blob)).size
            except Exception:
                continue
            w_in, h_in = inch(shape.width), inch(shape.height)
            dx = iw / w_in if w_in else 0
            dy = ih / h_in if h_in else 0
            flag = "" if min(dx, dy) >= 110 else "   <-- LOW"
            print(f"  s{idx:02d} {w_in:5.2f}x{h_in:4.2f}in  src {iw:4d}x{ih:<4d} "
                  f"-> {dx:6.0f} x {dy:5.0f} px/in{flag}")
            if min(dx, dy) < 110:
                issues.append(f"s{idx:02d} screenshot {dx:.0f}x{dy:.0f} px/in")

    print("\n-- rendered slides --")
    files = sorted(RENDER.glob("slide-*.png"))
    if not files:
        print("  (no renders — run the LibreOffice + Ghostscript pipeline first)")
    for f in files:
        im = Image.open(f).convert("L")
        w, h = im.size
        px = im.load()
        cy0, cy1 = int(h * 0.03), int(h * 0.97)
        cx0, cx1 = int(w * 0.03), int(w * 0.97)
        step = max(1, w // 700)
        step_y = max(1, step // 2)
        # modal luminance in the content area = the page background, whatever
        # colour it is; "content" is anything far enough away from it
        from collections import Counter
        hist: Counter = Counter()
        for y in range(cy0, cy1, step_y):
            for x in range(cx0, cx1, step):
                hist[px[x, y] // 8] += 1
        bg_lvl = hist.most_common(1)[0][0] * 8 + 4
        rows = []
        dark_n = 0
        for y in range(cy0, cy1, step_y):
            n = 0
            tot = 0
            for x in range(cx0, cx1, step):
                tot += 1
                if abs(px[x, y] - bg_lvl) > 28:
                    n += 1
            rows.append((y, n / tot if tot else 0))
            dark_n += n
        sampled = len(rows)
        ink = dark_n / (sampled * max(1, (cx1 - cx0) // step)) * 100 if sampled else 0
        best = cur = 0
        for _, frac in rows:
            cur = cur + 1 if frac < 0.004 else 0
            best = max(best, cur)
        band_in = best * step_y / h * sh
        ring = 0
        ring_n = 0
        for x in range(0, w, step):
            for y in list(range(0, int(h * 0.012))) + list(range(int(h * 0.988), h)):
                ring_n += 1
                if px[x, y] < 200:
                    ring += 1
        edge = ring / ring_n * 100 if ring_n else 0
        print(f"  {f.name}: ink {ink:5.1f}%  biggest empty band {band_in:4.2f}in  "
              f"edge ink {edge:4.1f}%")
        if band_in > 1.9:
            issues.append(f"{f.name} empty band {band_in:.2f}in")
        if ink < 3.0:
            issues.append(f"{f.name} ink {ink:.1f}% (looks blank)")
        if ink > 40.0:
            issues.append(f"{f.name} ink {ink:.1f}% (overloaded)")

    print("\n-- contrast (>= 4.5 body, >= 3.0 large) --")
    # Read the real palette from the deck kit, so this check can never drift
    # away from the colours actually used on the slides.
    from deckkit import (CORAL, CORAL_DEEP, DIM, INK, INK_2, LINE, MINT,
                         MUTED, PAPER, TEXT, WHITE)

    def rgb(c):
        return (c[0], c[1], c[2])

    pairs = [
        ("body on paper", rgb(TEXT), rgb(PAPER)),
        ("muted on paper", rgb(MUTED), rgb(PAPER)),
        ("muted on white", rgb(MUTED), rgb(WHITE)),
        ("coral-deep on paper", rgb(CORAL_DEEP), rgb(PAPER)),
        ("coral-deep on white", rgb(CORAL_DEEP), rgb(WHITE)),
        ("coral on ink", rgb(CORAL), rgb(INK)),
        ("white on ink", rgb(WHITE), rgb(INK)),
        ("soft on ink", rgb(LINE), rgb(INK)),
        ("dim on ink", rgb(DIM), rgb(INK)),
        ("dim on ink2", rgb(DIM), rgb(INK_2)),
        ("mint on ink", rgb(MINT), rgb(INK)),
        ("mint on ink2", rgb(MINT), rgb(INK_2)),
    ]
    for name, fg, bgc in pairs:
        r = contrast(fg, bgc)
        flag = "" if r >= 4.5 else ("  large-only" if r >= 3.0 else "  LOW")
        print(f"  {name:16s} {r:5.2f}:1{flag}")
        if r < 3.0:
            issues.append(f"contrast {name} {r:.2f}:1")

    print()
    if issues:
        print(f"ISSUES ({len(issues)}):")
        for i in issues:
            print("  ", i)
    else:
        print("no visual QA issues")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
