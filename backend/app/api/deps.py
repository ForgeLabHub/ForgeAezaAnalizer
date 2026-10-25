from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from core import Core
from backend.auth.service import AuthService, AuthError
from backend.app.config import Settings
from backend.app.db import Database
from backend.app.modules import CalculationAdapter
from backend.app.storage import Storage

bearer = HTTPBearer(auto_error=False)
source_token_header = APIKeyHeader(name="X-Source-Token", auto_error=False)


@dataclass
class Runtime:
    settings: Settings
    database: Database
    storage: Storage
    auth: AuthService
    calculation: CalculationAdapter
    core: Core


    ai: object | None = None
    telegram: object | None = None


@dataclass(frozen=True)
class Principal:
    email: str
    session_id: str


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


def current_user(runtime: RuntimeDep, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Principal:
    if credentials is None:
        raise AuthError(401, "invalid_token", "Authentication required", {"WWW-Authenticate": "Bearer"})
    session, user, _ = runtime.auth.bearer(f"Bearer {credentials.credentials}")
    return Principal(user.login, session.id)


UserDep = Annotated[Principal, Depends(current_user)]


def source_ingest_actor(
    runtime: RuntimeDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    source_token: Annotated[str | None, Depends(source_token_header)],
) -> str:
    configured = runtime.settings.source_ingest_token
    if configured and source_token and hmac.compare_digest(source_token.encode(), configured.encode()):
        return "source-integration"
    return current_user(runtime, credentials).email


SourceIngestActorDep = Annotated[str, Depends(source_ingest_actor)]


def version_headers(response, payload: dict):
    if "generation" in payload:
        response.headers["X-Analysis-Generation"] = str(payload["generation"])
    response.headers["Cache-Control"] = "no-store"
    return payload
