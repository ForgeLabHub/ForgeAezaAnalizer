import type {
  AiExplanation,
  AiStatus,
  CustomerDetail,
  CustomerPage,
  ModelSettings,
  PlaybookList,
  PlaybookUpdate,
  RecommendationState,
  PriorityView,
  QualityReport,
  ScenarioComparison,
  Summary,
} from '../types'

const TOKEN_KEY = 'aeza.token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init.headers as Record<string, string>) ?? {}),
  }
  if (init.body) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(path, { ...init, headers })
  } catch {
    throw new ApiError(0, 'Не удалось связаться с сервером. Проверьте, что API запущен.')
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : `Ошибка запроса (${response.status})`
    throw new ApiError(response.status, detail)
  }

  return payload as T
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string; expires_in: number }>(
      '/api/v1/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password }) },
    ),

  me: () => request<{ email: string }>('/api/v1/auth/me'),

  logout: () => request<void>('/api/v1/auth/logout', { method: 'POST' }),

  summary: () => request<Summary>('/api/v1/analytics/summary'),

  customers: (params: {
    search?: string
    riskCategory?: string
    serviceStatus?: string
    sortBy: string
    sortDir: 'asc' | 'desc'
    page: number
    pageSize: number
  }) => {
    const query = new URLSearchParams()
    if (params.search) query.set('search', params.search)
    if (params.riskCategory) query.set('riskCategory', params.riskCategory)
    if (params.serviceStatus) query.set('serviceStatus', params.serviceStatus)
    query.set('sortBy', params.sortBy)
    query.set('sortDir', params.sortDir)
    query.set('page', String(params.page))
    query.set('pageSize', String(params.pageSize))
    return request<CustomerPage>(`/api/v1/customers?${query.toString()}`)
  },

  customer: (id: number) => request<CustomerDetail>(`/api/v1/customers/${id}`),

  /** Playbooks for one customer, each with its stored workflow status. */
  playbooks: (id: number) => request<PlaybookList>(`/api/v1/customers/${id}/recommendations`),

  /**
   * Move one playbook to a new status. Only the addressed (customer, code)
   * pair changes; the backend rejects an unknown code or status.
   */
  setPlaybookStatus: (id: number, code: string, status: RecommendationState) =>
    request<PlaybookUpdate>(
      `/api/v1/customers/${id}/recommendations/${encodeURIComponent(code)}`,
      { method: 'PATCH', body: JSON.stringify({ status }) },
    ),

  modelSettings: () => request<ModelSettings>('/api/v1/model/settings'),

  patchSettings: (patch: Record<string, unknown>) =>
    request<ModelSettings>('/api/v1/model/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  resetSettings: () =>
    request<ModelSettings>('/api/v1/model/settings/reset', { method: 'POST' }),

  /** Audit of the raw snapshot. Read-only: it never modifies a record. */
  quality: () => request<QualityReport>('/api/v1/quality'),

  /** Work queues. The four measurements stay separate; categories carry no probability. */
  priority: (params: { horizonDays?: number; category?: string; sortBy?: string; sortDir?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.horizonDays) query.set('horizonDays', String(params.horizonDays))
    if (params.category) query.set('category', params.category)
    if (params.sortBy) query.set('sortBy', params.sortBy)
    if (params.sortDir) query.set('sortDir', params.sortDir)
    const suffix = query.toString()
    return request<PriorityView>(`/api/v1/priority${suffix ? `?${suffix}` : ''}`)
  },

  /**
   * Evaluate alternative parameters without touching the working configuration.
   * The server returns baseline and scenario side by side; nothing is persisted.
   */
  compareScenario: (name: string, overrides: Record<string, unknown>) =>
    request<ScenarioComparison>('/api/v1/scenarios/compare', {
      method: 'POST',
      body: JSON.stringify({ name, overrides }),
    }),

  /**
   * Whether the local LLM layer is enabled and reachable.
   *
   * The customer page calls this before offering the explanation button, so a
   * disabled or unreachable provider produces an explanatory notice instead of
   * a button that would always fail.
   */
  aiStatus: () => request<AiStatus>('/api/v1/ai/status'),

  /**
   * Ask the local model to explain one customer, grounded in the calculation.
   *
   * Read-only: the backend sends only this customer's whitelisted facts and
   * verifies every number in the answer against them. A 503 means the provider
   * is unavailable; a 502 means the answer was rejected as ungrounded.
   */
  aiExplain: (id: number, question?: string) =>
    request<AiExplanation>(`/api/v1/ai/customers/${id}/explain`, {
      method: 'POST',
      body: JSON.stringify(question ? { question } : {}),
    }),

  /** URL for the CSV export of the current selection, so the browser can download it. */
  exportUrl: (params: { search?: string; riskCategory?: string; sortBy?: string; sortDir?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.search) query.set('search', params.search)
    if (params.riskCategory) query.set('riskCategory', params.riskCategory)
    if (params.sortBy) query.set('sortBy', params.sortBy)
    if (params.sortDir) query.set('sortDir', params.sortDir)
    const suffix = query.toString()
    return `/api/v1/export/customers.csv${suffix ? `?${suffix}` : ''}`
  },
}

/**
 * The export endpoint needs the bearer token, so a plain link cannot fetch it.
 * This downloads through fetch and hands the blob to the browser.
 */
export async function downloadExport(params: Parameters<typeof api.exportUrl>[0] = {}) {
  const token = getToken()
  const response = await fetch(api.exportUrl(params), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw new ApiError(response.status, 'Не удалось сформировать экспорт')
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'aeza-customers.csv'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
  return Number(response.headers.get('X-Export-Rows') ?? 0)
}
