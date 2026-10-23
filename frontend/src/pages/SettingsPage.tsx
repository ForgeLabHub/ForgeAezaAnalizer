import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { ModelSettings, Summary } from '../types'
import { ErrorBox, Loading, Metric, formatEur } from '../components/ui'

export default function SettingsPage() {
  const [model, setModel] = useState<ModelSettings | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [horizon, setHorizon] = useState(30)
  const [lowMax, setLowMax] = useState(34)
  const [mediumMax, setMediumMax] = useState(64)
  // The window is nullable by design: null means "the whole snapshot".
  const [windowEnabled, setWindowEnabled] = useState(true)
  const [windowDays, setWindowDays] = useState(90)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null)

  const applyModel = useCallback((data: ModelSettings) => {
    setModel(data)
    setWeights({ ...data.settings.weights })
    setHorizon(data.settings.horizonDays)
    setLowMax(data.settings.lowMax)
    setMediumMax(data.settings.mediumMax)
    const stored = data.settings.failedRenewalWindowDays
    setWindowEnabled(stored !== null && stored !== undefined)
    setWindowDays(stored ?? 90)
  }, [])

  const refreshSummary = useCallback(async () => {
    const data = await api.summary()
    setSummary(data)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [settings, summaryData] = await Promise.all([api.modelSettings(), api.summary()])
        if (cancelled) return
        applyModel(settings)
        setSummary(summaryData)
      } catch (err) {
        if (!cancelled)
          setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить настройки модели')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [applyModel])

  const dirty = useMemo(() => {
    if (!model) return false
    if (horizon !== model.settings.horizonDays) return true
    if (lowMax !== model.settings.lowMax || mediumMax !== model.settings.mediumMax) return true
    const storedWindow = model.settings.failedRenewalWindowDays ?? null
    if ((windowEnabled ? windowDays : null) !== storedWindow) return true
    return Object.keys(weights).some(
      (key) => Math.abs(weights[key] - (model.settings.weights[key] ?? 0)) > 1e-9,
    )
  }, [model, weights, horizon, lowMax, mediumMax, windowEnabled, windowDays])

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const updated = await api.patchSettings({
        horizonDays: horizon,
        weights,
        lowMax,
        mediumMax,
        failedRenewalWindowDays: windowEnabled ? windowDays : null,
      })
      applyModel(updated)
      await refreshSummary()
      setToast({ text: 'Настройки сохранены, аналитика пересчитана.' })
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сохранить настройки')
    } finally {
      setSaving(false)
    }
  }

  async function reset() {
    setSaving(true)
    setError(null)
    try {
      const updated = await api.resetSettings()
      applyModel(updated)
      await refreshSummary()
      setToast({ text: 'Восстановлены значения по умолчанию.' })
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сбросить настройки')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 3200)
    return () => clearTimeout(timer)
  }, [toast])

  if (loading) return <Loading label="Загрузка настроек модели…" />
  if (!model) return <ErrorBox>{error ?? 'Настройки недоступны'}</ErrorBox>

  const totalWeight = Object.values(weights).reduce((sum, w) => sum + (w > 0 ? w : 0), 0)

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Настройки модели риска</h1>
          <p>
            Веса факторов влияют на backend-расчёт: после сохранения аналитика и все карточки
            пересчитываются. Нулевой вес исключает фактор из расчёта, оставшиеся веса
            перенормируются.
          </p>
        </div>
        <div className="row">
          <button className="btn" onClick={reset} disabled={saving || model.isDefault}>
            Значения по умолчанию
          </button>
          <button className="btn primary" onClick={save} disabled={saving || !dirty}>
            {saving ? 'Сохранение…' : dirty ? 'Сохранить' : 'Сохранено'}
          </button>
        </div>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}

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
            label="Сумма весов"
            value={totalWeight.toFixed(1)}
            foot="нормировка: 100 × Σ(w·f) / Σw"
          />
        </div>
      ) : null}

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <h2>Веса факторов риска</h2>
            <span className="hint">
              {model.isDefault ? 'конфигурация по умолчанию' : 'настроено аналитиком'}
              {model.updatedAt ? ` · обновлено ${new Date(model.updatedAt).toLocaleString('ru-RU')}` : ''}
            </span>
          </div>
          <div className="card-body">
            {model.factors.map((factor) => {
              const value = weights[factor.key] ?? 0
              const isDefault = Math.abs(value - factor.defaultWeight) < 1e-9
              return (
                <div className="weight-row" key={factor.key}>
                  <div className="weight-info">
                    <div className="name">
                      {factor.label}{' '}
                      <span className="hint">
                        · ключ <code>{factor.key}</code> · по умолчанию {factor.defaultWeight}
                        {isDefault ? '' : ' (изменено)'}
                      </span>
                    </div>
                    <div className="desc">{factor.description}</div>
                    <div className="formula">Расчёт: {factor.howComputed}</div>
                    <div className="formula">Нормализация: {factor.normalization}</div>
                  </div>
                  <input
                    className="input num"
                    type="number"
                    min={0}
                    max={100}
                    step={0.5}
                    value={value}
                    onChange={(e) => {
                      const parsed = Number(e.target.value)
                      setWeights((prev) => ({
                        ...prev,
                        [factor.key]: Number.isFinite(parsed) ? Math.max(0, parsed) : 0,
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
              <h2>Горизонт и пороги</h2>
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
                  value={horizon}
                  onChange={(e) => setHorizon(Math.max(1, Math.min(365, Number(e.target.value) || 1)))}
                />
                <span className="hint">
                  Продления вне горизонта не учитываются в выручке под риском.
                </span>
              </div>
              <div className="field">
                <label htmlFor="windowDays">Окно неудачных продлений, дней</label>
                <input
                  id="windowDays"
                  className="input num"
                  style={{ width: '100%', textAlign: 'left' }}
                  type="number"
                  min={1}
                  max={3650}
                  value={windowDays}
                  disabled={!windowEnabled}
                  onChange={(e) =>
                    setWindowDays(Math.max(1, Math.min(3650, Number(e.target.value) || 1)))
                  }
                />
                <label className="hint">
                  <input
                    type="checkbox"
                    checked={!windowEnabled}
                    onChange={(e) => setWindowEnabled(!e.target.checked)}
                  />{' '}
                  учитывать весь снимок (null)
                </label>
                <span className="hint">
                  Доля неуспешных продлений считается только по попыткам внутри окна. При
                  выключенном ограничении используются все события снимка. События позже момента
                  расчёта не учитываются никогда.
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
                  value={lowMax}
                  onChange={(e) => setLowMax(Number(e.target.value))}
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
                  value={mediumMax}
                  onChange={(e) => setMediumMax(Number(e.target.value))}
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
                признак нормализован в диапазон 0…1.
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
