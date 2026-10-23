export interface Money {
  cents: number
  eur: string
}

export type RiskCategory =
  | 'low'
  | 'medium'
  | 'high'
  | 'insufficient_data'
  | 'not_applicable'

export interface FactorResult {
  key: string
  label: string
  value: number | null
  weight: number
  contribution: number
  available: boolean
  reason: string
}

export interface Recommendation {
  code: string
  title: string
  detail: string
  priority: number
}

export interface ServiceItem {
  id: number
  name: string
  status: string
  statusLabel: string
  paymentTerm: string
  paymentTermLabel: string
  autoProlong: boolean
  createdAt: string
  expiresAt: string
  daysToExpiry: number | null
  price: Money
  riskScore: number | null
  riskCategory: RiskCategory
  riskCategoryLabel: string
  eligibleForForecast: boolean
  stateNote: string
  reasons: string[]
  missingData: string[]
  factors: FactorResult[]
  revenueAtRisk: Money | null
  upcomingRenewalAt: string | null
  recommendations: Recommendation[]
}

export interface CustomerSummary {
  id: number
  email: string
  balance: Money
  withdrawBalance: Money
  totalReplenished: Money
  bonusBalance: Money
  bonusState: string
  riskScore: number | null
  riskCategory: RiskCategory
  riskCategoryLabel: string
  serviceCount: number
  eligibleServiceCount: number
  highRiskServiceCount: number
  concludedStates: Record<string, number>
  stateNote: string
  revenueAtRisk: Money
  upcomingRenewals: Money
  topReasons: string[]
  missingData: string[]
}

export interface CustomerDetail extends CustomerSummary {
  reasons: string[]
  services: ServiceItem[]
  recommendations: Recommendation[]
  renewalDetails: Array<{
    serviceId: number
    renewalAt: string
    amount: Money
    riskScore: number
    revenueAtRisk: Money
  }>
}

export interface CustomerPage {
  items: CustomerSummary[]
  page: number
  pageSize: number
  total: number
  pages: number
  sortBy: string
  sortDir: string
}

export interface Summary {
  generatedAt: string
  horizonDays: number
  customers: {
    total: number
    byCategory: Record<RiskCategory, number>
    highRisk: number
    mediumRisk: number
    insufficientData: number
    withRevenueAtRisk: number
  }
  services: {
    total: number
    open: number
    concluded: number
    byStatus: Record<string, number>
    highRisk: number
  }
  revenue: {
    revenueAtRiskEur: string
    revenueAtRiskCents: number
    upcomingRenewalsEur: string
    upcomingRenewalsCents: number
    historicalReplenishedEur: string
    historicalReplenishedCents: number
  }
  topRiskReasons: Array<{ label: string; count: number }>
  upcomingRenewals: Array<{
    customerId: number
    serviceId: number
    serviceName: string
    renewalAt: string
    amountCents: number
    amountEur: string
    riskScore: number
    riskCategory: RiskCategory
    revenueAtRiskEur: string
  }>
  historyAvailable: boolean
  historyNote: string
  model: { type: string; calibrated: boolean; note: string }
}

export interface FactorInfo {
  key: string
  label: string
  description: string
  howComputed: string
  normalization: string
  defaultWeight: number
  missingDataBehaviour: string
}

export interface PriorityExposure {
  cents: number
  eur: string
}

/** One row of the retention worklist. Risk, exposure, urgency and data quality
 *  are four separate measurements; ``categories`` groups work without
 *  collapsing them into a single number. */
export interface PriorityItem {
  id: number
  email: string
  riskScore: number | null
  riskCategory: RiskCategory
  serviceCount: number
  highRiskServiceCount: number
  highRiskShare: number | null
  revenueAtRiskOnHorizon: PriorityExposure | null
  upcomingRenewalsOnHorizon: PriorityExposure | null
  overdueOperational: PriorityExposure | null
  overdueServiceCount: number
  lifecycleInconsistentCount: number
  categories: string[]
  urgencyRank: number
}

export interface PriorityResponse {
  horizonDays: number
  total: number
  categories: Record<string, string>
  qualityCounts: Record<string, number>
  items: PriorityItem[]
  note: string
}

/** One measured quantity inside a scenario comparison. */
export interface ScenarioMeasure {
  baseline: number
  scenario: number
  absolute: number
  relative: number | null
}

export interface ScenarioCustomerChange {
  id: number
  email: string
  scoreBefore: number | null
  scoreAfter: number | null
  categoryBefore: RiskCategory
  categoryAfter: RiskCategory
  categoryChanged: boolean
  revenueAtRiskBefore: number
  revenueAtRiskAfter: number
}

export interface ScenarioComparison {
  horizonDays: ScenarioMeasure
  revenueAtRiskCents: ScenarioMeasure
  upcomingRenewalsCents: ScenarioMeasure
  highRiskCustomers: ScenarioMeasure
  mediumRiskCustomers: ScenarioMeasure
  highRiskServices: ScenarioMeasure
  categories: Record<string, ScenarioMeasure>
  note?: string
  [key: string]: ScenarioMeasure | Record<string, ScenarioMeasure> | string | undefined
}

export interface ScenarioResult {
  name: string
  baselineSettings: ModelSettings['settings']
  scenarioSettings: ModelSettings['settings']
  appliedOverrides: Record<string, unknown>
  allowedParameters: string[]
  asOf: string | null
  baseline: Summary
  scenario: Summary
  comparison: ScenarioComparison
  customers: ScenarioCustomerChange[]
  factorAvailability: unknown
  note: string
}

export interface ModelSettings {
  settings: {
    horizonDays: number
    weights: Record<string, number>
    lowMax: number
    mediumMax: number
    failedRenewalWindowDays?: number | null
  }
  factors: FactorInfo[]
  updatedAt: string | null
  isDefault: boolean
}

export interface QualityIssue {
  level: 'critical' | 'warning' | 'info'
  code: string
  message: string
  count: number
  records: number[]
  action: string
}

export interface QualityReport {
  levels: Record<string, string>
  issues: QualityIssue[]
  counts: Record<string, number>
  recordsInspected: number
  note: string
  asOf: string | null
}
