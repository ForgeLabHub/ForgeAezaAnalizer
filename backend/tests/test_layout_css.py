"""Layout regression tests for the stylesheet.

The deployed dashboard scrolled sideways on narrow viewports because two CSS
grids used a bare ``1fr`` track: a bare ``1fr`` is ``minmax(auto, 1fr)`` and
cannot shrink below its content, so a wide table inside the grid pushed the
whole page wider than the viewport. The same class of bug hit the header, whose
nowrap nav links made the flex item unable to shrink.

These tests read the real stylesheet and fail if the shrink-safe form is
replaced. They are cheap and do not need a browser; the browser check lives in
the production acceptance audit.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")


SHRINK_SENSITIVE = (".grid-2", ".grid-main")


def _rules(selector: str) -> list[str]:
    """Return every declaration block whose selector list contains ``selector``."""

    blocks = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        selectors = [s.strip() for s in match.group(1).split(",")]
        if any(s == selector or s.endswith(selector) for s in selectors):
            blocks.append(match.group(2))
    return blocks


def test_grids_use_a_shrink_safe_first_track():
    for selector in SHRINK_SENSITIVE:
        blocks = _rules(selector)
        assert blocks, f"{selector} has no rule in styles.css"
        for body in blocks:
            cols = re.search(r"grid-template-columns:\s*([^;]+);", body)
            if not cols:
                continue
            value = cols.group(1).strip()


            remainder = re.sub(r"minmax\([^)]*\)", "", value)
            assert "1fr" not in remainder, (
                f"{selector} uses a bare 1fr track ({value!r}); use minmax(0, 1fr) "
                "so wide content scrolls inside its own container"
            )


def test_header_nav_can_shrink():
    blocks = _rules(".app-nav")
    assert blocks, ".app-nav has no rule"
    assert any("min-width: 0" in b for b in blocks), (
        ".app-nav needs min-width: 0, otherwise its nowrap links overflow the "
        "header and the page scrolls sideways"
    )


def test_table_wrapper_scrolls_instead_of_the_page():
    blocks = _rules(".table-wrap")
    assert blocks, ".table-wrap has no rule"
    assert any("overflow-x: auto" in b for b in blocks), (
        ".table-wrap must scroll horizontally itself so the page does not"
    )
