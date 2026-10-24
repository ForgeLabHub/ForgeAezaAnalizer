from __future__ import annotations

import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Lock

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from core import Analysis
from backend.app.api.routes_analytics import events
from backend.app.db import AnalysisRow, CustomerRow, SourceRow
from backend.app.main import create_app
from backend.app.modules import ModuleContractError
from backend.tests.conftest import TEST_LOGIN, TEST_PASSWORD


def test_import_idempotency_and_validation(client, auth_headers, snapshot_payload, analytics):
    calls = analytics.calls
    response = client.put("/api/v1/source/snapshot", json=snapshot_payload, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["generation"] == 1 and analytics.calls == calls
    broken = copy.deepcopy(snapshot_payload)
    broken["services"][0]["ownerId"] = 9999
    assert client.put("/api/v1/source/snapshot", json=broken, headers=auth_headers).status_code == 422
    broken = copy.deepcopy(snapshot_payload)
    broken["accounts"][0]["balance"] = True
    assert client.put("/api/v1/source/snapshot", json=broken, headers=auth_headers).status_code == 422
    assert client.get("/api/v1/source/snapshot", headers=auth_headers).json()["generation"] == 1


def test_failed_calculation_retains_inputs_and_published_result(client, auth_headers, snapshot_payload, analytics):
    before = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    analytics.error = RuntimeError("fixture failure")
    source = copy.deepcopy(snapshot_payload)
    source["accounts"][0]["balance"] += 1
    assert client.put("/api/v1/source/snapshot", json=source, headers=auth_headers).status_code == 500
    assert client.patch("/api/v1/model/settings", json={"horizonDays": 7}, headers=auth_headers).status_code == 500
    assert client.get("/api/v1/analytics/summary", headers=auth_headers).json() == before
    assert client.get("/api/v1/model/settings", headers=auth_headers).json()["settings"]["horizonDays"] == 30
    assert client.app.state.runtime.storage.load().source["accounts"][0]["balance"] == snapshot_payload["accounts"][0]["balance"]


def test_invalid_external_output_is_502_and_not_published(client, auth_headers, analytics):
    analytics.transform = lambda result: Analysis(result.summary, [])
    response = client.patch("/api/v1/model/settings", json={"horizonDays": 7}, headers=auth_headers)
    assert response.status_code == 502
    assert client.app.state.runtime.storage.load().generation == 1


def test_module_cannot_mutate_published_inputs(client, analytics):
    runtime = client.app.state.runtime
    before = runtime.storage.load()
    calculate = analytics.calculate
    def mutate(state):
        state.source["accounts"][0]["email"] = "changed@example.test"
        return calculate(state)
    analytics.calculate = mutate
    import pytest
    with pytest.raises(ModuleContractError):
        runtime.core.update(patch={"horizonDays": 7})
    assert runtime.storage.load() == before


def test_a_plain_tick_does_not_publish_a_new_generation(client, analytics):
    """A recalculation with no input change must not create a generation.

    Regression: ``Core.update(recalculate=True)`` entered the publication branch
    unconditionally, so the generation advanced on every tick, the analysis tables
    grew by one row per customer per minute, and a generation-based dedupe key
    looked "new" forever.
    """

    runtime = client.app.state.runtime
    before = runtime.storage.load()
    assert before.generation == 1

    for _ in range(3):
        returned = runtime.core.update(actor="clock")
        assert returned.generation == before.generation

    assert runtime.storage.load().generation == 1

    # A real input change still publishes, so the guard is not over-broad.
    published = runtime.core.update(patch={"horizonDays": 7}, actor="analyst")
    assert published.generation == 2


def test_force_publishes_without_an_input_change(client, analytics):
    """``force`` is the one path that republishes unchanged inputs.

    It exists for an engine-version upgrade, where the inputs are identical but
    the result must be recomputed.
    """

    runtime = client.app.state.runtime
    before = runtime.storage.load()
    forced = runtime.core.update(force=True, actor="clock")
    assert forced.generation == before.generation + 1


def test_live_clock_recalculates_without_source_change(settings, analytics, auth_settings, monkeypatch):
    from threading import Event
    completed = Event()
    live = replace(settings, as_of="now", recalculate_seconds=1)
    with TestClient(create_app(live, analytics, auth_settings)) as running:
        storage = running.app.state.runtime.storage
        publish = storage.publish
        def observe(previous, candidate, result, actor):
            published = publish(previous, candidate, result, actor)
            if published and candidate.generation >= 2:
                completed.set()
            return published
        monkeypatch.setattr(storage, "publish", observe)
        assert completed.wait(timeout=5)
        state = storage.load()
        assert state.generation >= 2 and state.source_version == 1 and state.model_version == 1


def test_metrics_support_dedicated_collector_token(settings, analytics, auth_settings):
    configured = replace(settings, metrics_token="collector-token")
    with TestClient(create_app(configured, analytics, auth_settings)) as client:
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer collector-token"}).status_code == 200


def test_write_failure_rolls_back_entire_publication(client, auth_headers, snapshot_payload):
    def fail(*args):
        raise RuntimeError("fixture storage failure")
    event.listen(CustomerRow, "before_insert", fail)
    try:
        source = copy.deepcopy(snapshot_payload)
        source["accounts"][0]["balance"] += 1
        assert client.put("/api/v1/source/snapshot", json=source, headers=auth_headers).status_code == 500
    finally:
        event.remove(CustomerRow, "before_insert", fail)
    runtime = client.app.state.runtime
    assert runtime.storage.load().generation == 1
    with runtime.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceRow)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisRow)) == 1


