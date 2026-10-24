"""Deterministic offline provider.

Used as the default and in tests: it produces a schema-valid answer that quotes
only lines from the FACTS block, so the full request path (context building,
grounding validation, serialisation) can be exercised without a model server.
It can be scripted with a fixed ``raw`` string to simulate a misbehaving model.
"""

from __future__ import annotations

import json
import re

from .base import Generation

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


class MockProvider:
    name = "mock"

    def __init__(self, *, model: str = "mock-echo", raw: str | None = None):
        self.model = model
        self.raw = raw
        self.calls: list[dict] = []

    def generate(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict | None = None,
        num_ctx: int,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> Generation:
        self.calls.append({"system": system, "user": user, "json_schema": json_schema})
        text = self.raw if self.raw is not None else self._compose(user)
        return Generation(text=text, model=self.model, provider=self.name, latency_ms=0)

    def _compose(self, user: str) -> str:
        """Build a grounded answer by quoting the FACTS block verbatim."""

        lines = []
        in_facts = False
        for line in user.splitlines():
            stripped = line.strip()
            if stripped.startswith("ФАКТЫ"):
                in_facts = True
                continue
            if stripped.startswith(("ДОКУМЕНТЫ", "ВОПРОС", "ЗАДАЧА")):
                in_facts = False
            if in_facts and stripped and not stripped.startswith("=="):
                lines.append(stripped)
        facts = lines[:12] or ["Факты не переданы."]
        payload = {
            "summary": "Ответ построен на переданных фактах: " + facts[0],
            "facts": facts,
            "factor_explanation": " ".join(facts[:6]),
            "recommendations": ["Проверить ближайшее продление по фактам."],
            "limitations": "Mock-провайдер: содержательного анализа модель не выполняет.",
        }
        return json.dumps(payload, ensure_ascii=False)

    def health(self, *, timeout: float) -> bool:
        return True


def numbers_in(text: str) -> list[str]:
    """Extract numeric literals, for grounding checks and tests."""

    return [match.group(0) for match in _NUMBER.finditer(text)]
