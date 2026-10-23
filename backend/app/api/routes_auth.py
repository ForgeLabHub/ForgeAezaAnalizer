"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user, get_db
from app.api.schemas import LoginRequest, TokenResponse, UserInfo
from app.auth.security import create_access_token, verify_password
from app.config import get_settings
from app.db import UserRow

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, summary="Получить access-токен")
def login(payload: LoginRequest, session: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate with email + password and receive a bearer token.

    The same generic error is returned for an unknown user and a wrong password
    so the endpoint cannot be used to enumerate accounts.
    """

    user = session.scalar(select(UserRow).where(UserRow.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = get_settings()
    token = create_access_token(user.email)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.get("/me", response_model=UserInfo, summary="Текущий пользователь")
def me(principal: Principal = Depends(get_current_user)) -> UserInfo:
    return UserInfo(email=principal.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Выйти")
def logout(principal: Principal = Depends(get_current_user)) -> None:
    """Invalidate the client session.

    Tokens are stateless, so logout is enforced client-side by discarding the
    token; the endpoint exists so a client has an explicit, authenticated
    signal and so the contract in the brief is satisfied.
    """

    return None
