"""Read-only retention-action tool.

The AI Analyst may *see* which retention steps a colleague already confirmed for
a customer — so it does not propose the same thing twice and can report what is
already in flight.  It can never create, change or close an action: that write
path exists only on the REST API and requires an authenticated human.
"""

from __future__ import annotations

from backend.app.storage import Storage


_ACTIVE = ("open", "in_progress")


def customer_actions(storage: Storage, customer_id: int, *, limit: int = 10) -> list[dict]:
    """Confirmed retention actions for one customer, newest first."""

    rows = storage.actions(customer_id=customer_id)
    out: list[dict] = []
    for row in rows[:limit]:
        out.append(
            {
                "id": row["id"],
                "code": row["code"],
                "title": row["title"],
                "status": row["status"],
                "active": row["status"] in _ACTIVE,
                "serviceId": row["serviceId"],
                "note": row["note"],
                "createdBy": row["createdBy"],
                "createdAt": row["createdAt"],
            }
        )
    return out
