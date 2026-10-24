"""Outbound e-mail for the product: Yandex Cloud Postbox or the SMTP.BZ HTTP API.

This is the single place in the product that talks to an e-mail provider. It is
deliberately a thin, explicit client: the analytics engine never sends mail, and
nothing here recomputes risk, money or scores.

Two transports sit behind one contract, selected by ``AEZA_EMAIL_PROVIDER``
(empty = auto: Postbox when configured, else SMTP.BZ). The choice is resolved
once in :attr:`Settings.active_email_provider`; there is no runtime failover, so
a confirmation can only ever come from the provider that was actually used.

* **Postbox** (Yandex Cloud, managed): SMTP to ``postbox.cloud.yandex.net``,
  implicit TLS on 465 or STARTTLS on 587. The API key id is the username and its
  secret the password; the key must carry the ``yc.postbox.send`` scope.
* **SMTP.BZ**: ``POST https://api.smtp.bz/v1/smtp/send``; the API key travels in
  the ``Authorization`` header verbatim (no ``Bearer`` prefix); the JSON body
  carries ``from``, ``name``, ``subject``, ``to`` and ``html``.

Rules this module enforces:

1. **No secret is ever echoed.** Credentials are read from configuration, placed
   in the transport and never logged, returned or embedded in an error message.
2. **A success is a confirmed success.** A non-2xx answer, an unreadable body, a
   timeout, a transport failure or an SMTP refusal all raise; the caller is never
   told a letter went out when the provider did not accept it.
3. **Absence is honest.** With no provider configured the module raises
   :class:`EmailDisabled` (mapped to ``503``), exactly like the optional AI
   surfaces, so the rest of the product keeps working.
"""

from __future__ import annotations

import html as html_lib
import re
import smtplib
import ssl
from dataclasses import dataclass, replace
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any

import httpx

from backend.app.config import Settings

# The Telegram OTP flow already defines the interface it calls
# (``EmailProvider.send_otp``) and the two exceptions it catches. The adapter
# below implements that exact contract so OTP can be sent through SMTP.BZ
# without changing or bypassing the existing Telegram service.
from backend.app.telegram.providers import DeliveryError, IntegrationNotConfigured

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


def is_valid_address(value: str) -> bool:
    """Shape check shared by the client and the HTTP routes.

    The provider performs the authoritative validation; this only rejects input
    that could never be an address, so a bad recipient is refused with ``422``
    at the route instead of becoming a ``502`` provider refusal.
    """

    return bool(_ADDRESS_RE.match((value or "").strip()))


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
    """Return the provider's own error text, when the body carries one.

    SMTP.BZ reports refusals as ``{"result": false, "errors": {"message": "..."}}``
    (e.g. "Domain ... not verified") or, for validation failures, as per-field
    messages ``{"errors": {"to": "Invalid or missing to address"}}``. Both shapes
    are surfaced so the reason an operator sees is the provider's own wording.
    """

    if not isinstance(payload, dict):
        return None
    for key in ("message", "error", "detail", "msg", "errors"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("message") or value.get("detail")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
            # Field-level validation errors: keep them, they name the bad field.
            fields = [text.strip() for text in value.values() if isinstance(text, str) and text.strip()]
            if fields:
                return "; ".join(fields)
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
    if status == 429:
        # Rate limiting is transient: the letter was not accepted, but the
        # provider is reachable, so this is "try again later", not "refused".
        raise EmailUnavailable("SMTP.BZ ограничил частоту запросов (HTTP 429)")
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
        if result is False or (result is None and (payload.get("error") or payload.get("errors"))):
            reason = _failure_reason(payload) or "провайдер не подтвердил отправку"
            raise EmailRejected(reason)

    return EmailResult(accepted=True, message_id=_extract_message_id(payload), status_code=status)


def _validate_message(settings: Settings, *, to: str, subject: str, html: str) -> tuple[str, str, str]:
    """Validate the parts common to every transport and return (to, from, subject)."""

    recipient = _check_address(to, "to")
    sender = _check_address(_from_address(settings), "from")
    checked_subject = _check_header_value((subject or "").strip(), "subject")
    if not checked_subject:
        raise EmailRejected("Тема письма не может быть пустой")
    if not (html or "").strip():
        raise EmailRejected("HTML-версия письма не может быть пустой")
    return recipient, sender, checked_subject


def _from_address(settings: Settings) -> str:
    return settings.postbox_from_email if settings.active_email_provider == "postbox" else settings.smtp_bz_from_email


def _from_name(settings: Settings) -> str:
    return settings.postbox_from_name if settings.active_email_provider == "postbox" else settings.smtp_bz_from_name


def _send_via_smtp_bz(
    settings: Settings,
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None,
    to_name: str | None,
    transport: httpx.BaseTransport | None,
) -> EmailResult:
    """Send through the SMTP.BZ HTTP API. The key only ever travels in a header."""

    recipient, sender, checked_subject = _validate_message(settings, to=to, subject=subject, html=html)

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

    result = _interpret(response)
    return replace(result, provider="smtp.bz")


def _build_message(sender: str, sender_name: str, to: str, to_name: str | None,
                   subject: str, html: str, text: str | None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender)) if sender_name else sender
    message["To"] = formataddr((to_name, to)) if to_name else to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1])
    message.set_content(text or _html_to_text(html))
    message.add_alternative(html, subtype="html")
    return message


