import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api, triggerBlobDownload } from '../lib/api'
import { useAnalysis } from '../lib/realtime'
import type { CustomerPage, CustomerSummary, ObservationsResponse } from '../types'
import { SlidingTabs } from '../components/motion'
import {
  EmptyState,
  ErrorBox,
  Loading,
  RiskBadge,
  ScoreCell,
  StatusBadge,
  formatDateTime,
  formatEur,
} from '../components/ui'

type SortDir = 'asc' | 'desc'
type CustomersTab = 'customers' | 'observations'

const CUSTOMER_TABS = [
  { value: 'customers' as const, label: 'Список клиентов' },
  { value: 'observations' as const, label: 'Наблюдения статусов' },
]

const COLUMNS: Array<{
  key: string
  label: string
  numeric?: boolean
  width?: string
}> = [
  { key: 'id', label: 'ID', numeric: true },
  { key: 'email', label: 'Email' },
  { key: 'riskScore', label: 'Риск' },
  { key: 'balance', label: 'Баланс', numeric: true },
  { key: 'totalReplenished', label: 'Всего пополнено', numeric: true },
]

const PAGE_SIZE = 25

export default function CustomersPage() {
  const { activeGeneration, refreshKey } = useAnalysis()
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState<CustomerPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null)

  const rawTab = params.get('tab') as CustomersTab | null
  const tab: CustomersTab = rawTab === 'observations' ? 'observations' : 'customers'
  const tabDirRef = useRef<{ tab: CustomersTab; dir: -1 | 0 | 1 }>({ tab, dir: 0 })
  if (tabDirRef.current.tab !== tab) {
    tabDirRef.current = {
      tab,
      dir: tab === 'observations' ? 1 : -1,
    }
  }

  const sortBy = params.get('sortBy') ?? 'riskScore'
  const sortDir = (params.get('sortDir') as SortDir) ?? 'desc'
  const riskCategory = params.get('riskCategory') ?? ''
  const serviceStatus = params.get('serviceStatus') ?? ''
  const page = Number(params.get('page') ?? '1')
  const searchParam = params.get('search') ?? ''
  const [search, setSearch] = useState(searchParam)

  const serviceIdParam = params.get('serviceId') ?? ''
  const limitParam = Number(params.get('limit') ?? '100')
  const obsLimit = [25, 50, 100, 200].includes(limitParam) ? limitParam : 100
  const [serviceInput, setServiceInput] = useState(serviceIdParam)
  const [observations, setObservations] = useState<ObservationsResponse | null>(null)
  const [obsLoading, setObsLoading] = useState(false)
  const [obsError, setObsError] = useState<string | null>(null)

  useEffect(() => {
    setSearch(searchParam)
  }, [searchParam])

  useEffect(() => {
    setServiceInput(serviceIdParam)
  }, [serviceIdParam])

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(timer)
  }, [toast])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await api.customers({
        generation: activeGeneration,
        search: searchParam || undefined,
        riskCategory: riskCategory || undefined,
        serviceStatus: serviceStatus || undefined,
        sortBy,
        sortDir,
        page,
        pageSize: PAGE_SIZE,
      })
      setData(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить клиентов')
    } finally {
      setLoading(false)
    }
  }, [activeGeneration, searchParam, riskCategory, serviceStatus, sortBy, sortDir, page])

  const loadObservations = useCallback(async () => {
    setObsLoading(true)
    setObsError(null)
    try {
      const parsedServiceId = serviceIdParam ? Number(serviceIdParam) : undefined
      const validServiceId =
        parsedServiceId !== undefined && Number.isInteger(parsedServiceId) && parsedServiceId >= 1
          ? parsedServiceId
          : undefined
      const obs = await api.observations({ serviceId: validServiceId, limit: obsLimit })
      setObservations(obs)
    } catch (err) {
      setObsError(
        err instanceof ApiError ? err.detail : 'Не удалось загрузить журнал наблюдений',
      )
    } finally {
      setObsLoading(false)
    }
  }, [serviceIdParam, obsLimit])

  useEffect(() => {
    if (tab === 'observations') {
      void loadObservations()
    } else {
      void load()
    }
  }, [tab, load, loadObservations, refreshKey])

  function update(next: Record<string, string | null>) {
    const merged = new URLSearchParams(params)
    Object.entries(next).forEach(([key, value]) => {
      if (value === null || value === '') merged.delete(key)
      else merged.set(key, value)
    })
    setParams(merged, { replace: true })
  }

  function toggleSort(key: string) {
    if (sortBy === key) {
      update({ sortDir: sortDir === 'asc' ? 'desc' : 'asc', page: '1' })
    } else {
      update({ sortBy: key, sortDir: key === 'email' ? 'asc' : 'desc', page: '1' })
    }
  }

  function submitSearch(e: React.FormEvent) {
    e.preventDefault()
    update({ search: search.trim() || null, page: '1' })
  }

  function submitObservationFilter(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = serviceInput.trim()
    if (!trimmed) {
      update({ serviceId: null })
      return
    }
    const num = Number(trimmed)
    if (!Number.isInteger(num) || num < 1) {
      setToast({ text: 'ID услуги должен быть положительным целым числом.', err: true })
      return
    }
    update({ serviceId: String(num) })
  }

  async function handleExportCsv() {
    setExporting(true)
    try {
      const result = await api.exportCustomersCsv({
        generation: activeGeneration,
        search: searchParam || undefined,
        riskCategory: riskCategory || undefined,
        serviceStatus: serviceStatus || undefined,
        sortBy,
        sortDir,
      })
      triggerBlobDownload(result.blob, result.filename)
      const countPart = result.rows !== null ? ` (${result.rows} строк)` : ''
      setToast({ text: `Экспортирован файл ${result.filename}${countPart}.` })
    } catch (err) {
      setToast({
        text: err instanceof ApiError ? err.detail : 'Не удалось экспортировать CSV',
        err: true,
      })
    } finally {
      setExporting(false)
    }
  }

  const activeFilters = useMemo(
    () => [riskCategory && 'риск', serviceStatus && 'статус', searchParam && 'поиск'].filter(Boolean),
    [riskCategory, serviceStatus, searchParam],
  )

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Клиенты</h1>
        </div>
        <div className="row">
          <span className="hint">
            {tab === 'observations' ? (
              observations ? `записей: ${observations.items.length}` : ''
            ) : (
              <>
                {data ? `${data.total} записей` : ''}
                {data?.generation ? ` · поколение #${data.generation}` : ''}
                {activeFilters.length ? ` · активны: ${activeFilters.join(', ')}` : ''}
              </>
            )}
          </span>
          <SlidingTabs
            ariaLabel="Раздел страницы клиентов"
            items={CUSTOMER_TABS}
            value={tab}
            onChange={(next) => update({ tab: next === 'customers' ? null : 'observations' })}
          />
          {tab === 'customers' ? (
            <button
              type="button"
              className="btn"
              onClick={handleExportCsv}
              disabled={exporting || loading || !data || data.total === 0}
            >
              {exporting ? 'Формирование CSV…' : 'Экспорт в CSV'}
            </button>
          ) : null}
        </div>
      </div>

      {tab === 'customers' ? (
        <section
          key="customers"
          className="card tab-panel"
          style={{ '--enter-dir': tabDirRef.current.dir } as CSSProperties}
        >
          <form className="toolbar" onSubmit={submitSearch}>
            <input
              className="input search"
              type="search"
              placeholder="Поиск по email или ID…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Поиск клиентов"
            />
            <button className="btn" type="submit">
              Найти
            </button>

            <select
              className="select"
              value={riskCategory}
              onChange={(e) => update({ riskCategory: e.target.value || null, page: '1' })}
              aria-label="Фильтр по категории риска"
            >
              <option value="">Все уровни риска</option>
              <option value="high">Высокий</option>
              <option value="medium">Средний</option>
              <option value="low">Низкий</option>
              <option value="insufficient_data">Недостаточно данных</option>
              <option value="not_applicable">Не применимо</option>
            </select>

            <select
              className="select"
              value={serviceStatus}
              onChange={(e) => update({ serviceStatus: e.target.value || null, page: '1' })}
              aria-label="Фильтр по статусу услуги"
            >
              <option value="">Любой статус услуги</option>
              <option value="active">Активна</option>
              <option value="prolong_wait">Ожидает продления</option>
              <option value="suspended">Приостановлена</option>
              <option value="blocked">Заблокирована</option>
              <option value="deleted">Удалена</option>
            </select>

            {activeFilters.length ? (
              <button
                type="button"
                className="btn sm"
                onClick={() => {
                  setSearch('')
                  setParams(new URLSearchParams(), { replace: true })
                }}
              >
                Сбросить
              </button>
            ) : null}
          </form>

          {error ? <ErrorBox>{error}</ErrorBox> : null}
          {loading ? (
            <Loading label="Загрузка клиентов…" />
          ) : !data || data.items.length === 0 ? (
            <EmptyState>
              Ничего не найдено. Измените условия поиска или сбросьте фильтры.
            </EmptyState>
          ) : (
            <>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      {COLUMNS.map((col) => (
                        <th
                          key={col.key}
                          className={`sortable${col.numeric ? ' num' : ''}`}
                          onClick={() => toggleSort(col.key)}
                          aria-sort={
                            sortBy === col.key
                              ? sortDir === 'asc'
                                ? 'ascending'
                                : 'descending'
                              : 'none'
                          }
                          title={`Сортировать по «${col.label}»`}
                        >
                          {col.label}
                          {sortBy === col.key ? (
                            <span className="sort-ind">{sortDir === 'asc' ? '▲' : '▼'}</span>
                          ) : null}
                        </th>
                      ))}
                      <th className="num">Услуги</th>
                      <th>Уровень</th>
                      <th className="num">Выручка под риском</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((customer: CustomerSummary) => {
                      const overdue = customer.overdueServiceCount ?? 0
                      const highShare =
                        customer.highRiskShare !== undefined && customer.eligibleServiceCount > 0
                          ? ` · выс. ${Math.round(customer.highRiskShare * 100)}%`
                          : ''
                      return (
                        <tr key={customer.id}>
                          <td className="num">
                            <Link to={`/customers/${customer.id}`} className="cell-primary">
                              {customer.id}
                            </Link>
                          </td>
                          <td>
                            <span className="cell-primary">{customer.email}</span>
                            {overdue > 0 ? (
                              <div className="cell-sub">
                                просрочено откр.: {overdue}
                                {(customer.lifecycleInconsistentCount ?? 0) > 0
                                  ? ` (регл.: ${customer.lifecycleInconsistentCount})`
                                  : ''}
                              </div>
                            ) : null}
                          </td>
                          <td>
                            <ScoreCell
                              score={customer.riskScore}
                              category={customer.riskCategory}
                            />
                          </td>
                          <td className="num">{formatEur(customer.balance.eur)}</td>
                          <td className="num">{formatEur(customer.totalReplenished.eur)}</td>
                          <td className="num">
                            <div>
                              {customer.serviceCount}
                              <span className="cell-sub">
                                {' '}
                                / {customer.eligibleServiceCount} в прогнозе
                              </span>
                            </div>
                            {highShare ? <div className="cell-sub">{highShare.slice(3)}</div> : null}
                          </td>
                          <td>
                            <RiskBadge
                              category={customer.riskCategory}
                              label={customer.riskCategoryLabel}
                            />
                          </td>
                          <td className="num">
                            <div>{formatEur(customer.revenueAtRisk.eur)}</div>
                            {(customer.overdueOperational?.cents ?? 0) > 0 ? (
                              <div className="cell-sub">
                                операц.: {formatEur(customer.overdueOperational?.eur)}
                              </div>
                            ) : null}
                          </td>
                          <td>
                            <Link className="btn sm" to={`/customers/${customer.id}`}>
                              Карточка
                            </Link>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              <div className="pager">
                <span>
                  Страница {data.page} из {data.pages} · всего {data.total} клиентов
                </span>
                <div className="pager-actions">
                  <button
                    className="btn sm"
                    disabled={data.page <= 1}
                    onClick={() => update({ page: String(data.page - 1) })}
                  >
                    ← Назад
                  </button>
                  <button
                    className="btn sm"
                    disabled={data.page >= data.pages}
                    onClick={() => update({ page: String(data.page + 1) })}
                  >
                    Вперёд →
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      ) : (
        <section
          key="observations"
          className="card tab-panel"
          style={{ '--enter-dir': tabDirRef.current.dir } as CSSProperties}
        >
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
              Найти
            </button>

            <select
              className="select"
              value={String(obsLimit)}
              onChange={(e) => update({ limit: e.target.value })}
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
                  update({ serviceId: null })
                }}
              >
                Сбросить
              </button>
            ) : null}
          </form>

          {obsError ? <ErrorBox>{obsError}</ErrorBox> : null}
          {obsLoading ? (
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
                            onClick={() => update({ serviceId: String(obs.serviceId) })}
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
      )}

      {toast ? <div className={`toast${toast.err ? ' err' : ''}`}>{toast.text}</div> : null}
    </div>
  )
}
