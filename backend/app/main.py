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
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from core import ConflictError, Core, InvalidInput, NotReadyError, ResourceNotFoundError
from backend.app.api import routes_actions, routes_ai, routes_analytics, routes_auth, routes_client, routes_customers, routes_email, routes_export, routes_insights, routes_model, routes_source, routes_telegram
from backend.app.api.deps import Runtime, RuntimeDep
from backend.app.api.schemas import ErrorResponse
from backend.app.ai.service import AIDisabled, AIService, AIUnavailable
from backend.app.config import Settings, get_settings
from backend.app.db import Database
from backend.app.integrations.email import EmailDisabled, EmailRejected, EmailUnavailable, SmtpBzEmailProvider
from backend.app.metrics import Metrics
from backend.app.modules import AnalyticsModule, CalculationAdapter, ModuleContractError, UnavailableAnalytics, load_module
from backend.app.storage import Storage
from backend.app.telegram import EmailProvider, TelegramProvider, TelegramService
from backend.auth.service import AuthError, AuthService
from backend.config import Settings as AuthSettings
from backend.database import UserRepository

logger = logging.getLogger("aeza")


def snapshot_file_signature(path: Path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size, getattr(stat, "st_ino", 0)


def read_snapshot_file(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


async def snapshot_file_worker(runtime: Runtime, stop: asyncio.Event):
    path = Path(runtime.settings.snapshot_path)
    signature = snapshot_file_signature(path)
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=runtime.settings.snapshot_poll_seconds)
            return
        except asyncio.TimeoutError:
            pass
        current = snapshot_file_signature(path)
        if current is None:
            signature = None
            continue
        if current == signature:
            continue
        try:
            source = await run_in_threadpool(read_snapshot_file, path)
            await run_in_threadpool(runtime.core.update, source=source, actor="snapshot-file")
            signature = current
            logger.info("snapshot file checked: %s", path)
        except (json.JSONDecodeError, UnicodeDecodeError, InvalidInput) as exc:
            signature = current
            logger.warning("snapshot file rejected: %s", exc)
        except Exception as exc:
            logger.warning("snapshot file import rejected: %s", exc)


async def recalculate(runtime: Runtime, stop: asyncio.Event):
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=runtime.settings.recalculate_seconds)
            return
        except asyncio.TimeoutError:
            try:
                await run_in_threadpool(runtime.core.update, actor="clock")
            except Exception:
                logger.exception("scheduled calculation failed; previous result retained")


