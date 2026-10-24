import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import type { AIResponse, AIStatus } from '../types'
import { ErrorBox, Loading } from './ui'

/** Pull customer ids out of the backend citation sources, so an answer can link
 * straight to the records it was grounded in rather than leaving the analyst to
 * hunt for them. */
function citedCustomerIds(response: AIResponse): number[] {
  const found = new Set<number>()
  for (const citation of response.citations) {
    const matches = citation.source.matchAll(/customers\/(\d+)/g)
    for (const match of matches) {
      found.add(Number(match[1]))
    }
  }
  return [...found].sort((a, b) => a - b)
}

/**
 * Renders one AI answer with the visual hierarchy the backend contract defines:
 * verdict, verified facts, factor explanation, recommendations, limitations.
 * Numbers shown here are the backend's, not the model's — the model only
 * narrates them, and any ungrounded claim is already stripped server-side.
 */
function AnswerBlock({ response }: { response: AIResponse }) {
  const { answer } = response
  const customerIds = useMemo(() => citedCustomerIds(response), [response])
  const mentionsActions = response.citations.some((citation) => citation.source.includes('/actions'))
  return (
    <article className="ai-answer">
      <p className="ai-summary">{answer.summary}</p>

      {customerIds.length > 0 && (
        <nav className="ai-links" aria-label="Перейти к данным">
          <span className="ai-links-label">Открыть в системе:</span>
          {customerIds.map((id) => (
            <Link className="ai-link" key={id} to={`/customers/${id}`}>
              Клиент #{id}
            </Link>
          ))}
          {mentionsActions && customerIds.length === 1 && (
            <Link className="ai-link" to={`/customers/${customerIds[0]}#retention-actions`}>
              Подтверждённые действия
            </Link>
          )}
        </nav>
      )}

      {answer.facts.length > 0 && (
        <section className="ai-section">
          <h4>Подтверждённые факты</h4>
          <ul>
            {answer.facts.map((fact, index) => (
              <li key={index}>{fact}</li>
            ))}
          </ul>
        </section>
      )}

      {answer.factor_explanation && (
        <section className="ai-section">
          <h4>Объяснение факторов</h4>
          <p>{answer.factor_explanation}</p>
        </section>
      )}

      {answer.recommendations.length > 0 && (
        <section className="ai-section">
          <h4>Рекомендации по удержанию</h4>
          <ul>
            {answer.recommendations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      )}

      {answer.limitations && (
        <section className="ai-section ai-limitations">
          <h4>Ограничения</h4>
          <p>{answer.limitations}</p>
        </section>
      )}

      {response.warnings.length > 0 && (
        <section className="ai-section ai-warnings">
          <h4>Проверка достоверности</h4>
          <ul>
            {response.warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </section>
      )}

      {response.citations.length > 0 && (
        <section className="ai-section ai-citations">
          <h4>Источники</h4>
          <ul>
            {response.citations.map((citation, index) => (
              <li key={index}>
                <span className={`ai-cite-kind ai-cite-${citation.kind}`}>
                  {citation.kind === 'fact' ? 'данные' : 'документ'}
                </span>{' '}
                <code>{citation.source}</code>
                {citation.detail ? ` — ${citation.detail}` : ''}
              </li>
            ))}
          </ul>
        </section>
      )}

      <footer className="ai-meta">
        <span>Модель: {response.model}</span>
        {typeof response.context.latencyMs === 'number' && (
          <span>{(response.context.latencyMs / 1000).toFixed(1)} с</span>
        )}
        <span className={response.grounded ? 'ai-grounded' : 'ai-ungrounded'}>
          {response.grounded ? 'Все числа подтверждены данными' : 'Часть утверждений отклонена проверкой'}
        </span>
      </footer>
    </article>
  )
}

const PORTFOLIO_EXAMPLES = [
  'Какая выручка под риском в портфеле и из чего она складывается?',
  'Какие клиенты требуют внимания в первую очередь и почему?',
  'Объясни методологию: почему балл риска — не вероятность оттока?',
]

const CUSTOMER_EXAMPLES = [
  'Почему у этого клиента такой балл риска?',
  'Какие факторы влияют на риск сильнее всего?',
  'Что означает его выручка под риском и что предпринять?',
]

interface Turn {
  question: string
  response?: AIResponse
  error?: string
}

/**
 * Chat panel. Uses the same bearer-authenticated fetch layer as the rest of the
 * app, so the AI surface is never less protected than the data it explains.
 * When the model is unavailable the panel says so and the rest of the product
 * keeps working.
 */
export function AIAnalystPanel({ customerId }: { customerId?: number }) {
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    api
      .aiStatus()
      .then(setStatus)
      .catch(() => setStatus(null))
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [turns])

  const ask = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || busy) return
      setQuestion('')
      setTurns((previous) => [...previous, { question: trimmed }])
      setBusy(true)
      try {
        const response = customerId
          ? await api.aiExplainCustomer(customerId, trimmed)
          : await api.aiChat(trimmed)
        setTurns((previous) =>
          previous.map((turn, index) =>
            index === previous.length - 1 ? { ...turn, response } : turn,
          ),
        )
      } catch (error) {
        const detail =
          error instanceof ApiError ? error.detail : 'Не удалось получить ответ аналитика.'
        setTurns((previous) =>
          previous.map((turn, index) =>
            index === previous.length - 1 ? { ...turn, error: detail } : turn,
          ),
        )
      } finally {
        setBusy(false)
      }
    },
    [busy, customerId],
  )

  const examples = customerId ? CUSTOMER_EXAMPLES : PORTFOLIO_EXAMPLES

  return (
    <section className="card ai-panel">
      <header className="ai-panel-head">
        <div>
          <h3>AI-аналитик</h3>
          <p className="muted">
            Локальная модель объясняет оценки Risk Engine. Числа берутся из backend, модель их не
            вычисляет.
          </p>
        </div>
        {status && (
          <span className={`ai-status ai-status-${status.status}`}>
            {status.status === 'ready'
              ? `готов · ${status.model}`
              : status.status === 'disabled'
                ? 'выключен'
                : 'недоступен'}
          </span>
        )}
      </header>

      {status && status.status !== 'ready' && (
        <p className="ai-status-note">
          {status.status === 'disabled'
            ? 'AI Analyst выключен (AEZA_AI_ENABLED=0). Основная аналитика работает без него.'
            : `Локальная модель недоступна. ${status.reason} Основная аналитика работает без неё.`}
        </p>
      )}

      {turns.length > 0 && (
        <div className="ai-thread">
          {turns.map((turn, index) => (
            <div key={index} className="ai-turn">
              <p className="ai-question">{turn.question}</p>
              {turn.response && <AnswerBlock response={turn.response} />}
              {turn.error && <ErrorBox>{turn.error}</ErrorBox>}
              {!turn.response && !turn.error && <Loading label="Модель думает…" />}
            </div>
          ))}
          <div ref={endRef} />
        </div>
      )}

      <div className="ai-examples">
        {examples.map((example) => (
          <button
            key={example}
            type="button"
            className="ai-example"
            disabled={busy}
            onClick={() => ask(example)}
          >
            {example}
          </button>
        ))}
      </div>

      <form
        className="ai-input"
        onSubmit={(event) => {
          event.preventDefault()
          void ask(question)
        }}
      >
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={customerId ? 'Спросите про этого клиента…' : 'Спросите про портфель…'}
          maxLength={2000}
          disabled={busy}
          aria-label="Вопрос AI-аналитику"
        />
        <button type="submit" className="btn" disabled={busy || !question.trim()}>
          {busy ? '…' : 'Спросить'}
        </button>
        {turns.length > 0 && (
          <button type="button" className="btn sm" onClick={() => setTurns([])} disabled={busy}>
            Очистить
          </button>
        )}
      </form>
    </section>
  )
}
