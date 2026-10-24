from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST
from sqlalchemy import select, text
from starlette.concurrency import run_in_threadpool

from core import ConflictError, Core, InvalidInput, NotReadyError, ResourceNotFoundError
from backend.app.api import routes_actions, routes_ai, routes_analytics, routes_auth, routes_customers, routes_export, routes_insights, routes_model, routes_source, routes_telegram
from backend.app.api.deps import Runtime, RuntimeDep
from backend.app.api.schemas import ErrorResponse
from backend.app.auth.security import AuthService, RateLimited, Unauthorized
from backend.app.ai.service import AIDisabled, AIService, AIUnavailable
from backend.app.config import Settings, get_settings
from backend.app.db import Database
from backend.app.metrics import Metrics
from backend.app.modules import AnalyticsModule, CalculationAdapter, ModuleContractError, UnavailableAnalytics, load_module
from backend.app.storage import Storage

logger = logging.getLogger("aeza")


def dispatch_notifications(runtime: Runtime) -> None:
    """Push notifications for the newly published generation to linked chats.

    Called after a recalculation publishes a new generation, so alerts follow the
    data instead of a timer that might race it. Failures are swallowed and
    logged: a Telegram problem must never affect the analytics run that produced
    the generation.
    """

    service = getattr(runtime, "telegram", None)
    if service is None:
        return
    try:
        from backend.app.integrations.telegram import notifications
        from backend.app.integrations.telegram.service import TelegramLinkRow

        analysis = runtime.calculation.calculate(runtime.storage.load())
        with runtime.database.sessions() as session:
            chats = [
                row.chat_id
                for row in session.scalars(
                    select(TelegramLinkRow).where(TelegramLinkRow.revoked_at.is_(None))
                ).all()
            ]
        for chat_id in chats:
            notifications.dispatch(
                service, analysis, settings=runtime.settings, chat_id=chat_id
            )
    except Exception:
        logger.exception("telegram notification dispatch failed; analytics unaffected")


async def recalculate(runtime: Runtime, stop: asyncio.Event):
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=runtime.settings.recalculate_seconds)
            return
        except asyncio.TimeoutError:
            try:
                await run_in_threadpool(runtime.core.update, actor="clock", recalculate=True)
                await run_in_threadpool(dispatch_notifications, runtime)
            except Exception:
                logger.exception("scheduled calculation failed; previous result retained")


def build_ai(storage: Storage, calculation: CalculationAdapter) -> AIService | None:
    """Construct the AI Analyst, or ``None`` if it cannot be built.

    A configuration error in the AI subsystem must not stop the analytics
    product from starting: the AI surface is optional, the risk engine is not.
    """

    try:
        return AIService(storage, calculation)
    except Exception:
        logger.exception("AI Analyst could not be initialised; continuing without it")
        return None


def build_telegram(settings: Settings, database: Database):
    """Build the Telegram service, or ``None`` when the feature is off.

    Same contract as the AI layer: an optional integration must never stop the
    analytics product from starting. A misconfiguration is logged and the
    integration is simply absent, which the API reports as ``enabled: false``.
    """

    if not settings.telegram_enabled:
        return None
    try:
        from backend.app.integrations.telegram.service import TelegramService

        return TelegramService(database, settings)
    except Exception:
        logger.exception("Telegram integration could not be initialised; continuing without it")
        return None


