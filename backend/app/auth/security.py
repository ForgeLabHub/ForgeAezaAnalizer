from __future__ import annotations

import hashlib
import hmac
import secrets
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

    def bootstrap(self):
        with self.database.sessions() as session:
            if session.scalar(select(UserRow.id).where(UserRow.email == self.settings.bootstrap_admin_email)):
                return
        password = self.settings.bootstrap_admin_password or "aeza-demo-password"
        try:
            with self.database.transaction() as session:
                session.add(UserRow(email=self.settings.bootstrap_admin_email,
                    password_hash=hash_password(password), created_at=datetime.now(timezone.utc)))
        except IntegrityError:
            with self.database.sessions() as session:
                if not session.scalar(select(UserRow.id).where(UserRow.email == self.settings.bootstrap_admin_email)):
                    raise

    def login(self, email: str, password: str) -> dict:
        with self.database.transaction() as session:
            user = session.scalar(select(UserRow).where(UserRow.email == email))
            matches = verify_password(password, user.password_hash if user else self.dummy_hash)
            if not user or not matches:
                raise Unauthorized("Неверный email или пароль")
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
