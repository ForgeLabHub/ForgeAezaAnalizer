from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.service import AuthError
from backend.app.api.deps import Runtime, RuntimeDep

client_bearer = HTTPBearer(auto_error=False)


def current_client(
    runtime: RuntimeDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(client_bearer)],
) -> dict:
    if credentials is None or runtime.telegram is None:
        raise AuthError(401, "invalid_token", "Требуется авторизация клиента", {"WWW-Authenticate": "Bearer"})
    try:
        return runtime.telegram.authenticate(credentials.credentials)
    except ValueError:
        raise AuthError(401, "invalid_token", "Сессия клиента недействительна", {"WWW-Authenticate": "Bearer"}) from None


ClientDep = Annotated[dict, Depends(current_client)]
