from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.app.config import Settings
from backend.app.db import AuthSessionRow, Database, UserRow

ITERATIONS = 600_000
ISSUER = "aeza-analyzer"
AUDIENCE = "aeza-api"


class Unauthorized(Exception):
    pass


class RateLimited(Exception):
    """Raised when a client exceeds the login attempt budget."""

    def __init__(self, retry_after: int):
        super().__init__("Слишком много попыток входа. Повторите позже.")
        self.retry_after = retry_after


class LoginThrottle:
    """Sliding-window limiter for failed login attempts.

    Keyed by ``email|client`` so one noisy client cannot lock an unrelated
    account out, and in-process on purpose: the reference deployment runs a
    single API worker, and a shared store would be a larger change than the
    threat warrants. Swap the store if the service is ever scaled out.
    """

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        attempts = self._failures[key]
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            attempts = self._failures[key]
            if len(attempts) >= self.max_attempts:
                retry_after = max(1, int(attempts[0] + self.window_seconds - now) + 1)
                raise RateLimited(retry_after)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            self._failures[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return "$".join(("pbkdf2_sha256", str(ITERATIONS), salt, digest))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$")
        iterations = int(iterations)
        if algorithm != "pbkdf2_sha256" or not 1 <= iterations <= 1_000_000:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Principal:
    email: str
    session_id: str


class AuthService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))
        self.throttle = LoginThrottle(
            settings.login_max_attempts, settings.login_window_seconds)

    def bootstrap(self):
        with self.database.sessions() as session:
            if session.scalar(select(UserRow.id).where(UserRow.email == self.settings.bootstrap_admin_email)):
                return
        # Dev-only fallback: reachable only while AEZA_ALLOW_DEV_SECRET is on and
        # no password was supplied.  Production settings refuse to start without
        # AEZA_ADMIN_PASSWORD, so this value never reaches a shared environment.
        # It matches the Compose default so a bare `uvicorn` run and the demo
        # stand share one credential instead of two.
        password = self.settings.bootstrap_admin_password or "demo123"
        try:
            with self.database.transaction() as session:
                session.add(UserRow(email=self.settings.bootstrap_admin_email,
                    password_hash=hash_password(password), created_at=datetime.now(timezone.utc)))
        except IntegrityError:
            with self.database.sessions() as session:
                if not session.scalar(select(UserRow.id).where(UserRow.email == self.settings.bootstrap_admin_email)):
                    raise

    def login(self, email: str, password: str, client: str = "") -> dict:
        key = f"{email.strip().lower()}|{client}"
        self.throttle.check(key)
        with self.database.transaction() as session:
            user = session.scalar(select(UserRow).where(UserRow.email == email))
            matches = verify_password(password, user.password_hash if user else self.dummy_hash)
            if not user or not matches:
                self.throttle.record_failure(key)
                raise Unauthorized("Неверный email или пароль")
            self.throttle.reset(key)
            now = datetime.now(timezone.utc)
            expires = now + timedelta(minutes=self.settings.access_token_ttl_minutes)
            session.execute(delete(AuthSessionRow).where(AuthSessionRow.expires_at <= now))
            session_id = secrets.token_urlsafe(32)
            session.add(AuthSessionRow(id=session_id, user_id=user.id, expires_at=expires))
            token = jwt.encode({"sub": str(user.id), "jti": session_id, "iat": int(now.timestamp()),
                "exp": int(expires.timestamp()), "iss": ISSUER, "aud": AUDIENCE},
                self.settings.jwt_secret, algorithm="HS256")
            return {"access_token": token, "token_type": "bearer",
                "expires_in": self.settings.access_token_ttl_minutes * 60}

    def authenticate(self, token: str) -> Principal:
        try:
            claims = jwt.decode(token, self.settings.jwt_secret, algorithms=["HS256"],
                issuer=ISSUER, audience=AUDIENCE,
                options={"require_exp": True, "require_sub": True, "require_iat": True, "require_jti": True})
            session_id = claims["jti"]
            if not isinstance(session_id, str):
                raise ValueError
            with self.database.sessions() as session:
                record = session.get(AuthSessionRow, session_id)
                if record is None or record.expires_at <= datetime.now(timezone.utc):
                    raise ValueError
                if claims["sub"] != str(record.user_id):
                    raise ValueError
                user = session.get(UserRow, record.user_id)
                if user is None:
                    raise ValueError
                return Principal(user.email, session_id)
        except (JWTError, ValueError, KeyError, TypeError) as exc:
            raise Unauthorized("Недействительный или истёкший токен") from exc

    def logout(self, principal: Principal):
        with self.database.transaction() as session:
            session.execute(delete(AuthSessionRow).where(AuthSessionRow.id == principal.session_id))
