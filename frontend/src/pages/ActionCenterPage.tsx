import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { PriorityItem, PriorityResponse, PriorityTier } from '../types'
import {
  BarChart,
  EmptyState,
  ErrorBox,
  Loading,
  Metric,
  ScoreCell,
  formatDateTime,
  formatEur,
} from '../components/ui'

const TIER_ORDER: PriorityTier[] = ['p1', 'p2', 'p3']

const TIER_COLORS: Record<PriorityTier, string> = {
  p1: 'var(--risk-high-line)',
  p2: 'var(--risk-med-line)',
  p3: 'var(--n-400)',
}

const STATUS_LABELS: Record<string, string> = {
  active: 'Активна',
  suspended: 'Приостановлена',
  prolong_wait: 'Ожидает продления',
  deleted: 'Удалена',
  blocked: 'Заблокирована',
}

function TierBadge({ tier, label }: { tier: PriorityTier; label: string }) {
  return <span className={`badge tier-${tier}`}>{label}</span>
}

function PriorityCell({ value }: { value: number }) {
  return (
    <div className="row" style={{ gap: 8 }}>
      <span className="score">
        <span className="val">{value.toFixed(1)}</span>
      </span>
      <span className="score-bar" aria-hidden="true">
        <span style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
      </span>
    </div>
  )
}

