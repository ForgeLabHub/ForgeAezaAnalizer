"""The defence deck must not drift away from the engine.

The slides once carried literals captured under an older weighting (73,3 /
5,74 EUR) while the product reproduced 71.4 / 5.80 EUR, and nothing caught it.
``docs/deck/values.py`` now computes every figure, and these tests fail if the
generator starts printing a number the engine does not produce.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DECK = ROOT / "docs" / "deck"

pytestmark = pytest.mark.skipif(
    not (DECK / "values.py").exists(), reason="deck generator not present"
)


def _load_values():
    """Import docs/deck/values.py without polluting sys.path for other tests."""

    sys.path.insert(0, str(DECK))
    try:
        spec = importlib.util.spec_from_file_location("_deck_values", DECK / "values.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(DECK))


def test_deck_values_match_the_engine():
    facts = _load_values().facts()

    assert facts["weight_sum"] == 13.0
    assert facts["customer"]["score"] == "71,4"
    assert facts["customer"]["score_raw"] == 71.4
    assert facts["revenue"]["total_eur"] == "5,80"
    assert facts["service"]["score"] == "71,4"


def test_deck_after_change_values_match_the_engine():
    """The demo raises expiry_proximity 3.0 -> 9.0; the slide shows the result."""

    facts = _load_values().facts()

    assert facts["demo"]["from"] == 3.0
    assert facts["demo"]["to"] == 9.0
    assert facts["demo"]["weight_sum_after"] == 19.0
    assert facts["after"]["score"] == "81,8"
    assert facts["revenue"]["after_eur"] == "7,72"


def test_deprecated_factor_is_excluded_from_the_chart():
    """The factor chart must not list failed_renewals as a scored factor.

    It is deprecated (weight 0) and its signal already lives in
    renewal_failure_rate. The old hardcoded chart showed it at 2.0.
    """

    facts = _load_values().facts()
    keys = {name for name, _, _ in facts["service"]["factors"]}


    assert "Неуспешные продления" not in keys
    assert "Доля неуспешных продлений" not in keys
    assert "Ожидание продления" in keys


def test_generator_has_no_stale_literals():
    """Guard the raw source: none of the old figures may reappear as literals."""

    lines = (DECK / "build_deck.py").read_text(encoding="utf-8").splitlines()

    code = [line for line in lines if not line.lstrip().startswith("#")]
    body = "\n".join(code)
    body = body.split('"""', 2)[2] if body.count('"""') >= 2 else body
    for stale in ("73,3", "5,74", "7,48", "81,0", "15,0", "21,0"):
        assert stale not in body, f"stale literal {stale!r} is back in the generator"
