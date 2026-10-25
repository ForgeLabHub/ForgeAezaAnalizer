"""Provenance of the loaded records.

The product must never present a synthetic record as a real Aéza customer, so
provenance is derived from facts in the data rather than from a hand-kept list:

* RFC 2606 / RFC 6761 reserve ``.test``, ``.invalid``, ``.example`` and the
  ``example.com`` / ``example.net`` / ``example.org`` domains for documentation
  and testing.  A record whose address sits in one of those domains cannot
  belong to a real customer.
* The demonstration cohort added for the hackathon is additionally recognisable
  by its ``demo-`` local-part prefix.

Nothing here feeds the risk score.  It is a labelling layer only, so a real
customer base would simply report zero synthetic records.
"""

from __future__ import annotations


RESERVED_TEST_DOMAINS = (
    "example.test",
    "example.com",
    "example.net",
    "example.org",
    "example.invalid",
)


DEMO_PREFIXES = ("demo-", "demo.", "demo_")

SYNTHETIC_EMAIL_DOMAIN = "тестовый домен (RFC 2606)"
SYNTHETIC_DEMO_PREFIX = "демонстрационная запись"


def classify_email(email: str | None) -> tuple[bool, str | None]:
    """Return ``(is_synthetic, reason)`` for one customer address."""

    if not email:
        return False, None
    value = email.strip().lower()
    if "@" not in value:
        return False, None
    local, _, domain = value.rpartition("@")

    if domain in RESERVED_TEST_DOMAINS or domain.endswith(".test") or domain.endswith(".invalid"):
        if local.startswith(DEMO_PREFIXES):
            return True, SYNTHETIC_DEMO_PREFIX
        return True, SYNTHETIC_EMAIL_DOMAIN
    if local.startswith(DEMO_PREFIXES):
        return True, SYNTHETIC_DEMO_PREFIX
    return False, None


def summarize(emails) -> dict:
    """Aggregate provenance over a customer base.

    ``mixed`` is the case that actually needs a warning in the UI: part of the
    base is synthetic and part is not, which is exactly the state that must not
    be mistaken for real data.
    """

    addresses = list(emails)
    synthetic = 0
    demo = 0
    for email in addresses:
        is_synthetic, reason = classify_email(email)
        if is_synthetic:
            synthetic += 1
            if reason == SYNTHETIC_DEMO_PREFIX:
                demo += 1

    total = len(addresses)
    real = total - synthetic
    if total == 0:
        state = "empty"
    elif synthetic == 0:
        state = "real"
    elif real == 0:
        state = "synthetic"
    else:
        state = "mixed"

    return {
        "total": total,
        "synthetic": synthetic,
        "real": real,
        "demonstrationRecords": demo,
        "state": state,
        "note": _note(state, synthetic, total, demo),
    }


def _note(state: str, synthetic: int, total: int, demo: int) -> str:
    if state == "empty":
        return "Записи не загружены."
    if state == "real":
        return "Все записи принадлежат реальным адресам."
    if state == "synthetic":
        base = (
            f"Все {total} записей — синтетические (тестовый домен). "
            "Это не клиенты Aéza, а данные для демонстрации."
        )
    else:
        base = (
            f"{synthetic} из {total} записей — синтетические (тестовый домен); "
            "они смешаны с реальными адресами."
        )
    if demo:
        base += f" Из них {demo} помечены как демонстрационные (demo-*)."
    return base
