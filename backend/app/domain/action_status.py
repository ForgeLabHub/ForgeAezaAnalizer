"""Persistence for the retention workflow (Action Center).

Status changes are deliberately isolated from the analytics tables.  A status
transition must never alter a risk score, an exposure figure or the model
settings, so this module only ever reads and writes ``analyzer_action_status``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import ActionStatusRow

#: Allowed workflow states.  ``done`` can return to ``in_progress`` so an
#: operator can reopen a case that was closed too early.
STATUSES = ("new", "in_progress", "done")

DEFAULT_STATUS = "new"

STATUS_LABELS = {
    "new": "Новое",
    "in_progress": "В работе",
    "done": "Выполнено",
}

#: Explicitly supported transitions, including the reopen path.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("in_progress", "done"),
    "in_progress": ("done", "new"),
    "done": ("in_progress", "new"),
}

MAX_NOTE_LENGTH = 1000
MAX_ASSIGNEE_LENGTH = 320


class ActionStatusError(ValueError):
    """Raised when a workflow update is not allowed."""


def validate_status(status: str) -> str:
    if status not in STATUSES:
        raise ActionStatusError(
            f"Недопустимый статус «{status}». Допустимо: {', '.join(STATUSES)}"
        )
    return status


def validate_transition(current: str, target: str) -> str:
    validate_status(current)
    validate_status(target)
    if target == current:
        return target
    if target not in TRANSITIONS[current]:
        raise ActionStatusError(
            f"Переход «{STATUS_LABELS[current]}» → «{STATUS_LABELS[target]}» не поддерживается"
        )
    return target


def load_for_generation(session: Session, generation: int) -> dict[tuple[int, str], ActionStatusRow]:
    """Every stored workflow row for one generation, keyed by (customer, code)."""

    rows = session.execute(
        select(ActionStatusRow).where(ActionStatusRow.generation == generation)
    ).scalars()
    return {(row.customer_id, row.code): row for row in rows}


def upsert(
    session: Session,
    *,
    generation: int,
    customer_id: int,
    code: str,
    status: str | None = None,
    assignee: str | None = None,
    note: str | None = None,
    actor: str | None = None,
) -> ActionStatusRow:
    """Create or update one workflow row.

    The caller is responsible for verifying that ``(customer_id, code)`` exists
    in the published generation, so a status can never be attached to a
    recommendation that the model did not actually produce.
    """

    row = session.get(ActionStatusRow, (generation, customer_id, code))
    current = row.status if row is not None else DEFAULT_STATUS
    target = validate_transition(current, status) if status is not None else current

    if row is None:
        row = ActionStatusRow(
            generation=generation,
            customer_id=customer_id,
            code=code,
            status=target,
            updated_at=dt.datetime.now(dt.timezone.utc),
        )
        session.add(row)
    else:
        row.status = target

    if assignee is not None:
        row.assignee = assignee.strip()[:MAX_ASSIGNEE_LENGTH] or None
    if note is not None:
        row.note = note.strip()[:MAX_NOTE_LENGTH] or None

    row.updated_at = dt.datetime.now(dt.timezone.utc)
    if actor:
        row.updated_by = actor
    session.flush()
    return row


def payload(row: ActionStatusRow | None) -> dict:
    """Serialise a workflow row, defaulting to the untouched state."""

    if row is None:
        return {
            "status": DEFAULT_STATUS,
            "statusLabel": STATUS_LABELS[DEFAULT_STATUS],
            "assignee": None,
            "note": None,
            "updatedAt": None,
            "updatedBy": None,
        }
    return {
        "status": row.status,
        "statusLabel": STATUS_LABELS.get(row.status, row.status),
        "assignee": row.assignee,
        "note": row.note,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "updatedBy": row.updated_by,
    }
