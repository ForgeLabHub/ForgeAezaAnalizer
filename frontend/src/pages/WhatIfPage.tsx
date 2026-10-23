import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { ModelSettings, Simulation } from '../types'
import {
  EmptyState,
  ErrorBox,
  Loading,
  Metric,
  RiskBadge,
  formatEur,
} from '../components/ui'

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
  const eur = (Math.abs(cents) / 100).toFixed(2)
  return (
    <span className={cents > 0 ? 'delta-bad' : 'delta-good'}>
      {cents > 0 ? '+' : '−'}
      {formatEur(eur, false)} €
    </span>
  )
}

export default function WhatIfPage() {
  const [settings, setSettings] = useState<ModelSettings | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [horizonDays, setHorizonDays] = useState(30)
  const [result, setResult] = useState<Simulation | null>(null)
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

  const patch = useMemo(() => {
    if (!settings) return {}
    const changedWeights: Record<string, number> = {}
    for (const [key, value] of Object.entries(weights)) {
      if (settings.settings.weights[key] !== value) changedWeights[key] = value
    }
    const body: Record<string, unknown> = {}
    if (Object.keys(changedWeights).length) body.weights = changedWeights
    if (horizonDays !== settings.settings.horizonDays) body.horizonDays = horizonDays
    return body
  }, [settings, weights, horizonDays])

  const dirty = Object.keys(patch).length > 0

  async function run() {
    if (!dirty) return
    setRunning(true)
    setError(null)
    setApplied(null)
    try {
      setResult(await api.simulate(patch))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось выполнить симуляцию')
    } finally {
      setRunning(false)
    }
  }

  async function apply() {
    if (!dirty) return
    setApplying(true)
    setError(null)
    try {
      await api.patchSettings(patch)
      const fresh = await api.modelSettings()
      setSettings(fresh)
      setWeights(fresh.settings.weights)
      setHorizonDays(fresh.settings.horizonDays)
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
    setResult(null)
    setApplied(null)
  }

  if (loading) return <Loading label="Загрузка параметров модели…" />
  if (!settings) return <ErrorBox>{error ?? 'Настройки недоступны'}</ErrorBox>

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Лаборатория сценариев</h1>
          <p>
            Проверьте, как изменение весов и горизонта повлияет на результат, прежде чем
            публиковать модель. Симуляция не сохраняется и не влияет на других пользователей.
          </p>
        </div>
        <Link className="btn" to="/settings">
          Настройки модели
        </Link>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}
      {applied ? <div className="notice">{applied}</div> : null}

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <h2>Параметры сценария</h2>
            <span className="hint">текущая модель: поколение {settings.generation ?? '—'}</span>
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

            {settings.factors.map((factor) => (
              <div className="factor" key={factor.key}>
                <div className="factor-name">
                  {factor.label}
                  <span className="hint">
                    по умолчанию {factor.defaultWeight.toFixed(1)}
                  </span>
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
          {!result ? (
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
                      {result.baseline.customers.highRisk} → {result.scenario.customers.highRisk}{' '}
                      <Delta value={result.delta.highRisk} />
                    </dd>
                    <dt>Клиентов среднего риска</dt>
                    <dd>
                      {result.baseline.customers.mediumRisk} → {result.scenario.customers.mediumRisk}{' '}
                      <Delta value={result.delta.mediumRisk} />
                    </dd>
                    <dt>Клиентов низкого риска</dt>
                    <dd>
                      {result.baseline.customers.byCategory.low ?? 0} →{' '}
                      {result.scenario.customers.byCategory.low ?? 0}{' '}
                      <Delta value={result.delta.lowRisk} invert />
                    </dd>
                    <dt>Услуг высокого риска</dt>
                    <dd>
                      {result.baseline.services.highRisk} → {result.scenario.services.highRisk}{' '}
                      <Delta value={result.delta.servicesHighRisk} />
                    </dd>
                    <dt>Выручка под риском</dt>
                    <dd>
                      {formatEur(result.baseline.revenue.revenueAtRiskEur)} →{' '}
                      {formatEur(result.scenario.revenue.revenueAtRiskEur)}{' '}
                      <DeltaEur cents={result.delta.revenueAtRiskCents} />
                    </dd>
                    <dt>Предстоящие продления</dt>
                    <dd>
                      {formatEur(result.baseline.revenue.upcomingRenewalsEur)} →{' '}
                      {formatEur(result.scenario.revenue.upcomingRenewalsEur)}
                    </dd>
                  </dl>
                </div>
                <div className="card-note">{result.note}</div>
              </section>

              <div className="metric-grid">
                <Metric
                  label="Изменили категорию"
                  value={result.categoryChanges}
                  foot={`затронуто клиентов: ${result.movedCustomers}`}
                />
                <Metric
                  label="Изменение выручки под риском"
                  value={formatEur(
                    (Math.abs(result.delta.revenueAtRiskCents) / 100).toFixed(2),
                    false,
                  )}
                  unit="€"
                  small
                  accent={result.delta.revenueAtRiskCents > 0}
                  foot={result.delta.revenueAtRiskCents >= 0 ? 'сценарий строже' : 'сценарий мягче'}
                />
              </div>

              <section className="card">
                <div className="card-head">
                  <h2>Кого затронет</h2>
                  <span className="hint">{result.movements.length} записей</span>
                </div>
                {result.movements.length === 0 ? (
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
                        {result.movements.slice(0, 25).map((m) => (
                          <tr key={m.customerId}>
                            <td>
                              <Link to={`/customers/${m.customerId}`} className="cell-primary">
                                #{m.customerId}
                              </Link>
                              <div className="cell-sub">{m.email}</div>
                            </td>
                            <td>
                              <RiskBadge category={m.before} />
                            </td>
                            <td>
                              <RiskBadge category={m.after} />
                            </td>
                            <td className="num mono">
                              {m.beforeScore?.toFixed(1) ?? '—'} → {m.afterScore?.toFixed(1) ?? '—'}
                            </td>
                            <td>
                              {m.categoryChanged ? (
                                <Delta value={m.delta ?? 0} />
                              ) : (
                                <span className="cell-sub">
                                  только балл{' '}
                                  <Delta value={m.delta ?? 0} />
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="card-note">
                  Сначала показаны клиенты, сменившие категорию риска; затем те, у кого изменился
                  только балл.
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
