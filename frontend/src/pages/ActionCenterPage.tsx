import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api, downloadExport } from '../lib/api'
import type { PriorityCategory, PriorityView, QualityReport } from '../types'
import { EmptyState, ErrorBox, Loading, Metric, RiskBadge, formatEur } from '../components/ui'

/**
 * Action Center.
 *
 * Four measurements are shown side by side and sorted independently: risk,
 * financial exposure, operational urgency and data quality. There is no single
 * blended priority score, because a number the user cannot decompose is a
 * number they cannot defend. The queue categories organise attention; they are
 * not risk classes and carry no probability of churn.
 */

const CATEGORY_LABELS: Record<PriorityCategory, string> = {
  operational_attention: 'Операционная проблема',
  high_risk_with_exposure: 'Высокий риск с экспозицией',
  high_risk_review: 'Высокий риск без экспозиции',
  data_quality_review: 'Проверить данные',
  normal_review: 'Плановый обзор',
}

const LEVEL_LABELS = {
  critical: 'Критические',
  warning: 'Предупреждения',
  info: 'Информация',
} as const

type SortKey = 'urgency' | 'riskScore' | 'exposure' | 'id'

export default function ActionCenterPage() {
  const [view, setView] = useState<PriorityView | null>(null)
  const [quality, setQuality] = useState<QualityReport | null>(null)
  const [horizon, setHorizon] = useState(30)
  const [category, setCategory] = useState<'' | PriorityCategory>('')
  const [sortBy, setSortBy] = useState<SortKey>('urgency')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [priorityData, qualityData] = await Promise.all([
        api.priority({ horizonDays: horizon, category: category || undefined, sortBy, sortDir }),
        api.quality(),
      ])
      setView(priorityData)
      setQuality(qualityData)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить очередь действий')
    } finally {
      setLoading(false)
    }
  }, [horizon, category, sortBy, sortDir])

  useEffect(() => {
    load()
  }, [load])

  async function onExport() {
    setExporting(true)
    setToast(null)
    try {
      const rows = await downloadExport({ sortBy: 'riskScore', sortDir: 'desc' })
      setToast(`Экспортировано записей: ${rows}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сформировать экспорт')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Очередь действий</h1>
          <p className="hint">
            Риск, финансовая экспозиция, операционная срочность и качество данных показаны
            раздельно. Категории организуют работу и не являются вероятностью оттока.
          </p>
        </div>
      </div>

      <section className="card">
        <div className="card-body">
          <div className="toolbar">
            <label className="field">
              Горизонт
              <select
                className="select"
                value={horizon}
                onChange={(event) => setHorizon(Number(event.target.value))}
              >
                <option value={7}>7 дней</option>
                <option value={30}>30 дней</option>
                <option value={90}>90 дней</option>
              </select>
            </label>
            <label className="field">
              Категория
              <select
                className="select"
                value={category}
                onChange={(event) => setCategory(event.target.value as '' | PriorityCategory)}
              >
                <option value="">Все</option>
                {(Object.keys(CATEGORY_LABELS) as PriorityCategory[]).map((key) => (
                  <option key={key} value={key}>
                    {CATEGORY_LABELS[key]}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Сортировка
              <select
                className="select"
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value as SortKey)}
              >
                <option value="urgency">Операционная срочность</option>
                <option value="riskScore">Риск</option>
                <option value="exposure">Экспозиция</option>
                <option value="id">ID клиента</option>
              </select>
            </label>
            <label className="field">
              Порядок
              <select
                className="select"
                value={sortDir}
                onChange={(event) => setSortDir(event.target.value as 'asc' | 'desc')}
                disabled={sortBy === 'urgency'}
              >
                <option value="asc">По возрастанию</option>
                <option value="desc">По убыванию</option>
              </select>
            </label>
            <button type="button" className="btn" onClick={load} disabled={loading}>
              Обновить
            </button>
            <button type="button" className="btn" onClick={onExport} disabled={exporting}>
              {exporting ? 'Экспорт…' : 'Экспорт CSV'}
            </button>
          </div>

          {toast ? <div className="notice">{toast}</div> : null}
          {error ? <ErrorBox>{error}</ErrorBox> : null}
        </div>
      </section>

      {quality ? (
        <section className="card">
          <div className="card-head">
            <h2 className="section-title">Качество данных</h2>
            <span className="hint">
              аккаунтов {quality.recordsInspected.accounts} · услуг{' '}
              {quality.recordsInspected.services} · транзакций{' '}
              {quality.recordsInspected.transactions}
            </span>
          </div>
          <div className="card-body">
            <div className="metric-grid">
              {(Object.keys(LEVEL_LABELS) as (keyof typeof LEVEL_LABELS)[]).map((level) => (
                <Metric
                  key={level}
                  label={LEVEL_LABELS[level]}
                  value={String(quality.counts[level] ?? 0)}
                  foot={quality.levels[level]}
                  accent={level === 'critical' && (quality.counts[level] ?? 0) > 0}
                />
              ))}
            </div>

            {quality.issues.length ? (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Уровень</th>
                      <th>Проблема</th>
                      <th className="num">Записей</th>
                      <th>Действие</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quality.issues.map((issue) => (
                      <tr key={issue.code}>
                        <td>
                          <span className={`badge level-${issue.level}`}>{issue.level}</span>
                        </td>
                        <td>
                          <div className="cell-primary">{issue.message}</div>
                          {issue.records.length ? (
                            <div className="cell-sub">
                              ID: {issue.records.slice(0, 8).join(', ')}
                              {issue.records.length > 8 ? '…' : ''}
                            </div>
                          ) : null}
                        </td>
                        <td className="num">{issue.count}</td>
                        <td>
                          <span className="cell-sub">{issue.action}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState>Проблем качества данных не обнаружено.</EmptyState>
            )}
            <div className="card-note">{quality.note}</div>
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="card-head">
          <h2 className="section-title">
            Клиенты{view ? ` · ${view.total}` : ''}
            {view ? <span className="hint"> · горизонт {view.horizonDays} дн.</span> : null}
          </h2>
        </div>
        <div className="card-body">
          {loading ? (
            <Loading label="Загрузка очереди…" />
          ) : !view || view.items.length === 0 ? (
            <EmptyState>Под выбранные условия клиентов нет.</EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Email</th>
                    <th>Уровень</th>
                    <th className="num">Score</th>
                    <th className="num">Услуги</th>
                    <th className="num">Экспозиция</th>
                    <th className="num">Просрочено</th>
                    <th>Причины</th>
                  </tr>
                </thead>
                <tbody>
                  {view.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link to={`/customers/${item.id}`}>{item.id}</Link>
                      </td>
                      <td>
                        <Link to={`/customers/${item.id}`}>{item.email}</Link>
                      </td>
                      <td>
                        <RiskBadge category={item.riskCategory} />
                      </td>
                      <td className="num">
                        {item.riskScore !== null ? item.riskScore.toFixed(1) : '—'}
                      </td>
                      <td className="num">
                        {item.highRiskServiceCount ?? 0} / {item.serviceCount ?? 0}
                      </td>
                      <td className="num">
                        {item.revenueAtRiskOnHorizon
                          ? formatEur(item.revenueAtRiskOnHorizon.eur)
                          : '—'}
                      </td>
                      <td className="num">
                        {item.overdueOperational && item.overdueOperational.cents
                          ? formatEur(item.overdueOperational.eur)
                          : '—'}
                      </td>
                      <td>
                        {item.categories.map((cat) => (
                          <span key={cat} className="badge" title={view.categories[cat]}>
                            {CATEGORY_LABELS[cat]}
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {view ? <div className="card-note">{view.note}</div> : null}
        </div>
      </section>
    </div>
  )
}
