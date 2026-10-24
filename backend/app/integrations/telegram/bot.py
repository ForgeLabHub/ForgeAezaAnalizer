"""Bot command handling for the Telegram webhook.

Every command that returns Sentinel data first resolves the chat to an account
through :class:`TelegramService` and refuses when there is no active link. A
``chat_id`` on its own grants nothing, and a Telegram username is never treated
as identity.

Replies are plain text (no ``parse_mode``), so a customer name or a reason string
cannot inject markup. Errors are translated into short, safe sentences — a stack
trace or a database message must never reach the chat.
"""

from __future__ import annotations

import logging

from backend.app.config import Settings
from backend.app.integrations.telegram.client import escape_text
from backend.app.integrations.telegram.service import (
    NOTIFICATION_KINDS,
    TelegramLinkError,
    TelegramRateLimited,
    TelegramService,
)

logger = logging.getLogger("aeza.telegram")

HELP_TEXT = (
    "Aéza Sentinel — уведомления о риске оттока.\n\n"
    "Команды:\n"
    "/start — подключение и краткая справка\n"
    "/help — эта справка\n"
    "/status — статус подключения и подписок\n"
    "/subscribe — включить уведомления\n"
    "/unsubscribe — выключить уведомления и отвязать чат\n"
    "/top — клиенты с наибольшим риском\n"
    "/customer <id> — карточка клиента\n"
    "/digest on|off — ежедневная сводка\n\n"
    "Подключение: откройте панель Aéza Sentinel → «Telegram», создайте код "
    "и отправьте его командой /start <КОД>.\n"
    "Балл риска — взвешенная эвристика, а не вероятность оттока."
)


def _require_link(service: TelegramService, chat_id: str) -> str | None:
    return service.owner_of(chat_id)


def handle_update(service: TelegramService, settings: Settings, update: dict, *, analytics=None) -> str | None:
    """Handle one Telegram update and return the reply text (or ``None``).

    ``analytics`` is an optional callable returning the current ``Analysis``;
    it is only invoked for commands that need customer data, so a plain
    ``/help`` never triggers a calculation.
    """

    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if chat_id is None or not text:
        return None
    chat_id = str(chat_id)
    username = message.get("from", {}).get("username")

    parts = text.split()
    command = parts[0].split("@")[0].lower()
    args = parts[1:]

    if command == "/start":
        if args:
            return _do_link(service, chat_id, username, args[0])
        if _require_link(service, chat_id):
            return "Чат уже подключён.\n\n" + HELP_TEXT
        return (
            "Здравствуйте! Этот бот присылает уведомления Aéza Sentinel "
            "о риске оттока клиентов.\n\n"
            "Чтобы подключить чат: откройте панель Aéza Sentinel → «Telegram», "
            "создайте код и отправьте его сюда командой:\n"
            "/start <КОД>\n\n"
            "Код действует ограниченное время и используется один раз.\n\n"
            + HELP_TEXT
        )

    if command == "/help":
        return HELP_TEXT

    # Every remaining command needs a linked account.
    owner = _require_link(service, chat_id)
    if owner is None:
        return (
            "Чат не подключён к Aéza Sentinel.\n"
            "Создайте код в панели Sentinel и отправьте /start <КОД>."
        )

    if command == "/status":
        subscription = service.subscription(chat_id)
        kinds = ", ".join(subscription["kinds"]) or "нет"
        return (
            f"Подключено к аккаунту: {escape_text(owner)}\n"
            f"Уведомления: {kinds}\n"
            f"Порог балла: {subscription['thresholds']['riskScore']}\n"
            f"Порог роста выручки: {subscription['thresholds']['exposureEur']} €\n"
            f"Ежедневная сводка: {'вкл' if subscription['dailyDigest'] else 'выкл'}"
        )

    if command == "/subscribe":
        service.update_subscription(chat_id, kinds=list(NOTIFICATION_KINDS))
        return "Уведомления включены. Отключить — /unsubscribe."

    if command == "/unsubscribe":
        service.unlink(chat_id)
        return "Чат отключён от Aéza Sentinel. Уведомления больше не приходят."

    if command == "/digest":
        if not args or args[0].lower() not in {"on", "off"}:
            return "Использование: /digest on или /digest off"
        service.update_subscription(chat_id, daily_digest=args[0].lower() == "on")
        return f"Ежедневная сводка {'включена' if args[0].lower() == 'on' else 'выключена'}."

    if command == "/top":
        return _top(analytics, settings)

    if command == "/customer":
        if not args or not args[0].isdigit():
            return "Использование: /customer <id>, например /customer 10"
        return _customer(analytics, settings, int(args[0]))

    return "Неизвестная команда. /help — список команд."


def _do_link(service: TelegramService, chat_id: str, username: str | None, code: str) -> str:
    try:
        owner = service.redeem_link_code(code, chat_id, username)
    except TelegramRateLimited as exc:
        return str(exc)
    except TelegramLinkError as exc:
        return str(exc)
    return (
        f"Готово: чат подключён к аккаунту {escape_text(owner)}.\n"
        "Уведомления включены. /status — настройки, /help — команды."
    )


def _top(analytics, settings: Settings) -> str:
    if analytics is None:
        return "Данные расчёта недоступны."
    try:
        analysis = analytics()
    except Exception:
        logger.exception("telegram /top failed to read the analysis")
        return "Расчёт ещё не опубликован. Попробуйте позже."
    ranked = sorted(
        (c for c in analysis.customers if c.get("riskScore") is not None),
        key=lambda c: c["riskScore"],
        reverse=True,
    )[:5]
    if not ranked:
        return "Нет клиентов с рассчитанным риском."
    lines = ["Клиенты с наибольшим риском:"]
    for customer in ranked:
        lines.append(
            f"#{customer['id']} · {customer['riskScore']} · "
            f"{escape_text(customer.get('riskCategoryLabel') or customer.get('riskCategory'))}"
        )
    lines.append("")
    lines.append("Балл — эвристика, не вероятность оттока.")
    return "\n".join(lines)


def _customer(analytics, settings: Settings, customer_id: int) -> str:
    if analytics is None:
        return "Данные расчёта недоступны."
    try:
        analysis = analytics()
    except Exception:
        logger.exception("telegram /customer failed to read the analysis")
        return "Расчёт ещё не опубликован. Попробуйте позже."
    customer = next((c for c in analysis.customers if c["id"] == customer_id), None)
    if customer is None:
        return f"Клиент #{customer_id} не найден."
    reasons = customer.get("topReasons") or []
    lines = [
        f"Клиент #{customer['id']}",
        f"Балл: {customer.get('riskScore')} · "
        f"{escape_text(customer.get('riskCategoryLabel') or customer.get('riskCategory'))}",
        f"Выручка под риском: {(customer.get('revenueAtRisk') or {}).get('eur') or '—'} €",
    ]
    if reasons:
        lines.append("Причины:")
        lines.extend(f"— {escape_text(reason)}" for reason in reasons[:3])
    recommendations = customer.get("recommendations") or []
    if recommendations:
        lines.append("Рекомендации:")
        lines.extend(f"— {escape_text(item.get('title'))}" for item in recommendations[:3])
    lines.append("")
    lines.append(f"{settings.telegram_app_base_url.rstrip('/')}/customers/{customer['id']}")
    return "\n".join(lines)
