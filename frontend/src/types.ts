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

export interface ModelSettings {
  settings: {
    horizonDays: number
    weights: Record<string, number>
    lowMax: number
    mediumMax: number
  }
  factors: FactorInfo[]
  updatedAt: string | null
  isDefault: boolean
}
