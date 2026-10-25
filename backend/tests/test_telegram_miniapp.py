"""Static invariants of the Telegram Mini App surface.

These are cheap file-level checks (no browser) for the two defects that made the
Mini App unusable in production:

* the Telegram Web App SDK was never loaded, so ``window.Telegram.WebApp`` did not
  exist and ``initData`` was always empty — the client could never authenticate;
* nginx sent ``X-Frame-Options: DENY``, which blocks the WebView iframe Telegram
  serves the Mini App in.

The browser check lives in the acceptance run; these tests keep the fix from being
reverted by accident.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
NGINX = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
MINI_APP = (ROOT / "frontend" / "src" / "pages" / "MiniAppPage.tsx").read_text(encoding="utf-8")


def test_index_loads_the_telegram_web_app_sdk():
    assert "telegram-web-app.js" in INDEX, (
        "index.html must load the Telegram Web App SDK, otherwise "
        "window.Telegram.WebApp is undefined and initData can never be obtained"
    )


def test_the_sdk_is_loaded_from_the_official_https_origin():
    match = re.search(r'<script[^>]+src="([^"]+telegram-web-app\.js)"', INDEX)
    assert match, "the SDK script tag must have a src"
    assert match.group(1).startswith("https://telegram.org/"), match.group(1)


def test_nginx_does_not_deny_framing_with_x_frame_options():

    directives = [line for line in NGINX.splitlines() if not line.strip().startswith("#")]
    joined = "\n".join(directives)
    assert "add_header X-Frame-Options" not in joined, (
        "X-Frame-Options cannot express an allow list; use CSP frame-ancestors so "
        "Telegram's WebView may embed the Mini App"
    )


def test_nginx_allows_telegram_to_frame_the_app_and_nothing_else():
    assert "frame-ancestors" in NGINX
    assert "web.telegram.org" in NGINX

    assert "frame-ancestors *" not in NGINX
    assert "frame-ancestors 'none'" not in NGINX


def test_mini_app_sends_signed_init_data_not_a_client_account_id():
    assert "clientSession(initData)" in MINI_APP, "the session must be exchanged for signed initData"


    assert "accountId" not in MINI_APP, "the Mini App must not send or accept a client accountId"


def test_mini_app_uses_the_telegram_viewport_and_theme():
    assert "viewportHeight" in MINI_APP, "the layout must track Telegram's real viewport height"
    assert "colorScheme" in MINI_APP, "the app must follow the Telegram theme"
    assert "--tg-viewport-height" in (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")


def test_mini_app_handles_a_missing_telegram_context_gracefully():

    assert "недоступны" in MINI_APP
