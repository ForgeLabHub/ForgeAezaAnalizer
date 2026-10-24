import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useAnalysis } from '../lib/realtime'
import type { CustomerDetail, OverdueDetailItem, ServiceItem } from '../types'
import { RetentionActions } from '../components/RetentionActions'
import { Collapsible } from '../components/motion'
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

  const autoProlongLabel =
    service.autoProlong === true
      ? 'Автопродление вкл.'
      : service.autoProlong === false
        ? 'Автопродление выкл.'
        : 'Автопродление: нет данных'

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="row" style={{ gap: 8 }}>
            <h3>{service.name}</h3>
            <StatusBadge status={service.status} label={service.statusLabel} />
            <span className="badge neutral">{service.paymentTermLabel}</span>
            <span className="badge neutral">{autoProlongLabel}</span>
          </div>
          <div className="cell-sub" style={{ marginTop: 5 }}>
            Услуга #{service.id} · создана {formatDateTime(service.createdAt)} UTC · истекает{' '}
            {formatDateTime(service.expiresAt)} UTC ·{' '}
            {service.daysToExpiry !== null && service.daysToExpiry < 0
              ? `просрочена на ${formatDays(Math.abs(service.daysToExpiry))}`
              : `${formatDays(service.daysToExpiry)} до окончания`}
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

        {service.factors.length > 0 ? (
          <div>
            <button
              type="button"
              className="btn sm"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              {open ? 'Скрыть факторы' : `Показать все факторы (${service.factors.length})`}
            </button>
            <Collapsible open={open}>
              <div style={{ paddingTop: 12 }}>
                {service.factors.map((factor) => {
                  const isDeprecated = Boolean(factor.deprecated)
                  return (
                    <div
                      className={`factor${factor.available && !isDeprecated ? '' : ' muted'}`}
                      key={factor.key}
                    >
                      <span className="factor-name">
                        {factor.label}{' '}
                        {isDeprecated ? (
                          <span className="badge neutral" style={{ marginLeft: 4 }}>
                            диагностика · вне рейтинга
                          </span>
                        ) : null}
                      </span>
                      <span className="factor-meta">
                        {factor.value === null
                          ? 'нет данных'
                          : isDeprecated
                            ? `кол-во ${factor.value.toFixed(0)}`
                            : `знач. ${factor.value.toFixed(2)}`}{' '}
                        · вес {factor.weight} · вклад {factor.contribution.toFixed(2)}
                      </span>
                      {!isDeprecated ? (
                        <div className="bar-track">
                          <span
                            style={{
                              width: `${Math.min(100, Math.max(0, (factor.value ?? 0) * 100))}%`,
                              background: factor.available ? 'var(--brand-500)' : 'var(--n-300)',
                            }}
                          />
                        </div>
                      ) : null}
                      <span className="factor-reason">{factor.reason}</span>
                    </div>
                  )
                })}
              </div>
            </Collapsible>
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { activeGeneration, refreshKey } = useAnalysis()
  const [customer, setCustomer] = useState<CustomerDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await api.customer(Number(id), activeGeneration)
        if (!cancelled) setCustomer(data)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить карточку клиента')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    if (id) void load()
    return () => {
      cancelled = true
    }
  }, [id, activeGeneration, refreshKey])

  const overdueItems: OverdueDetailItem[] = useMemo(() => {
    if (!customer) return []
    if (customer.overdueDetails && customer.overdueDetails.length > 0) {
      return customer.overdueDetails
    }
    // Fallback derivation when reading older stored snapshots without overdueDetails.
    return customer.services
      .filter((s) => s.eligibleForForecast && s.daysToExpiry !== null && s.daysToExpiry < 0)
      .map((s) => {
        const daysOverdue = Math.abs(s.daysToExpiry ?? 0)
        return {
          serviceId: s.id,
          status: s.status,
          statusLabel: s.statusLabel,
          expiredAt: s.expiresAt ?? '',
          daysOverdue,
          amount: s.price,
          lifecycleInconsistent: s.status === 'prolong_wait' && daysOverdue > 5,
        }
      })
  }, [customer])

  if (loading) return <Loading label="Загрузка карточки клиента…" />
  if (error) return <ErrorBox>{error}</ErrorBox>
  if (!customer) return <EmptyState>Клиент не найден</EmptyState>

  const forecastServices = customer.services.filter((s) => s.eligibleForForecast)

  const highShareText =
    customer.highRiskShare !== undefined && customer.eligibleServiceCount > 0
      ? ` · доля ${Math.round(customer.highRiskShare * 100)}%`
      : ''

  const bonusLabel =
    customer.bonusState === 'locked'
      ? 'Заблокированы'
      : customer.bonusState === 'unlocked'
        ? 'Разблокированы (доступны для оплаты)'
        : 'Нет данных (не учитываются)'

  const overdueCount = customer.overdueServiceCount ?? overdueItems.length
  const inconsistentCount =
    customer.lifecycleInconsistentCount ??
    overdueItems.filter((item) => item.lifecycleInconsistent).length

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <div className="row page-title-row" style={{ gap: 10 }}>
            <h1>Клиент #{customer.id}</h1>
            <span className="badge neutral">{customer.email}</span>
            <RiskBadge category={customer.riskCategory} label={customer.riskCategoryLabel} />
            {inconsistentCount > 0 ? (
              <span className="badge risk-high">
                <span className="dot" aria-hidden="true" />
                Нарушение регламента ({inconsistentCount})
              </span>
            ) : null}
          </div>
        </div>
        <div className="row">
          <Link className="btn" to="/priority">
            Очередь приоритетов
          </Link>
          <Link className="btn" to="/customers">
            ← К списку клиентов
          </Link>
        </div>
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
          foot={`из ${customer.eligibleServiceCount} в прогнозе${highShareText}`}
        />
        <Metric
          label="Выручка под риском"
          value={formatEur(customer.revenueAtRisk.eur, false)}
          unit={customer.revenueAtRisk.eur !== null ? '€' : undefined}
          accent
          foot="в пределах горизонта"
        />
        <Metric
          label="Предстоящие продления"
          value={formatEur(customer.upcomingRenewals.eur, false)}
          unit={customer.upcomingRenewals.eur !== null ? '€' : undefined}
          small
          foot="номинальная сумма продлений"
        />
        <Metric
          label="Операционная просрочка"
          value={
            customer.overdueOperational
              ? formatEur(customer.overdueOperational.eur, false)
              : overdueCount > 0
                ? String(overdueCount)
                : '0,00'
          }
          unit={customer.overdueOperational?.eur !== null ? '€' : undefined}
          small
          foot={
            overdueCount > 0
              ? `${overdueCount} откр. услуг уже истекло`
              : 'нет просроченных откр. услуг'
          }
        />
      </div>

      <div className="row">
        <h2>Услуги клиента</h2>
      </div>

      <div className="grid-main">
        <div className="stack">
          {customer.services.length === 0 ? (
            <EmptyState>У клиента нет услуг.</EmptyState>
          ) : (
            customer.services.map((svc) => <ServiceCard key={svc.id} service={svc} />)
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
                <dd>{bonusLabel}</dd>
                <dt>Всего пополнено</dt>
                <dd>{formatEur(customer.totalReplenished.eur)}</dd>
              </dl>
              <div className="notice" style={{ marginTop: 12 }}>
                Баланс, реферальный баланс к выводу и исторические пополнения не входят в выручку
                под риском — это разные величины.
              </div>
            </div>
          </section>

          {customer.exposureByHorizon && customer.exposureByHorizon.length > 0 ? (
            <section className="card">
              <div className="card-head">
                <h2>Экспозиция по горизонтам</h2>
                <span className="hint">7 / 30 / 90 дн.</span>
              </div>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Горизонт</th>
                      <th className="num">Услуг</th>
                      <th className="num">Продления</th>
                      <th className="num">Под риском</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customer.exposureByHorizon.map((h) => (
                      <tr key={h.horizonDays}>
                        <td className="mono">{h.horizonDays} дн.</td>
                        <td className="num">{h.renewalCount}</td>
                        <td className="num">{formatEur(h.upcomingRenewals.eur)}</td>
                        <td className="num">{formatEur(h.revenueAtRisk.eur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="card-note">
                Каждое продление учитывается в горизонте не более одного раза.
              </div>
            </section>
          ) : null}

          {overdueItems.length > 0 ? (
            <section className="card">
              <div className="card-head">
                <h2>Просроченные открытые услуги</h2>
                <span className="badge risk-high">{overdueItems.length}</span>
              </div>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Услуга</th>
                      <th>Статус</th>
                      <th className="num">Просрочка</th>
                      <th className="num">Номинал</th>
                    </tr>
                  </thead>
                  <tbody>
                    {overdueItems.map((item) => (
                      <tr key={item.serviceId}>
                        <td className="mono">
                          #{item.serviceId}
                          {item.lifecycleInconsistent ? (
                            <div className="cell-sub" style={{ color: 'var(--risk-high-fg)' }}>
                              &gt; 5 дн. prolong_wait
                            </div>
                          ) : null}
                        </td>
                        <td>
                          <StatusBadge status={item.status} label={item.statusLabel} />
                        </td>
                        <td className="num">{item.daysOverdue.toFixed(1)} дн.</td>
                        <td className="num">{formatEur(item.amount.eur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="card-note">
                Срок действия этих открытых услуг уже прошёл: они не включаются в прогноз будущих
                продлений, но требуют операционной проверки.
              </div>
            </section>
          ) : null}

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
              {customer.missingData.length ? (
                <div className="notice" style={{ marginTop: 12 }}>
                  <strong>Отсутствующие сигналы по портфелю:</strong>{' '}
                  {customer.missingData.join(', ')}. Неизвестные факторы исключены и не снижают балл
                  риска.
                </div>
              ) : null}
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
        </div>
      </div>
    </div>
  )
}
