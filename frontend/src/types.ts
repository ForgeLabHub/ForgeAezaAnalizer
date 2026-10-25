export interface Money {
  cents: number | null
  eur: string | null
}

export interface VersionInfo {
  generation: number
  sourceVersion: number
  modelVersion: number
  capturedAt: string | null
  asOf: string | null
  calculatedAt: string | null
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
  deprecated?: boolean
}

export interface Recommendation {
  code: string
  title: string
  detail: string
  priority: number
}

export interface HorizonExposureItem {
  horizonDays: number
  renewalCount: number
  upcomingRenewals: Money
  revenueAtRisk: Money
}

export interface OverdueDetailItem {
  serviceId: number
  status: string
  statusLabel?: string
  expiredAt: string
  daysOverdue: number
  amount: Money
  lifecycleInconsistent: boolean
}

export interface ServiceItem {
  id: number
  name: string
  status: string
  statusLabel: string
  paymentTerm: string | null
  paymentTermLabel: string
  autoProlong: boolean | null
  createdAt: string | null
  expiresAt: string | null
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
  bonusState: string | null
  riskScore: number | null
  riskCategory: RiskCategory
  riskCategoryLabel: string
  serviceCount: number
  eligibleServiceCount: number
  highRiskServiceCount: number
  highRiskShare?: number
  overdueServiceCount?: number
  concludedStates: Record<string, number>
  stateNote: string
  revenueAtRisk: Money
  upcomingRenewals: Money
  overdueOperational?: Money
  lifecycleInconsistentCount?: number
  exposureByHorizon?: HorizonExposureItem[]
  topReasons: string[]
  missingData: string[]
}

export interface CustomerDetail extends CustomerSummary, Partial<VersionInfo> {
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
  overdueDetails?: OverdueDetailItem[]
}

export interface CustomerPage extends Partial<VersionInfo> {
  items: CustomerSummary[]
  page: number
  pageSize: number
  total: number
  pages: number
  sortBy: string
  sortDir: string
}

export interface Summary extends Partial<VersionInfo> {
  generatedAt: string
  horizonDays: number
  engineVersion?: string
  version?: VersionInfo
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
  deprecated?: boolean
}

export interface SettingsPayload {
  horizonDays: number
  weights: Record<string, number>
  lowMax: number
  mediumMax: number
  failedRenewalWindowDays: number | null
}

export interface SettingsPatch {
  horizonDays?: number
  weights?: Record<string, number>
  lowMax?: number
  mediumMax?: number
  failedRenewalWindowDays?: number | null
  expectedGeneration?: number
}

export interface ModelSettings extends Partial<VersionInfo> {
  settings: SettingsPayload
  factors: FactorInfo[]
  updatedAt: string | null
  isDefault: boolean
}

export type AIStatusValue = 'disabled' | 'ready' | 'unavailable'

export interface AIStatus {
  status: AIStatusValue
  provider: string
  model: string
  enabled: boolean
  reason: string
  reachable: boolean
  rag_indexed: boolean
  rag_chunks: number
}

export interface AICitation {
  kind: 'fact' | 'document'
  source: string
  detail: string
}

export interface AIAnswer {
  summary: string
  facts: string[]
  factor_explanation: string
  recommendations: string[]
  limitations: string
  citations: AICitation[]
}

export interface AIResponse {
  task: 'chat' | 'customer_explain' | 'scenario_explain' | 'report_summary'
  model: string
  provider: string
  grounded: boolean
  warnings: string[]
  citations: AICitation[]
  answer: AIAnswer
  context: {
    facts?: string
    documents?: string
    latencyMs?: number
    completionTokens?: number | null
    riskScore?: number | null
  }
}

export type SupportConversationStatus = 'open' | 'closed'
export type SupportDeliveryStatus = 'received' | 'pending' | 'delivered' | 'failed' | 'stubbed'

export interface ClientSession {
  accessToken: string
  tokenType: string
  expiresIn: number
}

export interface ClientMe {
  telegramUserId: string
  accountId: number
  email: string
  notificationsEnabled: boolean
}

export interface ClientAccount {
  id: number
  email: string
  balance: { cents: number | null; eur: string | null }
}

export interface ClientService {
  id: number
  name: string
  status: string
  autoProlong: boolean | null
  expiresAt: string | null
  price: { cents: number | null; eur: string | null }
}

export interface ClientServices {
  accountId: number
  items: ClientService[]
}

export interface ClientSupportMessage {
  id: number
  conversationId: number
  sender: 'client' | 'analyst'
  text: string
  deliveryStatus: SupportDeliveryStatus
  deliveryError: string | null
  createdAt: string
  deliveredAt: string | null
}

