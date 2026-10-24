"""Minimal Telegram Bot API client.

Only the three calls this integration needs are implemented: ``getMe``,
``sendMessage`` and ``setWebhook``. The client is deliberately dumb — it knows
nothing about Sentinel data, accounts or subscriptions — so no business logic can
leak into the transport layer.

Two behaviours matter for the rest of the system:

* **A failure is never fatal.** ``TelegramUnavailable`` is raised and the caller
  decides; nothing here raises into the analytics request path.
* **Temporary failures are retried, permanent ones are not.** A 5xx or a network
  error is retried with a short backoff; a 4xx (bad token, blocked chat) is
  returned immediately, because retrying cannot help.

The token is read from settings and never logged.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from backend.app.config import Settings

logger = logging.getLogger("aeza.telegram")


class TelegramError(Exception):
    """Base class for Telegram integration failures."""


class TelegramUnavailable(TelegramError):
    """The Bot API could not be reached, or failed after the retries."""


class TelegramRejected(TelegramError):
    """The Bot API answered but refused the request (permanent)."""

    def __init__(self, description: str, status: int = 400):
        super().__init__(description)
        self.status = status
        self.description = description


class TelegramClient:
    """Synchronous Bot API client.

    ``opener`` is injectable so tests can drive the client with a stub transport
    instead of reaching the real API.
    """

    def __init__(self, settings: Settings, *, opener=None):
        self.settings = settings
        self._opener = opener or urllib.request.urlopen

    @property
    def configured(self) -> bool:
        return bool(self.settings.telegram_bot_token.strip())

    def _url(self, method: str) -> str:
        base = self.settings.telegram_api_base.rstrip("/")
        return f"{base}/bot{self.settings.telegram_bot_token}/{method}"

    def call(self, method: str, payload: dict | None = None) -> dict:
        """Call one Bot API method and return its ``result``.

        Raises :class:`TelegramUnavailable` when the network fails after the
        retries, and :class:`TelegramRejected` when Telegram refuses the call.
        """

        if not self.configured:
            raise TelegramUnavailable("TELEGRAM_BOT_TOKEN не задан")

        body = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            self._url(method),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        attempts = self.settings.telegram_max_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with self._opener(request, timeout=self.settings.telegram_timeout_seconds) as response:
                    raw = response.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as exc:
                detail = _describe(exc)
                # 4xx is permanent: the token is wrong or the chat is blocked.
                if 400 <= exc.code < 500:
                    raise TelegramRejected(detail, exc.code) from exc
                last_error = TelegramUnavailable(f"Telegram ответил {exc.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = TelegramUnavailable(f"Telegram недоступен: {exc}")
            if attempt + 1 < attempts:
                time.sleep(min(0.5 * (attempt + 1), 2.0))
        else:
            raise last_error or TelegramUnavailable("Telegram недоступен")

        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise TelegramUnavailable("Telegram вернул не JSON") from exc
        if not parsed.get("ok"):
            raise TelegramRejected(str(parsed.get("description") or "Telegram отклонил запрос"))
        return parsed.get("result") or {}

    # -- thin wrappers ------------------------------------------------------ #

    def get_me(self) -> dict:
        return self.call("getMe")

    def send_message(self, chat_id: str, text: str, *, disable_preview: bool = True) -> dict:
        """Send plain text.

        The text is sent without ``parse_mode`` so a customer name or any other
        field can never inject markup into the message.
        """

        return self.call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_preview,
        })

    def set_webhook(self, url: str, secret_token: str) -> dict:
        return self.call("setWebhook", {
            "url": url,
            "secret_token": secret_token,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        })

    def delete_webhook(self) -> dict:
        return self.call("deleteWebhook", {"drop_pending_updates": False})


def _describe(exc: urllib.error.HTTPError) -> str:
    """Best-effort description from a Telegram error body, never the raw token."""

    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
        return str(payload.get("description") or f"HTTP {exc.code}")
    except Exception:
        return f"HTTP {exc.code}"


def escape_text(value: object) -> str:
    """Flatten an arbitrary value into a single safe line of plain text.

    Telegram messages are sent without ``parse_mode``, so no markup can execute;
    this only strips control characters and bounds the length so one long field
    cannot push a message past the API limit.
    """

    text = " ".join(str(value).split())
    return text[:400]
