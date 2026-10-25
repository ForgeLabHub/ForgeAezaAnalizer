"""Re-capture the defence-deck screenshots from the running product.

The slides must show the same numbers the product shows, so the shots are taken
from the deployed stack rather than cropped from an older build.

    env -u LD_LIBRARY_PATH /tmp/deckenv/bin/python docs/deck/capture_shots.py [base_url]

The default base URL is the local nginx port.  Output overwrites the files in
docs/deck/shots/.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "shots"
CHROMIUM = "/usr/lib/chromium/chromium"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:12000"

EMAIL, PASSWORD = "analyst@aeza.test", "demo123"


def main() -> int:
    SHOTS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROMIUM,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--force-device-scale-factor=2"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000},
                                device_scale_factor=2)
        page.goto(f"{BASE}/login", wait_until="networkidle", timeout=60000)
        inputs = page.locator("input")
        inputs.nth(0).fill(EMAIL)
        inputs.nth(1).fill(PASSWORD)
        page.get_by_role("button", name="Войти").click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)


        page.goto(f"{BASE}/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)
        _dump(page, "dashboard")

        browser.close()
    return 0


def _dump(page, name: str) -> None:
    """Print the top-level structure so selectors can be chosen."""

    html = page.evaluate(
        "() => Array.from(document.querySelectorAll('section, .card, .metric, table, h2, h3'))"
        ".slice(0, 60).map(e => e.tagName + '.' + (e.className||'') + ' :: ' + "
        "(e.textContent||'').trim().slice(0,60))"
    )
    print(f"--- {name} ---")
    for line in html:
        print(line)


if __name__ == "__main__":
    raise SystemExit(main())