export interface ClientSupport {
  conversation: { id: number; accountId: number; status: SupportConversationStatus; createdAt: string; updatedAt: string } | null
  items: ClientSupportMessage[]
}

export interface ClientSupportSend {
  conversation: { id: number; accountId: number; status: SupportConversationStatus; createdAt: string; updatedAt: string }
  message: ClientSupportMessage
}

export interface SupportConversation {
  id: number
  accountId: number
  email: string
  status: SupportConversationStatus
  createdAt: string
  updatedAt: string
}

export interface SupportMessage {
  id: number
  conversationId: number
  sender: 'client' | 'analyst'
  text: string
  deliveryStatus: SupportDeliveryStatus
  deliveryError: string | null
  createdAt: string
  deliveredAt: string | null
}

export interface SupportConversationMessages {
  conversation: Omit<SupportConversation, 'email'>
  items: SupportMessage[]
}

export type ActionStatus = 'open' | 'in_progress' | 'done' | 'dismissed'

export interface RetentionAction {
  id: number
  customerId: number
  serviceId: number | null
  code: string
  title: string
  detail: string
  status: ActionStatus
  note: string | null
  generation: number
  createdBy: string
  createdAt: string
  updatedAt: string
}

export interface RetentionActionList {
  items: RetentionAction[]
  statuses: ActionStatus[]
  note: string
}
export interface SourceInfo extends VersionInfo {
  counts: {
    accounts?: number
    services?: number
    transactions?: number
    [key: string]: number | undefined
  }
  capturedAt: string
}

export interface SourceAccepted extends VersionInfo {
  snapshot: {
    status: string
    accounts?: number
    services?: number
    transactions?: number
    [key: string]: number | string | undefined
  }
  report: {
    status: string
    accepted: Record<string, number>
    rejected: number
    duplicates: number
    previous: Record<string, number>
    message: string
  }
}

export interface ObservationItem {
  sourceVersion: number
  serviceId: number
  previousStatus: string | null
  status: string | null
  observedAt: string
  previousObservedAt: string | null
  eventAt: string | null
}

export interface ObservationsResponse {
  items: ObservationItem[]
  note: string
}

export type QualitySeverity = 'critical' | 'warning' | 'info'

export interface QualityIssue {
  level: QualitySeverity
  code: string
  message: string
  count: number
  records: number[]
  action: string
}

export interface QualityReport {
  asOf: string | null
  levels: Record<QualitySeverity, string>
  issues: QualityIssue[]
  counts: Record<QualitySeverity, number>
  recordsInspected: {
    accounts: number
    services: number
    transactions: number
  }
  note: string
}

export type PriorityCategoryKey =
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
  serviceCount: number
  highRiskServiceCount: number
  highRiskShare: number | null
  revenueAtRiskOnHorizon: Money | null
  upcomingRenewalsOnHorizon: Money | null
  overdueOperational: Money | null
  overdueServiceCount: number | null
  lifecycleInconsistentCount: number | null
  categories: PriorityCategoryKey[]
  urgencyRank: number
}

export interface PriorityResponse {
  horizonDays: number
  total: number
  categories: Record<string, string>
  qualityCounts: {
    critical: number
    warning: number
    info: number
  }
  items: PriorityItem[]
  note: string
}

export interface MetricDelta {
  baseline: number | null
  scenario: number | null
  absolute: number | null
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

export interface FactorAvailabilityShift {
  availableBefore: number
  availableAfter: number
  unknownBefore: number
  unknownAfter: number
  becameUnknown: number
  becameAvailable: number
}

export interface ScenarioOverrides {
  horizonDays?: number
  weights?: Record<string, number>
  lowMax?: number
  mediumMax?: number
  failedRenewalWindowDays?: number | null
}

export interface ScenarioComparisonResponse {
  name: string
  baselineSettings: SettingsPayload
  scenarioSettings: SettingsPayload
  appliedOverrides: Record<string, unknown>
  allowedParameters: string[]
  asOf: string | null
  baseline: Summary
  scenario: Summary
  comparison: {
    horizonDays: MetricDelta
    revenueAtRiskCents: MetricDelta
    upcomingRenewalsCents: MetricDelta
    highRiskCustomers: MetricDelta
    mediumRiskCustomers: MetricDelta
    highRiskServices: MetricDelta
    categories: Record<string, MetricDelta>
    note: string
  }
  customers: ScenarioCustomerChange[]
  factorAvailability: Record<string, FactorAvailabilityShift>
  note: string
}

export interface ValidationIssue {
  loc: Array<string | number>
  msg: string
  type: string
}

export interface CsvExportResult {
  blob: Blob
  filename: string
  rows: number | null
  asOf: string | null
  engineVersion: string | null
  horizonDays: number | null
}
