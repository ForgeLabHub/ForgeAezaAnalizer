"""Revenue-at-risk tests: eligible renewals only, no double counting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aeza_analyzer.analytics.service import AnalyticsService
from aeza_analyzer.db import get_session_factory, init_db
from aeza_analyzer.importer import import_dataset

REF = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)


def _service(**overrides):
    base = dict(
        id=1, name="svc", ownerId=1, paymentTerm="month", autoProlong=False,
        createdAt=REF - timedelta(days=1), expiresAt=REF + timedelta(days=10),
        status="active", price=1000,
    )
    base.update(overrides)
    return base


def _set_reference(session, reference):
    """Persist the snapshot instant, as the real importer does."""
    from aeza_analyzer.models import Meta

    session.merge(Meta(key="reference_at", value=reference.isoformat()))


def test_revenue_at_risk_counts_each_renewal_once(data_dir):
    from aeza_analyzer.models import Account, Service

    init_db()
    session = get_session_factory()()
    session.add(Account(id=1, email="a@example.test", balance=0, withdrawBalance=10_000,
                        totalReplenished=0, bonusBalance=0, bonusState="locked"))
    session.add(Service(**_service()))
    _set_reference(session, REF)
    session.commit()

    analytics = AnalyticsService(session)
    customers = analytics.customer_risk(horizon_days=30)
    session.close()

    assert len(customers) == 1
    customer = customers[0]
    # Exactly one eligible renewal of 1000 cents; revenue at risk <= that amount.
    assert customer.eligible_renewal_cents == 1000
    assert 0 <= customer.revenue_at_risk_cents <= 1000


def test_deleted_service_excluded_from_revenue(data_dir):
    from aeza_analyzer.models import Account, Service

    init_db()
    session = get_session_factory()()
    session.add(Account(id=1, email="a@example.test", balance=0, withdrawBalance=10_000,
                        totalReplenished=0, bonusBalance=0, bonusState="locked"))
    session.add(Service(**_service(status="deleted")))
    _set_reference(session, REF)
    session.commit()

    analytics = AnalyticsService(session)
    customers = analytics.customer_risk(horizon_days=30)
    session.close()

    assert customers[0].eligible_renewal_cents == 0
    assert customers[0].revenue_at_risk_cents == 0
    assert customers[0].risk_level == "churned"


def test_past_expiry_excluded_from_revenue(data_dir):
    from aeza_analyzer.models import Account, Service

    init_db()
    session = get_session_factory()()
    session.add(Account(id=1, email="a@example.test", balance=0, withdrawBalance=10_000,
                        totalReplenished=0, bonusBalance=0, bonusState="locked"))
    # Service created well before the snapshot, expiring shortly before it.
    session.add(Service(**_service(
        createdAt=REF - timedelta(days=30),
        expiresAt=REF - timedelta(days=5),
    )))
    _set_reference(session, REF)
    session.commit()

    analytics = AnalyticsService(session)
    customers = analytics.customer_risk(horizon_days=30)
    session.close()

    # A renewal that already happened is not a future renewal.
    assert customers[0].eligible_renewal_cents == 0


def test_balance_is_not_part_of_revenue_at_risk(data_dir):
    from aeza_analyzer.models import Account, Service

    init_db()
    session = get_session_factory()()
    session.add(Account(id=1, email="a@example.test", balance=999_999,
                        withdrawBalance=999_999, totalReplenished=999_999,
                        bonusBalance=0, bonusState="locked"))
    session.add(Service(**_service()))
    _set_reference(session, REF)
    session.commit()

    analytics = AnalyticsService(session)
    customers = analytics.customer_risk(horizon_days=30)
    session.close()

    # Revenue at risk is bounded by the renewal amount, never the balance.
    assert customers[0].revenue_at_risk_cents <= 1000


def test_real_dataset_revenue_is_bounded(data_dir):
    import_dataset()
    session = get_session_factory()()
    analytics = AnalyticsService(session)
    dashboard = analytics.dashboard(horizon_days=30)
    customers = analytics.customer_risk(horizon_days=30)
    session.close()

    assert dashboard["revenue_at_risk_cents"] <= dashboard["eligible_renewal_cents"]
    for customer in customers:
        assert customer.revenue_at_risk_cents <= customer.eligible_renewal_cents
