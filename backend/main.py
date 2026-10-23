import base64
import hmac
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, SecretStr
from starlette.concurrency import run_in_threadpool

from backend.auth.cache import CacheFull
from backend.auth.service import AuthError, AuthService, AuthorizationRequest, Session
from backend.config import Settings
from backend.database import User, UserRepository


SESSION_COOKIE = "auth_session"
FLOW_COOKIE = "auth_flow"


class LoginInput(BaseModel):
    login: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


def with_query(url: str, parameters: dict) -> str:
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key not in parameters]
    query.extend((key, value) for key, value in parameters.items() if value is not None)
    return urlunsplit(parts._replace(query=urlencode(query)))


def get_auth(request: Request) -> AuthService:
    return request.app.state.auth


Auth = Annotated[AuthService, Depends(get_auth)]


def require_origin(request: Request) -> None:
    settings = request.app.state.auth.settings
    issuer = urlsplit(settings.issuer)
    allowed = {settings.frontend_origin, f"{issuer.scheme}://{issuer.netloc}"}
    origin = request.headers.get("origin")
    if (origin is not None and origin not in allowed) or (
        origin is None and request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise AuthError(403, "forbidden", "Untrusted request origin")


def current_user(request: Request, auth: AuthService) -> tuple[Session, User]:
    if "authorization" in request.headers:
        session, user, _ = auth.bearer(request.headers["authorization"])
        return session, user
    session = auth.session_from_cookie(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise AuthError(401, "invalid_token", "Authentication required", {"WWW-Authenticate": "Bearer"})
    return session, auth.user_for_session(session)


def authenticate_client(auth: AuthService, fields: dict[str, str], header: str | None) -> None:
    settings = auth.settings
    valid = False
    if settings.client_secret:
        try:
            scheme, encoded = (header or "").split(" ", 1)
            if scheme.lower() != "basic":
                raise ValueError
            client_id, secret = base64.b64decode(encoded, validate=True).decode().split(":", 1)
            valid = (
                hmac.compare_digest(unquote_plus(client_id).encode(), settings.client_id.encode())
                and hmac.compare_digest(unquote_plus(secret).encode(), settings.client_secret.encode())
                and fields.get("client_id", settings.client_id) == settings.client_id
                and "client_secret" not in fields
            )
        except (ValueError, UnicodeError):
            pass
    else:
        valid = header is None and fields.get("client_id") == settings.client_id and "client_secret" not in fields
    if not valid:
        raise AuthError(401, "invalid_client", "Client authentication failed", {"WWW-Authenticate": "Basic"})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        users = UserRepository(settings.database)
        users.initialize()
        app.state.auth = AuthService(settings, users)
        yield

    app = FastAPI(title="Authentication and OIDC", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True,
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        })
        return response

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, error: AuthError):
        return JSONResponse(
            {"error": error.error, "error_description": error.description},
            status_code=error.status, headers=error.headers,
        )

    @app.exception_handler(CacheFull)
    async def cache_full(request: Request, error: CacheFull):
        return JSONResponse({"error": "temporarily_unavailable"}, status_code=503, headers={"Retry-After": "60"})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        details = [{key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()]
        return JSONResponse({"detail": details}, status_code=422)

    @app.post("/auth/login", dependencies=[Depends(require_origin)])
    def login(data: LoginInput, request: Request, auth: Auth):
        browser_secret = request.cookies.get(FLOW_COOKIE)
        if data.request_id:
            auth.flow(data.request_id, browser_secret)
        address = request.client.host if request.client else "unknown"
        user = auth.authenticate(data.login, data.password.get_secret_value(), address)
        flow = auth.flow(data.request_id, browser_secret, consume=True) if data.request_id else None
        session, cookie = auth.create_session(user)
        result = {**auth.tokens(session, user), "user": user.claims()}
        if flow:
            code = auth.create_code(flow.authorization, session)
            result["redirect_url"] = with_query(flow.authorization.redirect_uri, {
                "code": code, "state": flow.authorization.state,
            })
        previous = auth.session_from_cookie(request.cookies.get(SESSION_COOKIE))
        if previous:
            auth.sessions.pop(previous.id)
        response = JSONResponse(result)
        response.set_cookie(
            SESSION_COOKIE, cookie, max_age=settings.session_ttl, httponly=True,
            secure=settings.cookie_secure, samesite="lax", path="/",
        )
        return response

    @app.get("/auth/me")
    def me(request: Request, auth: Auth):
        _, user = current_user(request, auth)
        return user.claims()

    @app.post("/auth/refresh", dependencies=[Depends(require_origin)])
    def refresh(request: Request, auth: Auth):
        session = auth.session_from_cookie(request.cookies.get(SESSION_COOKIE))
        if session is None:
            raise AuthError(401, "invalid_token", "Authentication required")
        return auth.tokens(session, auth.user_for_session(session))

    @app.post("/auth/logout", status_code=204, dependencies=[Depends(require_origin)])
    def logout(request: Request, auth: Auth):
        if "authorization" in request.headers:
            session, _, _ = auth.bearer(request.headers["authorization"])
            auth.sessions.pop(session.id)
        session = auth.session_from_cookie(request.cookies.get(SESSION_COOKIE))
        if session:
            auth.sessions.pop(session.id)
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
        return response

    @app.get("/.well-known/openid-configuration")
    def discovery():
        return {
            "issuer": settings.issuer,
            "authorization_endpoint": f"{settings.issuer}/oidc/authorize",
            "token_endpoint": f"{settings.issuer}/oidc/token",
            "userinfo_endpoint": f"{settings.issuer}/oidc/userinfo",
            "jwks_uri": f"{settings.issuer}/oidc/jwks",
            "response_types_supported": ["code"], "response_modes_supported": ["query"],
            "subject_types_supported": ["public"], "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile"], "grant_types_supported": ["authorization_code"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic" if settings.client_secret else "none"],
            "code_challenge_methods_supported": ["S256"],
            "claims_supported": ["sub", "iss", "aud", "exp", "iat", "auth_time", "nonce", "sid", "amr", "at_hash", "preferred_username"],
            "request_parameter_supported": False, "request_uri_parameter_supported": False,
            "claims_parameter_supported": False,
        }

    @app.get("/oidc/jwks")
    def jwks(auth: Auth):
        return auth.signer.jwks()

    @app.get("/oidc/authorize")
    def authorize(request: Request, auth: Auth):
        pairs = list(request.query_params.multi_items())
        if len(pairs) != len(dict(pairs)) or len(str(request.url)) > 8192:
            raise AuthError(400, "invalid_request", "Duplicate or oversized parameters")
        parameters = dict(pairs)
        redirect_uri = parameters.get("redirect_uri", "")
        if parameters.get("client_id") != settings.client_id or redirect_uri not in settings.redirect_uris:
            raise AuthError(400, "invalid_request", "Unknown client or unregistered redirect URI")
        state = parameters.get("state")

        def error(name: str, description: str):
            return RedirectResponse(with_query(redirect_uri, {
                "error": name, "error_description": description, "state": state,
            }), status_code=302)

        if parameters.get("response_type") != "code":
            return error("unsupported_response_type", "Only authorization code flow is supported")
        if any(key in parameters for key in ("request", "request_uri", "claims")):
            return error("invalid_request", "Request objects and claims requests are not supported")
        if parameters.get("response_mode", "query") != "query":
            return error("invalid_request", "Only query response mode is supported")
        scopes = set(parameters.get("scope", "").split())
        if "openid" not in scopes or not scopes.issubset({"openid", "profile"}):
            return error("invalid_scope", "Supported scopes are openid and profile")
        challenge = parameters.get("code_challenge", "")
        if parameters.get("code_challenge_method") != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
            return error("invalid_request", "PKCE with S256 is required")
        prompt = parameters.get("prompt", "")
        if prompt not in {"", "none", "login"}:
            return error("invalid_request", "Supported prompts are none and login")
        max_age = parameters.get("max_age")
        if max_age is not None and not re.fullmatch(r"[0-9]{1,10}", max_age):
            return error("invalid_request", "max_age must be a nonnegative integer")
        authorization = AuthorizationRequest(
            redirect_uri, " ".join(sorted(scopes)), state, parameters.get("nonce"), challenge,
        )
        session = auth.session_from_cookie(request.cookies.get(SESSION_COOKIE))
        if session:
            try:
                auth.user_for_session(session)
            except AuthError:
                session = None
        if prompt == "login" or (session and max_age is not None and (
            int(max_age) == 0 or int(time.time()) - session.auth_time > int(max_age)
        )):
            session = None
        if session is not None:
            code = auth.create_code(authorization, session)
            return RedirectResponse(with_query(redirect_uri, {"code": code, "state": state}), status_code=302)
        if prompt == "none":
            return error("login_required", "Authentication required")
        browser_secret = request.cookies.get(FLOW_COOKIE)
        if browser_secret is None or not re.fullmatch(r"[A-Za-z0-9_-]{43}", browser_secret):
            browser_secret = secrets.token_urlsafe(32)
        request_id = auth.create_flow(authorization, browser_secret)
        response = RedirectResponse(with_query(settings.frontend_login_url, {"request_id": request_id}), status_code=302)
        response.set_cookie(
            FLOW_COOKIE, browser_secret, max_age=settings.flow_ttl, httponly=True,
            secure=settings.cookie_secure, samesite="lax", path="/",
        )
        return response

    @app.post("/oidc/token")
    async def token(request: Request, auth: Auth):
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/x-www-form-urlencoded":
            raise AuthError(400, "invalid_request", "Expected application/x-www-form-urlencoded")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise AuthError(400, "invalid_request", "Request body too large")
        try:
            pairs = parse_qsl(body.decode(), keep_blank_values=True, max_num_fields=16)
        except (ValueError, UnicodeError):
            raise AuthError(400, "invalid_request", "Invalid form body") from None
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise AuthError(400, "invalid_request", "Duplicate form parameters")
        authenticate_client(auth, fields, request.headers.get("authorization"))
        if fields.get("grant_type") != "authorization_code":
            raise AuthError(400, "unsupported_grant_type", "Only authorization_code is supported")
        if not all(fields.get(key) for key in ("code", "redirect_uri", "code_verifier")):
            raise AuthError(400, "invalid_request", "code, redirect_uri and code_verifier are required")
        return await run_in_threadpool(auth.exchange_code, fields["code"], fields["redirect_uri"], fields["code_verifier"])

    @app.api_route("/oidc/userinfo", methods=["GET", "POST"])
    def userinfo(request: Request, auth: Auth):
        _, user, claims = auth.bearer(request.headers.get("authorization"))
        return user.claims() if "profile" in claims["scope"].split() else {"sub": user.id}

    return app


app = create_app()
