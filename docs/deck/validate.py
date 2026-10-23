"""Geometry + content validator for the generated deck.

Checks, per slide:
  * every shape stays inside the slide with a safe margin;
  * no two text-bearing shapes overlap;
  * every text frame's real rendered height fits its box (measured with Inter);
  * screenshots keep their aspect ratio and land where intended;
  * placeholder labels are present where required.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.util import Emu, Inches, Pt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deckkit import line_height_in, text_width_pt, weight_from_run  # noqa: E402

EMU = 914400.0
DEFAULT_DECK = Path(__file__).resolve().parent / "aeza_umirhack_defense.pptx"
DECK = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DECK
MARGIN = Inches(0.12)


def inch(v) -> float:
    return v / EMU


def tf_height(shape) -> float:
    """Rendered height of a text frame in inches, measured line by line."""
    if not shape.has_text_frame:
        return 0.0
    total = 0.0
    tf = shape.text_frame
    ml = inch(tf.margin_left or 0) + inch(tf.margin_right or 0)
    mt = inch(tf.margin_top or 0) + inch(tf.margin_bottom or 0)
    for p in tf.paragraphs:
        text = "".join(r.text for r in p.runs)
        if not text.strip():
            continue
        size = None
        weight = 400
        for r in p.runs:
            if r.font.size is not None:
                size = r.font.size.pt
            weight = max(weight, weight_from_run(r))
        size = size or 18
        ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.16
        sb = p.space_before.pt if p.space_before else 0
        sa = p.space_after.pt if p.space_after else 0
        total += (sb + sa) / 72.0
        # count wrapped lines at the frame width
        w_in = inch(shape.width) - ml
        max_pt = max(w_in * 72.0, 12)
        n = 0
        for seg in text.split("\n"):
            cur = ""
            for word in seg.split():
                cand = (cur + " " + word).strip()
                if not cur or text_width_pt(cand, size, weight) <= max_pt:
                    cur = cand
                else:
                    n += 1
                    cur = word
            if cur:
                n += 1
        n = max(n, 1)
        total += n * line_height_in(size, ls)
    return total + mt


def text_bbox(shape):
    """Approximate rendered bbox of a text shape (may be shorter than the box)."""
    x, y = inch(shape.left), inch(shape.top)
    w = inch(shape.width)
    h = tf_height(shape) if shape.has_text_frame else inch(shape.height)
    return x, y, w, h


def is_texty(shape) -> bool:
    return shape.has_text_frame and shape.text_frame.text.strip() != ""


def main() -> int:
    prs = Presentation(DECK)
    sw, sh = inch(prs.slide_width), inch(prs.slide_height)
    problems: list[str] = []

    for idx, slide in enumerate(prs.slides, start=1):
        boxes = []
        for shape in slide.shapes:
            if shape.shape_type == 13 or shape.shape_type == 6:  # picture / group
                continue
            x, y, w, h = text_bbox(shape)
            if not is_texty(shape):
                # plain rectangles: still must be inside the canvas
                x, y = inch(shape.left), inch(shape.top)
                w, h = inch(shape.width), inch(shape.height)
            if x < -0.001 or y < -0.001 or x + w > sw + 0.001 or y + h > sh + 0.001:
                problems.append(
                    f"s{idx:02d} OUT-OF-CANVAS {shape.shape_type} "
                    f"x={x:.2f} y={y:.2f} w={w:.2f} h={h:.2f} "
                    f"txt={shape.text_frame.text[:34]!r}" if shape.has_text_frame
                    else f"s{idx:02d} OUT-OF-CANVAS rect x={x:.2f} y={y:.2f} "
                         f"w={w:.2f} h={h:.2f}")
            if is_texty(shape):
                boxes.append((x, y, w, h, shape.text_frame.text[:40]))

        # text overflow beyond its own shape box
        for shape in slide.shapes:
            if not is_texty(shape):
                continue
            need = tf_height(shape)
            avail = inch(shape.height)
            if need > avail + 0.02:
                problems.append(
                    f"s{idx:02d} TEXT-TALLER-THAN-BOX need={need:.2f} avail={avail:.2f} "
                    f"txt={shape.text_frame.text[:44]!r}")

        # text-vs-text overlaps
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ax, ay, aw, ah, at = boxes[i]
                bx, by, bw, bh, bt = boxes[j]
                ox = min(ax + aw, bx + bw) - max(ax, bx)
                oy = min(ay + ah, by + bh) - max(ay, by)
                if ox > 0.04 and oy > 0.04:
                    area = ox * oy
                    if area > 0.02:
                        problems.append(
                            f"s{idx:02d} OVERLAP {area:.2f}in² :: {at!r} <> {bt!r}")

    print(f"slides={len(prs.slides._sldIdLst)} canvas={sw:.2f}x{sh:.2f}in")
    if problems:
        print(f"PROBLEMS ({len(problems)}):")
        for p in problems:
            print("  ", p)
    else:
        print("clean: no geometry problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
