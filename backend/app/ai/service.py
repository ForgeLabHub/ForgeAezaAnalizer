"""AI Analyst orchestration.

Responsibilities, in order:

1. Decide whether the subsystem is enabled and reachable.
2. Build a grounded context from the canonical backend (facts) plus the local
   RAG index (documents).
3. Ask the provider for a structured answer.
4. Validate it against :class:`~backend.app.ai.schemas.AIAnswer` and strip
   anything not supported by the facts.
5. Return the answer with its citations, warnings and the facts it used.

The service never computes a score or an amount.  Concurrency is bounded by a
semaphore so a slow model cannot exhaust the worker pool, and every call has a
finite timeout, so a hung model cannot block the analytics API.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from core import InvalidInput, ResourceNotFoundError

from . import context_builder, parsing, prompts
from .config import AISettings, ai_settings
from .providers import Generation, Provider, ProviderError, build_provider
from .rag import Retriever
from .safety import enforce
from .schemas import AIAnswer, AIResponse, AIStatusResponse

logger = logging.getLogger("aeza.ai")


class AIUnavailable(Exception):
    pass


class AIDisabled(Exception):
    pass


@dataclass
class _Prepared:
    system: str
    user: str
    context: context_builder.Context
    task: str


class AIService:
    def __init__(self, storage, calculation, *, settings: AISettings | None = None, provider: Provider | None = None):
        self.storage = storage
        self.calculation = calculation
        self.settings = settings or ai_settings()
        self._provider = provider
        self._retriever: Retriever | None = None
        self._semaphore = threading.BoundedSemaphore(self.settings.max_concurrency)


    @property
    def provider(self) -> Provider:
        if self._provider is None:
            self._provider = build_provider(self.settings)
        return self._provider

    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever(Path(self.settings.rag_index_path))
        return self._retriever

    def status(self, *, probe: bool = False) -> AIStatusResponse:
        """Report ``disabled`` / ``ready`` / ``unavailable`` without raising."""

        settings = self.settings
        indexed = self.retriever.ready
        chunks = self.retriever.chunk_count if indexed else 0
        if not settings.enabled:
            return AIStatusResponse(status="disabled", provider=settings.provider, model=settings.model,
                enabled=False, reason="AI Analyst выключен (AEZA_AI_ENABLED=0)", reachable=False,
                rag_indexed=indexed, rag_chunks=chunks)
        reachable = True
        reason = ""
        if probe:
            try:
                reachable = self.provider.health(timeout=min(5.0, settings.request_timeout_seconds))
            except Exception:
                reachable = False
            if not reachable:
                reason = "локальная модель недоступна"
        return AIStatusResponse(status="ready" if reachable else "unavailable", provider=settings.provider,
            model=settings.model, enabled=True, reason=reason, reachable=reachable,
            rag_indexed=indexed, rag_chunks=chunks)


    def _prepare_customer(self, customer_id: int, question: str | None, task: str) -> _Prepared:
        try:
            self.storage.customer(customer_id)
        except ResourceNotFoundError:
            raise
        ctx = context_builder.build_customer_context(
            self.storage, customer_id, retriever=self.retriever, question=question or "",
            top_k=self.settings.rag_top_k, max_doc_chars=self.settings.max_context_chars)
        system = prompts.SYSTEM_PROMPT
        user = (
            f"{ctx.facts_text}\n\n{ctx.documents_text}\n"
            f"{prompts.task_instruction(task, question=question)}"
        )
        return _Prepared(system=system, user=user, context=ctx, task=task)

    def _prepare_portfolio(self, question: str | None, task: str) -> _Prepared:
        ctx = context_builder.build_portfolio_context(
            self.storage, retriever=self.retriever, question=question or "",
            top_k=self.settings.rag_top_k, max_doc_chars=self.settings.max_context_chars)
        system = prompts.SYSTEM_PROMPT
        user = (
            f"{ctx.facts_text}\n\n{ctx.documents_text}\n"
            f"{prompts.task_instruction(task, question=question)}"
        )
        return _Prepared(system=system, user=user, context=ctx, task=task)

    def _prepare_scenario(self, overrides: dict, question: str | None) -> _Prepared:
        if not overrides:
            raise InvalidInput("нужно передать overrides для сценария")
        ctx = context_builder.build_scenario_context(
            self.storage, self.calculation, overrides=overrides, question=question or "",
            retriever=self.retriever, top_k=self.settings.rag_top_k,
            max_doc_chars=self.settings.max_context_chars)
        system = prompts.SYSTEM_PROMPT
        user = (
            f"{ctx.facts_text}\n\n{ctx.documents_text}\n"
            f"{prompts.task_instruction('scenario_explain', question=question)}"
        )
        return _Prepared(system=system, user=user, context=ctx, task="scenario_explain")

    def _generate(self, prepared: _Prepared) -> tuple[AIAnswer, Generation, list[str], bool]:
        """Call the provider, validate and enforce grounding, with bounded retries.

        A schema-invalid reply is retried.  A reply that parses but contains
        unsupported numbers is *repaired* by :func:`enforce`; if a later attempt
        is fully grounded it wins, otherwise the repaired answer is returned with
        ``grounded=False`` and explicit warnings rather than an invented figure.
        """

        settings = self.settings
        attempts = settings.max_retries + 1
        warnings: list[str] = []
        context_text = prepared.context.facts_text + "\n" + prepared.context.documents_text
        best: tuple[AIAnswer, Generation, list[str]] | None = None

        for attempt in range(attempts):
            acquired = self._semaphore.acquire(timeout=settings.request_timeout_seconds)
            if not acquired:
                raise AIUnavailable("AI Analyst занят: превышен лимит одновременных генераций")
            try:
                generation = self.provider.generate(
                    system=prepared.system, user=prepared.user,
                    json_schema=prompts.ANSWER_JSON_SCHEMA,
                    num_ctx=settings.num_ctx, max_tokens=settings.max_tokens,
                    temperature=settings.temperature,
                    timeout=settings.request_timeout_seconds,
                )
            except ProviderError as exc:


                raise AIUnavailable(f"локальная модель недоступна: {exc}") from exc
            finally:
                self._semaphore.release()

            try:
                answer = AIAnswer.model_validate(parsing.parse_json(generation.text))
            except (json.JSONDecodeError, ValueError, TypeError):
                warnings.append(f"Попытка {attempt + 1}: ответ модели не прошёл разбор схемы")
                continue


            truncated = (
                generation.completion_tokens is not None
                and generation.completion_tokens >= settings.max_tokens
            )
            if truncated:
                warnings.append(
                    "Ответ модели был усечён по лимиту длины; часть полей может быть неполной."
                )

            answer, report = enforce(answer, context_text=context_text, risk_score=prepared.context.risk_score)
            if prepared.context.injection_hits:
                logger.warning("ai.rag.injection_hits=%s", prepared.context.injection_hits)
            if report.grounded:
                return answer, generation, warnings, True
            best = (answer, generation, warnings + report.warnings)

        if best is not None:
            answer, generation, collected = best
            collected.append("Модель не подтвердила часть утверждений данными; они удалены.")
            return answer, generation, collected, False
        raise AIUnavailable("модель не вернула ответ, пригодный для проверки")

    def _respond(self, prepared: _Prepared, *, task: str) -> AIResponse:
        answer, generation, warnings, grounded = self._generate(prepared)
        citations = answer.citations or _coerce_citations(prepared.context.citations)
        return AIResponse(
            task=task,
            model=generation.model,
            provider=generation.provider,
            grounded=grounded,
            warnings=warnings,
            citations=citations,
            answer=answer,
            context={
                "facts": prepared.context.facts_text,
                "documents": prepared.context.documents_text,
                "latencyMs": generation.latency_ms,
                "promptTokens": generation.prompt_tokens,
                "completionTokens": generation.completion_tokens,
                "riskScore": prepared.context.risk_score,
            },
        )


    def _guard(self) -> None:
        if not self.settings.enabled:
            raise AIDisabled("AI Analyst выключен (AEZA_AI_ENABLED=0)")

    def chat(self, *, question: str, customer_id: int | None) -> AIResponse:
        self._guard()
        self._check_question(question)
        if customer_id is not None:
            prepared = self._prepare_customer(customer_id, question, "customer_explain")
        else:
            prepared = self._prepare_portfolio(question, "chat")
        return self._respond(prepared, task="chat")

    def explain_customer(self, *, customer_id: int, question: str | None = None) -> AIResponse:
        self._guard()
        if question:
            self._check_question(question)
        prepared = self._prepare_customer(customer_id, question, "customer_explain")
        return self._respond(prepared, task="customer_explain")

    def explain_scenario(self, *, overrides: dict, question: str | None = None) -> AIResponse:
        self._guard()
        if question:
            self._check_question(question)
        prepared = self._prepare_scenario(overrides, question)
        return self._respond(prepared, task="scenario_explain")

    def report_summary(self, *, focus: str | None = None) -> AIResponse:
        self._guard()
        if focus:
            self._check_question(focus)
        prepared = self._prepare_portfolio(focus, "report_summary")
        return self._respond(prepared, task="report_summary")

    def _check_question(self, question: str) -> None:
        limit = self.settings.max_question_chars
        if len(question) > limit:
            raise InvalidInput(f"вопрос длиннее допустимых {limit} символов")
        if not question.strip():
            raise InvalidInput("вопрос не может быть пустым")


def _coerce_citations(raw: list[dict]) -> list:
    from .schemas import Citation

    return [Citation(**item) for item in raw]


def build_ai_service(storage, calculation) -> AIService:
    """Factory used by the API dependency."""

    return AIService(storage, calculation)


__all__ = ["AIService", "AIUnavailable", "AIDisabled", "build_ai_service"]
