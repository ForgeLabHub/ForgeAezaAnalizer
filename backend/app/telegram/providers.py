from __future__ import annotations

import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> str:
        raise IntegrationNotConfigured("Telegram Bot API is running in stub mode")


class TelegramBotApi:
    def __init__(self, token: str, timeout_seconds: float = 10):
        if not token:
            raise ValueError("Telegram bot token is required")
        self._token = token
        self._timeout = timeout_seconds

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> str:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        request = Request(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                result = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise DeliveryError("Telegram message delivery failed") from exc
        if not result.get("ok") or not isinstance(result.get("result"), dict):
            raise DeliveryError("Telegram rejected the message")
        return str(result["result"].get("message_id", ""))
