"""AI assistance endpoints.

The AI layer is deliberately thin and read-only:

* it never writes to the database, never changes model settings and never
  triggers a recalculation;
* every number it may mention comes from the already published calculation,
  passed through :func:`backend.app.domain.llm.build_customer_context`;
* the answer is checked against that fact set before it is returned, so an
  invented figure surfaces as a 502 rather than as an authoritative-looking
  sentence.

When the provider is off or unreachable the caller gets **503** with a clear
reason. The frontend shows that message and falls back to the deterministic
explanation it already has; nothing pretends the model answered.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.deps import RuntimeDep, UserDep
from backend.app.domain import llm

router = APIRouter(prefix="/ai", tags=["ai"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, max_length=600)


@router.get("/status", summary="Доступность локальной ИИ-модели")
def status(runtime: RuntimeDep, user: UserDep):
    """Report whether the AI layer is enabled and reachable.

    The UI calls this to decide whether to offer the explanation button at all,
    so a disabled provider produces no dead button.
    """

    settings = runtime.settings
    if not settings.llm_enabled:
        return {
            "enabled": False,
            "reachable": False,
            "model": settings.llm_model,
            "provider": "ollama",
            "detail": "ИИ-объяснения отключены конфигурацией (AEZA_LLM_ENABLED=0)",
        }

    client = llm.OllamaClient(settings)
    reachable, detail = client.probe()
    return {
        "enabled": True,
        "reachable": reachable,
        "model": settings.llm_model,
        "provider": "ollama",
        "detail": detail,
    }


@router.post("/customers/{customer_id}/explain", summary="Объяснение риска клиента локальной моделью")
def explain(
    customer_id: int,
    runtime: RuntimeDep,
    user: UserDep,
    payload: AskRequest | None = None,
    generation: Annotated[int | None, Query(ge=1)] = None,
):
    """Explain one customer's risk using the local model, grounded in the calculation.

    Read-only: the stored snapshot, the settings and the published generation are
    untouched. The model receives only the whitelisted fact set for this one
    customer.
    """

    detail = runtime.storage.customer(customer_id, generation)
    state = runtime.storage.load()
    settings = runtime.settings
    horizon_days = (state.settings or {}).get("horizonDays") or _horizon_of(detail)

    try:
        answer = llm.explain_customer(
            detail,
            settings=settings,
            as_of=state.as_of.isoformat() if state.as_of else None,
            horizon_days=horizon_days,
            question=(payload.question if payload else None),
        )
    except llm.LlmUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except llm.LlmUngrounded as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Ответ модели отклонён: он содержит данные, которых нет в расчёте "
                f"({'; '.join(exc.violations[:3])}). Ничего не показано, чтобы не "
                "выдавать вымысел за расчёт."
            ),
        ) from exc
    except llm.LlmBadResponse as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "customerId": customer_id,
        "generation": detail.get("generation"),
        "text": answer.text,
        "model": answer.model,
        "provider": answer.provider,
        "grounded": True,
        "note": (
            "Текст сгенерирован локальной моделью на основе расчёта Aéza Sentinel. "
            "Числа и факторы взяты из расчёта и проверены; модель не является "
            "источником данных и не изменяет настройки или снимок."
        ),
    }


def _horizon_of(detail: dict) -> int:
    """Best-effort horizon for the prompt, taken from the customer's exposure list."""

    horizons = [entry.get("horizonDays") for entry in detail.get("exposureByHorizon") or []]
    horizons = [h for h in horizons if isinstance(h, int)]
    return 30 if not horizons else horizons[0]
