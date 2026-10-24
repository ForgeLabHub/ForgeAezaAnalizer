import type {
  AIResponse,
  AIStatus,
  ActionStatus,
  CsvExportResult,
  CustomerDetail,
  CustomerPage,
  ModelSettings,
  ObservationsResponse,
  PriorityResponse,
  QualityReport,
  RetentionAction,
  RetentionActionList,
  ScenarioComparisonResponse,
  ScenarioOverrides,
  SettingsPatch,
  SourceAccepted,
  SourceInfo,
  Summary,
  ValidationIssue,
  VersionInfo,
} from '../types'

const TOKEN_KEY = 'aeza.token'
let accessToken: string | null = null
let refreshRequest: Promise<string | null> | null = null

try {
  localStorage.removeItem(TOKEN_KEY)
} catch {
  // Storage may be unavailable in restricted browser contexts.
}

export function getToken(): string | null {
  return accessToken
}

export function setToken(token: string | null) {
  accessToken = token
}

type UnauthorizedListener = () => void
type GenerationListener = (generation: number) => void

let unauthorizedListener: UnauthorizedListener | null = null
let generationListener: GenerationListener | null = null

export function setUnauthorizedListener(listener: UnauthorizedListener | null) {
  unauthorizedListener = listener
}

export function setGenerationListener(listener: GenerationListener | null) {
  generationListener = listener
}

export class ApiError extends Error {
  status: number
  detail: string
  errors?: ValidationIssue[]

  constructor(status: number, detail: string, errors?: ValidationIssue[]) {
    super(detail)
    this.status = status
    this.detail = detail
    this.errors = errors
  }
}

function parseErrorPayload(status: number, payload: unknown): ApiError {
  if (payload && typeof payload === 'object') {
    const obj = payload as { detail?: unknown; errors?: unknown }
    const detail = obj.detail !== undefined ? String(obj.detail) : `Ошибка запроса (${status})`
    const errors = Array.isArray(obj.errors) ? (obj.errors as ValidationIssue[]) : undefined
    return new ApiError(status, detail, errors)
  }
  return new ApiError(status, `Ошибка запроса (${status})`)
}

function notifyGenerationFromResponse(response: Response) {
  const header = response.headers.get('X-Analysis-Generation')
  if (header && generationListener) {
    const gen = Number(header)
    if (Number.isInteger(gen) && gen >= 1) {
      generationListener(gen)
    }
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init.headers as Record<string, string>) ?? {}),
  }
  if (init.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await authenticatedFetch(path, { ...init, headers })
  } catch {
    throw new ApiError(0, 'Не удалось связаться с сервером. Проверьте, что API запущен.')
  }

  notifyGenerationFromResponse(response)

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
    if (response.status === 401 && !path.endsWith('/auth/login')) {
      unauthorizedListener?.()
    }
    throw parseErrorPayload(response.status, payload)
  }

  return payload as T
}

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshRequest) {
    refreshRequest = fetch('/api/v1/auth/refresh', {
      method: 'POST',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
      cache: 'no-store',
    })
      .then(async response => {
        if (!response.ok) return null
        const payload = (await response.json()) as { access_token?: string }
        return payload.access_token ?? null
      })
      .catch(() => null)
      .finally(() => {
        refreshRequest = null
      })
  }
  return refreshRequest
}

async function authenticatedFetch(path: string, init: RequestInit): Promise<Response> {
  const headers = init.headers as Record<string, string>
  let token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const send = () => fetch(path, { ...init, headers, credentials: 'same-origin' })
  let response = await send()
  if (response.status === 401 && token && !path.endsWith('/auth/login') && !path.endsWith('/auth/refresh')) {
    token = await refreshAccessToken()
    if (token) {
      setToken(token)
      headers.Authorization = `Bearer ${token}`
      response = await send()
    }
  }
  return response
}

function withQuery(base: string, params: Record<string, string | number | undefined | null>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value))
    }
  }
  const str = query.toString()
  return str ? `${base}?${str}` : base
}

