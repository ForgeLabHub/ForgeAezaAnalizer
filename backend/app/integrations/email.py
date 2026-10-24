"""Outbound e-mail through the SMTP.BZ HTTP API.

This is the single place in the product that talks to an e-mail provider. It is
deliberately a thin, explicit client: the analytics engine never sends mail, and
nothing here recomputes risk, money or scores.

Contract (from the provider's own Swagger document, ``api.smtp.bz`` base path
``/v1``):

* ``POST https://api.smtp.bz/v1/smtp/send``
* the API key travels in the ``Authorization`` header, verbatim — no ``Bearer``
  prefix;
* the body carries ``from``, ``name``, ``subject``, ``to`` and ``html`` (the
  provider accepts both ``application/json`` and ``multipart/form-data``; JSON is
  used here).

Rules this module enforces:

1. **The key is never echoed.** It is read from configuration, placed in the
   request header and never logged, returned or embedded in an error message.
2. **A success is a confirmed success.** A non-2xx answer, an unreadable body, a
   timeout or a transport failure all raise; the caller is never told a letter
   went out when the provider did not accept it.
3. **Absence is honest.** With no key configured the module raises
   :class:`EmailDisabled` (mapped to ``503``), exactly like the optional AI
   surfaces, so the rest of the product keeps working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.config import Settings

#: A deliberately small e-mail shape check. The provider performs the real
#: validation; this only rejects input that could never be an address.
_ADDRESS_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


class EmailError(Exception):
    """Base class for SMTP.BZ failures."""


class EmailDisabled(EmailError):
    """SMTP.BZ is not configured, so nothing was sent."""


class EmailRejected(EmailError):
    """The provider answered but did not accept the message (4xx / refusal)."""


class EmailUnavailable(EmailError):
    """The provider could not be reached, timed out, or failed (5xx)."""


@dataclass(frozen=True)
class EmailResult:
    """A confirmed send. ``message_id`` is whatever the provider returned."""

    accepted: bool
    message_id: str | None
    status_code: int
    provider: str = "smtp.bz"

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "messageId": self.message_id,
            "statusCode": self.status_code,
            "provider": self.provider,
        }


def _check_header_value(value: str, field: str) -> str:
    """Reject CR/LF so a value cannot inject extra mail headers."""

    if "\r" in value or "\n" in value:
        raise EmailRejected(f"Недопустимый перевод строки в поле «{field}»")
    return value


def _check_address(value: str, field: str) -> str:
    candidate = (value or "").strip()
    if not _ADDRESS_RE.match(candidate):
        raise EmailRejected(f"Некорректный e-mail в поле «{field}»")
    return _check_header_value(candidate, field)


def _extract_message_id(payload: Any) -> str | None:
    """Pull a message id out of the provider's answer, if it gave one."""

    if not isinstance(payload, dict):
        return None
    for key in ("messageId", "message_id", "id", "uuid"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    result = payload.get("result")
    if isinstance(result, dict):
        return _extract_message_id(result)
    return None


def _failure_reason(payload: Any) -> str | None:
    """Return the provider's own error text, when the body carries one."""

    if not isinstance(payload, dict):
        return None
    for key in ("message", "error", "detail", "msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("message") or value.get("detail")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _interpret(response: httpx.Response) -> EmailResult:
    """Turn a provider response into a result or a precise exception."""

    status = response.status_code
    payload: Any = None
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if status in (401, 403):
        raise EmailRejected("SMTP.BZ отклонил ключ API (проверьте SMTP_BZ_API_KEY)")
    if status >= 500:
        raise EmailUnavailable(f"SMTP.BZ вернул ошибку сервера (HTTP {status})")
    if status >= 400:
        reason = _failure_reason(payload)
        suffix = f": {reason}" if reason else ""
        raise EmailRejected(f"SMTP.BZ отклонил письмо (HTTP {status}){suffix}")

    # A 2xx is the provider's confirmation. If the body explicitly denies the
    # send, trust the body over the status code and fail loudly.
    if isinstance(payload, dict):
        result = payload.get("result")
        if result is False or (result is None and payload.get("error")):
            reason = _failure_reason(payload) or "провайдер не подтвердил отправку"
            raise EmailRejected(reason)

    return EmailResult(accepted=True, message_id=_extract_message_id(payload), status_code=status)


def send_email(
    settings: Settings,
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    to_name: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> EmailResult:
    """Send one transactional letter and return the provider's confirmation.

    Raises :class:`EmailDisabled` when unconfigured, :class:`EmailRejected` when
    the provider refuses the message, and :class:`EmailUnavailable` when it
    cannot be reached. The API key is only ever placed in the request header.
    """

    if not settings.email_configured:
        raise EmailDisabled("Отправка почты не настроена (задайте SMTP_BZ_API_KEY и SMTP_BZ_FROM_EMAIL)")

    recipient = _check_address(to, "to")
    sender = _check_address(settings.smtp_bz_from_email, "from")
    checked_subject = _check_header_value((subject or "").strip(), "subject")
    if not checked_subject:
        raise EmailRejected("Тема письма не может быть пустой")
    if not (html or "").strip():
        raise EmailRejected("HTML-версия письма не может быть пустой")

    payload: dict[str, Any] = {
        "from": sender,
        "subject": checked_subject,
        "to": recipient,
        "html": html,
    }
    if settings.smtp_bz_from_name:
        payload["name"] = settings.smtp_bz_from_name
    if to_name:
        payload["to_name"] = to_name
    if text:
        payload["text"] = text

    headers = {
        "Authorization": settings.smtp_bz_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        with httpx.Client(
            timeout=settings.smtp_bz_timeout_seconds,
            transport=transport,
        ) as client:
            response = client.post(settings.smtp_bz_api_url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise EmailUnavailable("SMTP.BZ не ответил вовремя") from exc
    except httpx.HTTPError as exc:
        raise EmailUnavailable("SMTP.BZ недоступен") from exc

    return _interpret(response)


def describe(settings: Settings) -> dict[str, Any]:
    """Configuration status for operators. Never includes the API key."""

    return {
        "configured": settings.email_configured,
        "provider": "smtp.bz",
        "apiUrl": settings.smtp_bz_api_url,
        "fromEmail": settings.smtp_bz_from_email or None,
        "fromName": settings.smtp_bz_from_name or None,
        "timeoutSeconds": settings.smtp_bz_timeout_seconds,
        "keyPresent": bool(settings.smtp_bz_api_key),
        "requirements": (
            "Адрес отправителя должен принадлежать домену, верифицированному в панели SMTP.BZ "
            "(раздел «Домены отправителя»), а исходящий IP сервера — быть в разрешённом списке "
            "SMTP.BZ. Иначе провайдер отклонит отправку."
        ),
    }
