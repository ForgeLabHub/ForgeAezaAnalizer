"""Analytics service: reads the store and computes risk / revenue views.

Separation of concerns required by the case:
* **customer risk** and **monetary exposure** are computed independently;
* revenue at risk counts each *eligible future renewal* once, weighted by the
  owning service's risk, and never includes balances or historical top-ups.

``revenue_at_risk = eligible_renewal_amount * risk_score / 100``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session_factory, init_db
from ..models import Account, ImportRun, Meta, RiskWeight, Service, Transaction
from .risk import (
    DEFAULT_HORIZON_DAYS,
    DEFAULT_WEIGHTS,
    FACTOR_TITLES,
    RISK_LEVEL_BANDS,
    ServiceRisk,
    eligible_for_renewal,
    level_for,
    score_service,
    validate_weights,
)

REFERENCE_META_KEY = "reference_at"
SOURCE_SHA_META_KEY = "source_sha256"
SNAPSHOT_META_KEY = "imported_at"

# Transaction statuses that mean a renewal did not go through.
FAILED_TX_STATUS = "not_performed"
RENEWAL_TX_TYPE = "prolong"


@dataclass
class CustomerRisk:
    account_id: int
    email: str
    balance_cents: int
    withdraw_balance_cents: int
    bonus_balance_cents: int
    bonus_state: str
    total_replenished_cents: int
    service_count: int
    live_service_count: int
    risk_score: float
    risk_level: str
    confidence: float
    revenue_at_risk_cents: int
    eligible_renewal_cents: int
    reasons: list[str] = field(default_factory=list)
    services: list[ServiceRisk] = field(default_factory=list)

    def as_dict(self, *, include_services: bool = False) -> dict:
        payload = {
            "account_id": self.account_id,
            "email": self.email,
            "balance_cents": self.balance_cents,
            "withdraw_balance_cents": self.withdraw_balance_cents,
            "bonus_balance_cents": self.bonus_balance_cents,
            "bonus_state": self.bonus_state,
            "total_replenished_cents": self.total_replenished_cents,
            "service_count": self.service_count,
            "live_service_count": self.live_service_count,
            "risk_score": round(self.risk_score, 2),
            "risk_level": self.risk_level,
            "confidence": round(self.confidence, 4),
            "revenue_at_risk_cents": self.revenue_at_risk_cents,
            "eligible_renewal_cents": self.eligible_renewal_cents,
            "reasons": self.reasons,
        }
        if include_services:
            payload["services"] = [s.as_dict() for s in self.services]
        return payload


class AnalyticsService:
    """Computes risk and revenue views from the imported dataset."""

    def __init__(self, session: Session):
        self.session = session

    # ---------------------------------------------------------------- weights
    def get_weights(self) -> dict[str, float]:
        stored = {row.key: row.weight for row in self.session.scalars(select(RiskWeight))}
        if not stored:
            return dict(DEFAULT_WEIGHTS)
        merged = dict(DEFAULT_WEIGHTS)
        merged.update({k: v for k, v in stored.items() if k in DEFAULT_WEIGHTS})
        return merged

    def set_weights(self, weights: dict[str, float]) -> dict[str, float]:
        cleaned = validate_weights(weights)
        for key, value in cleaned.items():
            existing = self.session.get(RiskWeight, key)
            if existing is None:
                self.session.add(RiskWeight(key=key, weight=value))
            else:
                existing.weight = value
        self.session.flush()
        return cleaned

    def reset_weights(self) -> dict[str, float]:
        for row in self.session.scalars(select(RiskWeight)):
            self.session.delete(row)
        self.session.flush()
        return dict(DEFAULT_WEIGHTS)

    # ------------------------------------------------------------------ meta
    def reference_at(self) -> datetime:
        row = self.session.get(Meta, REFERENCE_META_KEY)
        if row is not None:
            return datetime.fromisoformat(row.value)
        latest = self.session.scalar(select(Service.expiresAt).order_by(Service.expiresAt.desc()))
        return latest or datetime.now(timezone.utc)

    def meta(self) -> dict:
        values = {row.key: row.value for row in self.session.scalars(select(Meta))}
        return {
            "reference_at": self.reference_at().isoformat(),
            "source_sha256": values.get(SOURCE_SHA_META_KEY),
            "source_path": values.get("source_path"),
            "imported_at": values.get(SNAPSHOT_META_KEY),
        }

    def last_import(self) -> dict | None:
        run = self.session.scalar(select(ImportRun).order_by(ImportRun.id.desc()))
        if run is None:
            return None
        return {
            "id": run.id,
            "source_path": run.source_path,
            "source_sha256": run.source_sha256,
            "accounts": run.accounts,
            "services": run.services,
            "transactions": run.transactions,
            "status": run.status,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }

    # -------------------------------------------------------------- analytics
    def _failed_renewals_by_service(self) -> dict[int, int]:
        rows = self.session.scalars(
            select(Transaction).where(
                Transaction.type == RENEWAL_TX_TYPE,
                Transaction.status == FAILED_TX_STATUS,
            )
        )
        counts: dict[int, int] = {}
        for tx in rows:
            counts[tx.serviceId] = counts.get(tx.serviceId, 0) + 1
        return counts

    def _score_services(
        self, weights: dict[str, float], horizon_days: int
    ) -> tuple[dict[int, ServiceRisk], datetime]:
        reference = self.reference_at()
        failed = self._failed_renewals_by_service()
        accounts = {a.id: a for a in self.session.scalars(select(Account))}
        scores: dict[int, ServiceRisk] = {}
        for service in self.session.scalars(select(Service)):
            owner = accounts.get(service.ownerId)
            scores[service.id] = score_service(
                service_id=service.id,
                service_name=service.name,
                status=service.status,
                price_cents=service.price,
                expires_at=service.expiresAt,
                auto_prolong=service.autoProlong,
                withdraw_balance=owner.withdrawBalance if owner else None,
                failed_renewals=failed.get(service.id, 0),
                reference=reference,
                horizon_days=horizon_days,
                weights=weights,
            )
        return scores, reference

    def customer_risk(
        self, weights: dict[str, float] | None = None, horizon_days: int = DEFAULT_HORIZON_DAYS
    ) -> list[CustomerRisk]:
        weights = weights or self.get_weights()
        scores, reference = self._score_services(weights, horizon_days)
        accounts = list(self.session.scalars(select(Account).order_by(Account.id)))
        services = list(self.session.scalars(select(Service)))

        by_owner: dict[int, list[Service]] = {}
        for service in services:
            by_owner.setdefault(service.ownerId, []).append(service)

        results: list[CustomerRisk] = []
        for account in accounts:
            owned = by_owner.get(account.id, [])
            owned_scores = [scores[s.id] for s in owned]

            # Customer risk = worst live service (a customer churns when a
            # service churns). Already-deleted services are excluded from the
            # forward-looking score and reported separately in reasons.
            live_scores = [s for s in owned_scores if s.is_live and s.confidence > 0]
            deleted_scores = [s for s in owned_scores if not s.is_live]

            if live_scores:
                worst = max(live_scores, key=lambda s: s.score)
                risk_score = worst.score
                confidence = sum(s.confidence for s in live_scores) / len(live_scores)
                risk_level = level_for(risk_score)
            elif deleted_scores:
                # No live services but history exists: churn already happened.
                # This is a known outcome, not an unknown-risk zero.
                risk_score = 0.0
                confidence = 0.0
                risk_level = "churned"
            else:
                # Account owns no services at all: genuinely unscoreable.
                risk_score = 0.0
                confidence = 0.0
                risk_level = "unknown"

            # Revenue at risk: each eligible future renewal counted exactly once.
            eligible = 0
            at_risk = 0.0
            for service in owned:
                score = scores[service.id]
                if service.status in ("deleted",) or not score.is_live:
                    continue
                if not eligible_for_renewal(service.expiresAt, reference, horizon_days):
                    continue
                eligible += service.price
                at_risk += service.price * score.score / 100.0

            reasons: list[str] = []
            if live_scores:
                top = max(live_scores, key=lambda s: s.score)
                reasons.append(
                    f"highest-risk service '{top.service_name}' scored {top.score:.0f}/100"
                )
                reasons.extend(f"{top.service_name}: {r}" for r in top.reasons[:3])
            if deleted_scores:
                names = ", ".join(s.service_name for s in deleted_scores)
                reasons.append(f"already churned (deleted) services: {names}")

            results.append(
                CustomerRisk(
                    account_id=account.id,
                    email=account.email,
                    balance_cents=account.balance,
                    withdraw_balance_cents=account.withdrawBalance,
                    bonus_balance_cents=account.bonusBalance,
                    bonus_state=account.bonusState,
                    total_replenished_cents=account.totalReplenished,
                    service_count=len(owned),
                    live_service_count=len(live_scores),
                    risk_score=risk_score,
                    risk_level=risk_level,
                    confidence=confidence,
                    revenue_at_risk_cents=int(round(at_risk)),
                    eligible_renewal_cents=eligible,
                    reasons=reasons,
                    services=owned_scores,
                )
            )

        results.sort(key=lambda c: c.risk_score, reverse=True)
        return results

    def dashboard(self, horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict:
        weights = self.get_weights()
        customers = self.customer_risk(weights, horizon_days)
        reference = self.reference_at()

        counts = {
            "accounts": self.session.query(Account).count(),
            "services": self.session.query(Service).count(),
            "transactions": self.session.query(Transaction).count(),
        }

        service_status = {}
        for service in self.session.scalars(select(Service)):
            service_status[service.status] = service_status.get(service.status, 0) + 1

        level_counts = {name: 0 for _, _, name in RISK_LEVEL_BANDS}
        level_counts["churned"] = 0
        level_counts["unknown"] = 0
        for customer in customers:
            level_counts[customer.risk_level] = level_counts.get(customer.risk_level, 0) + 1

        total_at_risk = sum(c.revenue_at_risk_cents for c in customers)
        total_eligible = sum(c.eligible_renewal_cents for c in customers)

        return {
            "counts": counts,
            "reference_at": reference.isoformat(),
            "horizon_days": horizon_days,
            "service_status": service_status,
            "risk_levels": level_counts,
            "revenue_at_risk_cents": total_at_risk,
            "eligible_renewal_cents": total_eligible,
            "high_risk_customers": sum(1 for c in customers if c.risk_level == "high"),
            "weights": weights,
        }


def get_analytics() -> AnalyticsService:
    init_db()
    return AnalyticsService(get_session_factory()())
