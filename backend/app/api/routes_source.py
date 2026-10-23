"""Snapshot import and current-source inspection routes."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user, get_db
from app.api.schemas import ImportReport, SnapshotAccepted, SourceSnapshotResponse
from app.db import ImportRunRow, session_scope
from app.domain.importer import (
    SnapshotValidationError,
    current_counts,
    import_snapshot,
    parse_snapshot,
)
from app.metrics import IMPORTS_TOTAL

router = APIRouter(prefix="/source", tags=["source"])


@router.get("/snapshot", summary="Текущее состояние загруженного набора")
def get_snapshot(
    session: Session = Depends(get_db), principal: Principal = Depends(get_current_user)
) -> dict:
    counts = current_counts(session)
    last_run = session.scalar(
        select(ImportRunRow).order_by(desc(ImportRunRow.started_at)).limit(1)
    )
    return {
        "counts": counts,
        "lastImport": None
        if last_run is None
        else {
            "startedAt": last_run.started_at.isoformat(),
            "finishedAt": last_run.finished_at.isoformat() if last_run.finished_at else None,
            "status": last_run.status,
            "accounts": last_run.accounts,
            "services": last_run.services,
            "transactions": last_run.transactions,
            "message": last_run.message,
        },
    }


@router.put(
    "/snapshot",
    response_model=SourceSnapshotResponse,
    summary="Атомарно заменить набор данных",
    responses={
        200: {"description": "Snapshot применён"},
        422: {"description": "Snapshot не прошёл валидацию; база не изменена"},
    },
)
def put_snapshot(
    payload: dict[str, Any] = Body(
        ...,
        description="Объект с массивами accounts, services и transactions в формате исходного data.json",
    ),
    session: Session = Depends(get_db),
    principal: Principal = Depends(get_current_user),
) -> SourceSnapshotResponse:
    """Validate the entire snapshot, then replace the dataset in one transaction.

    Validation completes before any write, and the write runs inside a single
    transaction, so a rejected payload leaves the previous dataset untouched.
    """

    try:
        snapshot = parse_snapshot(payload)
    except SnapshotValidationError as exc:
        IMPORTS_TOTAL.labels(status="rejected").inc()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Snapshot отклонён: {exc}",
        ) from exc

    try:
        result = import_snapshot(session, snapshot)
        session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        session.rollback()
        IMPORTS_TOTAL.labels(status="failed").inc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Импорт не выполнен, данные не изменены: {exc}",
        ) from exc

    IMPORTS_TOTAL.labels(status="succeeded").inc()
    return SourceSnapshotResponse(
        snapshot=SnapshotAccepted(
            status="applied",
            accounts=result.accounts,
            services=result.services,
            transactions=result.transactions,
        ),
        report=ImportReport(
            status="succeeded",
            accepted={
                "accounts": result.accounts,
                "services": result.services,
                "transactions": result.transactions,
            },
            rejected=result.rejected,
            duplicates=result.duplicate_ids,
            previous=result.previous_counts,
            message=result.message,
        ),
    )
