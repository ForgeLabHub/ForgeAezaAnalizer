from __future__ import annotations

import json
import logging
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger("aeza.telegram")


class IntegrationNotConfigured(RuntimeError):
    pass


class DeliveryError(RuntimeError):
    pass


class EmailProvider(Protocol):
    def send_otp(self, email: str, code: str, expires_in_seconds: int) -> None: ...


class UnconfiguredEmailProvider:
    def send_otp(self, email: str, code: str, expires_in_seconds: int) -> None:
        raise IntegrationNotConfigured("OTP email provider is not configured")


class TelegramProvider(Protocol):
    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> str: ...


class StubTelegramProvider:
    """Used when the bot is switched off.

    Raises instead of returning a fake message id, so a caller can never record a
    delivery that did not happen. The wording contains ``stub`` because the
    service keys off it to mark a delivery ``stubbed`` rather than ``failed``.
    """

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> str:
        raise IntegrationNotConfigured("Telegram Bot API is running in stub mode")


def _sanitize(message: str, token: str) -> str:
    """Strip the bot token (and the URL that carries it) from a message.

    ``urllib`` raises ``HTTPError`` whose ``.url`` is
    ``https://api.telegram.org/bot<token>/sendMessage``. Chaining that exception
    would put the token in every traceback and in any ``logger.exception`` line,
    so errors are reduced to a token-free summary before they leave this module.
    """

    if not message:
        return message
    cleaned = message
    if token:
        cleaned = cleaned.replace(token, "<redacted>")
        cleaned = cleaned.replace(f"bot{token}", "bot<redacted>")
    return cleaned


def _describe_http_error(exc: HTTPError, token: str) -> str:
    """A token-free summary of a Telegram HTTP error."""

    detail = ""
    try:
        body = exc.read().decode("utf-8", "replace")
        payload = json.loads(body)
        if isinstance(payload, dict):
            detail = str(payload.get("description") or "")
    except Exception:  # noqa: BLE001 - the body may be missing or not JSON
        detail = ""
    detail = _sanitize(detail, token)
    if detail:
        return f"HTTP {exc.code}: {detail}"
    return f"HTTP {exc.code}"


class TelegramBotApi:
    """Minimal Bot API client with bounded retries and token-safe errors.

    ``opener`` and ``sleep`` are injectable so tests drive the client without
    network access or real delays.
    """

    def __init__(self, token: str, timeout_seconds: float = 10, *, max_attempts: int = 3,
                 opener=None, sleep=time.sleep):
        if not token:
            raise ValueError("Telegram bot token is required")
        self._token = token
        self._timeout = timeout_seconds
        self._max_attempts = max(1, max_attempts)
        self._opener = opener or urlopen
        self._sleep = sleep

    def _call(self, method: str, payload: dict | None = None) -> dict:
        """Call one Bot API method, retrying only transient failures.

        A 429 honours ``Retry-After``; 5xx and network errors use exponential
        backoff. Any other 4xx is permanent and is raised immediately. Every error
        message is sanitized so the token never appears in it, and the original
        exception is deliberately **not** chained for the same reason.
        """

        url = f"https://api.telegram.org/bot{self._token}/{method}"
        body = json.dumps(payload or {}).encode()
        last_error = "Telegram API is unavailable"
        for attempt in range(1, self._max_attempts + 1):
            request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                try:
                    result = json.loads(raw)
                except ValueError:
                    raise DeliveryError("Telegram returned an unreadable response") from None
                if not isinstance(result, dict) or not result.get("ok"):
                    description = _sanitize(str((result or {}).get("description") or ""), self._token)
                    raise DeliveryError(
                        f"Telegram rejected the request: {description}" if description
                        else "Telegram rejected the request"
                    )
                return result.get("result") or {}
            except HTTPError as exc:
                summary = _describe_http_error(exc, self._token)
                retry_after = None
                if exc.code == 429:
                    try:
                        retry_after = int(exc.headers.get("Retry-After") or 0) or None
                    except (TypeError, ValueError):
                        retry_after = None
                if exc.code == 429 or exc.code >= 500:
                    last_error = summary
                    if attempt < self._max_attempts:
                        delay = retry_after if retry_after else min(2 ** attempt, 8)
                        logger.warning("telegram %s retryable failure (%s); retrying in %ss", method, summary, delay)
                        self._sleep(delay)
                        continue
                # Permanent, or retries exhausted: raise a token-free error.
                raise DeliveryError(f"Telegram API error: {summary}") from None
            except (URLError, TimeoutError, OSError) as exc:
                last_error = _sanitize(str(exc), self._token) or type(exc).__name__
                if attempt < self._max_attempts:
                    delay = min(2 ** attempt, 8)
                    logger.warning("telegram %s transport failure (%s); retrying in %ss", method, last_error, delay)
                    self._sleep(delay)
                    continue
                raise DeliveryError(f"Telegram API unreachable: {last_error}") from None
        raise DeliveryError(f"Telegram API error: {last_error}")

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> str:
        payload: dict = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result = self._call("sendMessage", payload)
        return str(result.get("message_id", ""))

    def get_me(self) -> dict:
        """Identify the bot. Used by diagnostics; the token is never returned."""

        return self._call("getMe")

    def set_webhook(self, url: str, secret_token: str, allowed_updates: list[str] | None = None) -> dict:
        payload: dict = {
            "url": url,
            "secret_token": secret_token,
            "allowed_updates": allowed_updates or ["message"],
            "drop_pending_updates": False,
        }
        return self._call("setWebhook", payload)

    def delete_webhook(self) -> dict:
        return self._call("deleteWebhook", {"drop_pending_updates": False})

    def get_webhook_info(self) -> dict:
        return self._call("getWebhookInfo")


def bot_api_host_ok(url: str) -> bool:
    """Guard for an operator-supplied API base: only the real Telegram host."""

    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == "api.telegram.org"
