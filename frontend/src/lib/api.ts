import type {
  CsvExportResult,
  CustomerDetail,
  CustomerPage,
  ModelSettings,
  ObservationsResponse,
  PriorityResponse,
  QualityReport,
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

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
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
  const token = getToken()
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init.headers as Record<string, string>) ?? {}),
  }
  if (init.body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(path, { ...init, headers })
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
    const token = getToken()
    const headers: Record<string, string> = { Accept: 'text/csv, application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`

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
      response = await fetch(url, { method: 'GET', headers })
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
    const token = getToken()
    if (!token) return

    const headers: Record<string, string> = {
      Accept: 'text/event-stream',
      Authorization: `Bearer ${token}`,
    }
    if (options.lastEventId !== undefined && options.lastEventId !== null) {
      headers['Last-Event-ID'] = String(options.lastEventId)
    }

    const response = await fetch('/api/v1/analytics/events', {
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
