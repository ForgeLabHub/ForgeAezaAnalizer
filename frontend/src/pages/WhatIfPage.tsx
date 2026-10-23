import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { ModelSettings, ScenarioMeasure, ScenarioResult } from '../types'
import { EmptyState, ErrorBox, Loading, Metric, RiskBadge, formatEur } from '../components/ui'

function Delta({ value, invert = false }: { value: number; invert?: boolean }) {
  if (value === 0) return <span className="cell-sub">без изменений</span>
  const positive = value > 0
  const good = invert ? positive : !positive
  return (
    <span className={good ? 'delta-good' : 'delta-bad'}>
      {positive ? '+' : '−'}
      {Math.abs(value).toFixed(value % 1 === 0 ? 0 : 2)}
    </span>
  )
}

function DeltaEur({ cents }: { cents: number }) {
  if (cents === 0) return <span className="cell-sub">без изменений</span>
  return (
    <span className={cents > 0 ? 'delta-bad' : 'delta-good'}>
      {cents > 0 ? '+' : '−'}
      {formatEur((Math.abs(cents) / 100).toFixed(2), false)} €
    </span>
  )
}

export default function WhatIfPage() {
  const [settings, setSettings] = useState<ModelSettings | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [horizonDays, setHorizonDays] = useState(30)
  const [windowDays, setWindowDays] = useState<number | ''>('')
  const [result, setResult] = useState<ScenarioResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applied, setApplied] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const data = await api.modelSettings()
        if (cancelled) return
        setSettings(data)
        setWeights(data.settings.weights)
        setHorizonDays(data.settings.horizonDays)
        setWindowDays(data.settings.failedRenewalWindowDays ?? '')
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить настройки')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  const overrides = useMemo(() => {
    if (!settings) return {}
    const changedWeights: Record<string, number> = {}
    for (const [key, value] of Object.entries(weights)) {
      if (settings.settings.weights[key] !== value) changedWeights[key] = value
    }
    const body: Record<string, unknown> = {}
    if (Object.keys(changedWeights).length) body.weights = changedWeights
    if (horizonDays !== settings.settings.horizonDays) body.horizonDays = horizonDays
    const currentWindow = settings.settings.failedRenewalWindowDays ?? null
    const nextWindow = windowDays === '' ? null : Number(windowDays)
    if (nextWindow !== currentWindow) body.failedRenewalWindowDays = nextWindow
    return body
  }, [settings, weights, horizonDays, windowDays])

  const dirty = Object.keys(overrides).length > 0

  async function run() {
    if (!dirty) return
    setRunning(true)
    setError(null)
    setApplied(null)
    try {
      setResult(await api.compareScenario(overrides))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось выполнить сравнение')
    } finally {
      setRunning(false)
    }
  }

  async function apply() {
    if (!dirty) return
    setApplying(true)
    setError(null)
    try {
      await api.patchSettings(overrides)
      const fresh = await api.modelSettings()
      setSettings(fresh)
      setWeights(fresh.settings.weights)
      setHorizonDays(fresh.settings.horizonDays)
      setWindowDays(fresh.settings.failedRenewalWindowDays ?? '')
      setResult(null)
      setApplied('Изменения сохранены: опубликована новая версия расчёта.')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сохранить настройки')
    } finally {
      setApplying(false)
    }
  }

  function reset() {
    if (!settings) return
    setWeights(settings.settings.weights)
    setHorizonDays(settings.settings.horizonDays)
    setWindowDays(settings.settings.failedRenewalWindowDays ?? '')
    setResult(null)
    setApplied(null)
  }

  if (loading) return <Loading label="Загрузка параметров модели…" />
  if (!settings) return <ErrorBox>{error ?? 'Настройки недоступны'}</ErrorBox>

  const cmp = result?.comparison
  const measure = (key: string): ScenarioMeasure | undefined => {
    const value = cmp?.[key]
    return value && typeof value === 'object' ? (value as ScenarioMeasure) : undefined
  }
  const changed = result?.customers.filter((c) => c.categoryChanged) ?? []
  const scoreOnly = result?.customers.filter((c) => !c.categoryChanged) ?? []

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Лаборатория сценариев</h1>
          <p>
            Проверьте, как изменение весов и горизонта повлияет на результат, прежде чем
            публиковать модель. Сценарий считается тем же движком на том же снимке данных и
            ничего не сохраняет.
          </p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Link className="btn" to="/action-center">
            Центр действий
          </Link>
          <Link className="btn" to="/settings">
            Настройки модели
          </Link>
        </div>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}
      {applied ? <div className="notice">{applied}</div> : null}

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <h2>Параметры сценария</h2>
            <span className="hint">
              допустимо менять:{' '}
              {(result?.allowedParameters ?? [
                'weights',
                'horizonDays',
                'lowMax',
                'mediumMax',
                'failedRenewalWindowDays',
              ]).join(', ')}
            </span>
          </div>
          <div className="card-body stack">
            <label className="field">
              <span>Горизонт прогноза, дней</span>
              <input
                className="input"
                type="number"
                min={1}
                max={365}
                value={horizonDays}
                onChange={(event) => setHorizonDays(Number(event.target.value))}
              />
            </label>

            <label className="field">
              <span>Окно подсчёта неуспешных продлений, дней (пусто = весь снимок)</span>
              <input
                className="input"
                type="number"
                min={1}
                max={3650}
                value={windowDays}
                placeholder="весь снимок"
                onChange={(event) =>
                  setWindowDays(event.target.value === '' ? '' : Number(event.target.value))
                }
              />
            </label>

            {settings.factors.map((factor) => (
              <div className="factor" key={factor.key}>
                <div className="factor-name">
                  {factor.label}
                  <span className="hint">по умолчанию {factor.defaultWeight.toFixed(1)}</span>
                </div>
                <div className="factor-note">{factor.description}</div>
                <label className="field">
                  <span>Вес</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={1000}
                    step={0.5}
                    value={weights[factor.key] ?? 0}
                    onChange={(event) =>
                      setWeights((current) => ({
                        ...current,
                        [factor.key]: Number(event.target.value),
                      }))
                    }
                  />
                </label>
                <div className="factor-note">
                  Нормализация: {factor.normalization}. При отсутствии данных:{' '}
                  {factor.missingDataBehaviour}
                </div>
              </div>
            ))}

            <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
              <button className="btn primary" type="button" onClick={run} disabled={!dirty || running}>
                {running ? 'Считаем…' : 'Сравнить с текущей моделью'}
              </button>
              <button className="btn" type="button" onClick={apply} disabled={!dirty || applying}>
                {applying ? 'Сохраняем…' : 'Сохранить как новую модель'}
              </button>
              <button className="btn sm" type="button" onClick={reset} disabled={!dirty}>
                Вернуть текущие значения
              </button>
            </div>
          </div>
        </section>

        <div className="stack">
          {!result || !cmp ? (
            <section className="card">
              <div className="card-head">
                <h2>Результат сравнения</h2>
              </div>
              <EmptyState>
                {dirty
                  ? 'Измените параметры и нажмите «Сравнить», чтобы увидеть эффект.'
                  : 'Измените хотя бы один вес или горизонт, чтобы запустить сравнение.'}
              </EmptyState>
            </section>
          ) : (
            <>
              <section className="card">
                <div className="card-head">
                  <h2>Эффект сценария</h2>
                  <span className="hint">относительно опубликованной модели</span>
                </div>
                <div className="card-body">
                  <dl className="kv">
                    <dt>Клиентов высокого риска</dt>
                    <dd>
                      {measure('highRiskCustomers')?.baseline} →{' '}
                      {measure('highRiskCustomers')?.scenario}{' '}
                      <Delta value={measure('highRiskCustomers')?.absolute ?? 0} />
                    </dd>
                    <dt>Клиентов среднего риска</dt>
                    <dd>
                      {measure('mediumRiskCustomers')?.baseline} →{' '}
                      {measure('mediumRiskCustomers')?.scenario}{' '}
                      <Delta value={measure('mediumRiskCustomers')?.absolute ?? 0} />
                    </dd>
                    <dt>Клиентов низкого риска</dt>
                    <dd>
                      {cmp.categories?.low?.baseline ?? 0} → {cmp.categories?.low?.scenario ?? 0}{' '}
                      <Delta value={cmp.categories?.low?.absolute ?? 0} invert />
                    </dd>
                    <dt>Услуг высокого риска</dt>
                    <dd>
                      {measure('highRiskServices')?.baseline ?? '—'} →{' '}
                      {measure('highRiskServices')?.scenario ?? '—'}{' '}
                      <Delta value={measure('highRiskServices')?.absolute ?? 0} />
                    </dd>
                    <dt>Выручка под риском</dt>
                    <dd>
                      {formatEur((result.baseline.revenue.revenueAtRiskCents / 100).toFixed(2))} →{' '}
                      {formatEur((result.scenario.revenue.revenueAtRiskCents / 100).toFixed(2))}{' '}
                      <DeltaEur cents={measure('revenueAtRiskCents')?.absolute ?? 0} />
                    </dd>
                    <dt>Предстоящие продления</dt>
                    <dd>
                      {formatEur((result.baseline.revenue.upcomingRenewalsCents / 100).toFixed(2))} →{' '}
                      {formatEur((result.scenario.revenue.upcomingRenewalsCents / 100).toFixed(2))}
                    </dd>
                  </dl>
                </div>
                <div className="card-note">{result.note}</div>
              </section>

              <div className="metric-grid">
                <Metric
                  label="Изменили категорию"
                  value={changed.length}
                  foot={`всего затронуто: ${result.customers.length}`}
                />
                <Metric
                  label="Изменение выручки под риском"
                  value={formatEur(
                    (Math.abs(measure('revenueAtRiskCents')?.absolute ?? 0) / 100).toFixed(2),
                    false,
                  )}
                  unit="€"
                  small
                  accent={(measure('revenueAtRiskCents')?.absolute ?? 0) > 0}
                  foot={
                    (measure('revenueAtRiskCents')?.absolute ?? 0) >= 0
                      ? 'сценарий строже'
                      : 'сценарий мягче'
                  }
                />
              </div>

              <section className="card">
                <div className="card-head">
                  <h2>Кого затронет</h2>
                  <span className="hint">{result.customers.length} записей</span>
                </div>
                {result.customers.length === 0 ? (
                  <EmptyState>Ни один клиент не изменил категорию или балл риска.</EmptyState>
                ) : (
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Клиент</th>
                          <th>Было</th>
                          <th>Станет</th>
                          <th className="num">Балл</th>
                          <th>Изменение</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...changed, ...scoreOnly].slice(0, 25).map((m) => (
                          <tr key={m.id}>
                            <td>
                              <Link to={`/customers/${m.id}`} className="cell-primary">
                                #{m.id}
                              </Link>
                              <div className="cell-sub">{m.email}</div>
                            </td>
                            <td>
                              <RiskBadge category={m.categoryBefore} />
                            </td>
                            <td>
                              <RiskBadge category={m.categoryAfter} />
                            </td>
                            <td className="num mono">
                              {m.scoreBefore?.toFixed(1) ?? '—'} → {m.scoreAfter?.toFixed(1) ?? '—'}
                            </td>
                            <td>
                              <Delta value={(m.scoreAfter ?? 0) - (m.scoreBefore ?? 0)} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="card-note">
                  Сначала показаны клиенты, сменившие категорию риска; затем те, у кого изменился
                  только балл. Расчёт привязан к текущему снимку данных.
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
