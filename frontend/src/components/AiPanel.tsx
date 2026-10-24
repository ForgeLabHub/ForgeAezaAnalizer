import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { AiExplanation, AiStatus } from '../types'
import { ErrorBox, Loading } from './ui'

/**
 * Local-AI explanation panel for one customer.
 *
 * Rules this component follows:
 *
 * - It asks `GET /ai/status` first. If the AI layer is disabled or the provider
 *   is unreachable, it shows that fact and offers **no button**, so there is
 *   never a control that can only fail.
 * - The explanation is produced by the backend from the already published
 *   calculation; the numbers in the reply are verified there. The panel renders
 *   the text as plain text (no markup), so a model cannot inject layout.
 * - Nothing here writes data. The panel never changes a score, a setting or a
 *   playbook status; the retention actions stay in the Playbooks card.
 */

const UNAVAILABLE_HINT =
  'Локальная ИИ-модель недоступна. Расчёт, причины риска и рекомендации выше ' +
  'построены детерминированным движком и остаются полностью рабочими.'

export default function AiPanel({ customerId }: { customerId: number }) {
  const [status, setStatus] = useState<AiStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)

  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<AiExplanation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const loadStatus = useCallback(async () => {
    setStatusLoading(true)
    setStatusError(null)
    try {
      setStatus(await api.aiStatus())
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.detail : 'Не удалось проверить доступность ИИ')
    } finally {
      setStatusLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  // A new customer invalidates the previous answer.
  useEffect(() => {
    setAnswer(null)
    setError(null)
  }, [customerId])

  async function explain() {
    setBusy(true)
    setError(null)
    try {
      setAnswer(await api.aiExplain(customerId, question.trim() || undefined))
    } catch (err) {
      setAnswer(null)
      setError(err instanceof ApiError ? err.detail : 'Не удалось получить объяснение')
    } finally {
      setBusy(false)
    }
  }

  if (statusLoading) return <Loading label="Проверка локальной модели…" />
  if (statusError) return <ErrorBox>{statusError}</ErrorBox>
  if (!status) return null

  if (!status.enabled || !status.reachable) {
    return (
      <div className="notice">
        <strong>ИИ-объяснение недоступно.</strong> {status.detail ?? UNAVAILABLE_HINT}
        <div className="hint" style={{ marginTop: 8 }}>
          Модель: <code>{status.model}</code> · провайдер <code>{status.provider}</code>.
          Включите её переменной <code>AEZA_LLM_ENABLED=1</code> и адресом{' '}
          <code>AEZA_LLM_BASE_URL</code>.
        </div>
      </div>
    )
  }

  return (
    <div className="ai-panel">
      <div className="ai-panel-head">
        <span className="hint">
          Локальная модель <code>{status.model}</code> · числа берутся из расчёта и проверяются
        </span>
      </div>

      <div className="field">
        <label htmlFor="ai-question">Уточняющий вопрос (необязательно)</label>
        <input
          id="ai-question"
          className="input"
          type="text"
          maxLength={600}
          placeholder="Например: что сделать в первую очередь?"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={busy}
        />
      </div>

      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="btn primary" onClick={explain} disabled={busy}>
          {busy ? 'Модель думает…' : 'Объяснить риск с помощью ИИ'}
        </button>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}

      {answer ? (
        <div className="ai-answer" aria-live="polite">
          {/* Plain text: a model must not be able to inject markup. */}
          <pre className="ai-answer-text">{answer.text}</pre>
          <div className="notice" style={{ marginTop: 10 }}>
            {answer.note}
          </div>
        </div>
      ) : null}
    </div>
  )
}
