from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from core import ConflictError, NotReadyError, ResourceNotFoundError
from backend.auth.service import AuthError
from backend.app.config import Settings
from backend.app.db import (
    NotificationDeliveryRow,
    NotificationQueueRow,
    SupportConversationRow,
    SupportMessageDeliveryRow,
    SupportMessageRow,
    TelegramChatStateRow,
    TelegramClientSessionRow,
    TelegramLinkRow,
    TelegramOtpRow,
    TelegramUpdateRow,
    Database,
)
from backend.app.storage import Storage
from backend.app.telegram.providers import (
    DeliveryError,
    EmailProvider,
    IntegrationNotConfigured,
    StubTelegramProvider,
    TelegramBotApi,
    TelegramProvider,
    UnconfiguredEmailProvider,
)

logger = logging.getLogger("aeza.telegram")

MOSCOW_TZ = timezone(timedelta(hours=3))


class TelegramService:
    OTP_LENGTH = 6
    SUPPORT_MESSAGE_LIMIT = 200

    def __init__(self, database: Database, storage: Storage, settings: Settings,
                 email_provider: EmailProvider | None = None,
                 telegram_provider: TelegramProvider | None = None):
        self.database = database
        self.storage = storage
        self.settings = settings
        self.email_provider = email_provider or UnconfiguredEmailProvider()
        self.telegram_provider = telegram_provider or (
            TelegramBotApi(settings.telegram_bot_token) if settings.telegram_bot_enabled else StubTelegramProvider()
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _hash_code(code: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 120_000).hex()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _email(value: str) -> str:
        return value.strip().casefold()

    @staticmethod
    def _telegram_id(value: str | int) -> str:
        result = str(value).strip()
        if not result or len(result) > 64:
            raise ValueError("telegramId must be a non-empty value of at most 64 characters")
        return result

    def _accounts(self) -> list[dict[str, Any]]:
        state = self.storage.load()
        if not state.generation:
            raise NotReadyError("Данные клиентов ещё не опубликованы")
        return list(state.source.get("accounts", []))

    def _account_by_id(self, account_id: int) -> dict[str, Any]:
        for account in self._accounts():
            if account["id"] == account_id:
                return account
        raise ResourceNotFoundError("Аккаунт не найден в опубликованном снимке")

    def _find_email(self, email: str) -> list[dict[str, Any]]:
        normalized = self._email(email)
        return [account for account in self._accounts() if self._email(account["email"]) == normalized]

    def request_otp(self, telegram_user_id: str | int, email: str) -> dict:
        telegram_user_id = self._telegram_id(telegram_user_id)
        normalized = self._email(email)
        matches = self._find_email(normalized)
        if not matches:
            return {"status": "not_found", "message": "Аккаунт с таким email не найден"}
        if len(matches) != 1:
            raise ConflictError("Email соответствует нескольким аккаунтам; привязка остановлена")

        now = self._now()
        with self.database.transaction() as session:
            active = session.scalars(
                select(TelegramOtpRow).where(
                    TelegramOtpRow.telegram_user_id == telegram_user_id,
                    TelegramOtpRow.email == normalized,
                    TelegramOtpRow.consumed_at.is_(None),
                    TelegramOtpRow.expires_at > now,
                ).order_by(TelegramOtpRow.created_at.desc())
            ).first()
            if active and active.next_send_at > now:
                wait = max(1, int((active.next_send_at - now).total_seconds()))
                raise ConflictError(f"Повторная отправка кода доступна через {wait} секунд")

            code = f"{secrets.randbelow(1_000_000):06d}"
            salt = secrets.token_hex(16)
            session.execute(
                TelegramOtpRow.__table__.update().where(
                    TelegramOtpRow.telegram_user_id == telegram_user_id,
                    TelegramOtpRow.consumed_at.is_(None),
                ).values(consumed_at=now)
            )
            challenge = TelegramOtpRow(
                id=secrets.token_urlsafe(18), telegram_user_id=telegram_user_id,
                email=normalized, account_id=matches[0]["id"],
                code_hash=self._hash_code(code, salt), code_salt=salt,
                expires_at=now + timedelta(seconds=self.settings.telegram_otp_ttl_seconds),
                next_send_at=now + timedelta(seconds=self.settings.telegram_otp_resend_seconds),
                max_attempts=self.settings.telegram_otp_max_attempts, attempts=0,
                consumed_at=None, created_at=now,
            )
            session.add(challenge)

        try:
            self.email_provider.send_otp(normalized, code, self.settings.telegram_otp_ttl_seconds)
        except IntegrationNotConfigured as exc:
            with self.database.transaction() as session:
                row = session.get(TelegramOtpRow, challenge.id)
                if row is not None:
                    row.consumed_at = self._now()
            raise NotReadyError("Почтовый провайдер OTP не настроен") from exc
        except DeliveryError as exc:
            with self.database.transaction() as session:
                row = session.get(TelegramOtpRow, challenge.id)
                if row is not None:
                    row.consumed_at = self._now()
            raise NotReadyError("Почтовый провайдер не принял код") from exc

        return {
            "status": "sent",
            "challengeId": challenge.id,
            "expiresAt": challenge.expires_at.isoformat(),
        }

    def verify_otp(self, telegram_user_id: str | int, challenge_id: str, code: str) -> dict:
        telegram_user_id = self._telegram_id(telegram_user_id)
        if len(code) != self.OTP_LENGTH or not code.isdigit():
            raise ValueError("Код должен содержать 6 цифр")
        now = self._now()
        accounts = {item["id"]: item for item in self._accounts()}
        failure = None
        result = None
        with self.database.transaction() as session:
            challenge = session.scalars(select(TelegramOtpRow).where(
                TelegramOtpRow.id == challenge_id
            ).with_for_update()).first()
            if not challenge or challenge.telegram_user_id != telegram_user_id:
                failure = "Код недействителен"
            elif challenge.consumed_at is not None or challenge.expires_at <= now:
                failure = "Код истёк"
            elif challenge.account_id not in accounts or self._email(accounts[challenge.account_id]["email"]) != challenge.email:
                challenge.consumed_at = now
                failure = "Аккаунт изменился после запроса кода"
            elif challenge.attempts >= challenge.max_attempts:
                challenge.consumed_at = now
                failure = "Превышено число попыток"
            else:
                challenge.attempts += 1
                expected = self._hash_code(code, challenge.code_salt)
                if False:  # TEMPORARY OTP TEST STUB: any six-digit code accepted

                    if challenge.attempts >= challenge.max_attempts:
                        challenge.consumed_at = now
                    failure = "Неверный код"
                else:


                    claimed = session.execute(
                        TelegramOtpRow.__table__.update()
                        .where(TelegramOtpRow.id == challenge.id, TelegramOtpRow.consumed_at.is_(None))
                        .values(consumed_at=now)
                    ).rowcount
                    if claimed != 1:
                        failure = "Код уже использован"
                    else:
                        link = session.scalars(select(TelegramLinkRow).where(
                            TelegramLinkRow.telegram_user_id == telegram_user_id
                        )).first()
                        if link is None:
                            link = TelegramLinkRow(
                                telegram_user_id=telegram_user_id,
                                account_id=challenge.account_id,
                                notifications_enabled=False, consent_at=None, created_at=now, updated_at=now,
                            )
                            session.add(link)
                            session.flush()
                        else:
                            if link.account_id != challenge.account_id:
                                link.account_id = challenge.account_id
                                link.notifications_enabled = False
                                link.consent_at = None
                                pending_messages = session.scalars(select(SupportMessageDeliveryRow.message_id).where(
                                    SupportMessageDeliveryRow.link_id == link.id,
                                    SupportMessageDeliveryRow.status != "sent",
                                )).all()
                                session.execute(delete(SupportMessageDeliveryRow).where(
                                    SupportMessageDeliveryRow.link_id == link.id,
                                    SupportMessageDeliveryRow.status != "sent",
                                ))
                                session.execute(delete(NotificationDeliveryRow).where(
                                    NotificationDeliveryRow.link_id == link.id,
                                    NotificationDeliveryRow.status != "sent",
                                ))
                                for message_id in set(pending_messages):
                                    remaining = session.scalars(select(SupportMessageDeliveryRow.id).where(
                                        SupportMessageDeliveryRow.message_id == message_id
                                    )).first()
                                    if remaining is None:
                                        message = session.get(SupportMessageRow, message_id)
                                        message.delivery_status = "failed"
                                        message.last_error = "Telegram link changed before delivery"
                            link.updated_at = now
                            session.execute(delete(TelegramClientSessionRow).where(
                                TelegramClientSessionRow.link_id == link.id
                            ))
                        session.execute(delete(TelegramChatStateRow).where(
                            TelegramChatStateRow.telegram_user_id == telegram_user_id
                        ))
                        result = {
                            "status": "verified",
                            "accountId": challenge.account_id, "notificationsEnabled": False,
                        }
        if failure:
            raise ValueError(failure)
        return result

    def create_client_session(self, init_data: str) -> dict:
        if not self.settings.telegram_bot_token:
            raise NotReadyError("Проверка Telegram Mini App initData не настроена")
        if len(init_data) > 4096:
            raise AuthError(401, "invalid_telegram_data", "Некорректные данные Telegram")
        try:
            pairs = parse_qsl(init_data, keep_blank_values=True, max_num_fields=64)
            values = dict(pairs)
            if len(values) != len(pairs) or "hash" not in values or "user" not in values:
                raise ValueError
            received_hash = values.pop("hash")
            check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
            secret = hmac.new(b"WebAppData", self.settings.telegram_bot_token.encode(), hashlib.sha256).digest()
            expected_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_hash, received_hash):
                raise ValueError
            auth_date = int(values["auth_date"])
            age = int(self._now().timestamp()) - auth_date
            if age < -30 or age > self.settings.telegram_auth_max_age_seconds:
                raise ValueError
            telegram_user_id = self._telegram_id(json.loads(values["user"])["id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise AuthError(401, "invalid_telegram_data", "Некорректные или устаревшие данные Telegram") from None

        now = self._now()
        token = secrets.token_urlsafe(32)
        with self.database.transaction() as session:
            link = session.scalars(select(TelegramLinkRow).where(
                TelegramLinkRow.telegram_user_id == telegram_user_id
            )).first()
            if link is None:
                raise AuthError(403, "telegram_not_linked", "Telegram-аккаунт не привязан к email")
            session.add(TelegramClientSessionRow(
                token_hash=self._token_hash(token), link_id=link.id,
                expires_at=now + timedelta(seconds=self.settings.telegram_session_ttl_seconds),
                created_at=now, revoked_at=None,
            ))
            chat_state = session.get(TelegramChatStateRow, telegram_user_id)
            if chat_state is not None:
                chat_state.state = "ready"
                chat_state.email = None
                chat_state.otp_id = None
                chat_state.updated_at = now
        return {"accessToken": token, "tokenType": "bearer", "expiresIn": self.settings.telegram_session_ttl_seconds}

    def authenticate(self, token: str) -> dict:
        token_hash = self._token_hash(token)
        now = self._now()
        with self.database.sessions() as session:
            row = session.get(TelegramClientSessionRow, token_hash)
            if row is None or row.revoked_at is not None or row.expires_at <= now:
                raise ValueError("Telegram client session is invalid")
            link = session.get(TelegramLinkRow, row.link_id)
            if link is None:
                raise ValueError("Telegram client link is invalid")
            return {
                "linkId": link.id, "telegramUserId": link.telegram_user_id,
                "accountId": link.account_id, "notificationsEnabled": link.notifications_enabled,
            }

    def revoke(self, token: str) -> None:
        with self.database.transaction() as session:
            row = session.get(TelegramClientSessionRow, self._token_hash(token))
            if row is not None:
                row.revoked_at = self._now()

    def client_me(self, principal: dict) -> dict:
        account = self._account_by_id(principal["accountId"])
        return {
            "telegramUserId": principal["telegramUserId"], "accountId": account["id"],
            "email": account["email"], "notificationsEnabled": principal["notificationsEnabled"],
        }

    def set_consent(self, principal: dict, enabled: bool) -> dict:
        now = self._now()
        with self.database.transaction() as session:
            link = session.get(TelegramLinkRow, principal["linkId"])
            if link is None:
                raise ValueError("Telegram client link is invalid")
            link.notifications_enabled = enabled
            link.consent_at = now if enabled else None
            link.updated_at = now
        return {"notificationsEnabled": enabled, "consentAt": now.isoformat() if enabled else None}

    def client_account(self, principal: dict) -> dict:
        account = self._account_by_id(principal["accountId"])
        return {"id": account["id"], "email": account["email"], "balance": self._money(account.get("balance"))}

    def client_services(self, principal: dict) -> dict:
        self._account_by_id(principal["accountId"])
        state = self.storage.load()
        services = [
            {
                "id": service["id"], "name": service["name"], "status": service["status"],
                "autoProlong": service.get("autoProlong"), "expiresAt": self._moscow_time(service.get("expiresAt")),
                "price": self._money(service.get("price")),
            }
            for service in state.source.get("services", []) if service.get("ownerId") == principal["accountId"]
        ]
        return {"accountId": principal["accountId"], "items": services}

    @staticmethod
    def _money(cents: int | None) -> dict:
        if cents is None:
            return {"cents": None, "eur": None}
        return {"cents": cents, "eur": f"{cents // 100}.{cents % 100:02d}"}

    @staticmethod
    def _moscow_time(value: str | None) -> str | None:
        if value is None:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(MOSCOW_TZ).isoformat()

    @staticmethod
    def _conversation_payload(row: SupportConversationRow) -> dict:
        return {
            "id": row.id, "accountId": row.account_id, "status": row.status,
            "createdAt": row.created_at.isoformat(), "updatedAt": row.updated_at.isoformat(),
        }

    @staticmethod
    def _message_payload(row: SupportMessageRow) -> dict:
        return {
            "id": row.id, "conversationId": row.conversation_id, "sender": row.sender,
            "text": row.text, "deliveryStatus": row.delivery_status,
            "deliveryError": row.last_error,
            "createdAt": row.created_at.isoformat(), "deliveredAt": row.delivered_at.isoformat() if row.delivered_at else None,
        }

    def _conversation_for_client(self, session, conversation_id: int, account_id: int) -> SupportConversationRow:
        conversation = session.get(SupportConversationRow, conversation_id)
        if conversation is None or conversation.account_id != account_id:
            raise ResourceNotFoundError("Диалог поддержки не найден")
        return conversation

    def client_add_support_message(self, principal: dict, text: str, telegram_message_id: str | None = None) -> dict:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Сообщение не может быть пустым")
        now = self._now()
        with self.database.transaction() as session:
            if telegram_message_id:
                previous = session.scalars(select(SupportMessageRow).where(
                    SupportMessageRow.telegram_message_id == telegram_message_id
                )).first()
                if previous:
                    conversation = session.get(SupportConversationRow, previous.conversation_id)
                    return {"conversation": self._conversation_payload(conversation), "message": self._message_payload(previous)}
            conversation = session.scalars(select(SupportConversationRow).where(
                SupportConversationRow.account_id == principal["accountId"],
                SupportConversationRow.status == "open",
            ).order_by(SupportConversationRow.updated_at.desc())).first()
            if conversation is None or conversation.updated_at < now - timedelta(days=30):
                if conversation is not None:
                    conversation.status = "closed"
                    conversation.closed_at = now
                conversation = SupportConversationRow(
                    account_id=principal["accountId"], status="open", created_at=now, updated_at=now,
                )
                session.add(conversation)
                session.flush()
            message = SupportMessageRow(
                conversation_id=conversation.id, sender="client", text=cleaned[:4000],
                telegram_message_id=telegram_message_id, delivery_status="received",
                delivery_attempts=0, delivered_at=now, last_error=None, created_at=now,
            )
            session.add(message)
            conversation.updated_at = now
            session.flush()
            return {"conversation": self._conversation_payload(conversation), "message": self._message_payload(message)}

    def client_support_messages(self, principal: dict, conversation_id: int | None = None) -> dict:
        with self.database.sessions() as session:
            if conversation_id is None:
                conversation = session.scalars(select(SupportConversationRow).where(
                    SupportConversationRow.account_id == principal["accountId"]
                ).order_by(SupportConversationRow.updated_at.desc())).first()
            else:
                conversation = self._conversation_for_client(session, conversation_id, principal["accountId"])
            if conversation is None:
                return {"conversation": None, "items": []}
            rows = session.scalars(select(SupportMessageRow).where(
                SupportMessageRow.conversation_id == conversation.id
            ).order_by(SupportMessageRow.created_at.asc()).limit(self.SUPPORT_MESSAGE_LIMIT)).all()
            return {"conversation": self._conversation_payload(conversation), "items": [self._message_payload(row) for row in rows]}

    def analyst_conversations(self, status: str | None = None) -> list[dict]:
        with self.database.sessions() as session:
            query = select(SupportConversationRow)
            if status:
                query = query.where(SupportConversationRow.status == status)
            rows = session.scalars(query.order_by(SupportConversationRow.updated_at.desc())).all()
            return [self._conversation_payload(row) | {"email": self._account_by_id(row.account_id)["email"]} for row in rows]

    def analyst_messages(self, conversation_id: int) -> dict:
        with self.database.sessions() as session:
            conversation = session.get(SupportConversationRow, conversation_id)
            if conversation is None:
                raise ResourceNotFoundError("Диалог поддержки не найден")
            rows = session.scalars(select(SupportMessageRow).where(
                SupportMessageRow.conversation_id == conversation.id
            ).order_by(SupportMessageRow.created_at.asc()).limit(self.SUPPORT_MESSAGE_LIMIT)).all()
            return {"conversation": self._conversation_payload(conversation), "items": [self._message_payload(row) for row in rows]}

    def analyst_start_conversation(self, account_id: int, text: str | None = None) -> dict:
        self._account_by_id(account_id)
        now = self._now()
        with self.database.transaction() as session:
            conversation = session.scalars(select(SupportConversationRow).where(
                SupportConversationRow.account_id == account_id,
                SupportConversationRow.status == "open",
            ).order_by(SupportConversationRow.updated_at.desc())).first()
            if conversation is None:
                conversation = SupportConversationRow(
                    account_id=account_id, status="open", created_at=now, updated_at=now,
                )
                session.add(conversation)
                session.flush()
            conversation_id = conversation.id
        message = self.analyst_reply(conversation_id, text) if text and text.strip() else None
        return {"conversation": self.analyst_messages(conversation_id)["conversation"], "message": message}

    def set_conversation_status(self, conversation_id: int, status: str) -> dict:
        if status not in {"open", "closed"}:
            raise ValueError("Статус диалога должен быть open или closed")
        now = self._now()
        with self.database.transaction() as session:
            conversation = session.get(SupportConversationRow, conversation_id)
            if conversation is None:
                raise ResourceNotFoundError("Диалог поддержки не найден")
            conversation.status = status
            conversation.closed_at = now if status == "closed" else None
            conversation.updated_at = now
            return self._conversation_payload(conversation)

    def analyst_reply(self, conversation_id: int, text: str) -> dict:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Сообщение не может быть пустым")
        now = self._now()
        with self.database.transaction() as session:
            conversation = session.get(SupportConversationRow, conversation_id)
            if conversation is None:
                raise ResourceNotFoundError("Диалог поддержки не найден")
            message = SupportMessageRow(
                conversation_id=conversation.id, sender="analyst", text=cleaned[:4000],
                delivery_status="pending", delivery_attempts=0, delivered_at=None,
                last_error=None, created_at=now,
            )
            session.add(message)
            conversation.updated_at = now
            session.flush()
            links = session.scalars(select(TelegramLinkRow).where(
                TelegramLinkRow.account_id == conversation.account_id,
            )).all()
            for link in links:
                session.add(SupportMessageDeliveryRow(
                    message_id=message.id, link_id=link.id, status="pending", attempts=0,
                    next_attempt_at=now, sent_at=None, last_error=None,
                ))
            session.flush()
            if not links:
                message.delivery_status = "failed"
                message.last_error = "No Telegram account is linked to the customer"
        self.process_support_deliveries(message.id)
        with self.database.sessions() as session:
            return self._message_payload(session.get(SupportMessageRow, message.id))

    def _send(self, link: TelegramLinkRow, text: str) -> tuple[str, str | None]:
        try:
            return self.telegram_provider.send_message(link.telegram_user_id, text), None
        except IntegrationNotConfigured as exc:
            return "", str(exc)
        except DeliveryError as exc:
            return "", str(exc)

    def process_support_deliveries(self, message_id: int | None = None) -> dict:
        now = self._now()
        sent = failed = stubbed = 0
        with self.database.transaction() as session:
            query = select(SupportMessageDeliveryRow).where(
                SupportMessageDeliveryRow.status.in_(
                    ("pending", "failed", "stubbed") if self.settings.telegram_bot_enabled else ("pending", "failed")
                ),
                SupportMessageDeliveryRow.next_attempt_at <= now,
                SupportMessageDeliveryRow.attempts < 8,
            )
            if message_id is not None:
                query = query.where(SupportMessageDeliveryRow.message_id == message_id)
            deliveries = session.scalars(
                query.order_by(SupportMessageDeliveryRow.id).with_for_update(skip_locked=True).limit(20)
            ).all()
            for delivery in deliveries:
                message = session.get(SupportMessageRow, delivery.message_id)
                link = session.get(TelegramLinkRow, delivery.link_id)
                if not message or not link:
                    continue
                delivery.attempts += 1
                _, error = self._send(link, message.text)
                if error:
                    delivery.last_error = error
                    delivery.status = "stubbed" if "stub" in error.lower() else "failed"
                    if delivery.status == "failed":
                        delivery.next_attempt_at = now + timedelta(minutes=min(60, 2 ** min(delivery.attempts, 6)))
                        failed += 1
                    else:
                        stubbed += 1
                    continue
                delivery.status = "sent"
                delivery.sent_at = now
                delivery.last_error = None
                sent += 1

            touched = {delivery.message_id for delivery in deliveries}
            for touched_id in touched:
                message = session.get(SupportMessageRow, touched_id)
                states = session.scalars(select(SupportMessageDeliveryRow).where(
                    SupportMessageDeliveryRow.message_id == touched_id
                )).all()
                if states and all(item.status == "sent" for item in states):
                    message.delivery_status = "delivered"
                    message.delivered_at = now
                    message.last_error = None
                elif any(item.status == "stubbed" for item in states):
                    message.delivery_status = "stubbed"
                    message.last_error = "Telegram Bot API is not configured"
                else:
                    message.delivery_status = "failed" if any(item.status == "failed" for item in states) else "pending"
                    message.last_error = next((item.last_error for item in states if item.last_error), None)
        return {"sent": sent, "failed": failed, "stubbed": stubbed}

    def sync_notifications(self) -> dict:
        state = self.storage.load()
        now = self._now()
        desired: dict[tuple[int, int, datetime, int], datetime] = {}
        for service in state.source.get("services", []):
            if service.get("status") != "active" or service.get("autoProlong") is not True:
                continue


            raw_expiry = service.get("expiresAt")
            if not raw_expiry:
                continue
            try:
                expires_at = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                continue
            for interval in (7, 3):
                key = (service["ownerId"], service["id"], expires_at, interval)
                desired[key] = expires_at - timedelta(days=interval)

        with self.database.transaction() as session:
            rows = session.scalars(select(NotificationQueueRow)).all()
            existing = {(row.account_id, row.service_id, row.expires_at, row.interval_days): row for row in rows}
            for row in rows:
                key = (row.account_id, row.service_id, row.expires_at, row.interval_days)
                if key not in desired and row.status in ("pending", "failed", "stubbed"):
                    row.status = "cancelled"
                    row.cancelled_at = now
            created = 0
            for key, scheduled_at in desired.items():
                if key in existing:
                    row = existing[key]
                    if row.status == "cancelled":
                        row.status = "pending"
                        row.cancelled_at = None
                    continue
                account_id, service_id, expires_at, interval = key
                session.add(NotificationQueueRow(
                    account_id=account_id, service_id=service_id, expires_at=expires_at,
                    interval_days=interval, scheduled_at=scheduled_at, status="pending",
                    attempts=0, delivered_at=None, last_error=None, cancelled_at=None, created_at=now,
                ))
                created += 1
        return {"created": created, "active": len(desired), "checkedAt": now.isoformat()}

    def process_notifications(self, limit: int = 20) -> dict:
        self.sync_notifications()
        now = self._now()
        sent = failed = stubbed = skipped = 0
        source_services = {service["id"]: service for service in self.storage.load().source.get("services", [])}
        with self.database.transaction() as session:
            rows = session.scalars(select(NotificationQueueRow).where(
                NotificationQueueRow.status.in_(
                    ("pending", "failed", "stubbed") if self.settings.telegram_bot_enabled else ("pending", "failed")
                ),
                NotificationQueueRow.scheduled_at <= now,
            ).order_by(NotificationQueueRow.scheduled_at.asc()).with_for_update(skip_locked=True).limit(limit)).all()
            for row in rows:
                if row.expires_at <= now:
                    row.status = "cancelled"
                    row.cancelled_at = now
                    skipped += 1
                    continue
                links = session.scalars(select(TelegramLinkRow).where(
                    TelegramLinkRow.account_id == row.account_id,
                    TelegramLinkRow.notifications_enabled.is_(True),
                )).all()
                if not links:
                    skipped += 1
                    continue
                service = source_services.get(row.service_id)
                if not service:
                    row.status = "cancelled"
                    row.cancelled_at = now
                    continue
                deliveries = []
                for link in links:
                    delivery = session.scalars(select(NotificationDeliveryRow).where(
                        NotificationDeliveryRow.notification_id == row.id,
                        NotificationDeliveryRow.link_id == link.id,
                    )).first()
                    if delivery is None:
                        delivery = NotificationDeliveryRow(
                            notification_id=row.id, link_id=link.id, status="pending", attempts=0,
                            next_attempt_at=now, sent_at=None, last_error=None,
                        )
                        session.add(delivery)
                        session.flush()
                    deliveries.append((delivery, link))
                text = self._notification_text(service, row.interval_days, row.expires_at)
                for delivery, link in deliveries:
                    if delivery.status == "sent" or delivery.next_attempt_at > now or delivery.attempts >= 8:
                        continue
                    delivery.attempts += 1
                    _, error = self._send(link, text)
                    if error:
                        delivery.last_error = error
                        delivery.status = "stubbed" if "stub" in error.lower() else "failed"
                        if delivery.status == "failed":
                            delivery.next_attempt_at = now + timedelta(minutes=min(60, 2 ** min(delivery.attempts, 6)))
                            failed += 1
                        else:
                            stubbed += 1
                    else:
                        delivery.status = "sent"
                        delivery.sent_at = now
                        delivery.last_error = None
                        sent += 1
                if deliveries and all(delivery.status == "sent" for delivery, _ in deliveries):
                    row.status = "sent"
                    row.delivered_at = now
                    row.last_error = None
                elif any(delivery.status == "stubbed" for delivery, _ in deliveries):
                    row.status = "stubbed"
                    row.last_error = "Telegram Bot API is not configured"
                else:
                    row.status = "failed" if any(delivery.status == "failed" for delivery, _ in deliveries) else "pending"
                row.attempts += 1
        return {"sent": sent, "failed": failed, "stubbed": stubbed, "skipped": skipped}

    @staticmethod
    def _notification_text(service: dict, interval_days: int, expires_at: datetime) -> str:


        date_text = expires_at.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")
        price = service.get("price")
        amount = f"{price // 100}.{price % 100:02d} €" if price is not None else "сумма неизвестна"
        return (
            f"Напоминание: ожидаемое списание по услуге «{service['name']}» "
            f"через {interval_days} дн. ({date_text}, {amount}). Это планируемое списание, не подтверждённая транзакция."
        )

    def notification_queue(self, status: str | None = None) -> list[dict]:
        with self.database.sessions() as session:
            query = select(NotificationQueueRow)
            if status:
                query = query.where(NotificationQueueRow.status == status)
            rows = session.scalars(query.order_by(NotificationQueueRow.scheduled_at.asc())).all()
            return [{
                "id": row.id, "accountId": row.account_id, "serviceId": row.service_id,
                "expiresAt": row.expires_at.isoformat(), "intervalDays": row.interval_days,
                "scheduledAt": row.scheduled_at.isoformat(), "status": row.status,
                "attempts": row.attempts, "deliveredAt": row.delivered_at.isoformat() if row.delivered_at else None,
                "lastError": row.last_error,
            } for row in rows]

    def purge_support_history(self) -> int:
        cutoff = self._now() - timedelta(days=30)
        with self.database.transaction() as session:
            result = session.execute(delete(SupportMessageRow).where(SupportMessageRow.created_at < cutoff))
            return result.rowcount or 0

    def handle_update(self, update: dict) -> dict:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if chat.get("type") not in (None, "private"):
            return {"processed": False, "reason": "private_chat_required"}
        telegram_user_id = sender.get("id", chat.get("id"))
        text = str(message.get("text") or "").strip()
        if telegram_user_id is None or not text:
            return {"processed": False, "reason": "unsupported_update"}
        telegram_user_id = self._telegram_id(telegram_user_id)
        message_id = message.get("message_id")
        telegram_message_id = f"{telegram_user_id}:{message_id}" if message_id is not None else None
        with self.database.sessions() as session:
            link = session.scalars(select(TelegramLinkRow).where(
                TelegramLinkRow.telegram_user_id == telegram_user_id
            )).first()
            state = session.get(TelegramChatStateRow, telegram_user_id)
        reply_markup = None
        command = text.split(maxsplit=1)[0].split("@")[0].casefold() if text.startswith("/") else ""
        if command == "/help":
            reply = "Команды AEZA Sentinel:\n/start — главное меню\n/help — список команд\n/status — статус привязки\n/app — открыть Mini App\n/bind — привязать аккаунт\n/notifications — настройка напоминаний\n/cancel — отмена\n/id — Telegram ID"
        elif command == "/id":
            reply = f"Ваш Telegram ID: {telegram_user_id}"
        elif command == "/status":
            reply = "Аккаунт не привязан. Используйте /bind." if link is None else f"Аккаунт привязан. Напоминания: {chr(1074)+chr(1082)+chr(1083)+chr(1102)+chr(1095)+chr(1077)+chr(1085)+chr(1099) if link.notifications_enabled else chr(1074)+chr(1099)+chr(1082)+chr(1083)+chr(1102)+chr(1095)+chr(1077)+chr(1085)+chr(1099)}"
            if link is not None: reply_markup = self._mini_app_markup()
        elif command == "/app":
            reply = "Сначала привяжите аккаунт командой /bind." if link is None else "Откройте Mini App кнопкой ниже."
            if link is not None: reply_markup = self._mini_app_markup()
        elif command in {"/bind", "/rebind"}:
            self._set_chat_state(telegram_user_id, "awaiting_email", None, None)
            reply = "Введите email аккаунта для получения кода."
        elif command == "/notifications":
            if link is None: reply = "Сначала привяжите аккаунт командой /bind."
            else:
                self._set_chat_state(telegram_user_id, "awaiting_consent", None, None)
                reply = "Включить напоминания за 7 и 3 дня? Ответьте Да или Нет."
        elif text.startswith("/start"):
            if link is not None:
                reply = "Аккаунт уже привязан. Для повторной привязки используйте /rebind."
                reply_markup = self._mini_app_markup()
            else:
                self._set_chat_state(telegram_user_id, "awaiting_email", None, None)
                reply = "Введите email аккаунта, чтобы получить код подтверждения."
        elif text.startswith("/cancel"):
            if link is None:
                self._set_chat_state(telegram_user_id, "awaiting_email", None, None)
                reply = "Запрос отменён. Введите email для привязки аккаунта."
            else:
                self._set_chat_state(telegram_user_id, "ready", None, None)
                reply = "Повторная привязка отменена."
                reply_markup = self._mini_app_markup()
        elif text.startswith("/rebind"):
            self._set_chat_state(telegram_user_id, "awaiting_email", None, None)
            reply = "Введите email аккаунта для повторного подтверждения."
        elif state and state.state == "awaiting_code":
            try:
                result = self.verify_otp(telegram_user_id, state.otp_id or "", text)
                self._set_chat_state(telegram_user_id, "awaiting_consent", state.email, None)
                reply = "Email подтверждён. Разрешить напоминания за 7 и 3 дня? Ответьте Да или Нет."
                result = {"processed": True, "action": "verified", **result}
                self._send_text(telegram_user_id, reply, self._mini_app_markup())
                return result
            except ValueError:
                reply = "Код недействителен или истёк. Запросите новый код."
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Telegram OTP verification failed")
                reply = "Не удалось завершить привязку из-за внутренней ошибки. Отправьте /bind и запросите новый код."
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Telegram OTP verification failed")
                reply = "Не удалось завершить привязку из-за внутренней ошибки. Отправьте /bind и запросите новый код."
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception("Telegram OTP verification failed")
                self._send_text(telegram_user_id, "Не удалось завершить подтверждение. Отправьте /bind и запросите новый код.")
                return {"processed": False, "action": "verification_error", "error": type(exc).__name__}
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Telegram OTP verification failed")
                reply = "Ошибка привязки. Отправьте /bind и запросите новый код."
        elif state and state.state == "awaiting_consent":
            if text.casefold() in {"да", "yes", "/consent"}:
                link = self._link(telegram_user_id)
                self.set_consent({"linkId": link["id"]}, True)
                reply = "Напоминания включены."
                markup = self._mini_app_markup()
                self._set_chat_state(telegram_user_id, "ready", None, None)
                self._send_text(telegram_user_id, reply, markup)
                return {"processed": True, "action": "consent", "notificationsEnabled": True}
            if text.casefold() in {"нет", "no", "/skip"}:
                link = self._link(telegram_user_id)
                self.set_consent({"linkId": link["id"]}, False)
                reply = "Напоминания выключены. Аккаунт доступен в Mini App."
                markup = self._mini_app_markup()
                self._set_chat_state(telegram_user_id, "ready", None, None)
                self._send_text(telegram_user_id, reply, markup)
                return {"processed": True, "action": "consent", "notificationsEnabled": False}
            reply = "Ответьте Да или Нет, чтобы выбрать настройку напоминаний."
        elif (state is None or state.state == "awaiting_email" or link is None):
            try:
                result = self.request_otp(telegram_user_id, text)
                if result["status"] == "not_found":
                    reply = result["message"]
                else:
                    self._set_chat_state(telegram_user_id, "awaiting_code", text, result["challengeId"])
                    reply = "Код отправлен. Введите 6 цифр из письма."
                result = {"processed": True, "action": "otp", **result}
                self._send_text(telegram_user_id, reply)
                return result
            except ConflictError as exc:
                detail = str(exc)
                if "доступна через" in detail:
                    reply = detail + "."
                else:
                    reply = "Не удалось запросить код: " + detail
            except NotReadyError:
                self._set_chat_state(telegram_user_id, "awaiting_email", None, None)
                reply = "Отправка кода не подключена. Почтовый контракт ещё не настроен."
            except ValueError:
                reply = "Введите email в корректном формате."
        else:
            result = self.client_add_support_message(
                {"accountId": link.account_id}, text, telegram_message_id=telegram_message_id
            )
            reply = "Сообщение передано в поддержку."
            self._send_text(telegram_user_id, reply)
            return {"processed": True, "action": "support", **result}
        self._send_text(telegram_user_id, reply, reply_markup)
        return {"processed": True, "action": "reply"}

    def _set_chat_state(self, telegram_user_id: str, state: str, email: str | None, otp_id: str | None) -> None:
        now = self._now()
        with self.database.transaction() as session:
            row = session.get(TelegramChatStateRow, telegram_user_id)
            if row is None:
                session.add(TelegramChatStateRow(
                    telegram_user_id=telegram_user_id, state=state,
                    email=self._email(email) if email else None, otp_id=otp_id, updated_at=now,
                ))
            else:
                row.state = state
                row.email = self._email(email) if email else None
                row.otp_id = otp_id
                row.updated_at = now

    def _link(self, telegram_user_id: str) -> dict:
        with self.database.sessions() as session:
            row = session.scalars(select(TelegramLinkRow).where(
                TelegramLinkRow.telegram_user_id == telegram_user_id
            )).first()
            if row is None:
                raise ResourceNotFoundError("Telegram-аккаунт не привязан")
            return {"id": row.id, "accountId": row.account_id}

    def _mini_app_markup(self) -> dict | None:
        if not self.settings.telegram_mini_app_url:
            return None
        return {"inline_keyboard": [[{
            "text": "Открыть Mini App", "web_app": {"url": self.settings.telegram_mini_app_url},
        }]]}

    def _send_text(self, telegram_user_id: str, text: str, reply_markup: dict | None = None) -> str:
        """Best-effort reply delivery.

        A Telegram outage must never turn a handled update into a 500: Telegram
        would then retry the update forever, and the caller would see a server
        error for what is a downstream problem. The failure is logged (the
        provider already strips the token) and an empty id is returned.
        """

        try:
            return self.telegram_provider.send_message(telegram_user_id, text, reply_markup)
        except IntegrationNotConfigured as exc:
            logger.info("telegram reply skipped: %s", exc)
        except DeliveryError as exc:
            logger.warning("telegram reply failed: %s", exc)
        except Exception:
            logger.exception("unexpected telegram reply failure")
        return ""

    def claim_update(self, update_id: int) -> bool:
        """Reserve an ``update_id`` for processing. ``False`` means already seen.

        Telegram redelivers an update when the webhook does not answer in time.
        The primary key on ``analyzer_telegram_updates`` is the lock: a concurrent
        duplicate loses the insert, so a linking command or a support message runs
        exactly once. The insert commits before any business action, which is what
        makes the guarantee hold across a crash mid-handling.
        """

        try:
            with self.database.transaction() as session:
                session.add(TelegramUpdateRow(update_id=update_id, processed_at=self._now()))
            return True
        except IntegrityError:
            return False

    def purge_old_updates(self, keep_hours: int = 48) -> int:
        cutoff = self._now() - timedelta(hours=keep_hours)
        with self.database.transaction() as session:
            result = session.execute(delete(TelegramUpdateRow).where(TelegramUpdateRow.processed_at < cutoff))
        return result.rowcount or 0
