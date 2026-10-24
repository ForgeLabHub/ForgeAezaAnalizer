"""Tests for the local-LLM (Ollama) integration.

The provider is never really called. A stub HTTP transport stands in for Ollama,
so every branch is exercised deterministically: a good answer, a timeout, a
refusal, malformed JSON, an empty body, an invented number and an invented
e-mail. The grounding verifier is also unit-tested directly, because it is the
control that stops a fabricated figure from reaching the analyst.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.domain import llm
from backend.app.main import create_app
from backend.app.modules import load_module

from backend.tests.conftest import ROOT

CUSTOMER_ID = 10


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite://",
        auth_database_url="sqlite://",
        jwt_secret="test-secret-key",
        bootstrap_admin_password="demo123",
        seed_demo_data=True,
        snapshot_path=str(ROOT / "dataset/data.json"),
        llm_enabled=True,
        llm_model="qwen2.5:7b",
    )
    base.update(overrides)
    return Settings(**base)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _good_answer(context: dict) -> str:
    """An answer that only restates facts present in the context."""

    customer = context["customer"]
    score = customer["riskScore"]
    return (
        f"Клиент {customer['id']} ({customer['email']}) имеет балл {score} — "
        f"категория «{customer['riskCategory']}». Это взвешенная эвристика, не вероятность.\n"
        "— Проверьте продление просроченной услуги.\n"
        "— Уточните причину ожидания продления."
    )


def _context_for_customer(client: TestClient, headers: dict) -> dict:
    detail = client.get(f"/api/v1/customers/{CUSTOMER_ID}", headers=headers).json()
    return llm.build_customer_context(detail, as_of="2026-10-19T15:00:00+00:00", horizon_days=30)


# --------------------------------------------------------------------------- #
# Grounding verifier (unit)
# --------------------------------------------------------------------------- #

def test_verifier_accepts_numbers_from_the_context():
    context = {"customer": {"riskScore": 71.4, "email": "user-0010@example.test"}}
    answer = "Балл 71.4, адрес user-0010@example.test, риск высокий."
    assert llm.verify_grounding(answer, context) == []


def test_verifier_accepts_a_rounded_number():
    context = {"customer": {"riskScore": 71.4}}
    assert llm.verify_grounding("Балл около 71.", context) == []


def test_verifier_rejects_an_invented_number():
    context = {"customer": {"riskScore": 71.4}}
    violations = llm.verify_grounding("Вероятность оттока 93 %.", context)
    assert any("93" in v for v in violations)


def test_verifier_rejects_an_invented_email():
    context = {"customer": {"email": "user-0010@example.test"}}
    violations = llm.verify_grounding("Напишите на someone@else.test", context)
    assert any("someone@else.test" in v for v in violations)


def test_verifier_allows_small_ordinals():
    context = {"customer": {"riskScore": 71.4}}
    assert llm.verify_grounding("Шаги 1 и 2 — проверить и позвонить.", context) == []


# --------------------------------------------------------------------------- #
# Context builder
# --------------------------------------------------------------------------- #

def test_context_excludes_unrelated_customer_data():
    detail = {
        "id": 10, "email": "u@example.test", "riskScore": 71.4, "riskCategory": "high",
        "balance": {"cents": 20379, "eur": "203.79"},
        "withdrawBalance": {"cents": 9999, "eur": "99.99"},
        "services": [{"name": "svc", "factors": [
            {"label": "L", "value": 1.0, "weight": 3.0, "contribution": 3.0,
             "available": True, "reason": "r"}]}],
        "recommendations": [], "topReasons": [], "missingData": [],
    }
    context = llm.build_customer_context(detail, as_of=None, horizon_days=30)
    blob = json.dumps(context, ensure_ascii=False)
    assert "203.79" in blob          # balance kept as an explanatory euro string
    assert "99.99" not in blob       # withdrawBalance is not part of the fact set
    assert "cents" not in blob       # raw cent values are not sent


# --------------------------------------------------------------------------- #
# Client behaviour against the stub provider
# --------------------------------------------------------------------------- #

def test_client_returns_text_on_a_good_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "готово"}})

    client = llm.OllamaClient(_settings(), transport=_transport(handler))
    assert client.chat([{"role": "user", "content": "hi"}]) == "готово"


def test_client_raises_unavailable_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = llm.OllamaClient(_settings(), transport=_transport(handler))
    with pytest.raises(llm.LlmUnavailable):
        client.chat([{"role": "user", "content": "hi"}])


def test_client_raises_unavailable_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = llm.OllamaClient(_settings(), transport=_transport(handler))
    with pytest.raises(llm.LlmUnavailable):
        client.chat([{"role": "user", "content": "hi"}])


def test_client_raises_bad_response_on_malformed_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    client = llm.OllamaClient(_settings(), transport=_transport(handler))
    with pytest.raises(llm.LlmBadResponse):
        client.chat([{"role": "user", "content": "hi"}])


def test_client_raises_bad_response_on_empty_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "   "}})

    client = llm.OllamaClient(_settings(), transport=_transport(handler))
    with pytest.raises(llm.LlmBadResponse):
        client.chat([{"role": "user", "content": "hi"}])


def test_explain_rejects_an_ungrounded_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "Вероятность оттока 99 %."}})

    payload = {"id": 10, "email": "u@example.test", "riskScore": 71.4,
               "riskCategory": "high", "services": [], "recommendations": [],
               "topReasons": [], "missingData": []}
    with pytest.raises(llm.LlmUngrounded):
        llm.explain_customer(payload, settings=_settings(), as_of=None, horizon_days=30,
                             client=llm.OllamaClient(_settings(), transport=_transport(handler)))


def test_explain_refuses_when_disabled():
    payload = {"id": 10, "email": "u@example.test", "riskScore": 71.4, "services": []}
    with pytest.raises(llm.LlmUnavailable):
        llm.explain_customer(payload, settings=_settings(llm_enabled=False),
                             as_of=None, horizon_days=30)


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #

@pytest.fixture
def ai_client(tmp_path, monkeypatch):
    """Return a factory that builds an app whose Ollama calls hit a stub."""

    @contextmanager
    def make(handler):
        settings = _settings(
            database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
            auth_database_url=f"sqlite:///{(tmp_path / 'auth.db').as_posix()}",
        )
        original_init = llm.OllamaClient.__init__

        def patched(self, s, *, transport=None):
            original_init(self, s, transport=_transport(handler))

        monkeypatch.setattr(llm.OllamaClient, "__init__", patched)
        # Use the real engine so the AI layer is grounded in genuine calculations,
        # not in the fixture adapter the other suites use.
        module = load_module("backend.app.domain.module:create")
        with TestClient(create_app(settings, module), raise_server_exceptions=False) as client:
            login = client.post("/api/v1/auth/login",
                                json={"email": "analyst@aeza.test", "password": "demo123"})
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            yield client, headers

    return make


def _explain_handler(request: httpx.Request) -> httpx.Response:

    if request.url.path.endswith("/api/tags"):
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
    body = json.loads(request.content)
    user = body["messages"][-1]["content"]
    # Echo facts straight from the prompt so the answer is grounded by construction.
    context = json.loads(
        user.split("ДАННЫЕ (единственный источник фактов):\n", 1)[1].split("\n\nЗАДАЧА", 1)[0]
    )
    return httpx.Response(200, json={"message": {"content": _good_answer(context)}})


def _down_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def _timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


def test_ai_status_reports_enabled_and_reachable(ai_client):
    with ai_client(_explain_handler) as (client, headers):
        body = client.get("/api/v1/ai/status", headers=headers).json()
    assert body["enabled"] is True and body["reachable"] is True
    assert body["model"] == "qwen2.5:7b"


def test_ai_status_reports_unreachable_provider(ai_client):
    with ai_client(_down_handler) as (client, headers):
        body = client.get("/api/v1/ai/status", headers=headers).json()
    assert body["enabled"] is True and body["reachable"] is False
    assert body["detail"]


def test_explain_returns_grounded_text(ai_client):
    with ai_client(_explain_handler) as (client, headers):
        response = client.post(f"/api/v1/ai/customers/{CUSTOMER_ID}/explain", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grounded"] is True
    assert "71.4" in body["text"] or "71,4" in body["text"]


def test_explain_is_503_when_provider_is_down(ai_client):
    with ai_client(_down_handler) as (client, headers):
        response = client.post(f"/api/v1/ai/customers/{CUSTOMER_ID}/explain", headers=headers)
    assert response.status_code == 503
    assert "недоступна" in response.json()["detail"].lower()


def test_explain_is_503_on_timeout(ai_client):
    with ai_client(_timeout_handler) as (client, headers):
        response = client.post(f"/api/v1/ai/customers/{CUSTOMER_ID}/explain", headers=headers)
    assert response.status_code == 503


def test_explain_is_502_on_ungrounded_answer(ai_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, json={"message": {"content": "Вероятность оттока 99 %."}})

    with ai_client(handler) as (client, headers):
        response = client.post(f"/api/v1/ai/customers/{CUSTOMER_ID}/explain", headers=headers)
    assert response.status_code == 502
    assert "вымысел" in response.json()["detail"]


def test_explain_is_502_on_malformed_provider_answer(ai_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, content=b"<html>oops</html>")

    with ai_client(handler) as (client, headers):
        response = client.post(f"/api/v1/ai/customers/{CUSTOMER_ID}/explain", headers=headers)
    assert response.status_code == 502


def test_explain_requires_authentication(client):
    assert client.post(f"/api/v1/ai/customers/{CUSTOMER_ID}/explain").status_code == 401
    assert client.get("/api/v1/ai/status").status_code == 401


def test_explain_is_404_for_an_unknown_customer(ai_client):
    with ai_client(_explain_handler) as (client, headers):
        response = client.post("/api/v1/ai/customers/999999/explain", headers=headers)
    assert response.status_code == 404


def test_explain_rejects_an_oversized_question(ai_client):
    with ai_client(_explain_handler) as (client, headers):
        response = client.post(
            f"/api/v1/ai/customers/{CUSTOMER_ID}/explain",
            headers=headers, json={"question": "x" * 700})
    assert response.status_code == 422


def test_explain_does_not_change_the_published_generation(ai_client):
    with ai_client(_explain_handler) as (client, headers):
        before = client.get("/api/v1/analytics/summary", headers=headers).json()["generation"]
        client.post(f"/api/v1/ai/customers/{CUSTOMER_ID}/explain", headers=headers)
        after = client.get("/api/v1/analytics/summary", headers=headers).json()["generation"]
    assert before == after


def test_disabled_llm_returns_503_and_no_dead_button(tmp_path):
    settings = _settings(
        database_url=f"sqlite:///{(tmp_path / 'd.db').as_posix()}",
        auth_database_url=f"sqlite:///{(tmp_path / 'a.db').as_posix()}",
        llm_enabled=False)
    module = load_module("backend.app.domain.module:create")
    with TestClient(create_app(settings, module), raise_server_exceptions=False) as client:
        login = client.post("/api/v1/auth/login",
                            json={"email": "analyst@aeza.test", "password": "demo123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        status = client.get("/api/v1/ai/status", headers=headers).json()
        assert status["enabled"] is False
        assert client.post(f"/api/v1/ai/customers/{CUSTOMER_ID}/explain",
                           headers=headers).status_code == 503
