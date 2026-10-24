import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import type { ModelSettings, ScenarioComparison } from '../types'
import { EmptyState, ErrorBox, Loading, Metric, RiskBadge, formatEur } from '../components/ui'

/**
 * What-if Lab.
 *
 * Every figure here comes from the backend, evaluated on the same snapshot and
 * the same as_of with alternative settings. The page never computes a score or
 * an amount of its own, and it never writes: the working configuration changes
 * only through the explicit action on the settings page.
 */

/** Named starting points. They are parameter presets, not calibrated models. */
const PRESETS: { key: string; title: string; hint: string; overrides: Record<string, unknown> }[] = [
  {
    key: 'conservative',
    title: 'Осторожный',
    hint: 'Больше внимания сроку окончания и достаточности баланса',
    overrides: { weights: { expiry_proximity: 4.0, insufficient_balance: 3.0 } },
  },
  {
    key: 'failures',
    title: 'Чувствительный к неудачам',
    hint: 'Больше внимания неуспешным продлениям',
    overrides: { weights: { renewal_failure_rate: 4.0 } },
  },
  {
    key: 'whole',
    title: 'Вся история',
    hint: 'Окно неудачных продлений = null, то есть весь снимок',
    overrides: { failedRenewalWindowDays: null },
  },
  {
    key: 'short',
    title: 'Короткое окно 30 дней',
    hint: 'Учитывать только свежие неуспешные продления',
    overrides: { failedRenewalWindowDays: 30 },
  },
]

function signed(value: number | null, suffix = ''): string {
  if (value === null) return '—'
  if (value === 0) return 'без изменений'
  return `${value > 0 ? '+' : ''}${value.toLocaleString('ru-RU')}${suffix}`
}

