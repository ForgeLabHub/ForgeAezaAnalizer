import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { CustomerDetail, ServiceItem } from '../types'
import { AIAnalystPanel } from '../components/AIAnalystPanel'
import { RetentionActions } from '../components/RetentionActions'
import {
  EmptyState,
  ErrorBox,
  Loading,
  Metric,
  RiskBadge,
  ScoreCell,
  StatusBadge,
  formatDateTime,
  formatDays,
  formatEur,
} from '../components/ui'

function ServiceCard({ service }: { service: ServiceItem }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="row" style={{ gap: 8 }}>
            <h3>{service.name}</h3>
            <StatusBadge status={service.status} label={service.statusLabel} />
            <span className="badge neutral">{service.paymentTermLabel}</span>
            <span className="badge neutral">
              {service.autoProlong ? 'Автопродление вкл.' : 'Автопродление выкл.'}
            </span>
          </div>
          <div className="cell-sub" style={{ marginTop: 5 }}>
            Услуга #{service.id} · истекает {formatDateTime(service.expiresAt)} UTC ·{' '}
            {formatDays(service.daysToExpiry)} до окончания
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <ScoreCell score={service.riskScore} category={service.riskCategory} />
          <div style={{ marginTop: 5 }}>
            <RiskBadge category={service.riskCategory} label={service.riskCategoryLabel} />
          </div>
        </div>
      </div>

      <div className="card-body stack" style={{ gap: 12 }}>
        {!service.eligibleForForecast ? (
          <div className="notice warn">{service.stateNote}</div>
        ) : null}

        <div className="grid-2" style={{ gap: 16 }}>
          <dl className="kv">
            <dt>Стоимость продления</dt>
            <dd>{formatEur(service.price.eur)}</dd>
            <dt>Выручка под риском</dt>
            <dd>{service.revenueAtRisk ? formatEur(service.revenueAtRisk.eur) : '—'}</dd>
            <dt>Ближайшее продление</dt>
            <dd>
              {service.upcomingRenewalAt ? formatDateTime(service.upcomingRenewalAt) : 'вне горизонта'}
            </dd>
          </dl>
          <div>
            <div className="section-title">Причины оценки</div>
            {service.reasons.length ? (
              <ul className="reasons">
                {service.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : (
              <p className="hint">Существенных сигналов риска по услуге не обнаружено.</p>
            )}
          </div>
        </div>

        {service.recommendations.length ? (
          <div>
            <div className="section-title">Рекомендуемые действия</div>
            <div className="rec-list">
              {service.recommendations.map((rec) => (
                <div className={`rec prio-${rec.priority}`} key={rec.code}>
                  <div className="rec-title">{rec.title}</div>
                  <div className="rec-detail">{rec.detail}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {service.missingData.length ? (
          <div className="notice">
            <strong>Недостаточно данных:</strong> {service.missingData.join(', ')}. Соответствующие
            факторы исключены из расчёта, веса перенормированы.
          </div>
        ) : null}

        <div>
          <button type="button" className="btn sm" onClick={() => setOpen((v) => !v)}>
            {open ? 'Скрыть факторы' : `Показать все факторы (${service.factors.length})`}
          </button>
        </div>

        {open ? (
          <div>
            {service.factors.map((factor) => (
              <div className={`factor${factor.available ? '' : ' muted'}`} key={factor.key}>
                <span className="factor-name">{factor.label}</span>
                <span className="factor-meta">
                  {factor.value === null ? 'нет данных' : `знач. ${factor.value.toFixed(2)}`} · вес{' '}
                  {factor.weight} · вклад {factor.contribution.toFixed(2)}
                </span>
                <div className="bar-track">
                  <span
                    style={{
                      width: `${Math.min(100, (factor.value ?? 0) * 100)}%`,
                      background: factor.available ? 'var(--brand-500)' : 'var(--n-300)',
                    }}
                  />
                </div>
                <span className="factor-reason">{factor.reason}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [customer, setCustomer] = useState<CustomerDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [onlyAtRisk, setOnlyAtRisk] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await api.customer(Number(id))
        if (!cancelled) setCustomer(data)
      } catch (err) {
        if (!cancelled)
          setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить карточку клиента')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    if (id) void load()
    return () => {
      cancelled = true
    }
  }, [id])

  if (loading) return <Loading label="Загрузка карточки клиента…" />
  if (error) return <ErrorBox>{error}</ErrorBox>
  if (!customer) return <EmptyState>Клиент не найден</EmptyState>

  const forecastServices = customer.services.filter((s) => s.eligibleForForecast)
  const visible = onlyAtRisk
    ? customer.services.filter((s) => s.riskCategory === 'high' || s.riskCategory === 'medium')
    : customer.services

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="row" style={{ gap: 10 }}>
            <h1>Клиент #{customer.id}</h1>
            <RiskBadge category={customer.riskCategory} label={customer.riskCategoryLabel} />
          </div>
          <p>
            {customer.email} · {customer.serviceCount} услуг, из них {customer.eligibleServiceCount}{' '}
            пригодны для прогноза оттока
          </p>
        </div>
        <Link className="btn" to="/customers">
          ← К списку клиентов
        </Link>
      </div>

      {customer.stateNote ? <div className="notice warn">{customer.stateNote}</div> : null}

      <div className="metric-grid">
        <Metric
          label="Балл риска клиента"
          value={customer.riskScore === null ? '—' : customer.riskScore.toFixed(1)}
          unit={customer.riskScore === null ? undefined : '/ 100'}
          foot="максимум по услугам в прогнозе"
        />
        <Metric
          label="Услуг высокого риска"
          value={customer.highRiskServiceCount}
          foot={`из ${customer.eligibleServiceCount} в прогнозе`}
        />
        <Metric
          label="Выручка под риском"
          value={formatEur(customer.revenueAtRisk.eur, false)}
          unit="€"
          accent
          foot="в пределах горизонта"
        />
        <Metric
          label="Предстоящие продления"
          value={formatEur(customer.upcomingRenewals.eur, false)}
          unit="€"
          small
        />
      </div>

      <div className="grid-main">
        <div className="stack">
          <div className="row">
            <h2>Услуги клиента</h2>
            <span className="spacer" />
            <label className="hint row" style={{ gap: 6, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={onlyAtRisk}
                onChange={(e) => setOnlyAtRisk(e.target.checked)}
              />
              только средний и высокий риск
            </label>
          </div>
          {visible.length === 0 ? (
            <EmptyState>
              {onlyAtRisk
                ? 'У клиента нет услуг среднего или высокого риска.'
                : 'У клиента нет услуг.'}
            </EmptyState>
          ) : (
            visible.map((service) => <ServiceCard key={service.id} service={service} />)
          )}
        </div>

        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h2>Финансовые показатели</h2>
            </div>
            <div className="card-body">
              <dl className="kv">
                <dt>Баланс</dt>
                <dd>{formatEur(customer.balance.eur)}</dd>
                <dt>Доступно к выводу</dt>
                <dd>{formatEur(customer.withdrawBalance.eur)}</dd>
                <dt>Бонусный баланс</dt>
                <dd>{formatEur(customer.bonusBalance.eur)}</dd>
                <dt>Статус бонусов</dt>
                <dd>{customer.bonusState === 'locked' ? 'Заблокированы' : 'Разблокированы'}</dd>
                <dt>Всего пополнено</dt>
                <dd>{formatEur(customer.totalReplenished.eur)}</dd>
              </dl>
              <div className="notice" style={{ marginTop: 12 }}>
                Баланс и исторические пополнения не входят в выручку под риском — это разные
                величины.
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Почему клиент в этой группе</h2>
            </div>
            <div className="card-body">
              {customer.reasons.length ? (
                <ul className="reasons">
                  {customer.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : (
                <p className="hint">
                  Существенных сигналов риска не обнаружено по услугам, пригодным для прогноза.
                </p>
              )}
              {Object.keys(customer.concludedStates).length ? (
                <div className="notice" style={{ marginTop: 12 }}>
                  Завершённые состояния (не прогноз):{' '}
                  {Object.entries(customer.concludedStates)
                    .map(([status, count]) => `${status} — ${count}`)
                    .join(', ')}
                </div>
              ) : null}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Продления в горизонте</h2>
            </div>
            <div className="card-body">
              {customer.renewalDetails.length ? (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Услуга</th>
                        <th>Дата (UTC)</th>
                        <th className="num">Стоимость</th>
                        <th className="num">Под риском</th>
                      </tr>
                    </thead>
                    <tbody>
                      {customer.renewalDetails.map((r) => (
                        <tr key={r.serviceId}>
                          <td className="mono">#{r.serviceId}</td>
                          <td className="mono">{formatDateTime(r.renewalAt)}</td>
                          <td className="num">{formatEur(r.amount.eur)}</td>
                          <td className="num">{formatEur(r.revenueAtRisk.eur)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="hint">В пределах горизонта нет продлений по открытым услугам.</p>
              )}
            </div>
          </section>

          <RetentionActions customer={customer} />

          {forecastServices.length === 0 ? (
            <div className="notice warn">
              Ни одна услуга клиента не пригодна для прогноза оттока: все они удалены или
              заблокированы.
            </div>
          ) : null}

          <AIAnalystPanel customerId={customer.id} />
        </div>
      </div>
    </div>
  )
}
