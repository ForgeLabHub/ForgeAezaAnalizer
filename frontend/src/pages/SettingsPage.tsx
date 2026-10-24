import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useAnalysis } from '../lib/realtime'
import type {
  ModelSettings,
  RiskCategory,
  ScenarioComparisonResponse,
  Summary,
  ValidationIssue,
} from '../types'
import {
  ErrorBox,
  Loading,
  Metric,
  RiskBadge,
  formatCents,
  formatEur,
  formatRelativePct,
  formatSignedCents,
  formatSignedNumber,
} from '../components/ui'

const CATEGORY_TITLES: Record<string, string> = {
  high: 'Высокий риск',
  medium: 'Средний риск',
  low: 'Низкий риск',
  insufficient_data: 'Недостаточно данных',
  not_applicable: 'Не применимо',
}

export default function SettingsPage() {
  const { activeGeneration, pinnedGeneration, setPinnedGeneration, refreshKey, notifyMutation } =
    useAnalysis()
  const [model, setModel] = useState<ModelSettings | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [horizon, setHorizon] = useState(30)
  const [lowMax, setLowMax] = useState(34)
  const [mediumMax, setMediumMax] = useState(64)
  const [useWindowLimit, setUseWindowLimit] = useState(true)
  const [windowDays, setWindowDays] = useState(90)

  const [scenarioName, setScenarioName] = useState('Проверка чувствительности')
  const [scenarioResult, setScenarioResult] = useState<ScenarioComparisonResponse | null>(null)
  const [simulating, setSimulating] = useState(false)

  const [error, setError] = useState<string | null>(null)
  const [errorIssues, setErrorIssues] = useState<ValidationIssue[] | undefined>(undefined)
  const [conflictDetected, setConflictDetected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null)

  const applyModel = useCallback((data: ModelSettings) => {
    setModel(data)
    setWeights({ ...data.settings.weights })
    setHorizon(data.settings.horizonDays)
    setLowMax(data.settings.lowMax)
    setMediumMax(data.settings.mediumMax)
    const win = data.settings.failedRenewalWindowDays
    if (win === null || win === undefined) {
      setUseWindowLimit(false)
      setWindowDays(90)
    } else {
      setUseWindowLimit(true)
      setWindowDays(win)
    }
    setConflictDetected(false)
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    setErrorIssues(undefined)
    try {
      const [settings, summaryData] = await Promise.all([
        api.modelSettings(activeGeneration),
        api.summary(activeGeneration),
      ])
      applyModel(settings)
      setSummary(summaryData)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
        setErrorIssues(err.errors)
      } else {
        setError('Не удалось загрузить настройки модели')
      }
    } finally {
      setLoading(false)
    }
  }, [activeGeneration, applyModel])

  useEffect(() => {
    void loadAll()
  }, [loadAll, refreshKey])

  const effectiveWindow: number | null = useWindowLimit
    ? Math.max(1, Math.min(3650, Math.round(windowDays || 90)))
    : null

  const dirty = useMemo(() => {
    if (!model) return false
    if (Math.round(horizon) !== model.settings.horizonDays) return true
    if (
      Math.round(lowMax) !== model.settings.lowMax ||
      Math.round(mediumMax) !== model.settings.mediumMax
    ) {
      return true
    }
    const storedWin = model.settings.failedRenewalWindowDays ?? null
    if (effectiveWindow !== storedWin) return true
    return Object.keys(weights).some(
      (key) => Math.abs(weights[key] - (model.settings.weights[key] ?? 0)) > 1e-9,
    )
  }, [model, weights, horizon, lowMax, mediumMax, effectiveWindow])

  function buildCandidateSettings() {
    return {
      horizonDays: Math.max(1, Math.min(365, Math.round(horizon || 1))),
      weights,
      lowMax: Math.max(0, Math.min(99, Math.round(lowMax))),
      mediumMax: Math.max(1, Math.min(100, Math.round(mediumMax))),
      failedRenewalWindowDays: effectiveWindow,
    }
  }

  async function save() {
    if (!model || pinnedGeneration !== null) return
    setSaving(true)
    setError(null)
    setErrorIssues(undefined)
    setConflictDetected(false)
    try {
      const candidate = buildCandidateSettings()
      const updated = await api.patchSettings({
        ...candidate,
        expectedGeneration: model.generation,
      })
      applyModel(updated)
      notifyMutation(updated)
      const freshSummary = await api.summary()
      setSummary(freshSummary)
      setScenarioResult(null)
      setToast({ text: `Настройки опубликованы (поколение #${updated.generation ?? 'новое'}).` })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
        setErrorIssues(err.errors)
        if (err.status === 409) setConflictDetected(true)
      } else {
        setError('Не удалось сохранить настройки')
      }
    } finally {
      setSaving(false)
    }
  }

  async function reset() {
    if (!model || pinnedGeneration !== null) return
    setSaving(true)
    setError(null)
    setErrorIssues(undefined)
    setConflictDetected(false)
    try {
      const updated = await api.resetSettings(model.generation)
      applyModel(updated)
      notifyMutation(updated)
      const freshSummary = await api.summary()
      setSummary(freshSummary)
      setScenarioResult(null)
      setToast({ text: 'Восстановлены значения по умолчанию.' })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
        setErrorIssues(err.errors)
        if (err.status === 409) setConflictDetected(true)
      } else {
        setError('Не удалось сбросить настройки')
      }
    } finally {
      setSaving(false)
    }
  }

  async function runScenario(customOverrides?: {
    name?: string
    horizonDays?: number
    lowMax?: number
    mediumMax?: number
    failedRenewalWindowDays?: number | null
    weights?: Record<string, number>
  }) {
    setSimulating(true)
    setError(null)
    setErrorIssues(undefined)
    try {
      const base = buildCandidateSettings()
      const nameToSend = (customOverrides?.name ?? scenarioName).trim() || 'Custom'
      const overrides = {
        horizonDays: customOverrides?.horizonDays ?? base.horizonDays,
        lowMax: customOverrides?.lowMax ?? base.lowMax,
        mediumMax: customOverrides?.mediumMax ?? base.mediumMax,
        failedRenewalWindowDays:
          customOverrides && 'failedRenewalWindowDays' in customOverrides
            ? customOverrides.failedRenewalWindowDays
            : base.failedRenewalWindowDays,
        weights: customOverrides?.weights ?? base.weights,
      }
      const res = await api.compareScenario(nameToSend, overrides)
      setScenarioResult(res)
      setToast({ text: `Сценарий «${res.name}» рассчитан без изменения рабочей модели.` })
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
        setErrorIssues(err.errors)
      } else {
        setError('Не удалось выполнить расчёт сценария')
      }
    } finally {
      setSimulating(false)
    }
  }

  function applyPreset(preset: 'h7' | 'h90' | 'whole_snapshot' | 'strict_bands') {
    if (!model) return
    let nextHorizon = model.settings.horizonDays
    let nextLow = model.settings.lowMax
    let nextMed = model.settings.mediumMax
    let nextUseWin = model.settings.failedRenewalWindowDays !== null
    let nextWin = model.settings.failedRenewalWindowDays ?? 90
    const nextWeights = { ...model.settings.weights }
    let label = 'Проверка чувствительности'

    if (preset === 'h7') {
      nextHorizon = 7
      label = 'Короткий горизонт (7 дн.)'
    } else if (preset === 'h90') {
      nextHorizon = 90
      label = 'Длинный горизонт (90 дн.)'
    } else if (preset === 'whole_snapshot') {
      nextUseWin = false
      label = 'Весь снимок без окна 90 дн.'
    } else if (preset === 'strict_bands') {
      nextLow = 25
      nextMed = 50
      label = 'Строгие пороги (25 / 50)'
    }

    setHorizon(nextHorizon)
    setLowMax(nextLow)
    setMediumMax(nextMed)
    setUseWindowLimit(nextUseWin)
    setWindowDays(nextWin)
    setWeights(nextWeights)
    setScenarioName(label)

    void runScenario({
      name: label,
      horizonDays: nextHorizon,
      lowMax: nextLow,
      mediumMax: nextMed,
      failedRenewalWindowDays: nextUseWin ? nextWin : null,
      weights: nextWeights,
    })
  }

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 3200)
    return () => clearTimeout(timer)
  }, [toast])

  if (loading) return <Loading label="Загрузка настроек модели…" />
  if (!model) return <ErrorBox issues={errorIssues}>{error ?? 'Настройки недоступны'}</ErrorBox>

  const factorLabelsByKey: Record<string, string> = {}
  for (const f of model.factors) {
    factorLabelsByKey[f.key] = f.label
  }

  const totalWeight = model.factors.reduce((sum, f) => {
    if (f.deprecated) return sum
    const w = weights[f.key] ?? 0
    return sum + (w > 0 ? w : 0)
  }, 0)

  const availabilityEntries = scenarioResult
    ? Object.entries(scenarioResult.factorAvailability)
    : []

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Модель риска и What-If сценарии</h1>
          <p>
            Настройте веса факторов, окно анализа отказов, горизонт и пороги риска. Перед
            публикацией в рабочую модель протестируйте изменения изолированно в режиме What-If —
            без перезаписи текущего поколения расчёта.
          </p>
        </div>
        <div className="row">
          <button
            type="button"
            className="btn"
            onClick={() => void runScenario()}
            disabled={simulating || saving}
          >
            {simulating ? 'Моделирование…' : 'Сравнить сценарий (What-If)'}
          </button>
          <button
            type="button"
            className="btn"
            onClick={reset}
            disabled={saving || model.isDefault || pinnedGeneration !== null}
          >
            Значения по умолчанию
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={save}
            disabled={saving || !dirty || pinnedGeneration !== null}
          >
            {saving ? 'Сохранение…' : dirty ? 'Опубликовать в модель' : 'Сохранено'}
          </button>
        </div>
      </div>

      {pinnedGeneration !== null ? (
        <div className="notice warn row" style={{ justifyContent: 'space-between' }}>
          <span>
            Вы просматриваете архивное поколение #{pinnedGeneration}. Сравнение сценариев What-If
            доступно, но публикация изменений возможна только из актуального поколения.
          </span>
          <button type="button" className="btn sm" onClick={() => setPinnedGeneration(null)}>
            К актуальному поколению
          </button>
        </div>
      ) : null}

      {conflictDetected ? (
        <div className="notice warn row" style={{ justifyContent: 'space-between' }}>
          <span>
            Параметры модели были изменены в другой сессии (конфликт expectedGeneration). Обновите
            данные перед повторным сохранением.
          </span>
          <button type="button" className="btn sm" onClick={() => void loadAll()}>
            Загрузить актуальные настройки
          </button>
        </div>
      ) : null}

      {error ? <ErrorBox issues={errorIssues}>{error}</ErrorBox> : null}

      {summary ? (
        <div className="metric-grid">
          <Metric label="Клиентов высокого риска" value={summary.customers.highRisk} />
          <Metric label="Клиентов среднего риска" value={summary.customers.mediumRisk} />
          <Metric
            label="Выручка под риском"
            value={formatEur(summary.revenue.revenueAtRiskEur, false)}
            unit="€"
            accent
            foot={`горизонт ${summary.horizonDays} дн.`}
          />
          <Metric
            label="Окно анализа отказов"
            value={
              model.settings.failedRenewalWindowDays === null
                ? 'Весь снимок'
                : `${model.settings.failedRenewalWindowDays} дн.`
            }
            small
            foot="для доли неуспешных продлений"
          />
          <Metric
            label="Сумма активных весов"
            value={totalWeight.toFixed(1)}
            foot="нормировка: 100 × Σ(w·f) / Σw"
          />
        </div>
      ) : null}

      <section className="card">
        <div className="card-head">
          <h2>Быстрая симуляция What-If</h2>
          <span className="hint">изолированный расчёт без изменения боевых настроек</span>
        </div>
        <div className="card-body stack" style={{ gap: 14 }}>
          <div className="row" style={{ gap: 10 }}>
            <input
              className="input"
              style={{ minWidth: 260, flex: '1 1 260px' }}
              type="text"
              maxLength={120}
              value={scenarioName}
              onChange={(e) => setScenarioName(e.target.value)}
              placeholder="Название сценария…"
              aria-label="Название сценария"
            />
            <button
              type="button"
              className="btn sm"
              disabled={simulating}
              onClick={() => applyPreset('h7')}
            >
              Горизонт 7 дн.
            </button>
            <button
              type="button"
              className="btn sm"
              disabled={simulating}
              onClick={() => applyPreset('h90')}
            >
              Горизонт 90 дн.
            </button>
            <button
              type="button"
              className="btn sm"
              disabled={simulating}
              onClick={() => applyPreset('whole_snapshot')}
            >
              Отказы за весь снимок
            </button>
            <button
              type="button"
              className="btn sm"
              disabled={simulating}
              onClick={() => applyPreset('strict_bands')}
            >
              Строгие пороги 25/50
            </button>
            <button
              type="button"
              className="btn primary sm"
              disabled={simulating}
              onClick={() => void runScenario()}
            >
              {simulating ? 'Расчёт…' : 'Рассчитать по форме'}
            </button>
          </div>

          {scenarioResult ? (
            <div className="stack" style={{ gap: 16 }}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <div>
                  <strong>Результат сценария «{scenarioResult.name}»</strong>
                  <span className="hint" style={{ marginLeft: 8 }}>
                    база vs сценарий · клиентов с изменением оценки:{' '}
                    {scenarioResult.customers.length}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn sm"
                  onClick={() => setScenarioResult(null)}
                >
                  Скрыть сравнение
                </button>
              </div>

              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Показатель</th>
                      <th className="num">Рабочая модель</th>
                      <th className="num">Сценарий</th>
                      <th className="num">Абс. изменение</th>
                      <th className="num">Относит.</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Горизонт прогноза, дн.</td>
                      <td className="num">{scenarioResult.comparison.horizonDays.baseline ?? '—'}</td>
                      <td className="num">{scenarioResult.comparison.horizonDays.scenario ?? '—'}</td>
                      <td className="num">
                        {formatSignedNumber(scenarioResult.comparison.horizonDays.absolute)}
                      </td>
                      <td className="num">
                        {formatRelativePct(scenarioResult.comparison.horizonDays.relative)}
                      </td>
                    </tr>
                    <tr>
                      <td>Выручка под риском</td>
                      <td className="num">
                        {formatCents(scenarioResult.comparison.revenueAtRiskCents.baseline)}
                      </td>
                      <td className="num">
                        {formatCents(scenarioResult.comparison.revenueAtRiskCents.scenario)}
                      </td>
                      <td className="num">
                        {formatSignedCents(scenarioResult.comparison.revenueAtRiskCents.absolute)}
                      </td>
                      <td className="num">
                        {formatRelativePct(scenarioResult.comparison.revenueAtRiskCents.relative)}
                      </td>
                    </tr>
                    <tr>
                      <td>Предстоящие продления</td>
                      <td className="num">
                        {formatCents(scenarioResult.comparison.upcomingRenewalsCents.baseline)}
                      </td>
                      <td className="num">
                        {formatCents(scenarioResult.comparison.upcomingRenewalsCents.scenario)}
                      </td>
                      <td className="num">
                        {formatSignedCents(scenarioResult.comparison.upcomingRenewalsCents.absolute)}
                      </td>
                      <td className="num">
                        {formatRelativePct(scenarioResult.comparison.upcomingRenewalsCents.relative)}
                      </td>
                    </tr>
                    <tr>
                      <td>Клиентов высокого риска</td>
                      <td className="num">
                        {scenarioResult.comparison.highRiskCustomers.baseline ?? '—'}
                      </td>
                      <td className="num">
                        {scenarioResult.comparison.highRiskCustomers.scenario ?? '—'}
                      </td>
                      <td className="num">
                        {formatSignedNumber(scenarioResult.comparison.highRiskCustomers.absolute)}
                      </td>
                      <td className="num">
                        {formatRelativePct(scenarioResult.comparison.highRiskCustomers.relative)}
                      </td>
                    </tr>
                    <tr>
                      <td>Клиентов среднего риска</td>
                      <td className="num">
                        {scenarioResult.comparison.mediumRiskCustomers.baseline ?? '—'}
                      </td>
                      <td className="num">
                        {scenarioResult.comparison.mediumRiskCustomers.scenario ?? '—'}
                      </td>
                      <td className="num">
                        {formatSignedNumber(scenarioResult.comparison.mediumRiskCustomers.absolute)}
                      </td>
                      <td className="num">
                        {formatRelativePct(scenarioResult.comparison.mediumRiskCustomers.relative)}
                      </td>
                    </tr>
                    <tr>
                      <td>Услуг высокого риска</td>
                      <td className="num">
                        {scenarioResult.comparison.highRiskServices.baseline ?? '—'}
                      </td>
                      <td className="num">
                        {scenarioResult.comparison.highRiskServices.scenario ?? '—'}
                      </td>
                      <td className="num">
                        {formatSignedNumber(scenarioResult.comparison.highRiskServices.absolute)}
                      </td>
                      <td className="num">
                        {formatRelativePct(scenarioResult.comparison.highRiskServices.relative)}
                      </td>
                    </tr>
                    {Object.entries(scenarioResult.comparison.categories).map(([cat, delta]) => (
                      <tr key={cat}>
                        <td className="cell-sub">
                          Категория: {CATEGORY_TITLES[cat] ?? cat}
                        </td>
                        <td className="num">{delta.baseline ?? 0}</td>
                        <td className="num">{delta.scenario ?? 0}</td>
                        <td className="num">{formatSignedNumber(delta.absolute)}</td>
                        <td className="num">{formatRelativePct(delta.relative)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {scenarioResult.customers.length > 0 ? (
                <div>
                  <div className="section-title">
                    Клиенты с изменившейся оценкой ({scenarioResult.customers.length})
                  </div>
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Клиент</th>
                          <th className="num">Балл (база → сценарий)</th>
                          <th>Категория</th>
                          <th className="num">Под риском (база → сценарий)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {scenarioResult.customers.map((c) => {
                          const scoreDiff =
                            c.scoreBefore !== null && c.scoreAfter !== null
                              ? c.scoreAfter - c.scoreBefore
                              : null
                          return (
                            <tr key={c.id}>
                              <td>
                                <Link to={`/customers/${c.id}`} className="cell-primary">
                                  #{c.id}
                                </Link>{' '}
                                <span className="cell-sub">{c.email ?? ''}</span>
                              </td>
                              <td className="num">
                                {c.scoreBefore === null ? '—' : c.scoreBefore.toFixed(1)} →{' '}
                                <strong>
                                  {c.scoreAfter === null ? '—' : c.scoreAfter.toFixed(1)}
                                </strong>
                                {scoreDiff !== null ? (
                                  <span className="cell-sub">
                                    {' '}
                                    ({formatSignedNumber(scoreDiff, 1)})
                                  </span>
                                ) : null}
                              </td>
                              <td>
                                <div className="row" style={{ gap: 6 }}>
                                  <RiskBadge category={c.categoryBefore as RiskCategory} />
                                  <span className="cell-sub">→</span>
                                  <RiskBadge category={c.categoryAfter as RiskCategory} />
                                </div>
                              </td>
                              <td className="num">
                                {formatCents(c.revenueAtRiskBefore)} →{' '}
                                <strong>{formatCents(c.revenueAtRiskAfter)}</strong>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="notice">
                  Ни у одного клиента не изменились итоговый балл или категория риска при этих
                  параметрах.
                </div>
              )}

              {availabilityEntries.length > 0 ? (
                <div>
                  <div className="section-title">Изменение доступности факторов по услугам</div>
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Фактор</th>
                          <th className="num">Доступен (база → сцен.)</th>
                          <th className="num">Неизвестен (база → сцен.)</th>
                          <th className="num">Стал неизвестен</th>
                          <th className="num">Стал доступен</th>
                        </tr>
                      </thead>
                      <tbody>
                        {availabilityEntries.map(([key, shift]) => (
                          <tr key={key}>
                            <td>
                              {factorLabelsByKey[key] ?? key}{' '}
                              <span className="hint">
                                (<code>{key}</code>)
                              </span>
                            </td>
                            <td className="num">
                              {shift.availableBefore} → {shift.availableAfter}
                            </td>
                            <td className="num">
                              {shift.unknownBefore} → {shift.unknownAfter}
                            </td>
                            <td className="num">{shift.becameUnknown}</td>
                            <td className="num">{shift.becameAvailable}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}

              <div className="notice info">
                <div>{scenarioResult.comparison.note}</div>
                <div style={{ marginTop: 4 }}>{scenarioResult.note}</div>
              </div>
            </div>
          ) : null}
        </div>
      </section>

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <h2>Веса факторов риска</h2>
            <span className="hint">
              {model.isDefault ? 'конфигурация по умолчанию' : 'настроено аналитиком'}
              {model.generation ? ` · поколение #${model.generation}` : ''}
              {model.updatedAt
                ? ` · обновлено ${new Date(model.updatedAt).toLocaleString('ru-RU')}`
                : ''}
            </span>
          </div>
          <div className="card-body">
            {model.factors.map((factor) => {
              const isDeprecated = Boolean(factor.deprecated)
              const value = isDeprecated ? 0 : (weights[factor.key] ?? 0)
              const isDefault = Math.abs(value - factor.defaultWeight) < 1e-9
              return (
                <div className="weight-row" key={factor.key}>
                  <div className="weight-info">
                    <div className="name">
                      {factor.label}{' '}
                      {isDeprecated ? (
                        <span className="badge neutral">диагностический · вне рейтинга</span>
                      ) : (
                        <span className="hint">
                          · ключ <code>{factor.key}</code> · по умолчанию {factor.defaultWeight}
                          {isDefault ? '' : ' (изменено)'}
                        </span>
                      )}
                    </div>
                    <div className="desc">{factor.description}</div>
                    <div className="formula">Расчёт: {factor.howComputed}</div>
                    <div className="formula">Нормализация: {factor.normalization}</div>
                  </div>
                  <input
                    className="input num"
                    type="number"
                    min={0}
                    max={1000}
                    step={0.5}
                    value={value}
                    disabled={isDeprecated}
                    title={
                      isDeprecated
                        ? 'Диагностический показатель уже учтён в renewal_failure_rate и не участвует в взвешенной сумме'
                        : undefined
                    }
                    onChange={(e) => {
                      const parsed = Number(e.target.value)
                      setWeights((prev) => ({
                        ...prev,
                        [factor.key]: Number.isFinite(parsed)
                          ? Math.max(0, Math.min(1000, parsed))
                          : 0,
                      }))
                    }}
                    aria-label={`Вес фактора ${factor.label}`}
                  />
                </div>
              )
            })}
          </div>
          <div className="card-note">
            Отрицательные веса запрещены. Если сумма весов равна нулю, услуга получает статус
            «Недостаточно данных» вместо произвольного нулевого риска.
          </div>
        </section>

        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h2>Горизонт, окно и пороги</h2>
            </div>
            <div className="card-body stack" style={{ gap: 14 }}>
              <div className="field">
                <label htmlFor="horizon">Горизонт прогноза, дней</label>
                <input
                  id="horizon"
                  className="input num"
                  style={{ width: '100%', textAlign: 'left' }}
                  type="number"
                  min={1}
                  max={365}
                  step={1}
                  value={horizon}
                  onChange={(e) =>
                    setHorizon(Math.max(1, Math.min(365, Math.round(Number(e.target.value) || 1))))
                  }
                />
                <span className="hint">
                  Продления вне горизонта не учитываются в выручке под риском.
                </span>
              </div>

              <div className="field">
                <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={useWindowLimit}
                    onChange={(e) => setUseWindowLimit(e.target.checked)}
                  />
                  <span>Ограничить окно анализа неуспешных продлений</span>
                </label>
                {useWindowLimit ? (
                  <input
                    id="failedRenewalWindowDays"
                    className="input num"
                    style={{ width: '100%', textAlign: 'left' }}
                    type="number"
                    min={1}
                    max={3650}
                    step={1}
                    value={windowDays}
                    onChange={(e) =>
                      setWindowDays(
                        Math.max(1, Math.min(3650, Math.round(Number(e.target.value) || 1))),
                      )
                    }
                    aria-label="Окно анализа неуспешных продлений, дней"
                  />
                ) : (
                  <div className="notice">
                    Режим <code>null</code>: учитываются все транзакции продления в снимке без
                    ограничения по давности.
                  </div>
                )}
                <span className="hint">
                  Если внутри выбранного окна нет попыток продления, фактор считается неизвестным
                  (не нулём).
                </span>
              </div>

              <div className="field">
                <label htmlFor="lowMax">Верхняя граница низкого риска</label>
                <input
                  id="lowMax"
                  className="input num"
                  style={{ width: '100%', textAlign: 'left' }}
                  type="number"
                  min={0}
                  max={99}
                  step={1}
                  value={lowMax}
                  onChange={(e) => setLowMax(Math.round(Number(e.target.value) || 0))}
                />
              </div>

              <div className="field">
                <label htmlFor="mediumMax">Верхняя граница среднего риска</label>
                <input
                  id="mediumMax"
                  className="input num"
                  style={{ width: '100%', textAlign: 'left' }}
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={mediumMax}
                  onChange={(e) => setMediumMax(Math.round(Number(e.target.value) || 1))}
                />
                <span className="hint">
                  Требуется lowMax &lt; mediumMax, иначе сервер отклонит изменение.
                </span>
              </div>

              <div className="notice">
                Текущие пороги: 0–{lowMax} низкий, {lowMax + 1}–{mediumMax} средний,{' '}
                {mediumMax + 1}–100 высокий.
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>Как читать модель</h2>
            </div>
            <div className="card-body">
              <div className="notice info">
                Формула:{' '}
                <code>risk_score = 100 × Σ(weight_i × feature_i) / Σ(weight_i)</code>. Каждый
                активный признак нормализован в диапазон 0…1.
              </div>
              <div className="notice" style={{ marginTop: 10 }}>
                <strong>Модель не откалибрована.</strong> Балл риска — не вероятность оттока: в
                данных нет исторических исходов, поэтому обучение и валидация невозможны. Значение
                отражает силу наблюдаемых сигналов риска.
              </div>
            </div>
          </section>
        </div>
      </div>

      {toast ? <div className={`toast${toast.err ? ' err' : ''}`}>{toast.text}</div> : null}
    </div>
  )
}
