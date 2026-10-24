"""Outbound-e-mail HTTP surface (SMTP.BZ).

Two endpoints, both behind the existing bearer-token dependency so the e-mail
surface is exactly as protected as the rest of the API:

* ``GET /email/status`` — is e-mail configured, and from which address? The API
  key is never returned, only whether it is present.
* ``POST /email/test`` — send one letter to a *controlled* address, on purpose.

Nothing here is on the analytics path: when the provider is unconfigured or
unreachable the endpoints answer ``503`` and the product keeps working. Real
letters are never sent implicitly — the test route refuses to run without an
explicit ``confirm: true``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core import InvalidInput
from backend.app.api.deps import RuntimeDep, UserDep
from backend.app.integrations import email as email_integration

router = APIRouter(prefix="/email", tags=["email"])

DEFAULT_TEST_SUBJECT = "Aéza Sentinel — проверка отправки"


class TestEmailRequest(BaseModel):
    # ``extra="forbid"`` is part of the SSRF guard: the provider URL comes only
    # from ``SMTP_BZ_API_URL``, so a request cannot smuggle in an endpoint.
    model_config = ConfigDict(extra="forbid")
    to: Annotated[str, Field(min_length=3, max_length=254)]
    subject: Annotated[str | None, Field(max_length=200)] = None
    #: A guard against accidental sends: a request without an explicit
    #: ``confirm: true`` is rejected before any provider call is made.
    confirm: bool = False

    @field_validator("to")
    @classmethod
    def _validate_recipient(cls, value: str) -> str:
        # Reject a malformed address with 422 at the edge, so it never becomes a
        # 502 "provider refused" and the provider is never called for it.
        if not email_integration.is_valid_address(value):
            raise ValueError("Некорректный e-mail получателя")
        return value.strip()


@router.get("/status", summary="Состояние интеграции с почтовым провайдером")
def status(runtime: RuntimeDep, user: UserDep):
    return email_integration.describe(runtime.settings)


@router.post("/test", summary="Безопасная тестовая отправка на контролируемый адрес")
def send_test(payload: TestEmailRequest, runtime: RuntimeDep, user: UserDep):
    if not payload.confirm:
        raise InvalidInput("Тестовая отправка требует confirm=true: письмо уйдёт реальному получателю из поля to")
    subject = (payload.subject or "").strip() or DEFAULT_TEST_SUBJECT
    provider = runtime.settings.active_email_provider or "не настроен"
    html = (
        "<html><body>"
        f"<p>Это тестовое письмо Aéza Sentinel, отправленное через {provider}.</p>"
        f"<p>Получатель: {payload.to}</p>"
        "<p>Если вы его получили, интеграция с провайдером настроена корректно.</p>"
        "</body></html>"
    )
    result = email_integration.send_email(
        runtime.settings, to=payload.to, subject=subject, html=html, text="Тестовое письмо Aéza Sentinel.")
    return {
        **result.as_dict(),
        "note": "Провайдер подтвердил приём письма. Доставку до ящика подтверждает только получатель.",
    }
