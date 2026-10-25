"""CSV export of the current customer view.

The export is generated from the same stored payloads the API serves, so the
file and the interface cannot disagree.  Text fields are sanitised against
CSV/Excel formula injection: a value beginning with ``= + - @`` or a control
character is prefixed with an apostrophe, which spreadsheets render as literal
text rather than executing.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.app.api.deps import RuntimeDep, UserDep

router = APIRouter(tags=["export"])


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

COLUMNS = (
    "id", "email", "riskScore", "riskCategory", "riskCategoryLabel",
    "serviceCount", "eligibleServiceCount", "highRiskServiceCount", "highRiskShare",
    "balanceCents", "balanceEur", "withdrawBalanceCents", "withdrawBalanceEur",
    "bonusBalanceCents", "bonusBalanceEur", "bonusState", "totalReplenishedCents",
    "revenueAtRiskCents", "revenueAtRiskEur", "upcomingRenewalsCents",
    "overdueOperationalCents", "overdueServiceCount", "lifecycleInconsistentCount",
    "exposure7dCents", "exposure30dCents", "exposure90dCents",
    "missingData", "topReasons",
)


def _safe(value) -> str:
    """Render a cell as text, neutralising anything a spreadsheet might execute."""

    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _cents(payload: dict, key: str) -> int | None:
    field = payload.get(key)
    return field.get("cents") if isinstance(field, dict) else None


def _eur(payload: dict, key: str) -> str | None:
    field = payload.get(key)
    return field.get("eur") if isinstance(field, dict) else None


def _horizon_cents(payload: dict, days: int) -> int | None:
    for entry in payload.get("exposureByHorizon") or []:
        if entry.get("horizonDays") == days:
            return (entry.get("revenueAtRisk") or {}).get("cents")
    return None


def row_for(payload: dict) -> dict:
    return {
        "id": payload.get("id"),
        "email": payload.get("email"),
        "riskScore": payload.get("riskScore"),
        "riskCategory": payload.get("riskCategory"),
        "riskCategoryLabel": payload.get("riskCategoryLabel"),
        "serviceCount": payload.get("serviceCount"),
        "eligibleServiceCount": payload.get("eligibleServiceCount"),
        "highRiskServiceCount": payload.get("highRiskServiceCount"),
        "highRiskShare": payload.get("highRiskShare"),
        "balanceCents": _cents(payload, "balance"),
        "balanceEur": _eur(payload, "balance"),
        "withdrawBalanceCents": _cents(payload, "withdrawBalance"),
        "withdrawBalanceEur": _eur(payload, "withdrawBalance"),
        "bonusBalanceCents": _cents(payload, "bonusBalance"),
        "bonusBalanceEur": _eur(payload, "bonusBalance"),
        "bonusState": payload.get("bonusState"),
        "totalReplenishedCents": _cents(payload, "totalReplenished"),
        "revenueAtRiskCents": _cents(payload, "revenueAtRisk"),
        "revenueAtRiskEur": _eur(payload, "revenueAtRisk"),
        "upcomingRenewalsCents": _cents(payload, "upcomingRenewals"),
        "overdueOperationalCents": _cents(payload, "overdueOperational"),
        "overdueServiceCount": payload.get("overdueServiceCount"),
        "lifecycleInconsistentCount": payload.get("lifecycleInconsistentCount"),
        "exposure7dCents": _horizon_cents(payload, 7),
        "exposure30dCents": _horizon_cents(payload, 30),
        "exposure90dCents": _horizon_cents(payload, 90),
        "missingData": "; ".join(payload.get("missingData") or []),
        "topReasons": "; ".join(payload.get("topReasons") or []),
    }


@router.get("/export/customers.csv", summary="Экспорт текущей выборки клиентов в CSV")
def export_customers(
    runtime: RuntimeDep,
    user: UserDep,
    search: Annotated[str | None, Query(max_length=320)] = None,
    risk_category: Annotated[str | None, Query(alias="riskCategory")] = None,
    sort_by: Annotated[Literal["id", "email", "riskScore", "balance", "totalReplenished"], Query(alias="sortBy")] = "riskScore",
    sort_dir: Annotated[Literal["asc", "desc"], Query(alias="sortDir")] = "desc",
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=2000)] = 500,
):
    """Export the filtered, sorted selection with its calculation metadata.

    Rows are read in pages and written to the response as they arrive, so peak
    memory stays proportional to one page rather than to the whole selection.
    Buffering every row first was measured at 50 000 customers to hold ~3.5 GiB
    resident and take 40 s; streaming keeps the working set bounded.

    The row set and order come from the same storage query the list endpoint
    uses, so the file matches what the analyst sees on screen.
    """

    def page(number: int, generation: int | None = None) -> dict:
        return runtime.storage.customers(
            generation=generation, search=search, risk_category=risk_category,
            sort_by=sort_by, sort_dir=sort_dir, page=number, page_size=page_size,
        )


    first = page(1)
    generation = first["generation"]
    total = first["total"]


    summary = runtime.storage.summary(generation)

    def rows():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\r\n")
        writer.writeheader()
        yield "\ufeff" + buffer.getvalue()

        current = first
        while current["items"]:
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\r\n")
            for item in current["items"]:
                writer.writerow({key: _safe(value) for key, value in row_for(item).items()})
            yield buffer.getvalue()
            if len(current["items"]) < page_size:
                break
            current = page(current["page"] + 1, generation)

    headers = {
        "Content-Disposition": 'attachment; filename="aeza-customers.csv"',
        "X-Export-Rows": str(total),
        "X-Export-Generation": str(generation),
        "X-Export-As-Of": str(summary.get("asOf")),
        "X-Export-Engine-Version": str(summary.get("engineVersion")),
        "X-Export-Horizon-Days": str(summary.get("horizonDays")),
        "X-Export-Currency": "EUR",
    }
    return StreamingResponse(rows(), media_type="text/csv; charset=utf-8", headers=headers)
