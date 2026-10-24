import hmac
import json
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.auth.service import AuthError
from core import NotReadyError
from backend.app.api.deps import RuntimeDep, UserDep

logger = logging.getLogger("aeza.telegram")

router = APIRouter(prefix="/telegram", tags=["telegram"])

#: Telegram updates are small. Anything larger is not a real update, and reading
#: it into memory would let an unauthenticated caller spend the server's RAM.
MAX_UPDATE_BYTES = 128 * 1024


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


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    runtime: RuntimeDep,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
):
    """Receive one Telegram update.

    The endpoint is not bearer-authenticated: Telegram cannot present a token, so
    authenticity comes from the secret header Telegram echoes back, compared in
    constant time. It always answers 200 for anything Telegram might retry
    forever (a bad body, a duplicate, an internal error), because a 5xx makes
    Telegram redeliver the same update indefinitely. A wrong or missing secret is
    the one case that answers 403: that request is not from Telegram.
    """

    if not runtime.settings.telegram_bot_enabled:
        raise NotReadyError("Telegram Bot API отключён")
    expected = runtime.settings.telegram_webhook_secret
    provided = secret or ""
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise AuthError(403, "invalid_webhook_secret", "Неверный webhook secret")

    raw = await request.body()
    if len(raw) > MAX_UPDATE_BYTES:
        logger.warning("telegram update rejected: body too large")
        return Response(status_code=200, content=b"ok")
    try:
        update = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return Response(status_code=200, content=b"ok")
    if not isinstance(update, dict):
        return Response(status_code=200, content=b"ok")

    update_id = update.get("update_id")
    if isinstance(update_id, int) and not runtime.telegram.claim_update(update_id):
        # A redelivery of an update already handled. Acknowledge without running
        # the business action again, so a retried /start cannot relink a chat.
        logger.info("ignoring a redelivered telegram update")
        return Response(status_code=200, content=b"ok")

    try:
        result = runtime.telegram.handle_update(update)
    except Exception:
        # Never leak a traceback to Telegram, and never 5xx (which would make it
        # retry forever). Log server-side and acknowledge.
        logger.exception("telegram update handling failed")
        return Response(status_code=200, content=b"ok")
    return result


@router.get("/diagnostics", summary="Состояние Telegram-бота")
def diagnostics(runtime: RuntimeDep, user: UserDep):
    """Operator view: feature state and (with the bot on) live Bot API identity.

    Never returns the bot token or the webhook secret — only whether they are
    set. ``getMe``/``getWebhookInfo`` are read only when the bot is enabled, so
    the endpoint adds no outbound call on a disabled deployment.
    """

    settings = runtime.settings
    payload: dict = {
        "enabled": settings.telegram_bot_enabled,
        "tokenConfigured": bool(settings.telegram_bot_token),
        "webhookSecretConfigured": bool(settings.telegram_webhook_secret),
        "miniAppUrlConfigured": bool(settings.telegram_mini_app_url),
        "webhookUrl": settings.telegram_webhook_url or None,
    }
    if not settings.telegram_bot_enabled:
        payload["detail"] = "Telegram Bot API выключен (AEZA_TELEGRAM_BOT_ENABLED=0)."
        return payload
    if not settings.telegram_bot_token:
        payload["detail"] = "Токен не задан."
        return payload
    try:
        provider = runtime.telegram.telegram_provider
        if hasattr(provider, "get_me"):
            me = provider.get_me() or {}
            payload["bot"] = {"id": me.get("id"), "username": me.get("username")}
            info = provider.get_webhook_info() or {}
            payload["webhook"] = {
                "url": info.get("url") or None,
                "pendingUpdateCount": info.get("pending_update_count"),
                "lastErrorMessage": info.get("last_error_message"),
            }
    except Exception as exc:  # noqa: BLE001 - diagnostics must never raise
        payload["detail"] = f"Telegram API недоступен: {type(exc).__name__}"
    return payload


@router.post("/webhook/register", summary="Зарегистрировать webhook в Telegram")
def register_webhook(runtime: RuntimeDep, user: UserDep):
    """Register the public HTTPS webhook URL with Telegram.

    Explicit, not automatic: re-registering on every restart races with other
    instances and can drop pending updates. Telegram requires a public HTTPS URL;
    a non-HTTPS URL is refused with a clear reason instead of an opaque API error.
    """

    settings = runtime.settings
    if not settings.telegram_bot_enabled:
        raise NotReadyError("Telegram Bot API отключён")
    url = (settings.telegram_webhook_url or "").strip()
    if not url:
        raise NotReadyError("AEZA_TELEGRAM_WEBHOOK_URL не задан")
    if not url.startswith("https://"):
        raise NotReadyError("Telegram требует публичный HTTPS URL для webhook")
    provider = runtime.telegram.telegram_provider
    if not hasattr(provider, "set_webhook"):
        raise NotReadyError("Провайдер Telegram не поддерживает регистрацию webhook")
    provider.set_webhook(url, settings.telegram_webhook_secret)
    info = provider.get_webhook_info() or {}
    return {"registered": (info.get("url") or "") == url, "url": info.get("url") or None,
            "pendingUpdateCount": info.get("pending_update_count")}


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
