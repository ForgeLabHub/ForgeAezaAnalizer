"""Retention actions and the AI read-only boundary.

These tests cover the mandatory guarantee: the AI Analyst explains and proposes,
but only a human writes.  The action API is the single write surface, and the AI
module reaches actions through a read-only tool.

They also cover the failure modes the brief calls out explicitly: empty data,
provider errors, and access control.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.ai import context_builder, tools
from backend.app.ai.providers.mock import MockProvider
from backend.app.ai.rag import build_index
from backend.app.config import Settings
from backend.app.domain import actions as actions_domain
from backend.app.main import create_app
from backend.tests.conftest import TEST_LOGIN, TEST_PASSWORD, make_test_auth_settings

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-10-19T15:00:00+00:00"


@pytest.fixture
def actions_settings(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "methodology.md").write_text("# Методология\n\nБалл риска — индекс, а не вероятность.\n", encoding="utf-8")
    index = tmp_path / "index.json"
    build_index(docs_path=docs, output_path=index)

    os.environ["AEZA_ANALYTICS_FACTORY"] = "backend.app.domain.module:create"
    os.environ.update({
        "AEZA_AI_ENABLED": "1",
        "AEZA_AI_PROVIDER": "mock",
        "AEZA_AI_RAG_TOP_K": "1",
        "AEZA_AI_RAG_INDEX_PATH": str(index),
        "AEZA_AI_MAX_RETRIES": "0",
    })
    yield
    for key in ("AEZA_AI_ENABLED", "AEZA_AI_PROVIDER", "AEZA_AI_RAG_TOP_K",
                "AEZA_AI_RAG_INDEX_PATH", "AEZA_AI_MAX_RETRIES", "AEZA_ANALYTICS_FACTORY"):
        os.environ.pop(key, None)


def _client(tmp_path, *, seed: bool = True) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'act.db').as_posix()}",
        seed_demo_data=seed,
        snapshot_path=str(ROOT / "dataset/data.json"), as_of=AS_OF,
    )
    auth_settings = make_test_auth_settings(tmp_path / "act_auth.db")
    app = create_app(settings, auth_settings=auth_settings)
    return TestClient(app, raise_server_exceptions=False)


def _headers(client: TestClient) -> dict:
    token = client.post("/api/v1/auth/login",
                        json={"email": TEST_LOGIN, "password": TEST_PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def act_client(actions_settings, tmp_path):
    with _client(tmp_path) as client:
        yield client


@pytest.fixture
def act_headers(act_client):
    return _headers(act_client)


def _first_code(client, headers, customer_id=5) -> str:
    customer = client.get(f"/api/v1/customers/{customer_id}", headers=headers).json()
    return customer["recommendations"][0]["code"]


# ------------------------------------------------------------------ happy path
def test_confirm_action_round_trip(act_client, act_headers):
    """The full demo loop: risk -> AI explains -> human confirms -> stored."""

    code = _first_code(act_client, act_headers)
    created = act_client.post("/api/v1/actions", headers=act_headers,
                              json={"customerId": 5, "code": code, "serviceId": 5, "note": "Позвонить"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "open"
    assert body["createdBy"] == "analyst@aeza.test"
    assert body["title"], "title must be copied from the engine's recommendation"

    listed = act_client.get("/api/v1/actions?customerId=5", headers=act_headers).json()
    assert [item["id"] for item in listed["items"]] == [body["id"]]

    closed = act_client.patch(f"/api/v1/actions/{body['id']}", headers=act_headers,
                              json={"status": "done", "note": "Дозвонились"}).json()
    assert closed["status"] == "done"
    assert closed["note"] == "Дозвонились"


def test_action_title_comes_from_engine_not_caller(act_client, act_headers):
    """A caller cannot smuggle arbitrary text into a stored action.

    ``title`` is not an accepted field at all, so supplying it is rejected
    outright rather than silently ignored.
    """

    code = _first_code(act_client, act_headers)
    rejected = act_client.post("/api/v1/actions", headers=act_headers,
                               json={"customerId": 5, "code": code, "title": "ВЫДУМАННЫЙ ТЕКСТ"})
    assert rejected.status_code == 422

    engine_title = next(
        rec["title"]
        for rec in act_client.get("/api/v1/customers/5", headers=act_headers).json()["recommendations"]
        if rec["code"] == code
    )
    created = act_client.post("/api/v1/actions", headers=act_headers,
                              json={"customerId": 5, "code": code}).json()
    assert created["title"] == engine_title


def test_action_survives_recalculation(act_client, act_headers):
    """An action is a human decision; a model change must not drop it."""

    code = _first_code(act_client, act_headers)
    action_id = act_client.post("/api/v1/actions", headers=act_headers,
                                json={"customerId": 5, "code": code}).json()["id"]

    # A model change republishes the analytics generation; the action is keyed by
    # customer, so it must remain visible afterwards.
    changed = act_client.patch("/api/v1/model/settings", headers=act_headers,
                               json={"weights": {"expiry_proximity": 2.0}})
    assert changed.status_code == 200, changed.text

    remaining = act_client.get("/api/v1/actions?customerId=5", headers=act_headers).json()["items"]
    assert action_id in [item["id"] for item in remaining]


# ------------------------------------------------------------------ validation
def test_unknown_recommendation_code_is_rejected(act_client, act_headers):
    response = act_client.post("/api/v1/actions", headers=act_headers,
                               json={"customerId": 5, "code": "totally_made_up"})
    assert response.status_code == 422


def test_service_must_belong_to_customer(act_client, act_headers):
    code = _first_code(act_client, act_headers)
    response = act_client.post("/api/v1/actions", headers=act_headers,
                               json={"customerId": 5, "code": code, "serviceId": 9999})
    assert response.status_code == 422


def test_unknown_customer_is_404(act_client, act_headers):
    response = act_client.post("/api/v1/actions", headers=act_headers,
                               json={"customerId": 9999, "code": "overdue_renewal"})
    assert response.status_code == 404


def test_unknown_status_is_rejected(act_client, act_headers):
    code = _first_code(act_client, act_headers)
    action_id = act_client.post("/api/v1/actions", headers=act_headers,
                                json={"customerId": 5, "code": code}).json()["id"]
    assert act_client.patch(f"/api/v1/actions/{action_id}", headers=act_headers,
                            json={"status": "sold"}).status_code == 422


def test_update_requires_a_field(act_client, act_headers):
    code = _first_code(act_client, act_headers)
    action_id = act_client.post("/api/v1/actions", headers=act_headers,
                                json={"customerId": 5, "code": code}).json()["id"]
    assert act_client.patch(f"/api/v1/actions/{action_id}", headers=act_headers, json={}).status_code == 422


def test_missing_action_is_404(act_client, act_headers):
    assert act_client.patch("/api/v1/actions/424242", headers=act_headers,
                            json={"status": "done"}).status_code == 404


# ---------------------------------------------------------------- access control
def test_action_routes_require_authentication(act_client):
    assert act_client.get("/api/v1/actions").status_code == 401
    assert act_client.post("/api/v1/actions", json={"customerId": 5, "code": "x"}).status_code == 401
    assert act_client.patch("/api/v1/actions/1", json={"status": "done"}).status_code == 401


def test_actions_are_scoped_to_requested_customer(act_client, act_headers):
    code5 = _first_code(act_client, act_headers, 5)
    code6 = _first_code(act_client, act_headers, 6)
    act_client.post("/api/v1/actions", headers=act_headers, json={"customerId": 5, "code": code5})
    act_client.post("/api/v1/actions", headers=act_headers, json={"customerId": 6, "code": code6})

    only5 = act_client.get("/api/v1/actions?customerId=5", headers=act_headers).json()["items"]
    assert {item["customerId"] for item in only5} == {5}


# ------------------------------------------------------------- AI read-only
def test_ai_tool_can_read_actions(act_client, act_headers):
    code = _first_code(act_client, act_headers)
    act_client.post("/api/v1/actions", headers=act_headers,
                    json={"customerId": 5, "code": code, "note": "Проверить"})
    runtime = act_client.app.state.runtime
    rows = tools.customer_actions(runtime.storage, 5)
    assert rows and rows[0]["code"] == code
    assert rows[0]["active"] is True


def test_ai_tool_module_exposes_no_write_functions():
    """The AI tool surface must stay read-only by construction.

    Checked on word boundaries so a legitimate name like ``model_settings``
    (a *read* of the configuration) is not mistaken for a writer.
    """

    import re

    import backend.app.ai.tools as ai_tools

    forbidden = re.compile(r"\b(create|update|delete|write|save|insert|remove|drop|patch|post)\b")
    for name in ai_tools.__all__:
        assert not forbidden.search(name.replace("_", " ")), name
        assert callable(getattr(ai_tools, name))


def test_confirmed_action_appears_in_ai_context(act_client, act_headers):
    """The model must be told what is already in flight, from real data."""

    code = _first_code(act_client, act_headers)
    act_client.post("/api/v1/actions", headers=act_headers,
                    json={"customerId": 5, "code": code, "note": "Уже звоним"})
    runtime = act_client.app.state.runtime
    context = context_builder.build_customer_context(
        runtime.storage, 5, retriever=runtime.ai.retriever, question="что уже сделано", top_k=0)
    assert "Уже подтверждённое действие" in context.facts_text
    assert any("actions" in citation["source"] for citation in context.citations)


def test_ai_context_notes_absence_of_actions(act_client):
    """With no confirmed actions the model is told so, not left to guess."""

    runtime = act_client.app.state.runtime
    context = context_builder.build_customer_context(
        runtime.storage, 5, retriever=runtime.ai.retriever, question="что сделано", top_k=0)
    assert "Подтверждённых действий по удержанию нет" in context.facts_text


def test_ai_chat_does_not_create_actions(act_client, act_headers):
    """Asking the AI about a customer must not write anything."""

    before = act_client.get("/api/v1/actions", headers=act_headers).json()["items"]
    response = act_client.post("/api/v1/ai/chat", headers=act_headers,
                               json={"question": "Предложи действия для клиента 5", "customerId": 5})
    assert response.status_code == 200
    after = act_client.get("/api/v1/actions", headers=act_headers).json()["items"]
    assert len(after) == len(before)


# ----------------------------------------------------------------- empty data
def test_actions_api_is_empty_but_valid_without_data(actions_settings, tmp_path):
    """No dataset: the endpoint returns an empty list, not an error."""

    with _client(tmp_path, seed=False) as client:
        headers = _headers(client)
        payload = client.get("/api/v1/actions", headers=headers).json()
        assert payload["items"] == []
        # Creating an action for a non-existent customer must fail cleanly.
        assert client.post("/api/v1/actions", headers=headers,
                           json={"customerId": 1, "code": "overdue_renewal"}).status_code == 404


def test_ai_explains_customer_with_no_confirmed_actions(act_client, act_headers):
    response = act_client.post("/api/v1/ai/customers/5/explain", headers=act_headers, json={})
    assert response.status_code == 200
    assert response.json()["answer"]["summary"]


# --------------------------------------------------------------- provider error
class _BrokenProvider(MockProvider):
    def generate(self, **kwargs):
        from backend.app.ai.providers.base import ProviderError

        raise ProviderError("модель упала")


def test_provider_failure_returns_503_not_fake_answer(act_client, act_headers):
    """A dead model must never be papered over with an invented answer."""

    act_client.app.state.runtime.ai._provider = _BrokenProvider()
    response = act_client.post("/api/v1/ai/chat", headers=act_headers, json={"question": "Сводка"})
    assert response.status_code == 503
    assert "модель" in response.json()["detail"].lower()


def test_analytics_still_work_when_model_is_down(act_client, act_headers):
    """AI availability must not be a precondition for the core product."""

    act_client.app.state.runtime.ai._provider = _BrokenProvider()
    assert act_client.post("/api/v1/ai/chat", headers=act_headers, json={"question": "x"}).status_code == 503
    assert act_client.get("/api/v1/analytics/summary", headers=act_headers).status_code == 200
    assert act_client.get("/api/v1/customers", headers=act_headers).status_code == 200


def test_action_error_type_maps_to_422():
    from core import InvalidInput

    assert issubclass(actions_domain.ActionError, InvalidInput)