export function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string; expires_in: number }>(
      '/api/v1/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password }) },
    ),

  refresh: () =>
    request<{ access_token: string; token_type: string; expires_in: number }>(
      '/api/v1/auth/refresh', { method: 'POST' },
    ),

  me: () => request<{ email: string }>('/api/v1/auth/me'),

  logout: () => request<void>('/api/v1/auth/logout', { method: 'POST' }),

  summary: (generation?: number) =>
    request<Summary>(withQuery('/api/v1/analytics/summary', { generation })),

  customers: (params: {
    generation?: number
    search?: string
    riskCategory?: string
    serviceStatus?: string
    sortBy: string
    sortDir: 'asc' | 'desc'
    page: number
    pageSize: number
  }) =>
    request<CustomerPage>(
      withQuery('/api/v1/customers', {
        generation: params.generation,
        search: params.search,
        riskCategory: params.riskCategory,
        serviceStatus: params.serviceStatus,
        sortBy: params.sortBy,
        sortDir: params.sortDir,
        page: params.page,
        pageSize: params.pageSize,
      }),
    ),

  customer: (id: number, generation?: number) =>
    request<CustomerDetail>(withQuery(`/api/v1/customers/${id}`, { generation })),

  exportCustomersCsv: async (params: {
    generation?: number
    search?: string
    riskCategory?: string
    serviceStatus?: string
    sortBy: string
    sortDir: 'asc' | 'desc'
  }): Promise<CsvExportResult> => {
    const headers: Record<string, string> = { Accept: 'text/csv, application/json' }

    const url = withQuery('/api/v1/export/customers.csv', {
      generation: params.generation,
      search: params.search,
      riskCategory: params.riskCategory,
      serviceStatus: params.serviceStatus,
      sortBy: params.sortBy,
      sortDir: params.sortDir,
    })

    let response: Response
    try {
      response = await authenticatedFetch(url, { method: 'GET', headers })
    } catch {
      throw new ApiError(0, 'Не удалось связаться с сервером для экспорта CSV.')
    }

    if (!response.ok) {
      if (response.status === 401) unauthorizedListener?.()
      let payload: unknown = null
      try {
        payload = await response.json()
      } catch {
        payload = null
      }
      throw parseErrorPayload(response.status, payload)
    }

    const blob = await response.blob()
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const match = disposition.match(/filename="?([^";]+)"?/i)
    const filename = match?.[1] ?? 'aeza-customers.csv'
    const rowsRaw = response.headers.get('X-Export-Rows')
    const horizonRaw = response.headers.get('X-Export-Horizon-Days')

    return {
      blob,
      filename,
      rows: rowsRaw !== null && rowsRaw !== '' ? Number(rowsRaw) : null,
      asOf: response.headers.get('X-Export-As-Of'),
      engineVersion: response.headers.get('X-Export-Engine-Version'),
      horizonDays: horizonRaw !== null && horizonRaw !== '' ? Number(horizonRaw) : null,
    }
  },

  modelSettings: (generation?: number) =>
    request<ModelSettings>(withQuery('/api/v1/model/settings', { generation })),

  patchSettings: (patch: SettingsPatch) =>
    request<ModelSettings>('/api/v1/model/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  aiStatus: () => request<AIStatus>('/api/v1/ai/status'),

  aiChat: (question: string, customerId?: number) =>
    request<AIResponse>('/api/v1/ai/chat', {
      method: 'POST',
      body: JSON.stringify(customerId ? { question, customerId } : { question }),
    }),

  aiExplainCustomer: (customerId: number, question?: string) =>
    request<AIResponse>(`/api/v1/ai/customers/${customerId}/explain`, {
      method: 'POST',
      body: JSON.stringify(question ? { question } : {}),
    }),

  aiExplainScenario: (overrides: Record<string, unknown>, question?: string) =>
    request<AIResponse>('/api/v1/ai/scenarios/explain', {
      method: 'POST',
      body: JSON.stringify(question ? { overrides, question } : { overrides }),
    }),

  aiReportSummary: (focus?: string) =>
    request<AIResponse>('/api/v1/ai/reports/summary', {
      method: 'POST',
      body: JSON.stringify(focus ? { focus } : {}),
    }),

  actions: (customerId?: number) =>
    request<RetentionActionList>(
      customerId ? `/api/v1/actions?customerId=${customerId}` : '/api/v1/actions',
    ),

  confirmAction: (customerId: number, code: string, serviceId?: number, note?: string) =>
    request<RetentionAction>('/api/v1/actions', {
      method: 'POST',
      body: JSON.stringify({ customerId, code, serviceId: serviceId ?? null, note: note ?? null }),
    }),

  updateAction: (actionId: number, patch: { status?: ActionStatus; note?: string }) =>
    request<RetentionAction>(`/api/v1/actions/${actionId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  resetSettings: (expectedGeneration?: number) =>
    request<ModelSettings>(withQuery('/api/v1/model/settings/reset', { expectedGeneration }), {
      method: 'POST',
    }),

  sourceSnapshot: (generation?: number) =>
    request<SourceInfo>(withQuery('/api/v1/source/snapshot', { generation })),

  uploadSnapshot: (snapshot: unknown, expectedGeneration?: number) =>
    request<SourceAccepted>(withQuery('/api/v1/source/snapshot', { expectedGeneration }), {
      method: 'PUT',
      body: JSON.stringify(snapshot),
    }),

  observations: (params?: { serviceId?: number; limit?: number }) =>
    request<ObservationsResponse>(
      withQuery('/api/v1/source/observations', {
        serviceId: params?.serviceId,
        limit: params?.limit ?? 100,
      }),
    ),

  quality: () => request<QualityReport>('/api/v1/quality'),

  compareScenario: (name: string, overrides: ScenarioOverrides) =>
    request<ScenarioComparisonResponse>('/api/v1/scenarios/compare', {
      method: 'POST',
      body: JSON.stringify({ name, overrides }),
    }),

  priority: (params?: {
    horizonDays?: number
    category?: string
    sortBy?: 'urgency' | 'riskScore' | 'exposure' | 'id'
    sortDir?: 'asc' | 'desc'
  }) =>
    request<PriorityResponse>(
      withQuery('/api/v1/priority', {
        horizonDays: params?.horizonDays ?? 30,
        category: params?.category,
        sortBy: params?.sortBy ?? 'urgency',
        sortDir: params?.sortDir ?? 'asc',
      }),
    ),

  /**
   * Connects to `/api/v1/analytics/events` via fetch stream so Bearer auth and
   * `Last-Event-ID` headers are transmitted without exposing tokens in URLs.
   */
  streamEvents: async (options: {
    lastEventId?: number | null
    signal: AbortSignal
    onOpen?: () => void
    onUpdate: (eventId: number, version: VersionInfo) => void
  }): Promise<void> => {
    const headers: Record<string, string> = {
      Accept: 'text/event-stream',
    }
    if (options.lastEventId !== undefined && options.lastEventId !== null) {
      headers['Last-Event-ID'] = String(options.lastEventId)
    }

    const response = await authenticatedFetch('/api/v1/analytics/events', {
      method: 'GET',
      headers,
      signal: options.signal,
      cache: 'no-store',
    })

    if (!response.ok) {
      if (response.status === 401) unauthorizedListener?.()
      throw new ApiError(response.status, `SSE error (${response.status})`)
    }

    if (!response.body) return
    options.onOpen?.()

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    try {
      while (!options.signal.aborted) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          if (!frame.trim()) continue
          let eventName = 'message'
          let eventId: number | null = null
          const dataLines: string[] = []

          for (const line of frame.split('\n')) {
            if (line.startsWith(':')) continue
            if (line.startsWith('id:')) {
              const parsed = Number(line.slice(3).trim())
              if (Number.isInteger(parsed) && parsed >= 0) eventId = parsed
            } else if (line.startsWith('event:')) {
              eventName = line.slice(6).trim()
            } else if (line.startsWith('data:')) {
              dataLines.push(line.slice(5).trim())
            }
          }

          if (eventName === 'analysis.updated' && dataLines.length > 0) {
            try {
              const version = JSON.parse(dataLines.join('\n')) as VersionInfo
              const id = eventId ?? version.generation
              if (typeof id === 'number' && Number.isFinite(id)) {
                options.onUpdate(id, version)
              }
            } catch {
              // Ignore malformed frames without tearing down the stream.
            }
          }
        }
      }
    } finally {
      try {
        await reader.cancel()
      } catch {
        // Stream already closed.
      }
    }
  },
}
