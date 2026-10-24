import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { ActionWorkflowStatus, PriorityItem, PriorityResponse } from '../types'
import { EmptyState, ErrorBox, Loading, Metric, RiskBadge, formatEur } from '../components/ui'

const STATUS_LABELS: Record<ActionWorkflowStatus, string> = {
  new: 'Новое',
  in_progress: 'В работе',
  done: 'Выполнено',
}

const STATUS_ORDER: ActionWorkflowStatus[] = ['new', 'in_progress', 'done']

const CATEGORY_LABELS: Record<string, string> = {
  operational_attention: 'Операционная проблема',
  high_risk_with_exposure: 'Высокий риск с экспозицией',
  high_risk_review: 'Высокий риск без экспозиции',
  data_quality_review: 'Проверка качества данных',
  normal_review: 'Плановый обзор',
}

const LEVEL_CLASS: Record<string, string> = {
  operational_attention: 'risk-high',
  high_risk_with_exposure: 'risk-medium',
  high_risk_review: '',
  data_quality_review: '',
  normal_review: '',
}

const CATEGORY_ORDER = [
  'operational_attention',
  'high_risk_with_exposure',
  'high_risk_review',
  'data_quality_review',
  'normal_review',
]

type SortKey = 'urgency' | 'riskScore' | 'exposure' | 'id'