def create_app(settings: Settings | None = None, analytics: AnalyticsModule | None = None) -> FastAPI:
    settings = settings or get_settings()
    module = analytics if analytics is not None else load_module(os.getenv("AEZA_ANALYTICS_FACTORY", ""))

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = Database(settings.database_url)
        auth_database = Database(settings.auth_database_url)
        storage = Storage(database)
        calculation = CalculationAdapter(module)
        auth = AuthService(auth_database, settings)
        runtime = Runtime(settings, database, storage, auth, calculation,
            Core(storage, calculation, settings.reference_now), ai=None)
        stop = asyncio.Event()
        task = None

        def initialize():
            database.initialize()
            auth_database.initialize_auth()
            auth.bootstrap()
            if isinstance(module, UnavailableAnalytics):
                return
            state = storage.load()
            if not state.generation:
                source = json.loads(Path(settings.snapshot_path).read_text(encoding="utf-8")) if settings.seed_demo_data else {
                    "accounts": [], "services": [], "transactions": []}
                runtime.core.update(source=source)
            else:
                changed_engine = storage.summary()["engineVersion"] != calculation.definition().version
                runtime.core.update(recalculate=changed_engine)

        try:
            await run_in_threadpool(initialize)
            runtime.ai = build_ai(storage, calculation)
            runtime.telegram = build_telegram(settings, database)
            application.state.runtime = runtime
            application.state.metrics = Metrics(storage)
            if settings.as_of.lower() == "now" and not isinstance(module, UnavailableAnalytics):
                task = asyncio.create_task(recalculate(runtime, stop))
            yield
        finally:
            stop.set()
            if task is not None:
                await task
            database.engine.dispose()
            auth_database.engine.dispose()

    app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan,
        docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json", redoc_url=None,
        description="Ядро и API Aéza. Аналитика и risk-engine подключаются отдельным модулем.",
        responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
            409: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "PUT"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
        expose_headers=["X-Analysis-Generation"])

    @app.middleware("http")
    async def observe(request: Request, call_next):
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            if hasattr(request.app.state, "metrics"):
                route = getattr(request.scope.get("route"), "path", "unmatched")
                request.app.state.metrics.observe(route, request.method, status_code, time.perf_counter() - started)

    @app.exception_handler(Unauthorized)
    async def unauthorized(request: Request, error: Unauthorized):
        return JSONResponse({"detail": str(error)}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(RateLimited)
    async def rate_limited(request: Request, error: RateLimited):
        return JSONResponse({"detail": str(error)}, status_code=429,
            headers={"Retry-After": str(error.retry_after)})

    @app.exception_handler(InvalidInput)
    async def invalid_input(request: Request, error: InvalidInput):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, error: ConflictError):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(NotReadyError)
    async def unavailable(request: Request, error: NotReadyError):
        return JSONResponse({"detail": str(error)}, status_code=503, headers={"Retry-After": "5"})

    @app.exception_handler(AIDisabled)
    async def ai_disabled(request: Request, error: AIDisabled):
        return JSONResponse({"detail": str(error)}, status_code=503, headers={"Retry-After": "30"})

    @app.exception_handler(AIUnavailable)
    async def ai_unavailable(request: Request, error: AIUnavailable):
        return JSONResponse({"detail": str(error)}, status_code=503, headers={"Retry-After": "5"})

    @app.exception_handler(ResourceNotFoundError)
    async def not_found(request: Request, error: ResourceNotFoundError):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ModuleContractError)
    async def invalid_module(request: Request, error: ModuleContractError):
        logger.exception("analytics module contract violation")
        return JSONResponse({"detail": str(error)}, status_code=502)

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, error: RequestValidationError):
        errors = [{key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()[:20]]
        return JSONResponse({"detail": "Ошибка валидации запроса", "errors": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, error: Exception):
        logger.exception("unhandled API error")
        return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)

    @app.get("/health", tags=["ops"])
    def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    def ready(runtime: RuntimeDep):
        with runtime.database.sessions() as session:
            session.execute(text("SELECT 1"))
        if isinstance(module, UnavailableAnalytics):
            raise NotReadyError("Модуль аналитики и risk-engine пока не подключён")
        runtime.storage.summary()
        return {"status": "ready"}

    @app.get("/metrics", tags=["ops"], response_class=Response)
    def metrics(request: Request, runtime: RuntimeDep):
        header = request.headers.get("authorization", "")
        if settings.metrics_token:
            if not hmac.compare_digest(header.encode(), f"Bearer {settings.metrics_token}".encode()):
                raise Unauthorized("Требуется токен метрик")
        else:
            scheme, _, token = header.partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise Unauthorized("Требуется авторизация")
            runtime.auth.authenticate(token)
        return Response(request.app.state.metrics.render(), headers={"Content-Type": CONTENT_TYPE_LATEST})

    for router in (routes_auth.router, routes_customers.router, routes_analytics.router,
                   routes_model.router, routes_source.router, routes_insights.router,
                   routes_export.router, routes_ai.router, routes_actions.router,
                   routes_telegram.router):
        app.include_router(router, prefix=settings.api_prefix)
    return app