def test_concurrent_patches_recalculate_after_cas_conflict(client, analytics):
    runtime = client.app.state.runtime
    barrier = Barrier(2)
    lock = Lock()
    calculate = analytics.calculate
    calls = 0
    def simultaneous(state):
        nonlocal calls
        with lock:
            calls += 1
            number = calls
        if number <= 2:
            barrier.wait(timeout=5)
        return calculate(state)
    analytics.calculate = simultaneous
    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(runtime.core.update, patch={"horizonDays": 7})
        second = executor.submit(runtime.core.update, patch={"weights": {"fixture": 2.0}})
        first.result(timeout=10)
        second.result(timeout=10)
    state = runtime.storage.load()
    assert state.generation == 3
    assert state.settings["horizonDays"] == 7
    assert state.settings["weights"]["fixture"] == 2
    assert calls == 3


def test_stale_result_cannot_replace_newer_result(client):
    runtime = client.app.state.runtime
    old = runtime.storage.load()
    stale = replace(old, generation=old.generation + 1)
    result = runtime.calculation.calculate(stale)
    new = runtime.core.update(patch={"horizonDays": 7})
    assert runtime.storage.publish(old, stale, result, "stale") is False
    assert runtime.storage.load() == new


def test_settings_survive_restart_and_auth_sessions_expire(settings, auth_settings, analytics):
    with TestClient(create_app(settings, analytics, auth_settings)) as client:
        login = client.post("/api/v1/auth/login", json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        updated = client.patch("/api/v1/model/settings", json={"horizonDays": 7}, headers=headers)
        assert updated.status_code == 200, updated.text
        calls = analytics.calls
    with TestClient(create_app(settings, analytics, auth_settings)) as restarted:
        assert restarted.get("/api/v1/auth/me", headers=headers).status_code == 401
        login = restarted.post("/api/v1/auth/login", json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        body = restarted.get("/api/v1/model/settings", headers=headers).json()
        assert body["settings"]["horizonDays"] == 7 and body["generation"] == 2
        assert analytics.calls == calls
    with TestClient(create_app(settings, auth_settings=auth_settings)) as without_module:
        assert without_module.get("/ready").status_code == 503
        login = without_module.post("/api/v1/auth/login", json={"email": TEST_LOGIN, "password": TEST_PASSWORD})
        fresh_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert without_module.get("/api/v1/customers", headers=fresh_headers).status_code == 200
        assert without_module.get("/api/v1/model/settings", headers=fresh_headers).status_code == 200
        assert without_module.patch("/api/v1/model/settings", json={"horizonDays": 8}, headers=fresh_headers).status_code == 503


def test_observations_do_not_invent_event_times(client, auth_headers, snapshot_payload):
    source = copy.deepcopy(snapshot_payload)
    first = source["services"][0]
    first["status"] = "deleted" if first["status"] != "deleted" else "active"
    response = client.put("/api/v1/source/snapshot", json=source, headers=auth_headers)
    assert response.status_code == 200, response.text
    history = client.get(f"/api/v1/source/observations?serviceId={first['id']}", headers=auth_headers).json()["items"]
    assert len(history) == 2
    assert history[0]["sourceVersion"] == 2
    assert history[0]["status"] == first["status"]
    assert history[0]["previousObservedAt"] is not None and history[0]["eventAt"] is None


def test_disappearance_is_observation_and_not_deleted_status(client, auth_headers, snapshot_payload):
    source = copy.deepcopy(snapshot_payload)
    service_id = source["services"].pop(0)["id"]
    source["transactions"] = [item for item in source["transactions"] if item["serviceId"] != service_id]
    assert client.put("/api/v1/source/snapshot", json=source, headers=auth_headers).status_code == 200
    item = client.get(f"/api/v1/source/observations?serviceId={service_id}", headers=auth_headers).json()["items"][0]
    assert item["status"] is None


def test_sse_sends_current_version_on_reconnect_and_stops_after_logout(client, auth_headers):
    class Connected:
        async def is_disconnected(self):
            return False
    runtime = client.app.state.runtime
    token = auth_headers["Authorization"].split(" ", 1)[1]
    async def read():
        stream = events(runtime, token, Connected(), 999)
        chunk = await anext(stream)
        assert "id: 1" in chunk and "analysis.updated" in chunk
        await stream.aclose()
        session, _, _ = runtime.auth.bearer(f"Bearer {token}")
        runtime.auth.sessions.pop(session.id)
        stream = events(runtime, token, Connected(), 1)
        try:
            await anext(stream)
            assert False
        except StopAsyncIteration:
            pass
    asyncio.run(read())
