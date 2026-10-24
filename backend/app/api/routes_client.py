from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi.security import HTTPAuthorizationCredentials

from backend.app.api.deps import RuntimeDep
from backend.app.api.deps_client import ClientDep, client_bearer

router = APIRouter(prefix="/client", tags=["telegram-client"])


class TelegramSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initData: str = Field(min_length=1, max_length=4096)


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class SupportMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Сообщение не может быть пустым")
        return value


@router.post("/session", summary="Обменять проверенные данные Mini App на клиентскую сессию")
def create_session(payload: TelegramSessionRequest, runtime: RuntimeDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return runtime.telegram.create_client_session(payload.initData)


@router.post("/session/logout", status_code=204, summary="Завершить клиентскую сессию")
def logout(
    runtime: RuntimeDep,
    client: ClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(client_bearer)],
):
    runtime.telegram.revoke(credentials.credentials)
    return Response(status_code=204)


@router.get("/me", summary="Текущий привязанный аккаунт")
def me(runtime: RuntimeDep, client: ClientDep):
    return runtime.telegram.client_me(client)


@router.get("/account", summary="Баланс клиентского аккаунта")
def account(runtime: RuntimeDep, client: ClientDep):
    return runtime.telegram.client_account(client)


@router.get("/services", summary="Услуги клиентского аккаунта")
def services(runtime: RuntimeDep, client: ClientDep):
    return runtime.telegram.client_services(client)


@router.post("/notifications-consent", summary="Включить или отключить напоминания")
def notifications_consent(payload: ConsentRequest, runtime: RuntimeDep, client: ClientDep):
    return runtime.telegram.set_consent(client, payload.enabled)


@router.get("/support", summary="История диалога клиента с поддержкой")
def support_messages(
    runtime: RuntimeDep,
    client: ClientDep,
    conversation_id: Annotated[int | None, Query(alias="conversationId", ge=1)] = None,
):
    return runtime.telegram.client_support_messages(client, conversation_id)


@router.post("/support/messages", status_code=201, summary="Написать в поддержку")
def add_support_message(payload: SupportMessageRequest, runtime: RuntimeDep, client: ClientDep):
    return runtime.telegram.client_add_support_message(client, payload.text)
