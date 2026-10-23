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
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from backend.app.api.deps import RuntimeDep, UserDep

router = APIRouter(tags=["export"])

#: Characters that make a spreadsheet treat a cell as a formula.
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
):
    """Export the filtered, sorted selection with its calculation metadata.

    The row set and order come from the same storage query the list endpoint
    uses, so the file matches what the analyst sees on screen.
    """

    page = runtime.storage.customers(
        search=search, risk_category=risk_category, sort_by=sort_by, sort_dir=sort_dir,
        page=1, page_size=100_000,
    )
    summary = runtime.storage.summary()

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\r\n")
    writer.writeheader()
    for item in page["items"]:
        writer.writerow({key: _safe(value) for key, value in row_for(item).items()})

    metadata = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "asOf": summary.get("asOf"),
        "generation": summary.get("generation"),
        "engineVersion": summary.get("engineVersion"),
        "horizonDays": summary.get("horizonDays"),
        "currency": "EUR",
        "moneyUnit": "eurocents",
        "rows": len(page["items"]),
        "filters": {"search": search, "riskCategory": risk_category,
                    "sortBy": sort_by, "sortDir": sort_dir},
    }

    # Metadata travels in headers so the CSV body stays a clean table that any
    # spreadsheet can open without skipping a preamble.
    headers = {
        "Content-Disposition": 'attachment; filename="aeza-customers.csv"',
        "X-Export-Rows": str(metadata["rows"]),
        "X-Export-As-Of": str(metadata["asOf"]),
        "X-Export-Engine-Version": str(metadata["engineVersion"]),
        "X-Export-Horizon-Days": str(metadata["horizonDays"]),
        "X-Export-Currency": metadata["currency"],
    }
    # A UTF-8 BOM keeps Cyrillic intact in Excel.
    body = "\ufeff" + buffer.getvalue()
    return Response(content=body, media_type="text/csv; charset=utf-8", headers=headers)