export default function ActionCenterPage() {
  const [data, setData] = useState<PriorityResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tier, setTier] = useState<PriorityTier | ''>('')
  const [sort, setSort] = useState<'priority' | 'risk'>('priority')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.priority({
          tier: tier || undefined,
          sort,
          limit: 100,
        })
        if (!cancelled) setData(result)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить приоритеты')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [tier, sort])

  const actions = useMemo(() => {
    if (!data) return []
    const counts = new Map<string, number>()
    for (const item of data.items) {
      for (const action of item.actions) counts.set(action, (counts.get(action) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([label, value]) => ({ label, value }))
  }, [data])

  if (loading) return <Loading label="Построение списка приоритетов…" />
  if (error) return <ErrorBox>{error}</ErrorBox>
  if (!data) return <EmptyState>Нет данных</EmptyState>

  const { summary } = data

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Центр действий: кого удерживать первым</h1>
          <p>
            Рабочий список по ожидаемой экспозиции: риск-взвешенная стоимость продлений внутри
            горизонта {data.horizonDays ?? '—'} дн. Список строится из опубликованного расчёта,
            поэтому совпадает с дашбордом и карточкой клиента.
          </p>
        </div>
        <Link className="btn" to="/settings">
          Настроить модель
        </Link>
      </div>

      <div className="metric-grid">
        <Metric
          label="Позиций в списке"
          value={summary.items}
          foot={`${summary.customers} клиентов · ${summary.servicesScored} из ${summary.servicesInPortfolio} услуг оценены`}
        />
        <Metric
          label="Выручка под риском"
          value={formatEur(summary.revenueAtRiskEur, false)}
          unit="€"
          accent
          foot="сумма по позициям списка"
        />
        {TIER_ORDER.map((t) => (
          <Metric
            key={t}
            label={summary.tierLabels[t] ?? t}
            value={summary.byTier[t] ?? 0}
            small
            foot={summary.tierDescriptions[t] ?? ''}
          />
        ))}
      </div>

      <div className="notice">
        <strong>Как читать приоритет.</strong> {summary.note} Балл риска услуги при этом не
        зависит от её цены: дорогая услуга не становится рискованной только из-за стоимости.
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Фильтры</h2>
          <span className="hint">пересчёт без перезагрузки страницы</span>
        </div>
        <div className="card-body row" style={{ gap: 16, flexWrap: 'wrap' }}>
          <label className="field">
            <span>Уровень срочности</span>
            <select
              className="select"
              value={tier}
              onChange={(event) => setTier(event.target.value as PriorityTier | '')}
            >
              <option value="">Все уровни</option>
              {TIER_ORDER.map((t) => (
                <option key={t} value={t}>
                  {summary.tierLabels[t] ?? t} ({summary.byTier[t] ?? 0})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Порядок сортировки</span>
            <select
              className="select"
              value={sort}
              onChange={(event) => setSort(event.target.value as 'priority' | 'risk')}
            >
              <option value="priority">По ожидаемой экспозиции (по умолчанию)</option>
              <option value="risk">По баллу риска</option>
            </select>
          </label>
        </div>
        <div className="card-note">
          «По ожидаемой экспозиции» отвечает на вопрос «где мы теряем больше денег», «по баллу
          риска» — «кого мы теряем вероятнее». Ни один из режимов не меняет сами оценки.
        </div>
      </div>

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <h2>Рабочий список</h2>
            <span className="hint">{data.items.length} позиций</span>
          </div>
          {data.items.length === 0 ? (
            <EmptyState>
              Нет услуг с рассчитанным риском в выбранном уровне срочности. Измените фильтр или
              проверьте веса модели в настройках.
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Уровень</th>
                    <th>Клиент</th>
                    <th>Услуга</th>
                    <th>Продление (UTC)</th>
                    <th className="num">Стоимость</th>
                    <th>Риск</th>
                    <th className="num">Экспозиция</th>
                    <th className="num">Приоритет</th>
                    <th>Рекомендации</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={`${item.customerId}-${item.serviceId}`}>
                      <td className="num mono">{item.rank}</td>
                      <td>
                        <TierBadge tier={item.tier} label={item.tierLabel} />
                      </td>
                      <td>
                        <Link to={`/customers/${item.customerId}`} className="cell-primary">
                          #{item.customerId}
                        </Link>
                        <div className="cell-sub">{item.email}</div>
                      </td>
                      <td className="mono">
                        {item.serviceName}
                        <div className="cell-sub">
                          {STATUS_LABELS[item.serviceStatus] ?? item.serviceStatus}
                        </div>
                      </td>
                      <td className="mono">
                        {item.renewalAt ? formatDateTime(item.renewalAt) : '—'}
                        {item.daysToExpiry !== null ? (
                          <div className="cell-sub">{item.daysToExpiry.toFixed(1)} дн.</div>
                        ) : null}
                      </td>
                      <td className="num">
                        {item.renewalAmount?.eur ? formatEur(item.renewalAmount.eur) : '—'}
                      </td>
                      <td>
                        <ScoreCell score={item.riskScore} category={item.riskCategory} />
                      </td>
                      <td className="num">{formatEur(item.revenueAtRisk.eur)}</td>
                      <td className="num">
                        <PriorityCell value={item.priorityScore} />
                      </td>
                      <td>
                        <ul className="reasons">
                          {item.actions.length === 0 ? (
                            <li className="cell-sub">—</li>
                          ) : (
                            item.actions.slice(0, 2).map((action) => <li key={action}>{action}</li>)
                          )}
                        </ul>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="card-note">
            Экспозиция — это риск-взвешенная доля стоимости продления, попадающего в горизонт. Это
            не потерянная выручка и не баланс клиента.
          </div>
        </section>

        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h2>Что делать</h2>
              <span className="hint">по позициям списка</span>
            </div>
            <div className="card-body">
              <BarChart
                unit="услуг"
                emptyText="Рекомендаций нет: список пуст"
                rows={actions.map((row) => ({ label: row.label, value: row.value }))}
              />
            </div>
            <div className="card-note">
              Рекомендации формируются по фактическим сигналам данных. Они не гарантируют
              предотвращение оттока и не отправляются клиентам автоматически.
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Распределение по уровням</h2>
            </div>
            <div className="card-body">
              <BarChart
                unit="позиций"
                rows={TIER_ORDER.map((t) => ({
                  label: summary.tierLabels[t] ?? t,
                  value: summary.byTier[t] ?? 0,
                  color: TIER_COLORS[t],
                  title: summary.tierDescriptions[t] ?? '',
                }))}
              />
            </div>
          </section>
        </div>
      </div>

      <details className="card">
        <summary className="card-head" style={{ cursor: 'pointer' }}>
          <h2>Почему у этих услуг такой риск</h2>
          <span className="hint">первые три причины по каждой позиции</span>
        </summary>
        <div className="card-body stack">
          {data.items.slice(0, 15).map((item: PriorityItem) => (
            <div className="factor" key={`why-${item.customerId}-${item.serviceId}`}>
              <div className="factor-name">
                #{item.rank} · {item.email} · <span className="mono">{item.serviceName}</span>
              </div>
              <div className="factor-reason">{item.tierReason}</div>
              <ul className="reasons">
                {item.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          ))}
          {data.items.length === 0 ? <EmptyState>Нет позиций для объяснения</EmptyState> : null}
        </div>
      </details>
    </div>
  )
}
