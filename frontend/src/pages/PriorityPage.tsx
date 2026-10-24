import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useAnalysis } from '../lib/realtime'
import type { PriorityCategoryKey, PriorityItem, PriorityResponse } from '../types'
import {
  EmptyState,
  ErrorBox,
  Loading,
  Metric,
  PRIORITY_SHORT_LABELS,
  PriorityBadge,
  ScoreCell,
  formatEur,
} from '../components/ui'

type PrioritySortBy = 'urgency' | 'riskScore' | 'exposure' | 'id'
type SortDir = 'asc' | 'desc'

const HORIZON_OPTIONS = [7, 30, 90] as const

const URGENCY_LABELS: Record<number, { text: string; cls: string }> = {
  0: { text: '1 · Нарушение регламента', cls: 'risk-high' },
  1: { text: '2 · Просрочена услуга', cls: 'risk-high' },
  2: { text: '3 · Высокий риск', cls: 'risk-medium' },
  3: { text: '4 · Средний риск', cls: 'neutral' },
  4: { text: '5 · Плановый контроль', cls: 'neutral' },
}

export default function PriorityPage() {
  const { pinnedGeneration, setPinnedGeneration, refreshKey } = useAnalysis()
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState<PriorityResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const rawHorizon = Number(params.get('horizonDays') ?? '30')
  const horizonDays = HORIZON_OPTIONS.includes(rawHorizon as 7 | 30 | 90) ? rawHorizon : 30
  const category = params.get('category') ?? ''
  const sortBy = (params.get('sortBy') as PrioritySortBy) || 'urgency'
  const sortDir = ((params.get('sortDir') as SortDir) || 'asc') === 'desc' ? 'desc' : 'asc'

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await api.priority({
        horizonDays,
        category: category || undefined,
        sortBy,
        sortDir,
      })
      setData(response)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить очередь приоритетов')
    } finally {
      setLoading(false)
    }
  }, [horizonDays, category, sortBy, sortDir])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  function update(next: Record<string, string | null>) {
    const merged = new URLSearchParams(params)
    Object.entries(next).forEach(([k, v]) => {
      if (v === null || v === '') merged.delete(k)
      else merged.set(k, v)
    })
    setParams(merged, { replace: true })
  }

  function handleSort(nextSort: PrioritySortBy) {
    if (nextSort === 'urgency') {
      update({ sortBy: 'urgency', sortDir: 'asc' })
      return
    }
    if (sortBy === nextSort) {
      update({ sortDir: sortDir === 'asc' ? 'desc' : 'asc' })
    } else {
      update({ sortBy: nextSort, sortDir: 'asc' })
    }
  }

  function renderSortIndicator(col: PrioritySortBy) {
    if (sortBy !== col) return null
    if (col === 'urgency') return <span className="sort-ind">▲</span>
    if (col === 'id') return <span className="sort-ind">{sortDir === 'asc' ? '▲' : '▼'}</span>
    // Backend orders riskScore and exposure descending when sortDir === 'asc'.
    return <span className="sort-ind">{sortDir === 'asc' ? '▼' : '▲'}</span>
  }

  const items = data?.items ?? []
  const operationalCount = items.filter((i) => i.categories.includes('operational_attention')).length
  const exposureCount = items.filter((i) => i.categories.includes('high_risk_with_exposure')).length
  const qualityAlerts = data ? data.qualityCounts.critical + data.qualityCounts.warning : 0

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Очередь приоритетных действий</h1>
        </div>
        <div className="tabs" role="tablist" aria-label="Горизонт экспозиции">
          {HORIZON_OPTIONS.map((h) => (
            <button
              key={h}
              type="button"
              role="tab"
              aria-selected={horizonDays === h}
              className={horizonDays === h ? 'active' : ''}
              onClick={() => update({ horizonDays: String(h) })}
            >
              Горизонт {h} дн.
            </button>
          ))}
        </div>
      </div>

      {pinnedGeneration !== null ? (
        <div className="notice info row" style={{ justifyContent: 'space-between' }}>
          <span>
            Очередь приоритетов рассчитывается по актуальному опубликованному поколению (в шапке
            сейчас выбран архивный просмотр #{pinnedGeneration}).
          </span>
          <button type="button" className="btn sm" onClick={() => setPinnedGeneration(null)}>
            К актуальному поколению
          </button>
        </div>
      ) : null}

      {data ? (
        <div className="metric-grid">
          <Metric
            label="Клиентов в выборке"
            value={data.total}
            foot={category ? `фильтр: ${PRIORITY_SHORT_LABELS[category as PriorityCategoryKey] ?? category}` : 'все рабочие очереди'}
          />
          <Metric
            label="Операционный контроль"
            value={operationalCount}
            foot="просрочка или нарушение регламента"
          />
          <Metric
            label="Высокий риск с экспозицией"
            value={exposureCount}
            accent={exposureCount > 0}
            foot={`продления внутри ${data.horizonDays} дн.`}
          />
          <Metric
            label="Замечаний к данным"
            value={qualityAlerts}
            foot={`критичных: ${data.qualityCounts.critical} · предупреждений: ${data.qualityCounts.warning}`}
          />
        </div>
      ) : null}

      <section className="card">
        <div className="toolbar">
          <select
            className="select"
            value={category}
            onChange={(e) => update({ category: e.target.value || null })}
            aria-label="Категория рабочей очереди"
          >
            <option value="">Все рабочие очереди</option>
            {(Object.keys(PRIORITY_SHORT_LABELS) as PriorityCategoryKey[]).map((key) => (
              <option key={key} value={key}>
                {PRIORITY_SHORT_LABELS[key]}
              </option>
            ))}
          </select>

          <select
            className="select"
            value={sortBy}
            onChange={(e) => handleSort(e.target.value as PrioritySortBy)}
            aria-label="Поле сортировки"
          >
            <option value="urgency">Сортировка: по срочности</option>
            <option value="exposure">Сортировка: по выручке под риском ({horizonDays} дн.)</option>
            <option value="riskScore">Сортировка: по баллу риска</option>
            <option value="id">Сортировка: по ID клиента</option>
          </select>

          {category || sortBy !== 'urgency' || sortDir !== 'asc' ? (
            <button
              type="button"
              className="btn sm"
              onClick={() => update({ category: null, sortBy: null, sortDir: null })}
            >
              Сбросить
            </button>
          ) : null}

          <span className="spacer" />
          {category && data?.categories[category] ? (
            <span className="hint">{data.categories[category]}</span>
          ) : null}
        </div>

        {error ? <ErrorBox>{error}</ErrorBox> : null}
        {loading ? (
          <Loading label="Формирование очереди приоритетов…" />
        ) : !data || data.items.length === 0 ? (
          <EmptyState>В выбранной категории нет клиентов.</EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th className="sortable num" onClick={() => handleSort('id')}>
                      ID{renderSortIndicator('id')}
                    </th>
                    <th>Клиент</th>
                    <th className="sortable" onClick={() => handleSort('urgency')}>
                      Срочность{renderSortIndicator('urgency')}
                    </th>
                    <th>Рабочие очереди</th>
                    <th className="sortable" onClick={() => handleSort('riskScore')}>
                      Балл риска{renderSortIndicator('riskScore')}
                    </th>
                    <th className="sortable num" onClick={() => handleSort('exposure')}>
                      Под риском ({data.horizonDays} дн.){renderSortIndicator('exposure')}
                    </th>
                    <th className="num">Операц. просрочка</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item: PriorityItem) => {
                    const urgency = URGENCY_LABELS[item.urgencyRank] ?? URGENCY_LABELS[4]
                    const sharePct =
                      item.highRiskShare !== null && item.highRiskShare !== undefined
                        ? `${Math.round(item.highRiskShare * 100)}%`
                        : '—'
                    return (
                      <tr key={item.id}>
                        <td className="num">
                          <Link to={`/customers/${item.id}`} className="cell-primary">
                            {item.id}
                          </Link>
                        </td>
                        <td>
                          <div className="cell-primary">{item.email ?? '—'}</div>
                          <div className="cell-sub">
                            услуг: {item.serviceCount} · выс. риск: {item.highRiskServiceCount} (доля{' '}
                            {sharePct})
                          </div>
                        </td>
                        <td>
                          <span className={`badge ${urgency.cls}`}>{urgency.text}</span>
                        </td>
                        <td>
                          <div className="badge-stack">
                            {item.categories.map((cat) => (
                              <PriorityBadge
                                key={cat}
                                category={cat}
                                title={data.categories[cat]}
                              />
                            ))}
                          </div>
                        </td>
                        <td>
                          <ScoreCell score={item.riskScore} category={item.riskCategory} />
                        </td>
                        <td className="num">
                          <div>{formatEur(item.revenueAtRiskOnHorizon?.eur)}</div>
                          <div className="cell-sub">
                            из {formatEur(item.upcomingRenewalsOnHorizon?.eur)}
                          </div>
                        </td>
                        <td className="num">
                          {(item.overdueServiceCount ?? 0) > 0 ? (
                            <>
                              <div>{formatEur(item.overdueOperational?.eur)}</div>
                              <div className="cell-sub">
                                просрочено: {item.overdueServiceCount}
                                {(item.lifecycleInconsistentCount ?? 0) > 0
                                  ? ` · регл.: ${item.lifecycleInconsistentCount}`
                                  : ''}
                              </div>
                            </>
                          ) : (
                            <span className="cell-sub">нет</span>
                          )}
                        </td>
                        <td>
                          <Link className="btn sm" to={`/customers/${item.id}`}>
                            Карточка
                          </Link>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