async def telegram_worker(runtime: Runtime, stop: asyncio.Event):
    while True:
        try:
            if runtime.settings.telegram_bot_enabled:
                await run_in_threadpool(runtime.telegram.process_notifications)
                await run_in_threadpool(runtime.telegram.process_support_deliveries)
            await run_in_threadpool(runtime.telegram.purge_support_history)
        except Exception:
            logger.exception("Telegram worker iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=runtime.settings.telegram_worker_interval_seconds)
            return
        except asyncio.TimeoutError:
            pass


async def telegram_polling_worker(runtime: Runtime, stop: asyncio.Event):
    """Telegram fallback for servers where inbound webhook delivery times out."""
    if not runtime.settings.telegram_bot_enabled or not runtime.settings.telegram_polling_enabled:
        return
    provider = runtime.telegram.telegram_provider
    if not hasattr(provider, "get_updates") or not hasattr(provider, "delete_webhook"):
        logger.error("Telegram polling unavailable: provider lacks required methods")
        return
    try:
        # Preserve Telegram pending updates; never drop the queue.
        await run_in_threadpool(provider.delete_webhook)
        logger.warning("Telegram webhook removed; long polling enabled")
    except Exception:
        logger.exception("Cannot switch Telegram from webhook to polling; worker stopped")
        return
    offset = None
    while not stop.is_set():
        try:
            updates = await run_in_threadpool(provider.get_updates, offset)
            for update in updates:
                if stop.is_set():
                    return
                update_id = update.get("update_id") if isinstance(update, dict) else None
                try:
                    if isinstance(update_id, int) and runtime.telegram.claim_update(update_id):
                        await run_in_threadpool(runtime.telegram.handle_update, update)
                except Exception:
                    logger.exception("Telegram polled update handling failed")
                finally:
                    if isinstance(update_id, int):
                        offset = max(offset or 0, update_id + 1)
        except Exception:
            logger.exception("Telegram polling failed; retrying shortly")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

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


def create_app(settings: Settings | None = None, analytics: AnalyticsModule | None = None,
               auth_settings: AuthSettings | None = None,
               email_provider: EmailProvider | None = None,
               telegram_provider: TelegramProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    auth_settings = auth_settings or AuthSettings.from_env()
    module = analytics if analytics is not None else load_module(os.getenv("AEZA_ANALYTICS_FACTORY", ""))

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = Database(settings.database_url)
        storage = Storage(database)
        calculation = CalculationAdapter(module)
        users = UserRepository(auth_settings.database)
        auth = AuthService(auth_settings, users)


        otp_provider = email_provider
        if otp_provider is None and settings.email_configured:
            otp_provider = SmtpBzEmailProvider(settings)
        telegram = TelegramService(database, storage, settings, otp_provider, telegram_provider)
        runtime = Runtime(settings, database, storage, auth, calculation,
            Core(storage, calculation, settings.reference_now), ai=None, telegram=telegram)
        stop = asyncio.Event()
        tasks = []
        def initialize():
            database.initialize()
            users.initialize()
            if isinstance(module, UnavailableAnalytics):
                return
            state = storage.load()
            if not state.generation:
                source = json.loads(Path(settings.snapshot_path).read_text(encoding="utf-8")) if settings.seed_demo_data else {
                    "accounts": [], "services": [], "transactions": []}
                runtime.core.update(source=source)
            else:
                changed_engine = storage.summary()["engineVersion"] != calculation.definition().version
                runtime.core.update(force=changed_engine)

        try:
            await run_in_threadpool(initialize)
            runtime.ai = build_ai(storage, calculation)
            application.state.runtime = runtime
            application.state.metrics = Metrics(storage)
            if settings.as_of.lower() == "now" and not isinstance(module, UnavailableAnalytics):
                tasks.append(asyncio.create_task(recalculate(runtime, stop)))
            if not isinstance(module, UnavailableAnalytics):
                tasks.append(asyncio.create_task(snapshot_file_worker(runtime, stop)))
            tasks.append(asyncio.create_task(telegram_worker(runtime, stop)))
            if settings.telegram_polling_enabled:
                tasks.append(asyncio.create_task(telegram_polling_worker(runtime, stop)))
            yield
        finally:
            stop.set()
            if tasks:
                await asyncio.gather(*tasks)
            database.engine.dispose()

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

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, error: AuthError):
        return JSONResponse({"detail": error.description}, status_code=error.status, headers=error.headers or {})

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

    @app.exception_handler(EmailDisabled)
    async def email_disabled(request: Request, error: EmailDisabled):
        return JSONResponse({"detail": str(error)}, status_code=503, headers={"Retry-After": "30"})

    @app.exception_handler(EmailRejected)
    async def email_rejected(request: Request, error: EmailRejected):
        return JSONResponse({"detail": str(error)}, status_code=502)

    @app.exception_handler(EmailUnavailable)
    async def email_unavailable(request: Request, error: EmailUnavailable):
        return JSONResponse({"detail": str(error)}, status_code=503, headers={"Retry-After": "10"})

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
        metrics_token = f"Bearer {settings.metrics_token}"
        if settings.metrics_token and hmac.compare_digest(header.encode(), metrics_token.encode()):
            pass
        elif header:
            runtime.auth.bearer(header)
        else:
            session = runtime.auth.session_from_cookie(request.cookies.get(routes_auth.METRICS_COOKIE))
            if session is None:
                raise AuthError(401, "invalid_token", "Требуется авторизация", {"WWW-Authenticate": "Bearer"})
            runtime.auth.user_for_session(session)
        return Response(request.app.state.metrics.render(), headers={"Content-Type": CONTENT_TYPE_LATEST})

    for router in (routes_auth.router, routes_customers.router, routes_analytics.router,
                   routes_model.router, routes_source.router, routes_insights.router,
                   routes_export.router, routes_ai.router, routes_actions.router,
                   routes_email.router, routes_telegram.router, routes_client.router):
        app.include_router(router, prefix=settings.api_prefix)
    return app
