from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from core import Analysis
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.modules import ModelDefinition

AS_OF = "2026-10-19T15:00:00+00:00"


def amount(value):
    if value is None:
        return {"cents": None, "eur": None}
    return {"cents": value, "eur": f"{value // 100}.{value % 100:02d}"}


def fixture_result(source):
    customers = []
    for index, account in enumerate(source["accounts"]):
        services = [{"id": item["id"], "name": item["name"], "status": item["status"],
            "statusLabel": "fixture", "paymentTerm": item.get("paymentTerm"), "paymentTermLabel": "fixture",
            "autoProlong": item.get("autoProlong"), "createdAt": item.get("createdAt"), "expiresAt": item.get("expiresAt"),
            "daysToExpiry": None, "price": amount(item.get("price")), "riskScore": None,
            "riskCategory": "insufficient_data", "riskCategoryLabel": "fixture", "eligibleForForecast": False,
            "stateNote": "fixture", "reasons": [], "missingData": [], "factors": [],
            "revenueAtRisk": None, "upcomingRenewalAt": None, "recommendations": []}
            for item in source["services"] if item["ownerId"] == account["id"]]
        customers.append({"id": account["id"], "email": account["email"],
            "balance": amount(account.get("balance")), "withdrawBalance": amount(account.get("withdrawBalance")),
            "totalReplenished": amount(account.get("totalReplenished")), "bonusBalance": amount(account.get("bonusBalance")),
            "bonusState": account.get("bonusState"), "riskScore": [10, 10, 70, None][index % 4],
            "riskCategory": ["low", "low", "high", "insufficient_data"][index % 4], "riskCategoryLabel": "fixture",
            "serviceCount": len(services), "eligibleServiceCount": 0, "highRiskServiceCount": 0,
            "concludedStates": {}, "stateNote": "fixture", "revenueAtRisk": amount(0), "upcomingRenewals": amount(0),
            "topReasons": [], "missingData": [], "reasons": [], "services": services, "recommendations": [], "renewalDetails": []})
    summary = {"generatedAt": AS_OF, "horizonDays": 30,
        "customers": {"total": len(customers), "byCategory": {}, "highRisk": 0, "mediumRisk": 0,
            "insufficientData": 0, "withRevenueAtRisk": 0},
        "services": {"total": len(source["services"]), "open": 0, "concluded": 0, "byStatus": {}, "highRisk": 0},
        "revenue": {"revenueAtRiskCents": 0, "revenueAtRiskEur": "0.00", "upcomingRenewalsCents": 0,
            "upcomingRenewalsEur": "0.00", "historicalReplenishedCents": 0, "historicalReplenishedEur": "0.00"},
        "topRiskReasons": [], "upcomingRenewals": [], "historyAvailable": False,
        "historyNote": "fixture", "model": {"type": "fixture", "calibrated": False, "note": "fixture"}}
    return Analysis(summary, customers)


class FixtureAnalytics:
    def __init__(self):
        self.calls = 0
        self.error = None
        self.transform = None

    def definition(self):
        return ModelDefinition({"horizonDays": 30, "lowMax": 34, "mediumMax": 64, "weights": {"fixture": 1.0}},
            ({"key": "fixture", "label": "fixture", "description": "fixture", "howComputed": "fixture",
                "normalization": "fixture", "defaultWeight": 1.0, "missingDataBehaviour": "fixture"},), "test-v1")

    def validate_settings(self, settings):
        return settings

    def calculate(self, state):
        self.calls += 1
        if self.error:
            raise self.error
        result = fixture_result(state.source)
        return self.transform(result) if self.transform else result


@pytest.fixture(scope="session")
def snapshot_payload():
    return json.loads((ROOT / "backend/data/snapshot.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-key", bootstrap_admin_password="demo123",
        snapshot_path=str(ROOT / "backend/data/snapshot.json"), as_of=AS_OF)


@pytest.fixture
def analytics():
    return FixtureAnalytics()


@pytest.fixture
def app(settings, analytics):
    return create_app(settings, analytics)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def auth_headers(client):
    response = client.post("/api/v1/auth/login", json={"email": "analyst@aeza.test", "password": "demo123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def reference_now():
    return datetime.fromisoformat(AS_OF)
