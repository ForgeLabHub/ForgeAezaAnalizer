from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

RiskCategory = Literal["low", "medium", "high", "insufficient_data", "not_applicable"]
RiskScore = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Weight = Annotated[float, Field(strict=True, ge=0, le=1000, allow_inf_nan=False)]


class Output(BaseModel):
    model_config = ConfigDict(extra="allow")


class Money(Output):
    cents: Annotated[int, Field(strict=True)] | None
    eur: str | None

    @model_validator(mode="after")
    def units(self):
        if self.cents is None:
            if self.eur is not None:
                raise ValueError("unknown cents require unknown eur")
        else:
            sign = "-" if self.cents < 0 else ""
            absolute = abs(self.cents)
            expected = f"{sign}{absolute // 100}.{absolute % 100:02d}"
            if self.eur != expected:
                raise ValueError("eur must represent cents exactly")
        return self


class Version(Output):
    generation: int
    sourceVersion: int
    modelVersion: int
    capturedAt: str | None
    asOf: str | None
    calculatedAt: str | None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    email: str


class FactorInfo(Output):
    key: str
    label: str
    description: str
    howComputed: str
    normalization: str
    defaultWeight: Weight
    missingDataBehaviour: str


class SettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizonDays: Annotated[int, Field(strict=True, ge=1, le=365)]
    weights: dict[str, Weight]
    lowMax: Annotated[int, Field(strict=True, ge=0, le=99)]
    mediumMax: Annotated[int, Field(strict=True, ge=1, le=100)]

    @model_validator(mode="after")
    def thresholds(self):
        if self.lowMax >= self.mediumMax:
            raise ValueError("lowMax must be below mediumMax")
        return self


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizonDays: Annotated[int, Field(strict=True, ge=1, le=365)] | None = None
    weights: dict[str, Weight] | None = None
    lowMax: Annotated[int, Field(strict=True, ge=0, le=99)] | None = None
    mediumMax: Annotated[int, Field(strict=True, ge=1, le=100)] | None = None
    expectedGeneration: Annotated[int, Field(strict=True, ge=0)] | None = None

    @model_validator(mode="after")
    def no_null(self):
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("supplied settings cannot be null")
        return self


class ModelSettingsResponse(Version):
    settings: SettingsPayload
    factors: list[FactorInfo]
    updatedAt: str | None
    isDefault: bool


class FactorResult(Output):
    key: str
    label: str
    value: float | None = Field(allow_inf_nan=False)
    weight: float = Field(ge=0, allow_inf_nan=False)
    contribution: float = Field(allow_inf_nan=False)
    available: bool
    reason: str


class Recommendation(Output):
    code: str
    title: str
    detail: str
    priority: int


class ServiceItem(Output):
    id: int
    name: str
    status: str
    statusLabel: str
    paymentTerm: str | None
    paymentTermLabel: str
    autoProlong: bool | None
    createdAt: str | None
    expiresAt: str | None
    daysToExpiry: float | None = Field(allow_inf_nan=False)
    price: Money
    riskScore: RiskScore | None
    riskCategory: RiskCategory
    riskCategoryLabel: str
    eligibleForForecast: bool
    stateNote: str
    reasons: list[str]
    missingData: list[str]
    factors: list[FactorResult]
    revenueAtRisk: Money | None
    upcomingRenewalAt: str | None
    recommendations: list[Recommendation]


class CustomerSummary(Output):
    id: int
    email: str
    balance: Money
    withdrawBalance: Money
    totalReplenished: Money
    bonusBalance: Money
    bonusState: str | None
    riskScore: RiskScore | None
    riskCategory: RiskCategory
    riskCategoryLabel: str
    serviceCount: int
    eligibleServiceCount: int
    highRiskServiceCount: int
    concludedStates: dict[str, int]
    stateNote: str
    revenueAtRisk: Money
    upcomingRenewals: Money
    topReasons: list[str]
    missingData: list[str]


class RenewalDetail(Output):
    serviceId: int
    renewalAt: str
    amount: Money
    riskScore: RiskScore
    revenueAtRisk: Money


class CustomerDetail(CustomerSummary):
    reasons: list[str]
    services: list[ServiceItem]
    recommendations: list[Recommendation]
    renewalDetails: list[RenewalDetail]


class PublishedCustomerDetail(CustomerDetail, Version):
    pass


class CustomerPage(Version):
    items: list[CustomerSummary]
    page: int
    pageSize: int
    total: int
    pages: int
    sortBy: str
    sortDir: str


class CustomerCounts(Output):
    total: int
    byCategory: dict[RiskCategory, int]
    highRisk: int
    mediumRisk: int
    insufficientData: int
    withRevenueAtRisk: int


class ServiceCounts(Output):
    total: int
    open: int
    concluded: int
    byStatus: dict[str, int]
    highRisk: int


class RevenueSummary(Output):
    revenueAtRiskCents: Annotated[int, Field(strict=True)]
    revenueAtRiskEur: str
    upcomingRenewalsCents: Annotated[int, Field(strict=True)]
    upcomingRenewalsEur: str
    historicalReplenishedCents: Annotated[int, Field(strict=True)]
    historicalReplenishedEur: str

    @model_validator(mode="after")
    def units(self):
        for prefix in ("revenueAtRisk", "upcomingRenewals", "historicalReplenished"):
            Money(cents=getattr(self, prefix + "Cents"), eur=getattr(self, prefix + "Eur"))
        return self


class RiskReason(Output):
    label: str
    count: int


class UpcomingRenewal(Output):
    customerId: int
    serviceId: int
    serviceName: str
    renewalAt: str
    amountCents: int
    amountEur: str
    riskScore: RiskScore
    riskCategory: RiskCategory
    revenueAtRiskEur: str


class ModelInfo(Output):
    type: str
    calibrated: bool
    note: str


class Summary(Output):
    generatedAt: str
    horizonDays: int
    customers: CustomerCounts
    services: ServiceCounts
    revenue: RevenueSummary
    topRiskReasons: list[RiskReason]
    upcomingRenewals: list[UpcomingRenewal]
    historyAvailable: bool
    historyNote: str
    model: ModelInfo


class PublishedSummary(Summary, Version):
    pass


class SourceInfo(Version):
    counts: dict[str, int]
    capturedAt: str


class SourceAccepted(Version):
    snapshot: dict[str, int | str]
    report: dict


class ErrorResponse(BaseModel):
    detail: str
    errors: list[dict] | None = None