def _html_to_text(html: str) -> str:
    """A minimal, dependency-free text fallback: strip tags, unescape entities."""

    without_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html_lib.unescape(without_tags)).strip()


def _send_via_postbox(
    settings: Settings,
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None,
    to_name: str | None,
    smtp_factory: Any | None,
    ssl_context: ssl.SSLContext | None,
) -> EmailResult:
    """Send through Yandex Cloud Postbox over SMTP (implicit TLS or STARTTLS).

    The API key id is the username and its secret is the password; both are read
    from configuration and never logged. A returned ``250`` from the server's
    ``DATA`` reply *is* the provider's acceptance — a refusal raises instead, so
    the caller is never told a letter went out when it did not.
    """

    recipient, sender, checked_subject = _validate_message(settings, to=to, subject=subject, html=html)
    message = _build_message(sender, settings.postbox_from_name, recipient, to_name,
                             checked_subject, html, text)

    context = ssl_context if ssl_context is not None else ssl.create_default_context()
    connect = smtp_factory or smtplib.SMTP_SSL
    try:
        if settings.postbox_port == 465:
            client = connect(settings.postbox_host, settings.postbox_port,
                             timeout=settings.postbox_timeout_seconds, context=context)
        else:
            client = connect(settings.postbox_host, settings.postbox_port,
                             timeout=settings.postbox_timeout_seconds)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise EmailUnavailable("Postbox недоступен") from exc

    try:
        if settings.postbox_port == 587:
            try:
                client.starttls(context=context)
            except (smtplib.SMTPException, ssl.SSLError) as exc:
                raise EmailUnavailable("Postbox отклонил STARTTLS") from exc
        try:
            client.login(settings.postbox_username, settings.postbox_password)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailRejected("Postbox отклонил ключ API (проверьте POSTBOX_SMTP_USERNAME/PASSWORD)") from exc
        except smtplib.SMTPException as exc:
            raise EmailUnavailable("Postbox не принял аутентификацию") from exc
        try:
            client.send_message(message)
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailRejected(f"Postbox отклонил получателя ({len(exc.recipients)} адрес(ов))") from exc
        except smtplib.SMTPSenderRefused as exc:
            # The classic unverified-domain refusal lives here.
            raise EmailRejected(f"Postbox отклонил отправителя: {exc.smtp_error!r}") from exc
        except smtplib.SMTPDataError as exc:
            raise EmailRejected(f"Postbox отклонил письмо (SMTP {exc.smtp_code})") from exc
        except smtplib.SMTPException as exc:
            raise EmailUnavailable("Postbox не принял письмо") from exc
    finally:
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            pass

    return EmailResult(accepted=True, message_id=message["Message-ID"], status_code=250, provider="postbox")


