"""Telegram integration services: account linking, subscriptions, notifications.

This module is the only place that knows how a Telegram chat relates to a
Sentinel account. It reads the *existing* analytics output — the same
``Storage``/``Analysis`` the HTTP API serves — and never recomputes risk, money
or recommendations. If the Risk Engine changes, the notifications change with
it, because there is no second source of truth here.

Security model
--------------
* A Telegram username is never identity. A chat becomes linked only by
  redeeming a one-time code that an **authenticated** Sentinel user generated.
* Only a hash of the code is stored, so a database leak does not yield codes.
* Redemption is atomic: the code is marked consumed inside the same transaction
  that creates the link, so two concurrent redemptions cannot both succeed.
* ``chat_id`` is unique in the links table, so a second redemption cannot
  silently take over an existing binding.
* Every command that returns customer data re-checks the link and the
  subscription; knowing a ``chat_id`` is not enough.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.app.config import Settings
from backend.app.db import (
    Database,
    TelegramDeliveryRow,
    TelegramLinkCodeRow,
    TelegramLinkRow,
    TelegramSubscriptionRow,
)
from backend.app.integrations.telegram.client import (
    TelegramClient,
    TelegramError,
    TelegramRejected,
    TelegramUnavailable,
    escape_text,
)
from backend.auth.cache import CacheFull, TTLCache

logger = logging.getLogger("aeza.telegram")

#: Notification kinds a chat can subscribe to. Kept here so the API, the bot
#: and the UI all validate against one list.
NOTIFICATION_KINDS = (
    "high_risk",        # a customer moved into the high-risk category
    "exposure_jump",    # revenue at risk grew past the configured threshold
    "new_action",       # a new retention recommendation appeared
    "data_quality",     # a data-quality problem was detected
    "daily_digest",     # periodic summary
)

DEFAULT_THRESHOLDS = {
    "riskScore": 65.0,       # score at or above which high_risk fires
    "exposureEur": 50.0,     # euro growth in revenue at risk that triggers a jump
}

#: How long a delivery row is kept; used only for cleanup.
DELIVERY_RETENTION_DAYS = 30


class TelegramLinkError(Exception):
    """A linking operation was refused. The message is safe to show a user."""


class TelegramRateLimited(Exception):
    """Too many attempts in a short window."""


@dataclass(frozen=True)
class LinkStatus:
    linked: bool
    chat_id: str | None
    username: str | None
    linked_at: datetime | None


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class TelegramService:
    def __init__(self, database: Database, settings: Settings, *, client: TelegramClient | None = None):
        self.database = database
        self.settings = settings
        self.client = client or TelegramClient(settings)
        self._last_send: dict[str, float] = {}
        #: Update ids already handled. Telegram redelivers an update when it does
        #: not receive a timely 200, and a redelivered ``/start <code>`` or
        #: ``/customer`` must not be processed twice.
        self._seen_updates: TTLCache[int] = TTLCache(1024)
        #: The last known webhook state, recorded by :meth:`ensure_webhook`.
        #: Diagnostics reads this instead of calling Telegram on every request.
        self._webhook_state: dict | None = None

    # ------------------------------------------------------------------ #
    # Webhook registration
    # ------------------------------------------------------------------ #

    def ensure_webhook(self) -> dict:
        """Register the webhook with Telegram and report what is now live.

        The integration is webhook-based, so without this call the bot receives
        nothing and ``TELEGRAM_WEBHOOK_URL`` is inert. It runs on startup, is
        idempotent (``setWebhook`` is a no-op when the URL and secret already
        match), and returns Telegram's own view via ``getWebhookInfo`` so the
        result can be verified instead of assumed.

        Never raises: a Telegram problem must not stop the analytics product.
        """

        url = (self.settings.telegram_webhook_url or "").strip()
        if not url:
            logger.warning(
                "TELEGRAM_WEBHOOK_URL is empty; the bot will not receive updates. "
                "Set it to https://<host>/api/v1/telegram/webhook"
            )
            self._webhook_state = {"registered": False, "url": None, "pendingUpdateCount": None,
                                   "lastErrorDate": None, "lastErrorMessage": None,
                                   "reason": "TELEGRAM_WEBHOOK_URL is not set", "checked": True}
            return self._webhook_state
        if not url.startswith("https://"):
            # Telegram refuses a non-HTTPS webhook, so this would fail anyway;
            # say why instead of surfacing an opaque API error.
            logger.error("TELEGRAM_WEBHOOK_URL must be https://; got %r", url[:40])
            self._webhook_state = {"registered": False, "url": None, "pendingUpdateCount": None,
                                   "lastErrorDate": None, "lastErrorMessage": None,
                                   "reason": "TELEGRAM_WEBHOOK_URL must use https", "checked": True}
            return self._webhook_state
        try:
            self.client.set_webhook(url, self.settings.telegram_webhook_secret)
            info = self.client.get_webhook_info()
        except TelegramError as exc:
            logger.error("could not register the Telegram webhook: %s", exc)
            self._webhook_state = {"registered": False, "url": None, "pendingUpdateCount": None,
                                   "lastErrorDate": None, "lastErrorMessage": None,
                                   "reason": str(exc), "checked": True}
            return self._webhook_state
        live = str(info.get("url") or "")
        registered = live == url
        if not registered:
            logger.error("Telegram reports webhook %r, expected %r", live[:40], url[:40])
        self._webhook_state = {
            "registered": registered,
            "url": live or None,
            "pendingUpdateCount": info.get("pending_update_count"),
            "lastErrorDate": info.get("last_error_date"),
            "lastErrorMessage": info.get("last_error_message"),
            "checked": True,
        }
        return self._webhook_state

    def webhook_status(self) -> dict:
        """The last recorded webhook state, without contacting Telegram.

        Diagnostics must not make an outbound API call per request, so this
        returns what :meth:`ensure_webhook` last observed. Before the first
        check it reports that nothing has been verified yet.
        """

        if self._webhook_state is not None:
            return self._webhook_state
        return {"registered": False, "url": None, "pendingUpdateCount": None,
                "lastErrorDate": None, "lastErrorMessage": None, "checked": False}

    def accept_update(self, update: dict) -> bool:
        """True the first time an ``update_id`` is seen, False on a redelivery.

        Telegram retries an update when the webhook does not answer in time, so
        the same ``update_id`` can arrive more than once. Processing it twice
        would, for example, re-run a linking command.
        """

        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            # Without an id there is nothing to deduplicate on; let it through
            # rather than dropping a legitimate update.
            return True
        key = str(update_id)
        if self._seen_updates.get(key) is not None:
            return False
        try:
            self._seen_updates.put(key, update_id, 600)
        except CacheFull:
            # The cache is full of live entries; skip dedup rather than refuse
            # a real update.
            return True
        return True

    # ------------------------------------------------------------------ #
    # Linking
    # ------------------------------------------------------------------ #

    def create_link_code(self, user_email: str) -> dict:
        """Issue a one-time linking code for an authenticated user.

        Returns the plaintext code exactly once; only its hash is persisted.
        Any earlier unconsumed code for the same user is invalidated, so a
        leaked code cannot outlive a newer one.
        """

        now = datetime.now(timezone.utc)
        ttl = self.settings.telegram_link_code_ttl_seconds
        # Human-friendly but cryptographically strong: 8 groups of base32-ish
        # characters is ~40 bits of entropy and still typeable.
        code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        with self.database.transaction() as session:
            session.execute(
                delete(TelegramLinkCodeRow).where(
                    TelegramLinkCodeRow.user_email == user_email,
                    TelegramLinkCodeRow.consumed_at.is_(None),
                )
            )
            session.add(TelegramLinkCodeRow(
                code_hash=_hash_code(code),
                user_email=user_email,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl),
                consumed_at=None,
                attempts=0,
            ))
        return {
            "code": code,
            "expiresAt": (now + timedelta(seconds=ttl)).isoformat(),
            "ttlSeconds": ttl,
        }

    def redeem_link_code(self, code: str, chat_id: str, username: str | None = None) -> str:
        """Bind ``chat_id`` to the account the code was issued for.

        Returns the account e-mail on success. Raises :class:`TelegramLinkError`
        with a safe message on any failure. The consumption and the link insert
        happen in one transaction.
        """

        normalised = (code or "").strip().upper()
        if not normalised:
            raise TelegramLinkError("Укажите код подключения.")
        chat = str(chat_id)
        now = datetime.now(timezone.utc)
        digest = _hash_code(normalised)

        with self.database.transaction() as session:
            row = session.scalar(
                select(TelegramLinkCodeRow).where(TelegramLinkCodeRow.code_hash == digest)
            )
            if row is None:
                raise TelegramLinkError("Код не найден. Создайте новый код в панели Sentinel.")
            if row.consumed_at is not None:
                raise TelegramLinkError("Этот код уже использован. Создайте новый.")
            if row.expires_at <= now:
                raise TelegramLinkError("Срок действия кода истёк. Создайте новый.")
            if row.attempts >= self.settings.telegram_link_max_attempts:
                raise TelegramRateLimited("Слишком много попыток. Создайте новый код.")
            row.attempts = row.attempts + 1

            existing = session.scalar(select(TelegramLinkRow).where(TelegramLinkRow.chat_id == chat))
            if existing is not None and existing.revoked_at is None:
                # Re-binding the same chat to the same account is idempotent;
                # a different account must revoke first, so a code cannot be
                # used to take over a chat silently.
                if existing.user_email != row.user_email:
                    raise TelegramLinkError(
                        "Этот чат уже подключён к другому аккаунту. "
                        "Сначала отключите его командой /unsubscribe."
                    )
                row.consumed_at = now
                return existing.user_email

            if existing is not None:
                existing.revoked_at = None
                existing.user_email = row.user_email
                existing.username = username
                existing.created_at = now
            else:
                session.add(TelegramLinkRow(
                    chat_id=chat,
                    user_email=row.user_email,
                    username=username,
                    created_at=now,
                    revoked_at=None,
                ))
            row.consumed_at = now
            owner = row.user_email

        self._ensure_subscription(chat)
        return owner

    def unlink(self, chat_id: str) -> bool:
        """Revoke the binding for a chat and drop its subscription."""

        now = datetime.now(timezone.utc)
        with self.database.transaction() as session:
            row = session.scalar(select(TelegramLinkRow).where(TelegramLinkRow.chat_id == str(chat_id)))
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = now
            session.execute(
                delete(TelegramSubscriptionRow).where(TelegramSubscriptionRow.chat_id == str(chat_id))
            )
        return True

    def unlink_account(self, user_email: str) -> int:
        """Revoke every chat bound to an account. Returns how many were closed."""

        now = datetime.now(timezone.utc)
        with self.database.transaction() as session:
            rows = session.scalars(
                select(TelegramLinkRow).where(
                    TelegramLinkRow.user_email == user_email,
                    TelegramLinkRow.revoked_at.is_(None),
                )
            ).all()
            for row in rows:
                row.revoked_at = now
                session.execute(
                    delete(TelegramSubscriptionRow).where(TelegramSubscriptionRow.chat_id == row.chat_id)
                )
        return len(rows)

    def link_status(self, user_email: str) -> LinkStatus:
        with self.database.sessions() as session:
            row = session.scalar(
                select(TelegramLinkRow).where(
                    TelegramLinkRow.user_email == user_email,
                    TelegramLinkRow.revoked_at.is_(None),
                )
            )
        if row is None:
            return LinkStatus(linked=False, chat_id=None, username=None, linked_at=None)
        return LinkStatus(linked=True, chat_id=row.chat_id, username=row.username, linked_at=row.created_at)

    def linked_chats(self) -> list[str]:
        """Every chat with an active link. Used by the notification dispatchers."""

        with self.database.sessions() as session:
            rows = session.scalars(
                select(TelegramLinkRow).where(TelegramLinkRow.revoked_at.is_(None))
            ).all()
        return [row.chat_id for row in rows]

    def owner_of(self, chat_id: str) -> str | None:
        """Return the account a chat is linked to, or ``None`` when unlinked."""

        with self.database.sessions() as session:
            row = session.scalar(
                select(TelegramLinkRow).where(
                    TelegramLinkRow.chat_id == str(chat_id),
                    TelegramLinkRow.revoked_at.is_(None),
                )
            )
        return row.user_email if row else None

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    def _ensure_subscription(self, chat_id: str) -> None:
        with self.database.transaction() as session:
            if session.get(TelegramSubscriptionRow, str(chat_id)) is None:
                session.add(TelegramSubscriptionRow(
                    chat_id=str(chat_id),
                    kinds=list(NOTIFICATION_KINDS),
                    thresholds=dict(DEFAULT_THRESHOLDS),
                    daily_digest=False,
                    updated_at=datetime.now(timezone.utc),
                ))

    def subscription(self, chat_id: str) -> dict:
        self._ensure_subscription(chat_id)
        with self.database.sessions() as session:
            row = session.get(TelegramSubscriptionRow, str(chat_id))
            return {
                "chatId": row.chat_id,
                "kinds": list(row.kinds or []),
                "thresholds": {**DEFAULT_THRESHOLDS, **(row.thresholds or {})},
                "dailyDigest": bool(row.daily_digest),
                "updatedAt": row.updated_at.isoformat(),
            }

    def update_subscription(
        self, chat_id: str, *, kinds: list[str] | None = None,
        thresholds: dict | None = None, daily_digest: bool | None = None,
    ) -> dict:
        """Validate and store preferences. Unknown kinds and bad thresholds are refused."""

        if kinds is not None:
            unknown = sorted(set(kinds) - set(NOTIFICATION_KINDS))
            if unknown:
                raise ValueError(f"неизвестные типы уведомлений: {', '.join(unknown)}")
        if thresholds:
            for key, value in thresholds.items():
                if key not in DEFAULT_THRESHOLDS:
                    raise ValueError(f"неизвестный порог: {key}")
                if not isinstance(value, (int, float)) or value < 0:
                    raise ValueError(f"порог {key} должен быть неотрицательным числом")

        self._ensure_subscription(chat_id)
        with self.database.transaction() as session:
            row = session.get(TelegramSubscriptionRow, str(chat_id))
            if kinds is not None:
                row.kinds = sorted(set(kinds))
            if thresholds:
                row.thresholds = {**(row.thresholds or {}), **thresholds}
            if daily_digest is not None:
                row.daily_digest = bool(daily_digest)
            row.updated_at = datetime.now(timezone.utc)
        return self.subscription(chat_id)

    def set_kinds_for_account(self, user_email: str, kinds: list[str]) -> dict:
        status = self.link_status(user_email)
        if not status.linked or status.chat_id is None:
            raise TelegramLinkError("Telegram не подключён.")
        return self.update_subscription(status.chat_id, kinds=kinds)

    def set_thresholds_for_account(self, user_email: str, thresholds: dict) -> dict:
        status = self.link_status(user_email)
        if not status.linked or status.chat_id is None:
            raise TelegramLinkError("Telegram не подключён.")
        return self.update_subscription(status.chat_id, thresholds=thresholds)

    # ------------------------------------------------------------------ #
    # Delivery
    # ------------------------------------------------------------------ #

    def _claim(self, dedupe_key: str, chat_id: str, kind: str) -> bool:
        """Reserve the right to send one event. ``False`` means already sent.

        The unique index on ``dedupe_key`` is the lock: a concurrent duplicate
        loses the insert and does not send.
        """

        with self.database.transaction() as session:
            session.add(TelegramDeliveryRow(
                dedupe_key=dedupe_key,
                chat_id=str(chat_id),
                kind=kind,
                status="pending",
                detail=None,
                created_at=datetime.now(timezone.utc),
            ))
        return True

    def _release(self, dedupe_key: str) -> None:
        """Drop a claim so the same event may be attempted again later.

        Used when the claim did not result in an attempt — a rate-limited send.
        Keeping the row would make the key permanently "seen", so the event would
        be lost rather than retried once the window passes.
        """

        with self.database.transaction() as session:
            row = session.scalar(
                select(TelegramDeliveryRow).where(TelegramDeliveryRow.dedupe_key == dedupe_key)
            )
            if row is not None:
                session.delete(row)

    def _finish(self, dedupe_key: str, status: str, detail: str | None = None) -> None:
        with self.database.transaction() as session:
            row = session.scalar(
                select(TelegramDeliveryRow).where(TelegramDeliveryRow.dedupe_key == dedupe_key)
            )
            if row is not None:
                row.status = status
                row.detail = (detail or "")[:300] or None

    def send(self, chat_id: str, text: str, *, kind: str = "manual", dedupe_key: str | None = None) -> bool:
        """Send one message, respecting the rate limit and the dedupe key.

        Returns ``True`` when the message was delivered. A Telegram failure is
        logged and returned as ``False`` — it must never break the caller, which
        may be an analytics request.
        """

        chat = str(chat_id)
        if dedupe_key is not None:
            try:
                if not self._claim(dedupe_key, chat, kind):
                    return False
            except IntegrityError:
                # Another worker already claimed this event.
                return False

        if not self._rate_limit_ok(chat):
            if dedupe_key:
                # Release rather than mark: a rate-limited send never happened, so
                # the event must stay deliverable once the window passes.
                self._release(dedupe_key)
            logger.warning("telegram send skipped: rate limited")
            return False

        try:
            self.client.send_message(chat, text)
        except TelegramRejected as exc:
            if dedupe_key:
                self._finish(dedupe_key, "rejected", exc.description)
            logger.warning("telegram rejected the message: %s", exc.description)
            return False
        except (TelegramUnavailable, TelegramError) as exc:
            if dedupe_key:
                self._finish(dedupe_key, "unavailable", str(exc))
            logger.warning("telegram unavailable: %s", exc)
            return False

        if dedupe_key:
            self._finish(dedupe_key, "sent")
        return True

    def _rate_limit_ok(self, chat_id: str) -> bool:
        import time

        now = time.monotonic()
        window = self.settings.telegram_min_send_interval_seconds
        last = self._last_send.get(chat_id)
        if last is not None and now - last < window:
            return False
        self._last_send[chat_id] = now
        return True

    def deliveries(self, limit: int = 50, *, chat_id: str | None = None) -> list[dict]:
        """Recent delivery records, optionally scoped to one chat.

        ``chat_id`` is how the diagnostics route limits the view to the caller's
        own linked chat: without it any authenticated user would see every chat's
        identifier and delivery history.
        """

        with self.database.sessions() as session:
            statement = select(TelegramDeliveryRow).order_by(TelegramDeliveryRow.created_at.desc())
            if chat_id is not None:
                statement = statement.where(TelegramDeliveryRow.chat_id == str(chat_id))
            rows = session.scalars(statement.limit(limit)).all()
        return [
            {
                "dedupeKey": row.dedupe_key,
                "chatId": row.chat_id,
                "kind": row.kind,
                "status": row.status,
                "detail": row.detail,
                "createdAt": row.created_at.isoformat(),
            }
            for row in rows
        ]

    def purge_old_deliveries(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=DELIVERY_RETENTION_DAYS)
        with self.database.transaction() as session:
            result = session.execute(
                delete(TelegramDeliveryRow).where(TelegramDeliveryRow.created_at < cutoff)
            )
        return result.rowcount or 0
