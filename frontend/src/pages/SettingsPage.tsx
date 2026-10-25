import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
import { Collapsible, SlidingTabs } from '../components/motion'
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

const SIMPLE_FACTOR_DESCRIPTIONS: Record<string, string> = {
  expiry_proximity: 'До окончания оплаченного периода осталось мало времени или срок уже вышел.',
  auto_prolong_disabled: 'Клиенту нужно продлевать услугу вручную.',
  insufficient_balance: 'На балансе не хватает средств для оплаты следующего продления.',
  prolong_wait_status: 'Срок оплаты подошёл, услуга ожидает списания средств.',
  failed_renewals: 'Количество неудачных попыток оплаты за всё время (справочно, не влияет на балл).',
  suspended_status: 'Работа услуги временно приостановлена.',
  renewal_failure_rate: 'Как часто попытки продлить услугу завершались ошибкой оплаты.',
}

type PresetKey = 'h7' | 'h90' | 'whole_snapshot' | 'strict_bands'

const PRESET_TABS: ReadonlyArray<{ value: PresetKey; label: string }> = [
  { value: 'h7', label: 'Горизонт 7 дн.' },
  { value: 'h90', label: 'Горизонт 90 дн.' },
  { value: 'whole_snapshot', label: 'Отказы за весь снимок' },
  { value: 'strict_bands', label: 'Строгие пороги 25/50' },
]

