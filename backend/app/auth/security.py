"""Authentication: password hashing and JWT bearer tokens."""

from __future__ import annotations

import datetime as dt
import hmac
import secrets

from jose import JWTError, jwt

from app.config import get_settings

# hashlib-based PBKDF2 keeps the dependency surface small and avoids the
# bcrypt backend-detection issues that passlib shows on modern Python builds.
_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_hex(16)
    digest = _pbkdf2(password, salt)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest}"


def _pbkdf2(password: str, salt: str) -> str:
    import hashlib

    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    import hashlib

    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(iterations)
    ).hex()
    return hmac.compare_digest(candidate, digest)


def create_access_token(subject: str, *, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    ttl = expires_minutes or settings.access_token_ttl_minutes
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=ttl)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Return the token subject, or ``None`` when the token is invalid/expired."""

    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
