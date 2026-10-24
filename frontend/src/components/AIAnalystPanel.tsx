import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useMatch } from 'react-router-dom'
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
  const mentionsActions = response.citations.some((citation) =>
    citation.source.includes('/actions'),
  )
  return (
    <article className="ai-answer">
      <p className="ai-summary">{answer.summary}</p>

      {customerIds.length > 0 && (
        <nav className="ai-links" aria-label="Перейти к данным">
          <span className="ai-links-label">Открыть:</span>
          {customerIds.map((id) => (
            <Link className="ai-link" key={id} to={`/customers/${id}`}>
              Клиент #{id}
            </Link>
          ))}
          {mentionsActions && customerIds.length === 1 && (
            <Link className="ai-link" to={`/customers/${customerIds[0]}#retention-actions`}>
              Действия
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
          {response.grounded
            ? 'Все числа подтверждены данными'
            : 'Часть утверждений отклонена проверкой'}
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
  customerId?: number
  response?: AIResponse
  error?: string
}

/**
 * Floating support-chat-style AI Analyst widget mounted in the application shell.
 * Starts collapsed as a circular button in the bottom-right corner and opens an
 * overlay chat window above the active page without losing state across navigation.
 */
export function AIAnalystWidget() {
  const customerMatch = useMatch('/customers/:id')
  const routeCustomerId = useMemo(() => {
    const raw = customerMatch?.params.id
    if (!raw) return undefined
    const parsed = Number(raw)
    return Number.isInteger(parsed) && parsed >= 1 ? parsed : undefined
  }, [customerMatch?.params.id])

  const [open, setOpen] = useState(false)
  const [scopeOverride, setScopeOverride] = useState<'auto' | 'portfolio'>('auto')
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)

  const endRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  // Reset scope override back to auto whenever the user navigates to a customer card
  useEffect(() => {
    if (routeCustomerId !== undefined) {
      setScopeOverride('auto')
    }
  }, [routeCustomerId])

  const activeCustomerId =
    routeCustomerId !== undefined && scopeOverride === 'auto' ? routeCustomerId : undefined

  useEffect(() => {
    api
      .aiStatus()
      .then(setStatus)
      .catch(() => setStatus(null))
  }, [])

  useEffect(() => {
    if (!open) return
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [turns, open])

  useEffect(() => {
    if (!open) return
    const timer = setTimeout(() => inputRef.current?.focus(), 60)
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      clearTimeout(timer)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const ask = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || busy) return
      const targetCustomerId = activeCustomerId
      setQuestion('')
      setTurns((previous) => [...previous, { question: trimmed, customerId: targetCustomerId }])
      setBusy(true)
      try {
        const response = targetCustomerId
          ? await api.aiExplainCustomer(targetCustomerId, trimmed)
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
    [busy, activeCustomerId],
  )

  const examples = activeCustomerId ? CUSTOMER_EXAMPLES : PORTFOLIO_EXAMPLES

  const statusText = status
    ? status.status === 'ready'
      ? `Онлайн · ${status.model}`
      : status.status === 'disabled'
        ? 'Выключен'
        : 'Недоступен'
    : 'Проверка…'

  return (
    <div className="ai-widget-root">
      {open ? (
        <section
          className="ai-widget-window"
          role="dialog"
          aria-label="Чат с AI-аналитиком"
        >
          <header className="ai-widget-header">
            <div className="ai-widget-header-top">
              <div className="ai-widget-identity">
                <div className="ai-widget-avatar" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <path
                      d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9L12 3z"
                      stroke="currentColor"
                      strokeWidth="1.9"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M18.5 15.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9.9-2.1z"
                      fill="currentColor"
                    />
                  </svg>
                </div>
                <div>
                  <div className="ai-widget-title">AI-аналитик</div>
                  <div className="ai-widget-sub">
                    <span
                      className={`ai-widget-dot ${status ? `is-${status.status}` : ''}`}
                      aria-hidden="true"
                    />
                    <span>{statusText}</span>
                  </div>
                </div>
              </div>

              <div className="ai-widget-actions">
                {turns.length > 0 ? (
                  <button
                    type="button"
                    className="ai-widget-icon-btn"
                    onClick={() => setTurns([])}
                    disabled={busy}
                    title="Очистить историю чата"
                    aria-label="Очистить историю чата"
                  >
                    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                      <path
                        d="M4.5 6h11M8 6V4.5a1 1 0 011-1h2a1 1 0 011 1V6m1.5 0l-.6 9.1a1.5 1.5 0 01-1.5 1.4H8.6a1.5 1.5 0 01-1.5-1.4L6.5 6"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                ) : null}
                <button
                  type="button"
                  className="ai-widget-icon-btn"
                  onClick={() => setOpen(false)}
                  title="Свернуть окно (Esc)"
                  aria-label="Свернуть окно"
                >
                  <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path
                      d="M5.5 5.5l9 9m0-9l-9 9"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              </div>
            </div>

            {routeCustomerId !== undefined ? (
              <div className="ai-widget-scope" role="tablist" aria-label="Контекст вопросов">
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeCustomerId !== undefined}
                  className={activeCustomerId !== undefined ? 'active' : ''}
                  onClick={() => setScopeOverride('auto')}
                >
                  Клиент #{routeCustomerId}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeCustomerId === undefined}
                  className={activeCustomerId === undefined ? 'active' : ''}
                  onClick={() => setScopeOverride('portfolio')}
                >
                  Весь портфель
                </button>
              </div>
            ) : null}
          </header>

          <div className="ai-widget-messages">
            {status && status.status !== 'ready' ? (
              <div className="ai-status-note">
                {status.status === 'disabled'
                  ? 'AI-аналитик выключен (AEZA_AI_ENABLED=0). Основная аналитика продолжает работать.'
                  : `Локальная модель недоступна. ${status.reason ?? ''}`}
              </div>
            ) : null}

            <div className="ai-bubble-bot ai-greeting">
              Задайте вопрос по{' '}
              {activeCustomerId ? `клиенту #${activeCustomerId}` : 'портфелю клиентов'}, факторам
              риска или выручке под риском. Все расчёты выполняются в Risk Engine — модель их
              объясняет.
            </div>

            {turns.map((turn, index) => (
              <div key={index} className="ai-chat-turn">
                <div className="ai-bubble-user-wrap">
                  {turn.customerId ? (
                    <span className="ai-turn-scope">Клиент #{turn.customerId}</span>
                  ) : null}
                  <div className="ai-bubble-user">{turn.question}</div>
                </div>
                <div className="ai-bubble-bot-wrap">
                  {turn.response ? <AnswerBlock response={turn.response} /> : null}
                  {turn.error ? <ErrorBox>{turn.error}</ErrorBox> : null}
                  {!turn.response && !turn.error ? <Loading label="Модель формирует ответ…" /> : null}
                </div>
              </div>
            ))}

            {!busy ? (
              <div className="ai-examples">
                {examples.map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="ai-example"
                    disabled={busy}
                    onClick={() => void ask(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
            ) : null}

            <div ref={endRef} />
          </div>

          <form
            className="ai-widget-composer"
            onSubmit={(event) => {
              event.preventDefault()
              void ask(question)
            }}
          >
            <input
              ref={inputRef}
              className="input"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={
                activeCustomerId
                  ? `Спросите про клиента #${activeCustomerId}…`
                  : 'Напишите вопрос AI-аналитику…'
              }
              maxLength={2000}
              disabled={busy}
              aria-label="Вопрос AI-аналитику"
            />
            <button
              type="submit"
              className="ai-send-btn"
              disabled={busy || !question.trim()}
              aria-label="Отправить вопрос"
              title="Отправить"
            >
              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path
                  d="M4 10h11.5m0 0L10.5 5m5 5l-5 5"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </form>
        </section>
      ) : null}

      <button
        type="button"
        className={`ai-fab${open ? ' is-open' : ''}`}
        onClick={() => setOpen((prev) => !prev)}
        aria-label={open ? 'Закрыть чат AI-аналитика' : 'Открыть чат AI-аналитика'}
        aria-expanded={open}
        title="AI-аналитик"
      >
        <span
          className={`ai-fab-status ${status ? `is-${status.status}` : ''}`}
          aria-hidden="true"
        />
        {open ? (
          <svg className="ai-fab-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M6.5 9.5L12 15l5.5-5.5"
              stroke="currentColor"
              strokeWidth="2.3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : (
          <svg className="ai-fab-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M20 11.5a7.5 7.5 0 01-7.5 7.5c-1.3 0-2.5-.33-3.57-.91L4 19.5l1.45-4.63A7.46 7.46 0 014.5 11.5 7.5 7.5 0 0112 4a7.5 7.5 0 018 7.5z"
              stroke="currentColor"
              strokeWidth="1.95"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M12 8l.95 2.15L15.1 11.1l-2.15.95L12 14.2l-.95-2.15L8.9 11.1l2.15-.95L12 8z"
              fill="currentColor"
            />
          </svg>
        )}
      </button>
    </div>
  )
}