export default function SettingsPage() {
  const { refreshKey, notifyMutation } = useAnalysis()
  const [model, setModel] = useState<ModelSettings | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [horizon, setHorizon] = useState(30)
  const [lowMax, setLowMax] = useState(34)
  const [mediumMax, setMediumMax] = useState(64)
  const [useWindowLimit, setUseWindowLimit] = useState(true)
  const [windowDays, setWindowDays] = useState(90)

  const [scenarioName, setScenarioName] = useState('Проверка чувствительности')
  const [activePreset, setActivePreset] = useState<PresetKey | null>(null)
  const [scenarioResult, setScenarioResult] = useState<ScenarioComparisonResponse | null>(null)
  const lastScenarioRef = useRef<ScenarioComparisonResponse | null>(null)
  if (scenarioResult) {
    lastScenarioRef.current = scenarioResult
  }
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
    setActivePreset(null)
    setConflictDetected(false)
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    setErrorIssues(undefined)
    try {
      const [settings, summaryData] = await Promise.all([
        api.modelSettings(),
        api.summary(),
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
  }, [applyModel])

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
    if (!model) return
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
    if (!model) return
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
    setActivePreset(preset)

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

  const shownScenario = scenarioResult ?? lastScenarioRef.current
  const availabilityEntries = shownScenario
    ? Object.entries(shownScenario.factorAvailability)
    : []

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Модель риска и What-If сценарии</h1>
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
            disabled={saving || model.isDefault}
          >
            Значения по умолчанию
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={save}
            disabled={saving || !dirty}
          >
            {saving ? 'Сохранение…' : dirty ? 'Опубликовать в модель' : 'Сохранено'}
          </button>
        </div>
      </div>

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
        <div className="card-body">
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
            <SlidingTabs
              ariaLabel="Быстрые пресеты сценария"
              variant="subtle"
              size="sm"
              value={activePreset}
              onChange={(preset) => applyPreset(preset)}
              items={PRESET_TABS.map((item) => ({ ...item, disabled: simulating }))}
            />
            <button
              type="button"
              className="btn primary sm"
              disabled={simulating}
              onClick={() => void runScenario()}
            >
              {simulating ? 'Расчёт…' : 'Рассчитать по форме'}
            </button>
          </div>

          <Collapsible open={Boolean(scenarioResult)}>
            {shownScenario ? (
              <div className="stack" style={{ gap: 16, paddingTop: 16 }}>
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <div>
                    <strong>Результат сценария «{shownScenario.name}»</strong>
                    <span className="hint" style={{ marginLeft: 8 }}>
                      база vs сценарий · клиентов с изменением оценки:{' '}
                      {shownScenario.customers.length}
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
                        <td className="num">{shownScenario.comparison.horizonDays.baseline ?? '—'}</td>
                        <td className="num">{shownScenario.comparison.horizonDays.scenario ?? '—'}</td>
                        <td className="num">
                          {formatSignedNumber(shownScenario.comparison.horizonDays.absolute)}
                        </td>
                        <td className="num">
                          {formatRelativePct(shownScenario.comparison.horizonDays.relative)}
                        </td>
                      </tr>
                      <tr>
                        <td>Выручка под риском</td>
                        <td className="num">
                          {formatCents(shownScenario.comparison.revenueAtRiskCents.baseline)}
                        </td>
                        <td className="num">
                          {formatCents(shownScenario.comparison.revenueAtRiskCents.scenario)}
                        </td>
                        <td className="num">
                          {formatSignedCents(shownScenario.comparison.revenueAtRiskCents.absolute)}
                        </td>
                        <td className="num">
                          {formatRelativePct(shownScenario.comparison.revenueAtRiskCents.relative)}
                        </td>
                      </tr>
                      <tr>
                        <td>Предстоящие продления</td>
                        <td className="num">
                          {formatCents(shownScenario.comparison.upcomingRenewalsCents.baseline)}
                        </td>
                        <td className="num">
                          {formatCents(shownScenario.comparison.upcomingRenewalsCents.scenario)}
                        </td>
                        <td className="num">
                          {formatSignedCents(shownScenario.comparison.upcomingRenewalsCents.absolute)}
                        </td>
                        <td className="num">
                          {formatRelativePct(shownScenario.comparison.upcomingRenewalsCents.relative)}
                        </td>
                      </tr>
                      <tr>
                        <td>Клиентов высокого риска</td>
                        <td className="num">
                          {shownScenario.comparison.highRiskCustomers.baseline ?? '—'}
                        </td>
                        <td className="num">
                          {shownScenario.comparison.highRiskCustomers.scenario ?? '—'}
                        </td>
                        <td className="num">
                          {formatSignedNumber(shownScenario.comparison.highRiskCustomers.absolute)}
                        </td>
                        <td className="num">
                          {formatRelativePct(shownScenario.comparison.highRiskCustomers.relative)}
                        </td>
                      </tr>
                      <tr>
                        <td>Клиентов среднего риска</td>
                        <td className="num">
                          {shownScenario.comparison.mediumRiskCustomers.baseline ?? '—'}
                        </td>
                        <td className="num">
                          {shownScenario.comparison.mediumRiskCustomers.scenario ?? '—'}
                        </td>
                        <td className="num">
                          {formatSignedNumber(shownScenario.comparison.mediumRiskCustomers.absolute)}
                        </td>
                        <td className="num">
                          {formatRelativePct(shownScenario.comparison.mediumRiskCustomers.relative)}
                        </td>
                      </tr>
                      <tr>
                        <td>Услуг высокого риска</td>
                        <td className="num">
                          {shownScenario.comparison.highRiskServices.baseline ?? '—'}
                        </td>
                        <td className="num">
                          {shownScenario.comparison.highRiskServices.scenario ?? '—'}
                        </td>
                        <td className="num">
                          {formatSignedNumber(shownScenario.comparison.highRiskServices.absolute)}
                        </td>
                        <td className="num">
                          {formatRelativePct(shownScenario.comparison.highRiskServices.relative)}
                        </td>
                      </tr>
                      {Object.entries(shownScenario.comparison.categories).map(([cat, delta]) => (
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

                {shownScenario.customers.length > 0 ? (
                  <div>
                    <div className="section-title">
                      Клиенты с изменившейся оценкой ({shownScenario.customers.length})
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
                          {shownScenario.customers.map((c) => {
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
                  <div>{shownScenario.comparison.note}</div>
                  <div style={{ marginTop: 4 }}>{shownScenario.note}</div>
                </div>
              </div>
            ) : null}
          </Collapsible>
        </div>
      </section>

      <div className="grid-main">
        <section className="card settings-equal-card">
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
              const shortDesc = SIMPLE_FACTOR_DESCRIPTIONS[factor.key] ?? factor.description
              return (
                <div className="weight-row" key={factor.key}>
                  <div className="weight-info">
                    <div className="name">
                      {factor.label}{' '}
                      {isDeprecated ? (
                        <span className="badge neutral">вне рейтинга</span>
                      ) : (
                        <span className="hint">
                          · по умолчанию {factor.defaultWeight}
                          {isDefault ? '' : ' (изменено)'}
                        </span>
                      )}
                    </div>
                    <div className="desc">{shortDesc}</div>
                  </div>
                  <div
                    className={`num-stepper${isDeprecated ? ' is-disabled' : ''}`}
                    title={
                      isDeprecated
                        ? 'Справочный показатель: уже учтён в доле неуспешных продлений и не влияет на балл'
                        : undefined
                    }
                  >
                    <input
                      className="input num"
                      type="number"
                      min={0}
                      max={1000}
                      step={0.5}
                      value={value}
                      disabled={isDeprecated}
                      onChange={(e) => {
                        setActivePreset(null)
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
                    <div className="num-stepper-btns">
                      <button
                        type="button"
                        className="num-step-btn"
                        disabled={isDeprecated || value >= 1000}
                        onClick={() => {
                          setActivePreset(null)
                          setWeights((prev) => ({
                            ...prev,
                            [factor.key]: Math.min(
                              1000,
                              Math.round(((prev[factor.key] ?? 0) + 0.5) * 10) / 10,
                            ),
                          }))
                        }}
                        aria-label={`Увеличить вес фактора ${factor.label}`}
                        title="Увеличить (+0.5)"
                      >
                        <svg viewBox="0 0 12 12" aria-hidden="true">
                          <path
                            d="M2.5 7.5L6 4l3.5 3.5"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.8"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </button>
                      <button
                        type="button"
                        className="num-step-btn"
                        disabled={isDeprecated || value <= 0}
                        onClick={() => {
                          setActivePreset(null)
                          setWeights((prev) => ({
                            ...prev,
                            [factor.key]: Math.max(
                              0,
                              Math.round(((prev[factor.key] ?? 0) - 0.5) * 10) / 10,
                            ),
                          }))
                        }}
                        aria-label={`Уменьшить вес фактора ${factor.label}`}
                        title="Уменьшить (−0.5)"
                      >
                        <svg viewBox="0 0 12 12" aria-hidden="true">
                          <path
                            d="M2.5 4.5L6 8l3.5-3.5"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.8"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="card settings-equal-card">
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
                onChange={(e) => {
                  setActivePreset(null)
                  setHorizon(Math.max(1, Math.min(365, Math.round(Number(e.target.value) || 1))))
                }}
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
                  onChange={(e) => {
                    setActivePreset(null)
                    setUseWindowLimit(e.target.checked)
                  }}
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
                  onChange={(e) => {
                    setActivePreset(null)
                    setWindowDays(
                      Math.max(1, Math.min(3650, Math.round(Number(e.target.value) || 1))),
                    )
                  }}
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
                onChange={(e) => {
                  setActivePreset(null)
                  setLowMax(Math.round(Number(e.target.value) || 0))
                }}
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
                onChange={(e) => {
                  setActivePreset(null)
                  setMediumMax(Math.round(Number(e.target.value) || 1))
                }}
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
      </div>

      {toast ? <div className={`toast${toast.err ? ' err' : ''}`}>{toast.text}</div> : null}
    </div>
  )
}
