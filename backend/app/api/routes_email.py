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
from pydantic import BaseModel, ConfigDict, Field

from core import InvalidInput
from backend.app.api.deps import RuntimeDep, UserDep
from backend.app.integrations import email as email_integration

router = APIRouter(prefix="/email", tags=["email"])

DEFAULT_TEST_SUBJECT = "Aéza Sentinel — проверка отправки"


class TestEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: Annotated[str, Field(min_length=3, max_length=254)]
    subject: Annotated[str | None, Field(max_length=200)] = None
    #: A guard against accidental sends: a request without an explicit
    #: ``confirm: true`` is rejected before any provider call is made.
    confirm: bool = False


@router.get("/status", summary="Состояние интеграции с SMTP.BZ")
def status(runtime: RuntimeDep, user: UserDep):
    return email_integration.describe(runtime.settings)


@router.post("/test", summary="Безопасная тестовая отправка на контролируемый адрес")
def send_test(payload: TestEmailRequest, runtime: RuntimeDep, user: UserDep):
    if not payload.confirm:
        raise InvalidInput("Тестовая отправка требует confirm=true: письмо уйдёт реальному получателю из поля to")
    subject = (payload.subject or "").strip() or DEFAULT_TEST_SUBJECT
    html = (
        "<html><body>"
        "<p>Это тестовое письмо Aéza Sentinel, отправленное через SMTP.BZ.</p>"
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
