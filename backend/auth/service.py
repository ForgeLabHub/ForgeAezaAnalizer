import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from threading import BoundedSemaphore

import jwt

from backend.auth.cache import LoginLimiter, TTLCache
from backend.auth.passwords import hash_password, verify_password
from backend.auth.tokens import TokenSigner, base64url
from backend.config import Settings
from backend.database import User, UserRepository


class AuthError(Exception):
    def __init__(self, status: int, error: str, description: str, headers: dict | None = None):
        self.status = status
        self.error = error
        self.description = description
        self.headers = headers


@dataclass(frozen=True)
class Session:
    id: str
    cookie_hash: str
    user_id: str
    auth_version: int
    auth_time: int
    expires_at: int


@dataclass(frozen=True)
class AuthorizationRequest:
    redirect_uri: str
    scope: str
    state: str | None
    nonce: str | None
    code_challenge: str


@dataclass(frozen=True)
class LoginFlow:
    authorization: AuthorizationRequest
    browser_hash: str


@dataclass(frozen=True)
class AuthorizationCode:
    authorization: AuthorizationRequest
    session_id: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class AuthService:
    def __init__(self, settings: Settings, users: UserRepository):
        self.settings = settings
        self.users = users
        self.signer = TokenSigner(settings)
        self.sessions: TTLCache[Session] = TTLCache(settings.cache_capacity)
        self.profiles: TTLCache[User] = TTLCache(settings.cache_capacity)
        self.flows: TTLCache[LoginFlow] = TTLCache(settings.cache_capacity)
        self.codes: TTLCache[AuthorizationCode] = TTLCache(settings.cache_capacity)
        self.limiter = LoginLimiter(settings.cache_capacity)
        self.password_slots = BoundedSemaphore(4)
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))

    def authenticate(self, login: str, password: str, address: str) -> User:
        if not self.limiter.check(address) or not self.password_slots.acquire(blocking=False):
            raise AuthError(429, "too_many_requests", "Try again later", {"Retry-After": "60"})
        try:
            record = self.users.credentials(login)
            valid = verify_password(password, record[1] if record else self.dummy_hash)
            if not valid or record is None or not record[0].is_active:
                raise AuthError(401, "invalid_credentials", "Invalid login or password")
            user = record[0]
            self.profiles.put(user.id, user, self.settings.user_cache_ttl)
            return user
        finally:
            self.password_slots.release()

    def create_session(self, user: User) -> tuple[Session, str]:
        now = int(time.time())
        secret = secrets.token_urlsafe(32)
        session = Session(
            secrets.token_urlsafe(24), digest(secret), user.id, user.auth_version,
            now, now + self.settings.session_ttl,
        )
        self.sessions.put(session.id, session, self.settings.session_ttl)
        return session, f"{session.id}.{secret}"

    def session_from_cookie(self, cookie: str | None) -> Session | None:
        if cookie is None or len(cookie) > 256:
            return None
        session_id, separator, secret = cookie.partition(".")
        session = self.sessions.get(session_id)
        if not separator or session is None or not hmac.compare_digest(session.cookie_hash, digest(secret)):
            return None
        return session if session.expires_at > int(time.time()) else None

    def user_for_session(self, session: Session) -> User:
        user = self.profiles.get(session.user_id)
        if user is None:
            user = self.users.find(session.user_id)
            if user is not None:
                self.profiles.put(user.id, user, self.settings.user_cache_ttl)
        if user is None or not user.is_active or user.auth_version != session.auth_version:
            self.sessions.pop(session.id)
            raise AuthError(401, "invalid_token", "Session is no longer valid", {"WWW-Authenticate": "Bearer"})
        return user

    def bearer(self, authorization: str | None) -> tuple[Session, User, dict]:
        scheme, _, token = (authorization or "").partition(" ")
        try:
            if scheme.lower() != "bearer" or not token:
                raise jwt.InvalidTokenError
            claims = self.signer.verify_access(token)
            session = self.sessions.get(claims["sid"])
            if session is None or session.expires_at <= int(time.time()) or session.user_id != claims["sub"]:
                raise jwt.InvalidTokenError
        except jwt.InvalidTokenError:
            raise AuthError(401, "invalid_token", "Invalid or expired access token", {"WWW-Authenticate": "Bearer"}) from None
        return session, self.user_for_session(session), claims

    def tokens(self, session: Session, user: User, authorization: AuthorizationRequest | None = None) -> dict:
        expires_in = min(self.settings.access_token_ttl, session.expires_at - int(time.time()))
        if expires_in <= 0:
            raise AuthError(401, "invalid_token", "Session expired")
        scope = authorization.scope if authorization else "openid profile"
        access = self.signer.access_token(user.id, session.id, expires_in, scope)
        response = {"access_token": access, "token_type": "Bearer", "expires_in": expires_in, "scope": scope}
        if authorization is not None:
            claims = user.claims() if "profile" in scope.split() else {"sub": user.id}
            response["id_token"] = self.signer.id_token(
                claims, session.id, session.auth_time, expires_in, authorization.nonce, access,
            )
        return response

    def create_flow(self, authorization: AuthorizationRequest, browser_secret: str) -> str:
        request_id = secrets.token_urlsafe(32)
        self.flows.put(
            digest(request_id), LoginFlow(authorization, digest(browser_secret)), self.settings.flow_ttl,
        )
        return request_id

    def flow(self, request_id: str, browser_secret: str | None, consume: bool = False) -> LoginFlow:
        lookup = self.flows.pop if consume else self.flows.get
        flow = lookup(digest(request_id))
        if flow is None or not browser_secret or not hmac.compare_digest(flow.browser_hash, digest(browser_secret)):
            raise AuthError(400, "invalid_request", "Login request expired or belongs to another browser")
        return flow

    def create_code(self, authorization: AuthorizationRequest, session: Session) -> str:
        code = secrets.token_urlsafe(32)
        self.codes.put(digest(code), AuthorizationCode(authorization, session.id), self.settings.code_ttl)
        return code

    def exchange_code(self, code: str, redirect_uri: str, verifier: str) -> dict:
        record = self.codes.pop(digest(code))
        if record is None:
            raise AuthError(400, "invalid_grant", "Invalid or expired authorization code")
        challenge = base64url(hashlib.sha256(verifier.encode()).digest())
        if (
            redirect_uri != record.authorization.redirect_uri
            or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
            or not hmac.compare_digest(challenge, record.authorization.code_challenge)
        ):
            raise AuthError(400, "invalid_grant", "Invalid redirect URI or PKCE verifier")
        session = self.sessions.get(record.session_id)
        if session is None or session.expires_at <= int(time.time()):
            raise AuthError(400, "invalid_grant", "Session expired")
        try:
            user = self.user_for_session(session)
        except AuthError:
            raise AuthError(400, "invalid_grant", "Session is no longer valid") from None
        return self.tokens(session, user, record.authorization)
