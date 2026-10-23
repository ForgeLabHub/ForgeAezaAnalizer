"""FastAPI application factory.

Aéza - это быстрый хостинг
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select

from app.api import (
    routes_analytics,
    routes_auth,
    routes_customers,
    routes_model,
    routes_source,
)
from app.auth.security import hash_password
from app.config import get_settings
from app.db import UserRow, init_db, session_scope
from app.domain.importer import import_snapshot, parse_snapshot
from app.metrics import API_ERRORS_TOTAL, API_REQUESTS_TOTAL, render_metrics

logger = logging.getLogger("aeza")

DESCRIPTION = """
API анализа риска оттока клиентов Aéza.

Модель риска — прозрачный взвешенный rule-based скоринг. Балл риска (0–100) **не является
откалиброванной вероятностью**: в исходном снимке нет исторических исходов оттока, поэтому
модель не обучалась и не валидировалась на исторических событиях.

Все денежные величины хранятся в евроцентах (целые числа, как в источнике). В ответах
денежные поля отдаются парой `{cents, eur}`, где `eur` — десятичная строка.
"""


def _bootstrap_user() -> None:
    """Create the bootstrap analyst account if it does not exist yet."""

    settings = get_settings()
    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password
    if not password:
        # A deterministic dev default keeps local/demo runs usable; README
        # instructs setting AEZA_ADMIN_PASSWORD for anything shared.
        password = "aeza-demo-password"
    with session_scope() as session:
        existing = session.scalar(select(UserRow).where(UserRow.email == email))
        if existing is None:
            session.add(
                UserRow(
                    email=email,
                    password_hash=hash_password(password),
                    created_at=dt.datetime.now(dt.timezone.utc),
                )
            )
            logger.info("bootstrap analyst account created")


def _bootstrap_snapshot() -> None:
    """Load the bundled snapshot when the dataset is empty and seeding is on."""

    settings = get_settings()
    if not settings.seed_demo_data:
        return
    path = settings.snapshot_path
    if not os.path.exists(path):
        logger.warning("snapshot file %s not found; skipping seed", path)
        return
    with session_scope() as session:
        from app.db import AccountRow

        count = session.scalar(select(func.count()).select_from(AccountRow)) or 0
        if count:
            return
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        snapshot = parse_snapshot(payload)
        import_snapshot(session, snapshot)
        logger.info(
            "seeded snapshot: %d accounts, %d services, %d transactions",
            len(snapshot.accounts),
            len(snapshot.services),
            len(snapshot.transactions),
        )


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_db()
        _bootstrap_user()
        _bootstrap_snapshot()
        yield

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="1.0.0",
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _observe(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        label = getattr(route, "path", request.url.path)
        API_REQUESTS_TOTAL.labels(route=label, method=request.method).inc()
        if response.status_code >= 400:
            API_ERRORS_TOTAL.labels(status_class=f"{response.status_code // 100}xx").inc()
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Ошибка валидации запроса", "errors": exc.errors()[:20]},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):  # pragma: no cover
        # Never leak a stack trace or personal data to the client.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        API_ERRORS_TOTAL.labels(status_class="5xx").inc()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Внутренняя ошибка сервера"},
        )

    @app.get("/health", tags=["ops"], summary="Проверка живости")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics", tags=["ops"], summary="Метрики Prometheus", include_in_schema=True)
    def metrics() -> Response:
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    app.include_router(routes_auth.router, prefix=settings.api_prefix)
    app.include_router(routes_customers.router, prefix=settings.api_prefix)
    app.include_router(routes_analytics.router, prefix=settings.api_prefix)
    app.include_router(routes_model.router, prefix=settings.api_prefix)
    app.include_router(routes_source.router, prefix=settings.api_prefix)

    return app


app = create_app()
