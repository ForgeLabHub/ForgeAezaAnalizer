import hmac
from typing import Annotated

from fastapi import APIRouter, Body, Header, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from backend.auth.service import AuthError
from core import NotReadyError
from backend.app.api.deps import RuntimeDep, UserDep

router = APIRouter(prefix="/telegram", tags=["telegram"])


class AnalystMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Сообщение не может быть пустым")
        return value


class ConversationStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "closed"]


class StartConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accountId: int = Field(ge=1)
    text: str | None = Field(default=None, max_length=4000)


@router.post("/webhook", summary="Принимать сообщения Telegram Bot API")
def webhook(
    runtime: RuntimeDep,
    payload: dict = Body(...),
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
):
    if not runtime.settings.telegram_bot_enabled:
        raise NotReadyError("Telegram Bot API отключён")
    expected = runtime.settings.telegram_webhook_secret
    if not secret or not hmac.compare_digest(secret, expected):
        raise AuthError(403, "invalid_webhook_secret", "Неверный webhook secret")
    return runtime.telegram.handle_update(payload)


@router.get("/support/conversations", summary="Диалоги Telegram-поддержки")
def support_conversations(
    runtime: RuntimeDep,
    user: UserDep,
    status: Annotated[str | None, Query(pattern=r"^(open|closed)$")] = None,
):
    return {"items": runtime.telegram.analyst_conversations(status)}


@router.post("/support/conversations", status_code=201, summary="Начать диалог с клиентом")
def start_conversation(payload: StartConversationRequest, runtime: RuntimeDep, user: UserDep):
    return runtime.telegram.analyst_start_conversation(payload.accountId, payload.text)


@router.get("/support/conversations/{conversation_id}/messages", summary="История диалога")
def conversation_messages(conversation_id: int, runtime: RuntimeDep, user: UserDep):
    return runtime.telegram.analyst_messages(conversation_id)


@router.post("/support/conversations/{conversation_id}/messages", status_code=201, summary="Ответить клиенту")
def reply_to_conversation(
    conversation_id: int, payload: AnalystMessageRequest, runtime: RuntimeDep, user: UserDep,
):
    return runtime.telegram.analyst_reply(conversation_id, payload.text)


@router.patch("/support/conversations/{conversation_id}", summary="Закрыть или открыть диалог")
def change_conversation_status(
    conversation_id: int, payload: ConversationStatusRequest, runtime: RuntimeDep, user: UserDep,
):
    return runtime.telegram.set_conversation_status(conversation_id, payload.status)


@router.post("/notifications/sync", summary="Пересчитать очередь напоминаний")
def sync_notifications(runtime: RuntimeDep, user: UserDep):
    return runtime.telegram.sync_notifications()


@router.post("/notifications/run", summary="Отправить наступившие напоминания")
def run_notifications(runtime: RuntimeDep, user: UserDep):
    return runtime.telegram.process_notifications()


@router.get("/notifications", summary="Очередь напоминаний")
def notification_queue(
    runtime: RuntimeDep,
    user: UserDep,
    status: Annotated[str | None, Query(pattern=r"^(pending|sent|failed|stubbed|cancelled)$")] = None,
):
    return {"items": runtime.telegram.notification_queue(status)}
