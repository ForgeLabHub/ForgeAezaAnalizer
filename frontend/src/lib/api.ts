import type {
  CustomerDetail,
  CustomerPage,
  ModelSettings,
  PriorityResponse,
  QualityReport,
  ScenarioResult,
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

  modelSettings: () => request<ModelSettings>('/api/v1/model/settings'),

  priority: (params: {
    horizonDays?: number
    category?: string
    sortBy?: 'urgency' | 'riskScore' | 'exposure' | 'id'
    sortDir?: 'asc' | 'desc'
  } = {}) => {
    const query = new URLSearchParams()
    if (params.horizonDays) query.set('horizonDays', String(params.horizonDays))
    if (params.category) query.set('category', params.category)
    if (params.sortBy) query.set('sortBy', params.sortBy)
    if (params.sortDir) query.set('sortDir', params.sortDir)
    const suffix = query.toString()
    return request<PriorityResponse>(`/api/v1/priority${suffix ? `?${suffix}` : ''}`)
  },

  quality: () => request<QualityReport>('/api/v1/quality'),

  compareScenario: (overrides: Record<string, unknown>, name = 'Custom') =>
    request<ScenarioResult>('/api/v1/scenarios/compare', {
      method: 'POST',
      body: JSON.stringify({ name, overrides }),
    }),

  patchSettings: (patch: Record<string, unknown>) =>
    request<ModelSettings>('/api/v1/model/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  resetSettings: () =>
    request<ModelSettings>('/api/v1/model/settings/reset', { method: 'POST' }),
}
