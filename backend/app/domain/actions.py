"""Human-confirmed retention actions.

This is the *only* place where a user's decision is written.  It exists so the
end-to-end demo can show the full loop — risk detected, AI explained it, the
analyst confirmed an action, the action is stored — without letting the model
or the AI surface mutate anything on its own.

Design rules:

* **A human is required.**  The AI Analyst can *read* actions but never create,
  change or close one.  Only an authenticated user hitting the REST API does.
* **Only known recommendations.**  ``code`` must be one the Risk Engine itself
  produced for that customer, so a stored action always traces to a real signal.
* **No money math here.**  An action records a decision and an optional note; it
  never recomputes risk, revenue or exposure.
* **Survives recalculation.**  Actions are keyed by customer, not by analysis
  generation, so an import does not silently drop a colleague's work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from core import InvalidInput

ACTION_STATUSES = ("open", "in_progress", "done", "dismissed")

#: Statuses a caller may set through the API.
OPEN_STATUSES = ("open", "in_progress")
CLOSED_STATUSES = ("done", "dismissed")


class ActionError(InvalidInput):
    """Raised when an action request is invalid; the API maps it to 422."""


@dataclass(frozen=True)
class ActionInput:
    customer_id: int
    service_id: int | None
    code: str
    note: str | None


def _recommendation_index(customer: dict) -> dict[str, dict]:
    """Map recommendation ``code`` -> recommendation for one customer payload."""

    index: dict[str, dict] = {}
    for recommendation in customer.get("recommendations") or []:
        code = recommendation.get("code")
        if code and code not in index:
            index[code] = recommendation
    return index


def validate_new_action(customer: dict, payload: ActionInput) -> dict:
    """Check an action against the customer's own Risk Engine output.

    The ``title`` and ``detail`` are copied from the engine's recommendation,
    not taken from the caller, so a stored action can never carry text the
    engine did not produce.
    """

    if payload.code not in _recommendation_index(customer):
        known = ", ".join(sorted(_recommendation_index(customer))) or "нет"
        raise ActionError(f"Код «{payload.code}» не является рекомендацией этого клиента. Доступно: {known}.")

    recommendation = _recommendation_index(customer)[payload.code]

    if payload.service_id is not None:
        service_ids = {service.get("id") for service in customer.get("services") or []}
        if payload.service_id not in service_ids:
            raise ActionError(f"Услуга {payload.service_id} не принадлежит клиенту {payload.customer_id}.")

    note = (payload.note or "").strip() or None
    if note is not None and len(note) > 2000:
        raise ActionError("Комментарий длиннее 2000 символов")

    return {
        "customer_id": payload.customer_id,
        "service_id": payload.service_id,
        "code": payload.code,
        "title": recommendation["title"],
        "detail": recommendation["detail"],
        "note": note,
    }


def validate_status(value: str) -> str:
    if value not in ACTION_STATUSES:
        raise ActionError(f"Неизвестный статус «{value}». Доступно: {', '.join(ACTION_STATUSES)}.")
    return value


def now() -> datetime:
    return datetime.now(timezone.utc)