function percent(value: number | null): string {
  // A null relative change means the baseline was zero; a percentage would be
  // mathematically undefined, so it is reported as N/A rather than as 0%.
  if (value === null) return 'N/A'
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

export default function WhatIfPage() {
  const [model, setModel] = useState<ModelSettings | null>(null)
  const [result, setResult] = useState<ScenarioComparison | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [windowEnabled, setWindowEnabled] = useState(true)
  const [windowDays, setWindowDays] = useState<number>(90)
  const [name, setName] = useState('Custom')
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const applyModel = useCallback((data: ModelSettings) => {
    setModel(data)
    setWeights({ ...data.settings.weights })
    const stored = data.settings.failedRenewalWindowDays
    setWindowEnabled(stored !== null && stored !== undefined)
    setWindowDays(stored ?? 90)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await api.modelSettings()
        if (!cancelled) applyModel(data)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить настройки модели')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [applyModel])

  /** Only the differences from the working configuration are sent. */
  const overrides = useMemo(() => {
    if (!model) return {}
    const patch: Record<string, unknown> = {}
    const weightPatch: Record<string, number> = {}
    for (const [key, value] of Object.entries(weights)) {
      if (value !== model.settings.weights[key]) weightPatch[key] = value
    }
    if (Object.keys(weightPatch).length) patch.weights = weightPatch
    const base = model.settings.failedRenewalWindowDays ?? null
    const next = windowEnabled ? windowDays : null
    if (next !== base) patch.failedRenewalWindowDays = next
    return patch
  }, [model, weights, windowEnabled, windowDays])

  const run = useCallback(async (label: string, patch: Record<string, unknown>) => {
    setRunning(true)
    setError(null)
    try {
      setResult(await api.compareScenario(label, patch))
    } catch (err) {
      setResult(null)
      setError(err instanceof ApiError ? err.detail : 'Не удалось рассчитать сценарий')
    } finally {
      setRunning(false)
    }
  }, [])

  if (loading) return <Loading label="Загрузка конфигурации модели…" />
  if (!model) return <ErrorBox>{error ?? 'Настройки модели недоступны'}</ErrorBox>

  const comparison = result?.comparison
  const moved = result?.customers ?? []
  const factorChanges = Object.entries(result?.factorAvailability ?? {})
  const hasOverrides = Object.keys(overrides).length > 0

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>What-if Lab</h1>
          <p className="hint">
            Сценарий считается тем же движком, что и рабочая конфигурация, на том же снимке и
            моменте времени. Просмотр сценария не изменяет рабочие настройки.
          </p>
        </div>
      </div>

      <section className="card">
        <div className="card-head">
          <h2 className="section-title">Пресеты</h2>
          <span className="hint">Параметры, а не откалиброванные модели</span>
        </div>
        <div className="card-body">
          <div className="toolbar">
            {PRESETS.map((preset) => (
              <button
                key={preset.key}
                type="button"
                className="btn"
                title={preset.hint}
                disabled={running}
                onClick={() => {
                  setName(preset.title)
                  run(preset.title, preset.overrides)
                }}
              >
                {preset.title}
              </button>
            ))}
            <button
              type="button"
              className="btn"
              disabled={running}
              onClick={() => {
                setName('Baseline')
                applyModel(model)
                run('Baseline', {})
              }}
            >
              Baseline
            </button>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2 className="section-title">Параметры сценария</h2>
          <span className="hint">
            Изменений относительно baseline: {hasOverrides ? JSON.stringify(overrides) : 'нет'}
          </span>
        </div>
        <div className="card-body">
          {model.factors
            .filter((factor) => factor.key in weights)
            .map((factor) => (
              <div className="weight-row" key={factor.key}>
                <div className="weight-info">
                  <div className="name">
                    {factor.label}{' '}
                    <span className="hint">
                      · ключ <code>{factor.key}</code> · по умолчанию {factor.defaultWeight}
                    </span>
                  </div>
                  <div className="desc">{factor.description}</div>
                </div>
                <input
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  step={0.1}
                  value={weights[factor.key]}
                  aria-label={`Вес ${factor.label}`}
                  onChange={(event) =>
                    setWeights((current) => ({ ...current, [factor.key]: Number(event.target.value) }))
                  }
                />
              </div>
            ))}

          <div className="weight-row">
            <div className="weight-info">
              <div className="name">Окно неудачных продлений</div>
              <div className="desc">
                Если ограничение выключено, используется весь снимок (<code>null</code>). Это
                допустимая конфигурация, а не отсутствие значения.
              </div>
            </div>
            <div className="row">
              <input
                className="input"
                type="number"
                min={1}
                max={3650}
                value={windowDays}
                disabled={!windowEnabled}
                aria-label="Окно неудачных продлений, дней"
                onChange={(event) => setWindowDays(Number(event.target.value))}
              />
              <label className="hint">
                <input
                  type="checkbox"
                  checked={!windowEnabled}
                  onChange={(event) => setWindowEnabled(!event.target.checked)}
                />{' '}
                весь снимок
              </label>
            </div>
          </div>

          <div className="toolbar">
            <input
              className="input"
              type="text"
              value={name}
              maxLength={120}
              aria-label="Название сценария"
              onChange={(event) => setName(event.target.value)}
            />
            <button
              type="button"
              className="btn primary"
              disabled={running || !hasOverrides}
              onClick={() => run(name || 'Custom', overrides)}
            >
              {running ? 'Расчёт…' : 'Сравнить с baseline'}
            </button>
          </div>
          {error ? <ErrorBox>{error}</ErrorBox> : null}
        </div>
      </section>

      {comparison ? (
        <>
          <section className="card">
            <div className="card-head">
              <h2 className="section-title">Сравнение «{result?.name}» с baseline</h2>
              <span className="hint">Снимок на {result?.asOf?.slice(0, 16).replace('T', ' ')} UTC</span>
            </div>
            <div className="card-body">
              <div className="metric-grid">
                <Metric
                  label="Клиентов высокого риска"
                  value={String(comparison.highRiskCustomers.scenario ?? '—')}
                  foot={`было ${comparison.highRiskCustomers.baseline ?? '—'} · ${signed(
                    comparison.highRiskCustomers.absolute,
                  )} (${percent(comparison.highRiskCustomers.relative)})`}
                />
                <Metric
                  label="Выручка под риском"
                  value={formatEur(((comparison.revenueAtRiskCents.scenario ?? 0) / 100).toFixed(2))}
                  foot={`было ${formatEur(
                    ((comparison.revenueAtRiskCents.baseline ?? 0) / 100).toFixed(2),
                  )} · ${signed(comparison.revenueAtRiskCents.absolute, ' ¢')}`}
                />
                <Metric
                  label="Услуг высокого риска"
                  value={String(comparison.highRiskServices.scenario ?? '—')}
                  foot={`было ${comparison.highRiskServices.baseline ?? '—'} · ${signed(
                    comparison.highRiskServices.absolute,
                  )}`}
                />
                <Metric
                  label="Клиентов изменилось"
                  value={String(moved.length)}
                  foot="по score или категории"
                />
              </div>

              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Категория</th>
                      <th className="num">Baseline</th>
                      <th className="num">Сценарий</th>
                      <th className="num">Изменение</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(comparison.categories).map(([key, change]) => (
                      <tr key={key}>
                        <td>{key}</td>
                        <td className="num">{change.baseline ?? '—'}</td>
                        <td className="num">{change.scenario ?? '—'}</td>
                        <td className="num">{signed(change.absolute)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="card-note">{comparison.note}</div>
            </div>
          </section>

          {factorChanges.length ? (
            <section className="card">
              <div className="card-head">
                <h2 className="section-title">Изменение доступности факторов</h2>
                <span className="hint">«Неизвестное» не равно нулю</span>
              </div>
              <div className="card-body">
                <p className="hint">
                  Если фактор перестал вычисляться, он исключается из среднего, и score может
                  вырасти, хотя состояние клиента не ухудшилось. Это следствие правила «неизвестное
                  не равно нулю».
                </p>
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Фактор</th>
                        <th className="num">Доступно (было → стало)</th>
                        <th className="num">Неизвестно (было → стало)</th>
                        <th className="num">Стало неизвестным</th>
                      </tr>
                    </thead>
                    <tbody>
                      {factorChanges.map(([key, change]) => (
                        <tr key={key}>
                          <td>{key}</td>
                          <td className="num">
                            {change.availableBefore} → {change.availableAfter}
                          </td>
                          <td className="num">
                            {change.unknownBefore} → {change.unknownAfter}
                          </td>
                          <td className="num">{change.becameUnknown}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          ) : null}

          <section className="card">
            <div className="card-head">
              <h2 className="section-title">Клиенты с изменениями · {moved.length}</h2>
              <span className="hint">Сценарий показывает чувствительность методологии</span>
            </div>
            <div className="card-body">
              {moved.length ? (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>Email</th>
                        <th className="num">Score</th>
                        <th>Категория</th>
                        <th className="num">Экспозиция, ¢</th>
                      </tr>
                    </thead>
                    <tbody>
                      {moved.slice(0, 25).map((row) => (
                        <tr key={row.id}>
                          <td>
                            <Link to={`/customers/${row.id}`}>{row.id}</Link>
                          </td>
                          <td>
                            <Link to={`/customers/${row.id}`}>{row.email}</Link>
                          </td>
                          <td className="num">
                            {row.scoreBefore ?? '—'} → {row.scoreAfter ?? '—'}
                          </td>
                          <td>
                            <RiskBadge category={row.categoryAfter} />
                            {row.categoryChanged ? (
                              <span className="hint">
                                {' '}
                                было {row.categoryBefore}
                              </span>
                            ) : null}
                          </td>
                          <td className="num">
                            {row.revenueAtRiskBefore ?? '—'} → {row.revenueAtRiskAfter ?? '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState>Ни один клиент не изменил score или категорию.</EmptyState>
              )}
              <div className="card-note">{result.note}</div>
            </div>
          </section>
        </>
      ) : (
        <section className="card">
          <div className="card-body">
            <EmptyState>
              Выберите пресет или измените параметры и нажмите «Сравнить с baseline».
            </EmptyState>
          </div>
        </section>
      )}
    </div>
  )
}
