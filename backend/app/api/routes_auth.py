from fastapi import APIRouter, Depends, Request, Response

from backend.app.api.deps import RuntimeDep, UserDep
from backend.app.api.schemas import LoginRequest, TokenResponse, UserInfo
from backend.auth.service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_COOKIE = "auth_session"
METRICS_COOKIE = "metrics_session"


def set_session_cookies(response: Response, runtime: RuntimeDep, value: str) -> None:
    cookie_options = {
        "max_age": runtime.auth.settings.session_ttl,
        "httponly": True,
        "secure": runtime.auth.settings.cookie_secure,
        "samesite": "lax",
    }
    response.set_cookie(SESSION_COOKIE, value, path="/api/v1/auth", **cookie_options)
    response.set_cookie(METRICS_COOKIE, value, path="/metrics", **cookie_options)


def require_trusted_origin(request: Request, runtime: RuntimeDep) -> None:
    allowed = set(runtime.settings.cors_origins) | {runtime.auth.settings.frontend_origin}
    origin = request.headers.get("origin")
    if (origin is not None and origin not in allowed) or (
        origin is None and request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise AuthError(403, "forbidden", "Untrusted request origin")


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(require_trusted_origin)])
def login(payload: LoginRequest, runtime: RuntimeDep, response: Response, request: Request):
    response.headers["Cache-Control"] = "no-store"
    client = request.client.host if request.client else ""
    user = runtime.auth.authenticate(payload.email, payload.password.get_secret_value(), client)
    session, cookie = runtime.auth.create_session(user)
    set_session_cookies(response, runtime, cookie)
    return runtime.auth.tokens(session, user)


@router.get("/me", response_model=UserInfo)
def me(user: UserDep):
    return {"email": user.email}


@router.post("/refresh", response_model=TokenResponse,
             dependencies=[Depends(require_trusted_origin)])
def refresh(request: Request, runtime: RuntimeDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    session = runtime.auth.session_from_cookie(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise AuthError(401, "invalid_token", "Authentication required", {"WWW-Authenticate": "Bearer"})
    set_session_cookies(response, runtime, request.cookies[SESSION_COOKIE])
    return runtime.auth.tokens(session, runtime.auth.user_for_session(session))


@router.post("/logout", status_code=204, dependencies=[Depends(require_trusted_origin)])
def logout(runtime: RuntimeDep, user: UserDep):
    runtime.auth.sessions.pop(user.session_id)
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE, path="/api/v1/auth", secure=runtime.auth.settings.cookie_secure,
        httponly=True, samesite="lax",
    )
    response.delete_cookie(
        METRICS_COOKIE, path="/metrics", secure=runtime.auth.settings.cookie_secure,
        httponly=True, samesite="lax",
    )
    return response