def send_email(
    settings: Settings,
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    to_name: str | None = None,
    transport: httpx.BaseTransport | None = None,
    smtp_factory: Any | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> EmailResult:
    """Send one transactional letter through the active provider.

    Raises :class:`EmailDisabled` when no provider is configured,
    :class:`EmailRejected` when the provider refuses the message, and
    :class:`EmailUnavailable` when it cannot be reached. Credentials are only
    ever placed in the transport, never in a result or an error message.
    """

    provider = settings.active_email_provider
    if provider == "postbox":
        return _send_via_postbox(settings, to=to, subject=subject, html=html, text=text,
                                 to_name=to_name, smtp_factory=smtp_factory, ssl_context=ssl_context)
    if provider == "smtp.bz":
        return _send_via_smtp_bz(settings, to=to, subject=subject, html=html, text=text,
                                 to_name=to_name, transport=transport)
    raise EmailDisabled(
        "Отправка почты не настроена: задайте Postbox (POSTBOX_SMTP_USERNAME, "
        "POSTBOX_SMTP_PASSWORD, POSTBOX_FROM_EMAIL) или SMTP.BZ (SMTP_BZ_API_KEY, SMTP_BZ_FROM_EMAIL)")


def describe(settings: Settings) -> dict[str, Any]:
    """Configuration status for operators. Never includes a key or a password."""

    provider = settings.active_email_provider
    base: dict[str, Any] = {
        "configured": settings.email_configured,
        "provider": provider or "none",
        "requestedProvider": settings.email_provider or "auto",
        "fromEmail": _from_address(settings) or None,
        "fromName": _from_name(settings) or None,
    }
    if provider == "postbox":
        base.update({
            "smtpHost": settings.postbox_host,
            "smtpPort": settings.postbox_port,
            "encryption": "TLS" if settings.postbox_port == 465 else "STARTTLS",
            "timeoutSeconds": settings.postbox_timeout_seconds,
            "keyPresent": bool(settings.postbox_username and settings.postbox_password),
            "requirements": (
                "Адрес отправителя должен принадлежать домену, привязанному к Postbox, "
                "а API-ключ — иметь область yc.postbox.send. Иначе сервер отклонит отправку."
            ),
        })
    elif provider == "smtp.bz":
        base.update({
            "apiUrl": settings.smtp_bz_api_url,
            "timeoutSeconds": settings.smtp_bz_timeout_seconds,
            "keyPresent": bool(settings.smtp_bz_api_key),
            "requirements": (
                "Адрес отправителя должен принадлежать домену, верифицированному в панели SMTP.BZ "
                "(раздел «Домены отправителя»), а исходящий IP сервера — быть в разрешённом списке "
                "SMTP.BZ. Иначе провайдер отклонит отправку."
            ),
        })
    else:
        base.update({
            "timeoutSeconds": None,
            "keyPresent": False,
            "requirements": (
                "Почта выключена: не заданы учётные данные ни Postbox, ни SMTP.BZ. "
                "Задайте POSTBOX_SMTP_USERNAME/POSTBOX_SMTP_PASSWORD/POSTBOX_FROM_EMAIL "
                "или SMTP_BZ_API_KEY/SMTP_BZ_FROM_EMAIL."
            ),
        })
    return base


class SmtpBzEmailProvider:

    """The active e-mail transport behind the Telegram flow's ``EmailProvider``.

    ``TelegramService`` already calls ``email_provider.send_otp(...)`` and catches
    :class:`IntegrationNotConfigured` / :class:`DeliveryError`. This adapter
    satisfies that contract so OTP can travel through whichever provider
    :attr:`Settings.active_email_provider` selects (Postbox or SMTP.BZ), while
    keeping the two responsibilities separate: this class owns the OTP *message*,
    the client above owns the *transport*.

    The historical name is kept because it is referenced by the app wiring and
    the tests; it is not specific to SMTP.BZ any more. When no provider is
    configured it raises :class:`IntegrationNotConfigured` instead of pretending
    to send, so OTP stays honestly disabled.
    """

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None,
                 smtp_factory: Any | None = None, ssl_context: ssl.SSLContext | None = None):
        self._settings = settings
        self._transport = transport
        self._smtp_factory = smtp_factory
        self._ssl_context = ssl_context

    def send_otp(self, email: str, code: str, expires_in_seconds: int) -> None:
        if not self._settings.email_configured:
            # Maps to ``NotReadyError`` (503) in TelegramService, exactly as the
            # unconfigured stub does — no silent success.
            raise IntegrationNotConfigured("Почтовый провайдер не настроен для отправки OTP")

        minutes = max(1, int(expires_in_seconds) // 60)
        subject = "Aéza Sentinel — код подтверждения"
        text = (
            f"Ваш код подтверждения: {code}\n"
            f"Код действует {minutes} мин. Никому его не сообщайте."
        )
        html = (
            "<html><body>"
            "<p>Ваш код подтверждения для входа в Aéza Sentinel:</p>"
            f"<p style=\"font-size:24px;font-weight:bold;letter-spacing:2px\">{code}</p>"
            f"<p>Код действует {minutes} мин. Никому его не сообщайте.</p>"
            "</body></html>"
        )
        try:
            send_email(self._settings, to=email, subject=subject, html=html, text=text,
                       transport=self._transport, smtp_factory=self._smtp_factory,
                       ssl_context=self._ssl_context)
        except EmailDisabled as exc:
            raise IntegrationNotConfigured("Почтовый провайдер не настроен для отправки OTP") from exc
        except EmailError as exc:
            # The code itself is never placed in the exception text or a log line.
            raise DeliveryError("Не удалось отправить код подтверждения по почте") from exc
