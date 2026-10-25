"""Render the @aezasentinelbot avatar.

Original artwork: a geometric Sentinel shield — a hexagonal shield outline with a
watchful eye at its centre, on the Aéza dark tile with the brand orange accent.
Designed to stay legible at 64 px in Telegram's circular crop, so it uses no text,
no fine gradients, and a single strong silhouette.

Usage:
    python docs/telegram/render_bot_avatar.py

Writes ``bot-avatar-512.png`` (Telegram accepts 512x512) and a 64 px preview next
to this file. Requires cairosvg and Pillow (already project dependencies).
"""

from __future__ import annotations

import io
from pathlib import Path

import cairosvg
from PIL import Image

HERE = Path(__file__).resolve().parent


BG = "#0b0d10"
ACCENT = "#ff6b00"
GLYPH = "#f5f6f7"

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <clipPath id="circle">
      <circle cx="256" cy="256" r="256"/>
    </clipPath>
  </defs>

  <g clip-path="url(#circle)">
    <rect width="512" height="512" fill="{BG}"/>

    <!-- Sentinel shield: a wide hexagon with a pointed base. -->
    <path d="M256 74
             L414 150
             L414 288
             C414 372 344 430 256 452
             C168 430 98 372 98 288
             L98 150 Z"
          fill="none" stroke="{GLYPH}" stroke-width="26" stroke-linejoin="round"/>

    <!-- Inner accent ring, echoing the brand orange. -->
    <path d="M256 128
             L366 180
             L366 288
             C366 344 318 384 256 402
             C194 384 146 344 146 288
             L146 180 Z"
          fill="none" stroke="{ACCENT}" stroke-width="10" stroke-linejoin="round" opacity="0.85"/>

    <!-- The watchful core: a vertical lens with a pupil. -->
    <path d="M256 196
             C298 216 316 244 316 268
             C316 300 290 328 256 344
             C222 328 196 300 196 268
             C196 244 214 216 256 196 Z"
          fill="{ACCENT}"/>
    <circle cx="256" cy="272" r="26" fill="{BG}"/>
    <circle cx="256" cy="272" r="10" fill="{GLYPH}"/>
  </g>
</svg>
"""


def render() -> None:
    png = cairosvg.svg2png(bytestring=SVG.encode("utf-8"), output_width=512, output_height=512)
    full = Image.open(io.BytesIO(png)).convert("RGBA")
    full.save(HERE / "bot-avatar-512.png")
    small = full.resize((64, 64), Image.LANCZOS)
    small.save(HERE / "bot-avatar-64.png")
    print(f"wrote {HERE / 'bot-avatar-512.png'} ({full.size[0]}x{full.size[1]})")
    print(f"wrote {HERE / 'bot-avatar-64.png'} (64x64 preview for the circular crop)")


if __name__ == "__main__":
    render()
