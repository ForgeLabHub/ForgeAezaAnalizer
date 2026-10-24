"""Action Center workflow persistence.

The status of a retention recommendation must survive a reload, must follow the
documented transitions, and must never leak into the analytics figures.
"""

from __future__ import annotations

import copy

from core import Analysis
from backend.app.domain.action_status import (
    ActionStatusError,
    STATUSES,
    validate_transition,
)

RECOMMENDATION = {
    "code": "review_autoprolong",
    "title": "Обсудить включение автопродления",
    "detail": "Автопродление отключено.",
    "priority": 3,
}


def _queue(client, headers, **params):
    response = client.get("/api/v1/priority", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _publish_with_actions(client, headers, snapshot, analytics):
    """Publish a generation whose customers carry one retention action.

    The conftest fixture produces customers without recommendations, so the
    action is injected through the module's transform hook and a changed
    snapshot forces a real recalculation.
    """

    def transform(result):
        return Analysis(
            result.summary,
            [{**customer, "recommendations": [dict(RECOMMENDATION)]} for customer in result.customers],
        )

    analytics.transform = transform
    source = copy.deepcopy(snapshot)
    source["accounts"][0]["balance"] += 1
    response = client.put("/api/v1/source/snapshot", json=source, headers=headers)
    assert response.status_code == 200, response.text


def _first_action(queue):
    """First (customer, action) pair the queue actually produced."""
    for item in queue["items"]:
        for action in item["actions"]:
            return item["id"], action
    raise AssertionError("queue produced no retention actions")


# ----------------------------------------------------------------- transitions


def test_documented_transitions_including_reopen():
    assert validate_transition("new", "in_progress") == "in_progress"
    assert validate_transition("in_progress", "done") == "done"
    # Reopening a case closed too early is explicitly supported.
    assert validate_transition("done", "in_progress") == "in_progress"
    assert validate_transition("done", "new") == "new"
    # Idempotent re-application of the same state is allowed.
    assert validate_transition("done", "done") == "done"


def test_unknown_status_is_rejected():
    try:
        validate_transition("new", "archived")
    except ActionStatusError as exc:
        assert "Недопустимый статус" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("unknown status accepted")


def test_statuses_are_exactly_the_documented_set():
    assert STATUSES == ("new", "in_progress", "done")


# -------------------------------------------------------------------- endpoints


def test_action_status_defaults_to_new_and_persists(client, auth_headers, snapshot_payload, analytics):
    _publish_with_actions(client, auth_headers, snapshot_payload, analytics)
    queue = _queue(client, auth_headers)
    customer_id, action = _first_action(queue)
    assert action["status"] == "new"
    assert action["updatedAt"] is None

    response = client.patch(
        "/api/v1/priority/actions",
        headers=auth_headers,
        json={"customerId": customer_id, "code": action["code"], "status": "in_progress"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "in_progress"

    # A fresh read (as after a page reload) must show the stored state.
    reloaded = _queue(client, auth_headers)
    stored = next(
        a
        for item in reloaded["items"]
        if item["id"] == customer_id
        for a in item["actions"]
        if a["code"] == action["code"]
    )
    assert stored["status"] == "in_progress"
    assert stored["updatedAt"] is not None


def test_assignee_and_note_are_persisted_and_trimmed(client, auth_headers, snapshot_payload, analytics):
    _publish_with_actions(client, auth_headers, snapshot_payload, analytics)
    queue = _queue(client, auth_headers)
    customer_id, action = _first_action(queue)
    response = client.patch(
        "/api/v1/priority/actions",
        headers=auth_headers,
        json={
            "customerId": customer_id,
            "code": action["code"],
            "assignee": "  retention-team  ",
            "note": "  Позвонить клиенту  ",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assignee"] == "retention-team"
    assert body["note"] == "Позвонить клиенту"
    assert body["status"] == "new"


def test_action_status_does_not_change_analytics(client, auth_headers, snapshot_payload, analytics):
    """Workflow state must be invisible to the score, exposure and settings."""
    _publish_with_actions(client, auth_headers, snapshot_payload, analytics)
    summary_before = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    settings_before = client.get("/api/v1/model/settings", headers=auth_headers).json()["settings"]

    queue = _queue(client, auth_headers)
    customer_id, action = _first_action(queue)
    client.patch(
        "/api/v1/priority/actions",
        headers=auth_headers,
        json={"customerId": customer_id, "code": action["code"], "status": "done"},
    )

    assert client.get("/api/v1/analytics/summary", headers=auth_headers).json() == summary_before
    assert client.get("/api/v1/model/settings", headers=auth_headers).json()["settings"] == settings_before


def test_unknown_recommendation_code_is_rejected(client, auth_headers, snapshot_payload, analytics):
    _publish_with_actions(client, auth_headers, snapshot_payload, analytics)
    queue = _queue(client, auth_headers)
    customer_id, _ = _first_action(queue)
    response = client.patch(
        "/api/v1/priority/actions",
        headers=auth_headers,
        json={"customerId": customer_id, "code": "not_a_real_code", "status": "done"},
    )
    assert response.status_code == 404


def test_unknown_customer_is_rejected(client, auth_headers, snapshot_payload, analytics):
    _publish_with_actions(client, auth_headers, snapshot_payload, analytics)
    response = client.patch(
        "/api/v1/priority/actions",
        headers=auth_headers,
        json={"customerId": 999_999, "code": "review_autoprolong", "status": "done"},
    )
    assert response.status_code == 404


def test_stale_generation_is_rejected(client, auth_headers, snapshot_payload, analytics):
    _publish_with_actions(client, auth_headers, snapshot_payload, analytics)
    queue = _queue(client, auth_headers)
    customer_id, action = _first_action(queue)
    response = client.patch(
        "/api/v1/priority/actions",
        headers=auth_headers,
        json={
            "customerId": customer_id,
            "code": action["code"],
            "status": "in_progress",
            "expectedGeneration": 999,
        },
    )
    assert response.status_code == 409


def test_action_status_requires_authentication(client):
    assert client.get("/api/v1/priority").status_code == 401
    assert (
        client.patch(
            "/api/v1/priority/actions",
            json={"customerId": 1, "code": "review_autoprolong", "status": "done"},
        ).status_code
        == 401
    )


def test_extra_payload_fields_are_rejected(client, auth_headers, snapshot_payload, analytics):
    _publish_with_actions(client, auth_headers, snapshot_payload, analytics)
    queue = _queue(client, auth_headers)
    customer_id, action = _first_action(queue)
    response = client.patch(
        "/api/v1/priority/actions",
        headers=auth_headers,
        json={
            "customerId": customer_id,
            "code": action["code"],
            "status": "done",
            "riskScore": 0,
        },
    )
    assert response.status_code == 422
