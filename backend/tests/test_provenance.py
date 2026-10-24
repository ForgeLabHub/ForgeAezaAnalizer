"""Provenance classification: a synthetic record must never pass as real."""

from __future__ import annotations

from app.domain.provenance import (
    SYNTHETIC_DEMO_PREFIX,
    SYNTHETIC_EMAIL_DOMAIN,
    classify_email,
    summarize,
)


def test_real_customer_address_is_not_synthetic():
    assert classify_email("client@aeza.net") == (False, None)
    assert classify_email("ops@hosting-provider.ru") == (False, None)


def test_reserved_test_domains_are_synthetic():
    for email in (
        "user-0001@example.test",
        "someone@example.com",
        "someone@example.org",
        "someone@example.invalid",
        "someone@sub.example.test",
    ):
        is_synthetic, reason = classify_email(email)
        assert is_synthetic is True, email
        assert reason == SYNTHETIC_EMAIL_DOMAIN


def test_demo_prefix_is_synthetic_even_on_a_real_looking_domain():
    is_synthetic, reason = classify_email("demo-customer-001@aeza.net")
    assert is_synthetic is True
    assert reason == SYNTHETIC_DEMO_PREFIX


def test_missing_or_malformed_address_is_not_flagged():
    # Absent data is unknown, not evidence of fabrication.
    assert classify_email(None) == (False, None)
    assert classify_email("") == (False, None)
    assert classify_email("no-at-sign") == (False, None)


def test_summarize_reports_mixed_base():
    result = summarize(
        [
            "user-0001@example.test",
            "user-0002@example.test",
            "real-client@aeza.net",
        ]
    )
    assert result["total"] == 3
    assert result["synthetic"] == 2
    assert result["real"] == 1
    assert result["state"] == "mixed"
    assert "2 из 3" in result["note"]


def test_summarize_all_synthetic_marks_demo_records():
    result = summarize(["demo-customer-001@example.test", "user-0002@example.test"])
    assert result["state"] == "synthetic"
    assert result["real"] == 0
    assert result["demonstrationRecords"] == 1
    assert "не клиенты Aéza" in result["note"]


def test_summarize_real_base_has_no_warning():
    result = summarize(["a@aeza.net", "b@aeza.net"])
    assert result["state"] == "real"
    assert result["synthetic"] == 0
    assert "реальн" in result["note"]


def test_summarize_empty_base_is_safe():
    result = summarize([])
    assert result["state"] == "empty"
    assert result["total"] == 0
