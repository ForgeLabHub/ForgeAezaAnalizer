"""Telegram integration API.

Two surfaces live here:

* the **authenticated management API** under ``/telegram``, which a logged-in
  analyst uses from the Sentinel UI to link a chat, tune subscriptions and send a
  test message;
* the **webhook** at ``/telegram/webhook``, which Telegram calls. It is not
  authenticated with a bearer token — Telegram cannot send one — so it is
  protected by the shared secret Telegram echoes in
  ``X-Telegram-Bot-Api-Secret-Token`` and compared in constant time.

The management API never returns the bot token. The webhook never returns
customer data to an unlinked chat: that decision belongs to the bot handler.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.deps import RuntimeDep, UserDep
from backend.app.integrations.telegram import bot
from backend.app.integrations.telegram.client import TelegramError
from backend.app.integrations.telegram.service import (
    NOTIFICATION_KINDS,
    TelegramLinkError,
    TelegramRateLimited,
)

logger = logging.getLogger("aeza.telegram")

router = APIRouter(prefix="/telegram", tags=["telegram"])

#: Telegram updates are small; anything larger is not a real update.
MAX_UPDATE_BYTES = 64 * 1024


class SubscriptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kinds: list[str] | None = None
    thresholds: dict[str, float] | None = None
    dailyDigest: bool | None = None


def _service(runtime: RuntimeDep):
    """Return the Telegram service, or 503 when the feature is switched off."""

    service = getattr(runtime, "telegram", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Интеграция Telegram отключена (TELEGRAM_ENABLED=0).",
        )
    return service


@router.get("/status", summary="Состояние интеграции Telegram")
def status(runtime: RuntimeDep, user: UserDep):
    """Report whether Telegram is on and whether this account has a linked chat.

    ``enabled`` is the feature flag; ``linked`` is this account's state. The bot
    token is never included.
    """

    settings = runtime.settings
    if not settings.telegram_enabled:
        return {
            "enabled": False,
            "linked": False,
            "kinds": list(NOTIFICATION_KINDS),
            "detail": "Интеграция отключена (TELEGRAM_ENABLED=0).",
        }
    if runtime.telegram is None:
        # Enabled but not built: the operator asked for the feature without a
        # token. Report the real reason instead of an enabled-but-broken state.
        return {
            "enabled": False,
            "linked": False,
            "kinds": list(NOTIFICATION_KINDS),
            "detail": (
                "TELEGRAM_ENABLED=1, но TELEGRAM_BOT_TOKEN не задан. "
                "Задайте токен бота на сервере и перезапустите API."
            ),
        }
    service = _service(runtime)
    link = service.link_status(user.email)
    payload = {
        "enabled": True,
        "linked": link.linked,
        "chatId": link.chat_id if link.linked else None,
        "username": link.username,
        "linkedAt": link.linked_at.isoformat() if link.linked_at else None,
        "kinds": list(NOTIFICATION_KINDS),
        "webhookConfigured": bool(settings.telegram_webhook_url),
        "detail": None,
    }
    if link.linked and link.chat_id:
        payload["subscription"] = service.subscription(link.chat_id)
    return payload


@router.post("/link-code", summary="Создать одноразовый код подключения")
def create_link_code(runtime: RuntimeDep, user: UserDep):
    """Issue a one-time code for the authenticated account.

    The plaintext code is returned once and never stored; only its hash is kept.
    """

    service = _service(runtime)
    issued = service.create_link_code(user.email)
    return {**issued, "botHint": "Отправьте боту: /start <КОД>"}


@router.post("/disconnect", summary="Отключить Telegram от аккаунта")
def disconnect(runtime: RuntimeDep, user: UserDep):
    service = _service(runtime)
    count = service.unlink_account(user.email)
    return {"disconnected": count, "detail": "Уведомления отключены."}


@router.get("/subscription", summary="Настройки уведомлений")
def get_subscription(runtime: RuntimeDep, user: UserDep):
    service = _service(runtime)
    link = service.link_status(user.email)
    if not link.linked or not link.chat_id:
        raise HTTPException(status_code=404, detail="Telegram не подключён.")
    return service.subscription(link.chat_id)


@router.patch("/subscription", summary="Изменить настройки уведомлений")
def patch_subscription(payload: SubscriptionPatch, runtime: RuntimeDep, user: UserDep):
    service = _service(runtime)
    link = service.link_status(user.email)
    if not link.linked or not link.chat_id:
        raise HTTPException(status_code=404, detail="Telegram не подключён.")
    try:
        return service.update_subscription(
            link.chat_id,
            kinds=payload.kinds,
            thresholds=payload.thresholds,
            daily_digest=payload.dailyDigest,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/test", summary="Отправить тестовое уведомление")
def send_test(runtime: RuntimeDep, user: UserDep):
    """Send one message to the account's linked chat.

    Uses a real message built from the current calculation, so the test proves
    the whole path (link → data → Bot API) rather than a canned string.
    """

    service = _service(runtime)
    link = service.link_status(user.email)
    if not link.linked or not link.chat_id:
        raise HTTPException(status_code=404, detail="Telegram не подключён.")

    from backend.app.integrations.telegram import notifications

    analysis = runtime.calculation.calculate(runtime.storage.load())
    text = "🔔 Тестовое уведомление Aéza Sentinel\n\n" + notifications.digest_text(
        analysis, settings=runtime.settings
    )
    delivered = service.send(link.chat_id, text, kind="test")
    if not delivered:
        raise HTTPException(status_code=502, detail="Не удалось отправить сообщение в Telegram.")
    return {"sent": True, "detail": "Тестовое сообщение отправлено."}


@router.get("/diagnostics", summary="Диагностика интеграции")
def diagnostics(runtime: RuntimeDep, user: UserDep):
    """Administrative view: feature state, recent deliveries and webhook state.

    Contains no token and no customer personal data — only delivery metadata.
    """

    settings = runtime.settings
    if not settings.telegram_enabled:
        return {"enabled": False, "detail": "Интеграция отключена."}
    service = _service(runtime)
    # Scope the delivery log to the caller's own chat. There are no roles in this
    # deployment, so "administrative" cannot mean "sees every account's chat". An
    # unlinked caller has no chat, so they see no delivery history at all rather
    # than everyone else's.
    link = service.link_status(user.email)
    recent = service.deliveries(limit=20, chat_id=link.chat_id) if link.linked and link.chat_id else []
    return {
        "enabled": True,
        "webhookConfigured": bool(settings.telegram_webhook_url),
        "webhookSecretConfigured": bool(settings.telegram_webhook_secret),
        "recentDeliveries": recent,
    }


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    runtime: RuntimeDep,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
):
    """Receive one Telegram update.

    Not bearer-authenticated: Telegram cannot present one. Authenticity comes
    from the secret token Telegram returns in the header, compared in constant
    time. The body is size-limited and a malformed body is acknowledged without
    processing, so Telegram does not retry forever.
    """

    settings = runtime.settings
    service = getattr(runtime, "telegram", None)
    if not settings.telegram_enabled or service is None:
        # Answer 200 so a misconfigured deployment does not make Telegram retry.
        return Response(status_code=200, content=b"ok")

    expected = settings.telegram_webhook_secret
    provided = x_telegram_bot_api_secret_token or ""
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        # 403 is correct here: this is not Telegram, or the secret is wrong.
        raise HTTPException(status_code=403, detail="Неверный секрет webhook.")

    raw = await request.body()
    if len(raw) > MAX_UPDATE_BYTES:
        return Response(status_code=200, content=b"ok")
    try:
        update = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return Response(status_code=200, content=b"ok")
    if not isinstance(update, dict):
        return Response(status_code=200, content=b"ok")

    def analytics():
        return runtime.calculation.calculate(runtime.storage.load())

    try:
        reply = bot.handle_update(service, settings, update, analytics=analytics)
    except Exception:
        # Never leak a traceback to Telegram; log server-side and acknowledge.
        logger.exception("telegram update handling failed")
        return Response(status_code=200, content=b"ok")

    if reply:
        chat = (update.get("message") or {}).get("chat") or {}
        if chat.get("id") is not None:
            service.send(str(chat["id"]), reply, kind="reply")
    return Response(status_code=200, content=b"ok")
