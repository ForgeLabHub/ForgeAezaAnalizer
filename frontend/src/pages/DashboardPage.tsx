import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { Summary } from '../types'
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

const CATEGORY_COLORS: Record<string, string> = {
  low: 'var(--risk-low-line)',
  medium: 'var(--risk-med-line)',
  high: 'var(--risk-high-line)',
  insufficient_data: 'var(--n-400)',
  not_applicable: 'var(--n-300)',
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await api.summary()
        if (!cancelled) setSummary(data)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить сводку')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <Loading label="Расчёт аналитики…" />
  if (error) return <ErrorBox>{error}</ErrorBox>
  if (!summary) return <EmptyState>Нет данных</EmptyState>

  const { customers, services, revenue } = summary

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Дашборд риска оттока</h1>
          <p>
            Горизонт прогноза — {summary.horizonDays} дн. Данные рассчитаны{' '}
            {formatDateTime(summary.generatedAt)} UTC. Балл риска — результат прозрачной
            взвешенной rule-based модели, а не откалиброванная вероятность оттока.
          </p>
        </div>
        <Link className="btn" to="/customers?riskCategory=high">
          Клиенты высокого риска
        </Link>
      </div>

      <div className="metric-grid">
        <Metric
          label="Проанализировано клиентов"
          value={customers.total}
          foot={`${customers.withRevenueAtRisk} с выручкой под риском`}
        />
        <Metric
          label="Открытых услуг"
          value={services.open}
          foot={`${services.concluded} в завершённом состоянии`}
        />
        <Metric
          label="Клиентов высокого риска"
          value={customers.highRisk}
          foot={`средний риск: ${customers.mediumRisk}`}
        />
        <Metric
          label="Выручка под риском"
          value={formatEur(revenue.revenueAtRiskEur, false)}
          unit="€"
          accent
          foot={`горизонт ${summary.horizonDays} дн.`}
        />
        <Metric
          label="Предстоящие продления"
          value={formatEur(revenue.upcomingRenewalsEur, false)}
          unit="€"
          small
          foot="сумма продлений в горизонте"
        />
        <Metric
          label="Исторические пополнения"
          value={formatEur(revenue.historicalReplenishedEur, false)}
          unit="€"
          small
          foot="справочно, не входит в выручку под риском"
        />
      </div>

      <div className="grid-2">
        <section className="card">
          <div className="card-head">
            <h2>Распределение клиентов по уровню риска</h2>
            <Link className="hint" to="/customers">
              Все клиенты →
            </Link>
          </div>
          <div className="card-body">
            <BarChart
              unit="клиентов"
              rows={[
                {
                  label: 'Высокий',
                  value: customers.byCategory.high ?? 0,
                  color: CATEGORY_COLORS.high,
                },
                {
                  label: 'Средний',
                  value: customers.byCategory.medium ?? 0,
                  color: CATEGORY_COLORS.medium,
                },
                { label: 'Низкий', value: customers.byCategory.low ?? 0, color: CATEGORY_COLORS.low },
                {
                  label: 'Недостаточно данных',
                  value: customers.byCategory.insufficient_data ?? 0,
                  color: CATEGORY_COLORS.insufficient_data,
                },
                {
                  label: 'Не применимо',
                  value: customers.byCategory.not_applicable ?? 0,
                  color: CATEGORY_COLORS.not_applicable,
                },
              ]}
            />
          </div>
          <div className="card-note">
            Категория «Не применимо» — все услуги клиента удалены или заблокированы: это известное
            состояние, а не прогноз.
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>Основные причины риска</h2>
            <span className="hint">по числу услуг</span>
          </div>
          <div className="card-body">
            <BarChart
              unit="услуг"
              emptyText="Ни один фактор риска не активен"
              rows={summary.topRiskReasons.map((r) => ({ label: r.label, value: r.count }))}
            />
          </div>
        </section>
      </div>

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <h2>Ближайшие продления в горизонте</h2>
            <span className="hint">{summary.upcomingRenewals.length} из ближайших</span>
          </div>
          {summary.upcomingRenewals.length === 0 ? (
            <EmptyState>
              В пределах горизонта {summary.horizonDays} дн. нет продлений открытых услуг.
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Клиент</th>
                    <th>Услуга</th>
                    <th>Дата продления (UTC)</th>
                    <th className="num">Стоимость</th>
                    <th>Риск</th>
                    <th className="num">Выручка под риском</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.upcomingRenewals.map((r) => (
                    <tr key={`${r.customerId}-${r.serviceId}`}>
                      <td>
                        <Link to={`/customers/${r.customerId}`} className="cell-primary">
                          #{r.customerId}
                        </Link>
                      </td>
                      <td className="mono">{r.serviceName}</td>
                      <td className="mono">{formatDateTime(r.renewalAt)}</td>
                      <td className="num">{formatEur(r.amountEur)}</td>
                      <td>
                        <ScoreCell score={r.riskScore} category={r.riskCategory} />
                      </td>
                      <td className="num">{formatEur(r.revenueAtRiskEur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h2>Статусы услуг</h2>
            </div>
            <div className="card-body">
              <dl className="kv">
                <dt>Всего услуг</dt>
                <dd>{services.total}</dd>
                <dt>Активные</dt>
                <dd>{services.byStatus.active ?? 0}</dd>
                <dt>Ожидают продления</dt>
                <dd>{services.byStatus.prolong_wait ?? 0}</dd>
                <dt>Приостановлены</dt>
                <dd>{services.byStatus.suspended ?? 0}</dd>
                <dt>Заблокированы</dt>
                <dd>{services.byStatus.blocked ?? 0}</dd>
                <dt>Удалены</dt>
                <dd>{services.byStatus.deleted ?? 0}</dd>
              </dl>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Модель и данные</h2>
            </div>
            <div className="card-body stack" style={{ gap: 10 }}>
              <div className="notice warn">
                <strong>Динамика недоступна.</strong> {summary.historyNote}
              </div>
              <div className="notice">
                <strong>Ограничение модели.</strong> {summary.model.note}
              </div>
              <div className="notice info">
                Выручка под риском рассчитывается отдельно от баланса клиента:{' '}
                <code>стоимость продления × балл риска / 100</code> и только для продлений внутри
                горизонта.
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