export default function ActionCenterPage() {
  const [data, setData] = useState<PriorityResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [category, setCategory] = useState<string>('')
  const [sortBy, setSortBy] = useState<SortKey>('urgency')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [horizon, setHorizon] = useState<number | ''>('')
  const [savingAction, setSavingAction] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.priority({
          category: category || undefined,
          sortBy,
          sortDir,
          horizonDays: typeof horizon === 'number' ? horizon : undefined,
        })
        if (!cancelled) setData(result)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить очередь')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [category, sortBy, sortDir, horizon, reloadToken])

  const items = data?.items ?? []

  /** Persist one workflow change. The queue is refetched so the row reflects
   *  exactly what the server stored rather than an optimistic guess. */
  async function setActionStatus(
    customerId: number,
    code: string,
    status: ActionWorkflowStatus,
  ) {
    const key = `${customerId}:${code}`
    setSavingAction(key)
    setActionError(null)
    try {
      await api.updateActionStatus({ customerId, code, status })
      setReloadToken((value) => value + 1)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.detail : 'Не удалось сохранить статус действия',
      )
    } finally {
      setSavingAction(null)
    }
  }

  const tierCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const item of items) {
      for (const key of item.categories) counts[key] = (counts[key] ?? 0) + 1
    }
    return counts
  }, [items])

  const exposureTotal = useMemo(
    () => items.reduce((sum, i) => sum + (i.revenueAtRiskOnHorizon?.cents ?? 0), 0),
    [items],
  )
  const renewalTotal = useMemo(
    () => items.reduce((sum, i) => sum + (i.upcomingRenewalsOnHorizon?.cents ?? 0), 0),
    [items],
  )
  const overdueTotal = useMemo(
    () => items.reduce((sum, i) => sum + (i.overdueOperational?.cents ?? 0), 0),
    [items],
  )

  const byCategory = useMemo(() => {
    const groups = new Map<string, PriorityItem[]>()
    for (const key of CATEGORY_ORDER) groups.set(key, [])
    for (const item of items) {
      const primary =
        CATEGORY_ORDER.find((key) => item.categories.includes(key)) ?? 'normal_review'
      groups.get(primary)?.push(item)
    }
    return groups
  }, [items])

  const workflowCounts = useMemo(() => {
    const counts: Record<ActionWorkflowStatus, number> = { new: 0, in_progress: 0, done: 0 }
    for (const item of items) {
      for (const action of item.actions ?? []) counts[action.status] += 1
    }
    return counts
  }, [items])

  function toggleSort(next: SortKey) {
    if (next === sortBy) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(next)
      setSortDir(next === 'urgency' ? 'asc' : 'desc')
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Центр действий</h1>
          <p>
            Очередь удержания на горизонте {data?.horizonDays ?? '—'} дн. Риск, финансовая
            экспозиция, операционная срочность и качество данных показаны раздельно:
            категория организует работу и не является вероятностью оттока.
          </p>
        </div>
        <Link className="btn" to="/what-if">
          Лаборатория сценариев
        </Link>
      </div>

      {error && <ErrorBox>{error}</ErrorBox>}
      {loading && !data && <Loading label="Расчёт приоритетов…" />}

      {data && (
        <>
          <div className="metric-grid">
            <Metric label="Позиций в очереди" value={data.total} />
            <Metric label="Клиентов затронуто" value={new Set(items.map((i) => i.id)).size} />
            <Metric
              label="Выручка под риском"
              value={formatEur((exposureTotal / 100).toFixed(2))}
              foot="на выбранном горизонте"
            />
            <Metric
              label="Предстоящие продления"
              value={formatEur((renewalTotal / 100).toFixed(2))}
              foot="всего, не только под риском"
            />
            <Metric
              label="Просрочено"
              value={formatEur((overdueTotal / 100).toFixed(2))}
              foot="операционная задолженность"
            />
            <Metric
              label="Действий в работе"
              value={workflowCounts.in_progress}
              foot={`новых: ${workflowCounts.new} · выполнено: ${workflowCounts.done}`}
            />
          </div>

          {actionError && <ErrorBox>{actionError}</ErrorBox>}

          <div className="card">
            <div className="row" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <label className="field">
                <span>Категория</span>
                <select value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">Все категории</option>
                  {CATEGORY_ORDER.map((key) => (
                    <option key={key} value={key}>
                      {CATEGORY_LABELS[key] ?? key} ({tierCounts[key] ?? 0})
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Горизонт, дней</span>
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={horizon}
                  placeholder="30"
                  onChange={(e) => setHorizon(e.target.value === '' ? '' : Number(e.target.value))}
                />
              </label>
              <div className="row" style={{ gap: 6 }}>
                {(
                  [
                    ['urgency', 'Срочность'],
                    ['riskScore', 'Риск'],
                    ['exposure', 'Экспозиция'],
                    ['id', 'ID'],
                  ] as Array<[SortKey, string]>
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={`btn sm${sortBy === key ? ' primary' : ''}`}
                    onClick={() => toggleSort(key)}
                  >
                    {label}
                    {sortBy === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                  </button>
                ))}
              </div>
            </div>
            <p className="hint">{data.note}</p>
          </div>

          {items.length === 0 ? (
            <EmptyState>По выбранной категории позиций нет.</EmptyState>
          ) : (
            CATEGORY_ORDER.map((key) => {
              const group = byCategory.get(key) ?? []
              if (!group.length) return null
              return (
                <div className="card" key={key}>
                  <div className="card-head">
                    <h2>
                      <span className={`badge ${LEVEL_CLASS[key] ?? ''}`}>
                        {CATEGORY_LABELS[key] ?? key}
                      </span>{' '}
                      <span className="hint">— {group.length}</span>
                    </h2>
                    <p className="hint">{data.categories[key]}</p>
                  </div>
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Клиент</th>
                          <th>Риск</th>
                          <th>Категория риска</th>
                          <th>Услуг</th>
                          <th>Высокий риск</th>
                          <th>Выручка под риском</th>
                          <th>Продления</th>
                          <th>Просрочено</th>
                          <th>Категории</th>
                          <th>Действия по удержанию</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.map((item) => (
                          <tr key={`${key}-${item.id}`}>
                            <td>
                              <Link to={`/customers/${item.id}`}>#{item.id}</Link>
                              <div className="hint">{item.email}</div>
                            </td>
                            <td className="num mono">{item.riskScore === null ? '—' : item.riskScore.toFixed(1)}</td>
                            <td><RiskBadge category={item.riskCategory} /></td>
                            <td className="num">{item.serviceCount}</td>
                            <td className="num">{item.highRiskServiceCount}</td>
                            <td className="num">{item.revenueAtRiskOnHorizon ? formatEur(item.revenueAtRiskOnHorizon.eur) : '—'}</td>
                            <td className="num">{item.upcomingRenewalsOnHorizon ? formatEur(item.upcomingRenewalsOnHorizon.eur) : '—'}</td>
                            <td className="num">{item.overdueOperational ? formatEur(item.overdueOperational.eur) : '—'}</td>
                            <td>
                              <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
                                {item.categories.map((c) => (
                                  <span className="badge" key={c}>
                                    {CATEGORY_LABELS[c] ?? c}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td>
                              {item.actions.length === 0 ? (
                                <span className="hint">—</span>
                              ) : (
                                <div className="stack" style={{ gap: 6 }}>
                                  {item.actions.map((action) => (
                                    <div key={action.code} className="action-row">
                                      <div className="action-title" title={action.detail}>
                                        {action.title}
                                      </div>
                                      <select
                                        aria-label={`Статус: ${action.title}`}
                                        value={action.status}
                                        disabled={savingAction === `${item.id}:${action.code}`}
                                        onChange={(e) =>
                                          void setActionStatus(
                                            item.id,
                                            action.code,
                                            e.target.value as ActionWorkflowStatus,
                                          )
                                        }
                                      >
                                        {STATUS_ORDER.map((status) => (
                                          <option key={status} value={status}>
                                            {STATUS_LABELS[status]}
                                          </option>
                                        ))}
                                      </select>
                                      {action.updatedAt && (
                                        <span className="hint">
                                          {new Date(action.updatedAt).toLocaleString('ru-RU')}
                                          {action.updatedBy ? ` · ${action.updatedBy}` : ''}
                                        </span>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )
            })
          )}
        </>
      )}
    </div>
  )
}
