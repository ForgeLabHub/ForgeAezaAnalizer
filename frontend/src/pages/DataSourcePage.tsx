import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useAnalysis } from '../lib/realtime'
import type {
  ObservationsResponse,
  QualityIssue,
  QualityReport,
  QualitySeverity,
  SourceAccepted,
  SourceInfo,
  ValidationIssue,
} from '../types'
import {
  EmptyState,
  ErrorBox,
  Loading,
  Metric,
  QUALITY_SEVERITY_LABELS,
  SeverityBadge,
  StatusBadge,
  formatDateTime,
} from '../components/ui'

type DataTab = 'snapshot' | 'quality' | 'observations'

interface StagedSnapshot {
  fileName: string
  fileSizeBytes: number
  payload: unknown
  counts: {
    accounts: number
    services: number
    transactions: number
  }
}

const ACCOUNT_ISSUE_CODES = new Set(['missing_money_field', 'negative_amount'])
const SERVICE_ISSUE_CODES = new Set([
  'unknown_owner',
  'overdue_open_service',
  'lifecycle_inconsistent',
])

export default function DataSourcePage() {
  const { activeGeneration, pinnedGeneration, setPinnedGeneration, refreshKey, notifyMutation } =
    useAnalysis()
  const [params, setParams] = useSearchParams()

  const rawTab = params.get('tab') as DataTab | null
  const tab: DataTab =
    rawTab === 'quality' || rawTab === 'observations' ? rawTab : 'snapshot'

  const serviceIdParam = params.get('serviceId') ?? ''
  const limitParam = Number(params.get('limit') ?? '100')
  const limit = [25, 50, 100, 200].includes(limitParam) ? limitParam : 100

  const [serviceInput, setServiceInput] = useState(serviceIdParam)

  const [sourceInfo, setSourceInfo] = useState<SourceInfo | null>(null)
  const [quality, setQuality] = useState<QualityReport | null>(null)
  const [observations, setObservations] = useState<ObservationsResponse | null>(null)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [errorIssues, setErrorIssues] = useState<ValidationIssue[] | undefined>(undefined)

  const [staged, setStaged] = useState<StagedSnapshot | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadIssues, setUploadIssues] = useState<ValidationIssue[] | undefined>(undefined)
  const [uploading, setUploading] = useState(false)
  const [importResult, setImportResult] = useState<SourceAccepted | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null)

  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    setServiceInput(serviceIdParam)
  }, [serviceIdParam])

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(timer)
  }, [toast])

  function updateParams(next: Record<string, string | null>) {
    const merged = new URLSearchParams(params)
    Object.entries(next).forEach(([k, v]) => {
      if (v === null || v === '') merged.delete(k)
      else merged.set(k, v)
    })
    setParams(merged, { replace: true })
  }

  const loadSnapshotAndQuality = useCallback(async () => {
    setLoading(true)
    setError(null)
    setErrorIssues(undefined)
    try {
      const [src, qual] = await Promise.all([
        api.sourceSnapshot(activeGeneration),
        api.quality(),
      ])
      setSourceInfo(src)
      setQuality(qual)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
        setErrorIssues(err.errors)
      } else {
        setError('Не удалось загрузить сведения об источнике данных')
      }
    } finally {
      setLoading(false)
    }
  }, [activeGeneration])

  const loadObservations = useCallback(async () => {
    setLoading(true)
    setError(null)
    setErrorIssues(undefined)
    try {
      const parsedServiceId = serviceIdParam ? Number(serviceIdParam) : undefined
      const validServiceId =
        parsedServiceId !== undefined && Number.isInteger(parsedServiceId) && parsedServiceId >= 1
          ? parsedServiceId
          : undefined
      const obs = await api.observations({ serviceId: validServiceId, limit })
      setObservations(obs)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
        setErrorIssues(err.errors)
      } else {
        setError('Не удалось загрузить журнал наблюдений')
      }
    } finally {
      setLoading(false)
    }
  }, [serviceIdParam, limit])

  useEffect(() => {
    if (tab === 'observations') {
      void loadObservations()
    } else {
      void loadSnapshotAndQuality()
    }
  }, [tab, loadSnapshotAndQuality, loadObservations, refreshKey])

  async function inspectSelectedFile(file: File) {
    setUploadError(null)
    setUploadIssues(undefined)
    setImportResult(null)
    try {
      const rawText = await file.text()
      let parsed: unknown
      try {
        parsed = JSON.parse(rawText)
      } catch {
        setStaged(null)
        setUploadError('Выбранный файл не является корректным JSON.')
        return
      }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setStaged(null)
        setUploadError(
          'Ожидается JSON-объект снимка с массивами accounts, services и transactions.',
        )
        return
      }
      const obj = parsed as Record<string, unknown>
      if (
        !Array.isArray(obj.accounts) ||
        !Array.isArray(obj.services) ||
        !Array.isArray(obj.transactions)
      ) {
        setStaged(null)
        setUploadError(
          'В снимке обязательны три массива верхнего уровня: accounts, services и transactions.',
        )
        return
      }
      setStaged({
        fileName: file.name,
        fileSizeBytes: file.size,
        payload: parsed,
        counts: {
          accounts: obj.accounts.length,
          services: obj.services.length,
          transactions: obj.transactions.length,
        },
      })
    } catch {
      setStaged(null)
      setUploadError('Не удалось прочитать файл.')
    }
  }

  async function publishStagedSnapshot() {
    if (!staged || pinnedGeneration !== null) return
    setUploading(true)
    setUploadError(null)
    setUploadIssues(undefined)
    try {
      const res = await api.uploadSnapshot(staged.payload, sourceInfo?.generation)
      setImportResult(res)
      setStaged(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      notifyMutation(res)
      await loadSnapshotAndQuality()
      setToast({
        text: `Снимок опубликован атомарно (поколение #${res.generation}, версия источника s${res.sourceVersion}).`,
      })
    } catch (err) {
      if (err instanceof ApiError) {
        setUploadError(err.detail)
        setUploadIssues(err.errors)
      } else {
        setUploadError('Не удалось импортировать снимок')
      }
    } finally {
      setUploading(false)
    }
  }

  function submitObservationFilter(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = serviceInput.trim()
    if (!trimmed) {
      updateParams({ serviceId: null })
      return
    }
    const num = Number(trimmed)
    if (!Number.isInteger(num) || num < 1) {
      setToast({ text: 'ID услуги должен быть положительным целым числом.', err: true })
      return
    }
    updateParams({ serviceId: String(num) })
  }

  const issueTotal = quality
    ? quality.counts.critical + quality.counts.warning + quality.counts.info
    : 0

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Источник данных и контроль качества</h1>
          <p>
            Управление снимком данных, атомарный импорт JSON-выгрузок, автоматический аудит
            целостности записей и журнал наблюдаемых изменений статусов услуг.
          </p>
        </div>
        <div className="tabs" role="tablist" aria-label="Раздел данных">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'snapshot'}
            className={tab === 'snapshot' ? 'active' : ''}
            onClick={() => updateParams({ tab: null })}
          >
            Снимок и импорт
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'quality'}
            className={tab === 'quality' ? 'active' : ''}
            onClick={() => updateParams({ tab: 'quality' })}
          >
            Качество данных{quality && issueTotal > 0 ? ` (${issueTotal})` : ''}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'observations'}
            className={tab === 'observations' ? 'active' : ''}
            onClick={() => updateParams({ tab: 'observations' })}
          >
            Наблюдения статусов
          </button>
        </div>
      </div>

      {error ? <ErrorBox issues={errorIssues}>{error}</ErrorBox> : null}

      {tab === 'snapshot' ? (
        loading && !sourceInfo ? (
          <Loading label="Загрузка метаданных снимка…" />
        ) : (
          <>
            {sourceInfo ? (
              <div className="metric-grid">
                <Metric
                  label="Аккаунтов в снимке"
                  value={sourceInfo.counts.accounts ?? 0}
                  foot={`версия источника s${sourceInfo.sourceVersion}`}
                />
                <Metric
                  label="Услуг в снимке"
                  value={sourceInfo.counts.services ?? 0}
                  foot={`поколение расчёта #${sourceInfo.generation}`}
                />
                <Metric
                  label="Транзакций в снимке"
                  value={sourceInfo.counts.transactions ?? 0}
                  foot={`модель m${sourceInfo.modelVersion}`}
                />
                <Metric
                  label="Загружен (UTC)"
                  value={formatDateTime(sourceInfo.capturedAt)}
                  small
                  foot={
                    sourceInfo.asOf ? `asOf: ${formatDateTime(sourceInfo.asOf)} UTC` : undefined
                  }
                />
              </div>
            ) : null}

            <div className="grid-main">
              <section className="card">
                <div className="card-head">
                  <h2>Атомарная загрузка нового снимка (PUT /source/snapshot)</h2>
                  <span className="hint">JSON · all-or-nothing</span>
                </div>
                <div className="card-body stack" style={{ gap: 16 }}>
                  {pinnedGeneration !== null ? (
                    <div className="notice warn row" style={{ justifyContent: 'space-between' }}>
                      <span>
                        Импорт нового снимка недоступен при фиксированном просмотре архивного
                        поколения #{pinnedGeneration}.
                      </span>
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() => setPinnedGeneration(null)}
                      >
                        К актуальному поколению
                      </button>
                    </div>
                  ) : null}

                  <div
                    className={`dropzone${dragActive ? ' is-drag' : ''}`}
                    onDragOver={(e) => {
                      e.preventDefault()
                      setDragActive(true)
                    }}
                    onDragLeave={() => setDragActive(false)}
                    onDrop={(e) => {
                      e.preventDefault()
                      setDragActive(false)
                      const file = e.dataTransfer.files?.[0]
                      if (file) void inspectSelectedFile(file)
                    }}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".json,application/json"
                      className="sr-only"
                      id="snapshot-file-input"
                      onChange={(e) => {
                        const file = e.target.files?.[0]
                        if (file) void inspectSelectedFile(file)
                      }}
                    />
                    <div className="dropzone-title">
                      Перетащите файл <code>data.json</code> сюда или выберите на устройстве
                    </div>
                    <div className="hint">
                      Ожидается структура <code>{'{ accounts, services, transactions }'}</code>. При
                      любой ошибке валидации текущий опубликованный снимок остаётся нетронутым.
                    </div>
                    <div style={{ marginTop: 12 }}>
                      <label htmlFor="snapshot-file-input" className="btn">
                        Выбрать JSON-файл
                      </label>
                    </div>
                  </div>

                  {uploadError ? (
                    <ErrorBox issues={uploadIssues}>
                      <strong>Импорт отклонён (предыдущий снимок сохранён):</strong> {uploadError}
                    </ErrorBox>
                  ) : null}

                  {staged ? (
                    <div className="card" style={{ background: 'var(--surface-muted)' }}>
                      <div className="card-head">
                        <h3>Предпросмотр файла «{staged.fileName}»</h3>
                        <span className="mono hint">
                          {(staged.fileSizeBytes / 1024).toFixed(1)} КБ
                        </span>
                      </div>
                      <div className="card-body stack" style={{ gap: 12 }}>
                        <dl className="kv">
                          <dt>Аккаунты (accounts)</dt>
                          <dd>
                            {staged.counts.accounts}
                            {sourceInfo?.counts.accounts !== undefined
                              ? ` (сейчас: ${sourceInfo.counts.accounts})`
                              : ''}
                          </dd>
                          <dt>Услуги (services)</dt>
                          <dd>
                            {staged.counts.services}
                            {sourceInfo?.counts.services !== undefined
                              ? ` (сейчас: ${sourceInfo.counts.services})`
                              : ''}
                          </dd>
                          <dt>Транзакции (transactions)</dt>
                          <dd>
                            {staged.counts.transactions}
                            {sourceInfo?.counts.transactions !== undefined
                              ? ` (сейчас: ${sourceInfo.counts.transactions})`
                              : ''}
                          </dd>
                        </dl>
                        <div className="row" style={{ justifyContent: 'flex-end' }}>
                          <button
                            type="button"
                            className="btn"
                            disabled={uploading}
                            onClick={() => {
                              setStaged(null)
                              if (fileInputRef.current) fileInputRef.current.value = ''
                            }}
                          >
                            Отменить
                          </button>
                          <button
                            type="button"
                            className="btn primary"
                            disabled={uploading || pinnedGeneration !== null}
                            onClick={() => void publishStagedSnapshot()}
                          >
                            {uploading ? 'Проверка и расчёт…' : 'Опубликовать снимок атомарно'}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {importResult ? (
                    <div className="notice info stack" style={{ gap: 8 }}>
                      <div>
                        <strong>{importResult.report.message}</strong> · поколение #
                        {importResult.generation} (источник s{importResult.sourceVersion}).
                      </div>
                      <div className="mono">
                        Принято: accounts={importResult.report.accepted.accounts ?? 0}, services=
                        {importResult.report.accepted.services ?? 0}, transactions=
                        {importResult.report.accepted.transactions ?? 0} (предыдущий снимок: accounts=
                        {importResult.report.previous.accounts ?? 0}, services=
                        {importResult.report.previous.services ?? 0}, transactions=
                        {importResult.report.previous.transactions ?? 0}).
                      </div>
                    </div>
                  ) : null}
                </div>
              </section>

              <div className="stack">
                <section className="card">
                  <div className="card-head">
                    <h2>Гарантии импорта</h2>
                  </div>
                  <div className="card-body stack" style={{ gap: 10 }}>
                    <div className="notice">
                      <strong>Атомарность (all-or-nothing):</strong> весь снимок проверяется по
                      строгой схеме до записи. Ошибка хотя бы в одной записи или ссылке (
                      <code>ownerId</code>, <code>serviceId</code>) отменяет импорт целиком.
                    </div>
                    <div className="notice">
                      <strong>Идемпотентность:</strong> повторная отправка идентичного снимка не
                      создаёт лишнего пересчёта и не дублирует наблюдения.
                    </div>
                    <div className="notice">
                      <strong>Единицы измерения:</strong> денежные поля в снимке передаются в целых
                      евроцентах (100 центов = 1,00 €). Поле <code>transactions.amount</code> не
                      является денежной суммой и не участвует в расчёте выручки.
                    </div>
                  </div>
                </section>
              </div>
            </div>
          </>
        )
      ) : null}

      {tab === 'quality' ? (
        loading && !quality ? (
          <Loading label="Аудит качества исходных данных…" />
        ) : !quality ? (
          <EmptyState>Отчёт качества недоступен</EmptyState>
        ) : (
          <>
            {pinnedGeneration !== null ? (
              <div className="notice info row" style={{ justifyContent: 'space-between' }}>
                <span>
                  Аудит качества выполняется по текущему рабочему снимку (в шапке выбран архивный
                  просмотр #{pinnedGeneration}).
                </span>
                <button
                  type="button"
                  className="btn sm"
                  onClick={() => setPinnedGeneration(null)}
                >
                  К актуальному поколению
                </button>
              </div>
            ) : null}

            <div className="metric-grid">
              <Metric
                label="Критичные ошибки"
                value={quality.counts.critical}
                accent={quality.counts.critical > 0}
                foot="требуют исправления выгрузки"
              />
              <Metric
                label="Предупреждения"
                value={quality.counts.warning}
                foot="требуют осторожной интерпретации"
              />
              <Metric
                label="Справочные сигналы"
                value={quality.counts.info}
                foot="операционные наблюдения"
              />
              <Metric
                label="Проверено записей"
                value={
                  quality.recordsInspected.accounts +
                  quality.recordsInspected.services +
                  quality.recordsInspected.transactions
                }
                small
                foot={`${quality.recordsInspected.accounts} акк. · ${quality.recordsInspected.services} усл. · ${quality.recordsInspected.transactions} транз.`}
              />
            </div>

            <div className="grid-main">
              <section className="card card-quality-main">
                <div className="card-head">
                  <h2>Обнаруженные замечания ({quality.issues.length})</h2>
                  {quality.asOf ? (
                    <span className="hint">на момент {formatDateTime(quality.asOf)} UTC</span>
                  ) : null}
                </div>
                <div className="card-body">
                  {quality.issues.length === 0 ? (
                    <EmptyState>
                      Замечаний к структуре и согласованности текущего снимка не обнаружено.
                    </EmptyState>
                  ) : (
                    <div className="stack" style={{ gap: 14 }}>
                      {quality.issues.map((issue: QualityIssue) => {
                        const isAccountIssue = ACCOUNT_ISSUE_CODES.has(issue.code)
                        const isServiceIssue = SERVICE_ISSUE_CODES.has(issue.code)
                        return (
                          <div className="quality-item" key={issue.code}>
                            <div className="row" style={{ justifyContent: 'space-between' }}>
                              <div className="row" style={{ gap: 8 }}>
                                <SeverityBadge level={issue.level} />
                                <code>{issue.code}</code>
                              </div>
                              <span className="mono hint">записей: {issue.count}</span>
                            </div>
                            <div className="quality-msg">{issue.message}</div>
                            <div className="hint">Рекомендация: {issue.action}</div>
                            {issue.records.length > 0 ? (
                              <div className="record-chips">
                                {issue.records.map((recId) =>
                                  isAccountIssue ? (
                                    <Link
                                      key={recId}
                                      to={`/customers/${recId}`}
                                      className="chip-link"
                                      title="Перейти в карточку клиента"
                                    >
                                      Клиент #{recId}
                                    </Link>
                                  ) : isServiceIssue ? (
                                    <button
                                      key={recId}
                                      type="button"
                                      className="chip-link"
                                      onClick={() =>
                                        updateParams({
                                          tab: 'observations',
                                          serviceId: String(recId),
                                        })
                                      }
                                      title="Показать наблюдения по услуге"
                                    >
                                      Услуга #{recId}
                                    </button>
                                  ) : (
                                    <span key={recId} className="badge neutral mono">
                                      Транзакция #{recId}
                                    </span>
                                  ),
                                )}
                                {issue.count > issue.records.length ? (
                                  <span className="hint">
                                    …и ещё {issue.count - issue.records.length}
                                  </span>
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </section>

              <section className="card card-quality-equal">
                <div className="card-head">
                  <h2>Уровни критичности</h2>
                </div>
                <div className="card-body">
                  {(['critical', 'warning', 'info'] as QualitySeverity[]).map((lvl) => (
                    <div key={lvl} className="notice">
                      <div style={{ marginBottom: 4 }}>
                        <SeverityBadge level={lvl} />
                      </div>
                      <div>
                        {quality.levels[lvl] ?? QUALITY_SEVERITY_LABELS[lvl]}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </>
        )
      ) : null}

      {tab === 'observations' ? (
        <section className="card">
          <form className="toolbar" onSubmit={submitObservationFilter}>
            <input
              className="input search"
              type="search"
              inputMode="numeric"
              placeholder="Фильтр по ID услуги (например, 1)…"
              value={serviceInput}
              onChange={(e) => setServiceInput(e.target.value)}
              aria-label="ID услуги"
            />
            <button type="submit" className="btn">
              Показать
            </button>

            <select
              className="select"
              value={String(limit)}
              onChange={(e) => updateParams({ limit: e.target.value })}
              aria-label="Лимит записей"
            >
              <option value="25">Лимит: 25</option>
              <option value="50">Лимит: 50</option>
              <option value="100">Лимит: 100</option>
              <option value="200">Лимит: 200</option>
            </select>

            {serviceIdParam ? (
              <button
                type="button"
                className="btn sm"
                onClick={() => {
                  setServiceInput('')
                  updateParams({ serviceId: null })
                }}
              >
                Все услуги
              </button>
            ) : null}

            <span className="spacer" />
            {observations ? (
              <span className="hint">записей: {observations.items.length}</span>
            ) : null}
          </form>

          {loading ? (
            <Loading label="Загрузка журнала наблюдений…" />
          ) : !observations || observations.items.length === 0 ? (
            <EmptyState>
              Наблюдения не найдены. Записи появляются при первичном импорте и при изменении
              статусов услуг между версиями снимка.
            </EmptyState>
          ) : (
            <>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th className="num">Версия снимка</th>
                      <th className="num">Услуга</th>
                      <th>Предыдущий статус</th>
                      <th>Наблюдаемый статус</th>
                      <th>Пред. наблюдение (UTC)</th>
                      <th>Наблюдение (UTC)</th>
                      <th>Время события</th>
                    </tr>
                  </thead>
                  <tbody>
                    {observations.items.map((obs, idx) => (
                      <tr key={`${obs.sourceVersion}-${obs.serviceId}-${idx}`}>
                        <td className="num mono">s{obs.sourceVersion}</td>
                        <td className="num mono">
                          <button
                            type="button"
                            className="link-btn mono"
                            onClick={() => updateParams({ serviceId: String(obs.serviceId) })}
                            title="Отфильтровать по этой услуге"
                          >
                            #{obs.serviceId}
                          </button>
                        </td>
                        <td>
                          {obs.previousStatus ? (
                            <StatusBadge status={obs.previousStatus} />
                          ) : (
                            <span className="cell-sub">первичное появление</span>
                          )}
                        </td>
                        <td>
                          {obs.status ? (
                            <StatusBadge status={obs.status} />
                          ) : (
                            <span className="badge risk-medium">
                              исчезла из снимка (не deleted)
                            </span>
                          )}
                        </td>
                        <td className="mono">{formatDateTime(obs.previousObservedAt)}</td>
                        <td className="mono">{formatDateTime(obs.observedAt)}</td>
                        <td className="cell-sub">
                          {obs.eventAt ? formatDateTime(obs.eventAt) : 'неизвестно'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="card-note">{observations.note}</div>
            </>
          )}
        </section>
      ) : null}

      {toast ? <div className={`toast${toast.err ? ' err' : ''}`}>{toast.text}</div> : null}
    </div>
  )
}
