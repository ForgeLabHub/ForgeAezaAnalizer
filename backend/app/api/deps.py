from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core import Core
from backend.app.auth.security import AuthService, Principal, Unauthorized
from backend.app.config import Settings
from backend.app.db import Database
from backend.app.modules import CalculationAdapter
from backend.app.storage import Storage

bearer = HTTPBearer(auto_error=False)


@dataclass
class Runtime:
    settings: Settings
    database: Database
    storage: Storage
    auth: AuthService
    calculation: CalculationAdapter
    core: Core


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


def current_user(runtime: RuntimeDep, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Principal:
    if credentials is None:
        raise Unauthorized("Требуется авторизация")
    return runtime.auth.authenticate(credentials.credentials)


UserDep = Annotated[Principal, Depends(current_user)]


def version_headers(response, payload: dict):
    if "generation" in payload:
        response.headers["X-Analysis-Generation"] = str(payload["generation"])
    response.headers["Cache-Control"] = "no-store"
    return payload
