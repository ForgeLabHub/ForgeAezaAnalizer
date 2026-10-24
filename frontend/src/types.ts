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
  generation?: number
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

export interface ModelSettings {
  settings: {
    horizonDays: number
    weights: Record<string, number>
    lowMax: number
    mediumMax: number
    /**
     * Trailing window for failed renewals. `null` means "the whole snapshot",
     * which is a valid configuration, not a missing value.
     */
    failedRenewalWindowDays?: number | null
  }
  factors: FactorInfo[]
  updatedAt: string | null
  isDefault: boolean
}

// ---------------------------------------------------------------- insights

export type QualityLevel = 'critical' | 'warning' | 'info'

export interface QualityIssue {
  level: QualityLevel
  code: string
  message: string
  count: number
  records: number[]
  action: string
}

export interface QualityReport {
  levels: Record<QualityLevel, string>
  issues: QualityIssue[]
  counts: Record<QualityLevel, number>
  recordsInspected: { accounts: number; services: number; transactions: number }
  note: string
  asOf?: string | null
}

/** Work queues. These organise attention and carry no probability. */
export type PriorityCategory =
  | 'operational_attention'
  | 'high_risk_with_exposure'
  | 'high_risk_review'
  | 'data_quality_review'
  | 'normal_review'

export interface PriorityItem {
  id: number
  email: string | null
  riskScore: number | null
  riskCategory: RiskCategory
  serviceCount: number | null
  highRiskServiceCount: number | null
  highRiskShare: number | null
  revenueAtRiskOnHorizon: Money | null
  upcomingRenewalsOnHorizon: Money | null
  overdueOperational: Money | null
  overdueServiceCount: number | null
  lifecycleInconsistentCount: number | null
  categories: PriorityCategory[]
  urgencyRank: number
}

export interface PriorityView {
  horizonDays: number
  total: number
  categories: Record<PriorityCategory, string>
  qualityCounts: Record<QualityLevel, number>
  items: PriorityItem[]
  note: string
}

export interface MetricChange {
  baseline: number | null
  scenario: number | null
  absolute: number | null
  /** Null when the baseline is zero: a relative change would be undefined. */
  relative: number | null
}

export interface ScenarioCustomerChange {
  id: number
  email: string | null
  scoreBefore: number | null
  scoreAfter: number | null
  categoryBefore: RiskCategory
  categoryAfter: RiskCategory
  categoryChanged: boolean
  revenueAtRiskBefore: number | null
  revenueAtRiskAfter: number | null
}

export interface FactorAvailabilityChange {
  availableBefore: number
  availableAfter: number
  unknownBefore: number
  unknownAfter: number
  becameUnknown: number
  becameAvailable: number
}

export interface ScenarioComparison {
  name: string
  baselineSettings: Record<string, unknown>
  scenarioSettings: Record<string, unknown>
  appliedOverrides: Record<string, unknown>
  allowedParameters: string[]
  asOf: string | null
  baseline: Summary
  scenario: Summary
  comparison: {
    horizonDays: MetricChange
    revenueAtRiskCents: MetricChange
    upcomingRenewalsCents: MetricChange
    highRiskCustomers: MetricChange
    mediumRiskCustomers: MetricChange
    highRiskServices: MetricChange
    categories: Record<string, MetricChange>
    note: string
  }
  customers: ScenarioCustomerChange[]
  factorAvailability: Record<string, FactorAvailabilityChange>
  note: string
}

// ------------------------------------------------------- retention playbooks

export type RecommendationState = 'new' | 'in_progress' | 'done'

export interface PlaybookItem {
  code: string
  title: string
  detail: string
  priority: number
  status: RecommendationState
  statusUpdatedAt: string | null
  statusUpdatedBy: string | null
}

export interface PlaybookList {
  customerId: number
  items: PlaybookItem[]
  statuses: RecommendationState[]
  note: string
}

export interface PlaybookUpdate {
  customerId: number
  code: string
  status: RecommendationState
  updatedAt: string
  updatedBy: string
  note: string
}
