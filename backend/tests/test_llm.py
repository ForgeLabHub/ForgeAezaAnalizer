"""Unit tests for the local-LLM (Ollama) integration in ``domain/llm.py``.

These cover the parts that do not depend on the HTTP surface: the grounding
verifier that rejects fabricated numbers, the context whitelist, and the client's
error mapping. The provider is never really called — a stub HTTP transport stands
in for Ollama, so every branch is deterministic and no model is required.

The aggregate HTTP endpoint that uses this module is tested separately in
``test_insights_ai.py``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.domain import llm

from backend.tests.conftest import ROOT

CUSTOMER_ID = 10


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite://",
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
#
# The per-customer HTTP routes this file used to exercise
# (``GET /api/v1/ai/status``, ``POST /api/v1/ai/customers/{id}/explain``) were
# superseded by the AI Analyst subsystem in ``backend/app/ai``, which ships its
# own router and its own tests (``backend/tests/test_ai.py``). Those HTTP tests
# were removed here rather than kept against a contract that no longer exists.
# The unit tests above still cover ``backend/app/domain/llm.py``, which serves
# the aggregate endpoint ``POST /api/v1/insights/ai``
# (tested in ``backend/tests/test_insights_ai.py``).
