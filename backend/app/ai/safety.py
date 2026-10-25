"""Grounding, claim and injection checks for AI output.

A prompt alone is not a control: during development the model answered a
"churn probability in percent?" question with ``71.4%``, reusing the risk *score*
as if it were a probability.  This module is the enforcement point that catches
that class of error after generation:

* :func:`check_numbers` rejects any number that is not present in the supplied
  backend facts or retrieved documents (an invented figure).
* :func:`check_claims` rejects presenting the index as a probability, and using
  the score with a percent sign.
* :func:`sanitize_document` defangs instruction-like text inside retrieved
  documents, and :func:`detect_injection` reports it for logging.

The functions are pure and total so they can be unit-tested exhaustively.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schemas import AIAnswer

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
_PERCENT_AFTER_NUMBER = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*%")


_PROBABILITY_WORDS = ("вероятност", "probability", "шанс", "chance", "prognos", "прогноз вероятн")
_NEGATIONS = ("не ", "не  ", "нельзя", "невозможн", "не является", "not ", "n't", "никогда")


_GUARANTEE_WORDS = ("гарантир", "guarantee", "точно уйд", "обязательно уйд", "100% уйд")


_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior)", re.I),
    re.compile(r"игнорируй\s+(все\s+)?(предыдущие|прежние)", re.I),
    re.compile(r"(reveal|print|repeat)\s+(the\s+)?system\s+prompt", re.I),
    re.compile(r"раскрой\s+(системный\s+)?промпт", re.I),
    re.compile(r"\b(DROP|DELETE|INSERT|UPDATE)\s+TABLE\b", re.I),
    re.compile(r"```\s*(bash|sh|shell|powershell)", re.I),
)


@dataclass
class GroundingReport:
    """Outcome of the checks, plus the violations that were found."""

    grounded: bool = True
    invented_numbers: list[str] = field(default_factory=list)
    claim_violations: list[str] = field(default_factory=list)
    injection_hits: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.invented_numbers:
            warnings.append(
                "Удалены числа, отсутствующие в данных: " + ", ".join(sorted(set(self.invented_numbers)))
            )
        if self.claim_violations:
            warnings.append("Отклонены утверждения: " + "; ".join(sorted(set(self.claim_violations))))
        if self.injection_hits:
            warnings.append("В документах найдены инструкции; они обезврежены и не выполнялись.")
        return warnings


def _normalise(number: str) -> str:
    return number.replace(",", ".").lstrip("+")


def _to_float(raw: str) -> float | None:
    try:
        return float(_normalise(raw))
    except ValueError:
        return None


def _allowed_numbers(text: str) -> set[float]:
    """Numeric values present in the context, for value-level comparison.

    Comparing *values* rather than strings accepts harmless formatting
    differences (``71.4`` vs ``71.40``, ``5,8`` vs ``5.80``) while still
    rejecting a genuinely different figure — an earlier prefix-based comparison
    wrongly accepted ``100`` when only ``1`` appeared in the context.
    """

    allowed: set[float] = set()
    for match in _NUMBER.finditer(text):
        value = _to_float(match.group(0))
        if value is not None:
            allowed.add(value)
    return allowed


def _ungrounded_numbers(text: str, allowed: set[float]) -> list[str]:
    """Return numbers in ``text`` that are not supported by ``allowed``."""

    found: list[str] = []
    for match in _NUMBER.finditer(text or ""):
        raw = match.group(0)
        value = _to_float(raw)
        if value is None:
            continue
        if any(abs(value - candidate) < 1e-9 for candidate in allowed):
            continue
        found.append(raw)
    return found


def check_numbers(answer: AIAnswer, context_text: str) -> list[str]:
    """Return numbers used in the answer that do not appear in the context.

    ``citations`` are checked too: a citation is shown to the user as the source
    of a claim, so an invented figure in ``citation.detail`` is as misleading as
    one in the prose.
    """

    allowed = _allowed_numbers(context_text)
    invented: list[str] = []
    for field_name in ("summary", "factor_explanation", "limitations"):
        invented.extend(_ungrounded_numbers(getattr(answer, field_name) or "", allowed))
    for item in answer.facts + answer.recommendations:
        invented.extend(_ungrounded_numbers(item, allowed))
    for citation in answer.citations:
        invented.extend(_ungrounded_numbers(citation.detail or "", allowed))
        invented.extend(_ungrounded_numbers(citation.source or "", allowed))
    return invented


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?;])\s+|\n+", text) if part.strip()]


def check_claims(answer: AIAnswer, *, risk_score: float | None) -> list[str]:
    """Return descriptions of probabilistic or guaranteed claims."""

    violations: list[str] = []
    blocks = {
        "summary": answer.summary,
        "factor_explanation": answer.factor_explanation,
        "limitations": answer.limitations,
        "facts": "\n".join(answer.facts),
        "recommendations": "\n".join(answer.recommendations),
    }
    score_forms = set()
    if risk_score is not None:
        score_forms = {_normalise(f"{risk_score:g}"), _normalise(f"{risk_score:.1f}")}

    for name, text in blocks.items():
        if not text:
            continue
        for sentence in _sentences(text):
            lowered = sentence.lower()
            negated = any(marker in lowered for marker in _NEGATIONS)
            if not negated and any(word in lowered for word in _PROBABILITY_WORDS):
                violations.append(f"{name}: балл представлен как вероятность")


            if not negated and any(word in lowered for word in _GUARANTEE_WORDS):
                violations.append(f"{name}: обещание гарантированного результата")
            for match in _PERCENT_AFTER_NUMBER.finditer(sentence):
                if _normalise(match.group(1)) in score_forms:
                    violations.append(f"{name}: балл риска использован как процент вероятности")
    return violations


def sanitize_document(text: str) -> tuple[str, list[str]]:
    """Defang instruction-like text inside a retrieved document.

    The document stays readable — it is still useful as context — but any line
    that looks like an instruction to the model is replaced by a marker, so it
    cannot be mistaken for a system directive.
    """

    hits: list[str] = []
    safe_lines: list[str] = []
    for line in text.splitlines():
        matched = None
        for pattern in _INJECTION_PATTERNS:
            found = pattern.search(line)
            if found:
                matched = found.group(0)
                break
        if matched:
            hits.append(matched[:80])
            safe_lines.append("[строка документа удалена: похожа на инструкцию, а не на справку]")
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines), hits


def detect_injection(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        hits.extend(match.group(0)[:80] for match in pattern.finditer(text))
    return hits


def enforce(answer: AIAnswer, *, context_text: str, risk_score: float | None) -> tuple[AIAnswer, GroundingReport]:
    """Strip ungrounded claims from an answer and report what was removed.

    Rather than serving a repaired-by-hope answer, the offending items are
    dropped and the removal is surfaced in ``warnings``.  The result is always
    schema-valid, so the API layer can return it directly.
    """

    report = GroundingReport()
    report.invented_numbers = check_numbers(answer, context_text)
    report.claim_violations = check_claims(answer, risk_score=risk_score)
    report.injection_hits = detect_injection(context_text)

    if not (report.invented_numbers or report.claim_violations):
        report.grounded = True
        return answer, report

    report.grounded = False
    allowed = _allowed_numbers(context_text)
    cleaned = answer.model_copy(deep=True)
    cleaned.facts = [item for item in cleaned.facts if not _ungrounded_numbers(item, allowed)]
    cleaned.recommendations = [
        item for item in cleaned.recommendations if not _ungrounded_numbers(item, allowed)
    ]
    cleaned.citations = [
        citation
        for citation in cleaned.citations
        if not _ungrounded_numbers(citation.detail or "", allowed)
        and not _ungrounded_numbers(citation.source or "", allowed)
    ]

    summary_violations = [v for v in report.claim_violations if v.startswith("summary")]
    if summary_violations or _ungrounded_numbers(cleaned.summary, allowed):
        cleaned.summary = (
            "Модель сформировала утверждение, не подтверждённое данными, поэтому оно отклонено. "
            "Ниже приведены только проверенные факты."
        )
    if any(v.startswith("factor_explanation") for v in report.claim_violations) or _ungrounded_numbers(
        cleaned.factor_explanation, allowed
    ):
        cleaned.factor_explanation = ""


    if _ungrounded_numbers(cleaned.limitations, allowed):
        cleaned.limitations = ""

    notice = (
        "Ответ прошёл автоматическую проверку: неподтверждённые числа и утверждения удалены. "
        "Балл риска — это индекс, а не вероятность оттока."
    )
    cleaned.limitations = (cleaned.limitations + " " + notice).strip()[:1200]
    return cleaned, report
