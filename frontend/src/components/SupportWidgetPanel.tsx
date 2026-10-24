import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type {
  SupportConversation,
  SupportConversationMessages,
  SupportConversationStatus,
  SupportMessage,
} from '../types'

type Filter = 'open' | 'closed' | 'all'
type View = 'list' | 'thread' | 'new'

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(date)
}

function errorText(error: unknown) {
  return error instanceof ApiError ? error.detail : 'Не удалось связаться с сервером.'
}

function DeliveryLabel({ message }: { message: SupportMessage }) {
  if (message.sender !== 'analyst') return null
  const label = {
    received: 'Получено',
    pending: 'Отправляется',
    delivered: 'Доставлено',
    failed: 'Не доставлено',
    stubbed: 'Telegram не настроен',
  }[message.deliveryStatus]
  return (
    <span
      className={`support-delivery is-${message.deliveryStatus}`}
      title={message.deliveryError ?? undefined}
    >
      {label}
    </span>
  )
}

export function SupportWidgetPanel({ suggestedAccountId }: { suggestedAccountId?: number }) {
  const [filter, setFilter] = useState<Filter>('open')
  const [view, setView] = useState<View>('list')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [conversations, setConversations] = useState<SupportConversation[]>([])
  const [thread, setThread] = useState<SupportConversationMessages | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingThread, setLoadingThread] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reply, setReply] = useState('')
  const [accountId, setAccountId] = useState(suggestedAccountId ? String(suggestedAccountId) : '')
  const [initialMessage, setInitialMessage] = useState('')
  const endRef = useRef<HTMLDivElement | null>(null)
  const selected = useMemo(
    () => conversations.find((item) => item.id === selectedId) ?? null,
    [conversations, selectedId],
  )

  const loadConversations = useCallback(async (quiet = false) => {
    if (!quiet) setLoadingList(true)
    try {
      const result = await api.supportConversations(filter === 'all' ? undefined : filter)
      setConversations(result.items)
      setError('')
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      if (!quiet) setLoadingList(false)
    }
  }, [filter])

  const loadThread = useCallback(async (id: number, quiet = false) => {
    if (!quiet) setLoadingThread(true)
    try {
      const result = await api.supportMessages(id)
      setThread(result)
      setError('')
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      if (!quiet) setLoadingThread(false)
    }
  }, [])

  useEffect(() => {
    void loadConversations()
    const timer = window.setInterval(() => void loadConversations(true), 12000)
    return () => window.clearInterval(timer)
  }, [loadConversations])

  useEffect(() => {
    if (selectedId === null || view !== 'thread') return
    void loadThread(selectedId)
    const timer = window.setInterval(() => void loadThread(selectedId, true), 8000)
    return () => window.clearInterval(timer)
  }, [loadThread, selectedId, view])

  useEffect(() => {
    if (view === 'thread') endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [thread?.items.length, view])

  async function sendReply(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = reply.trim()
    if (!selectedId || !text || busy) return
    setBusy(true)
    setError('')
    try {
      const message = await api.replyToSupportConversation(selectedId, text)
      setReply('')
      setThread((current) => current
        ? { ...current, items: [...current.items, message] }
        : current)
      void loadConversations(true)
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function createConversation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const id = Number(accountId)
    const text = initialMessage.trim()
    if (!Number.isInteger(id) || id < 1 || !text || busy) return
    setBusy(true)
    setError('')
    try {
      const result = await api.startSupportConversation(id, text)
      setSelectedId(result.conversation.id)
      setView('thread')
      setInitialMessage('')
      await loadConversations(true)
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  async function toggleStatus(status: SupportConversationStatus) {
    if (!selectedId || busy) return
    setBusy(true)
    setError('')
    try {
      const updated = await api.setSupportConversationStatus(selectedId, status)
      setThread((current) => current ? { ...current, conversation: updated } : current)
      await loadConversations(true)
    } catch (reason) {
      setError(errorText(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="support-widget-body">
      {view === 'list' ? (
        <>
          <div className="support-toolbar">
            <div className="support-filter" role="group" aria-label="Фильтр диалогов">
              {(['open', 'closed', 'all'] as const).map((value) => (
                <button
                  type="button"
                  key={value}
                  className={filter === value ? 'active' : ''}
                  onClick={() => setFilter(value)}
                >
                  {{ open: 'Открытые', closed: 'Закрытые', all: 'Все' }[value]}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="btn sm"
              onClick={() => {
                setAccountId(suggestedAccountId ? String(suggestedAccountId) : '')
                setError('')
                setView('new')
              }}
            >
              Новый диалог
            </button>
          </div>

          <div className="support-list" aria-live="polite">
            {error ? <div className="support-error" role="alert">{error}</div> : null}
            {loadingList ? <div className="support-empty">Загрузка диалогов…</div> : null}
            {!loadingList && !error && conversations.length === 0 ? (
              <div className="support-empty">Диалогов пока нет</div>
            ) : null}
            {conversations.map((item) => (
              <button
                type="button"
                className="support-conversation"
                key={item.id}
                onClick={() => {
                  setSelectedId(item.id)
                  setThread(null)
                  setError('')
                  setView('thread')
                }}
              >
                <span className="support-conversation-main">
                  <strong>{item.email}</strong>
                  <span>Аккаунт #{item.accountId}</span>
                </span>
                <span className="support-conversation-meta">
                  <span className={`support-status is-${item.status}`}>
                    {item.status === 'open' ? 'Открыт' : 'Закрыт'}
                  </span>
                  <time>{formatTime(item.updatedAt)}</time>
                </span>
              </button>
            ))}
          </div>
        </>
      ) : null}

      {view === 'thread' ? (
        <>
          <div className="support-thread-toolbar">
            <button type="button" className="btn sm btn-ghost" onClick={() => setView('list')}>
              Назад
            </button>
            <div className="support-thread-contact">
              <strong>{selected?.email ?? `Аккаунт #${thread?.conversation.accountId ?? ''}`}</strong>
              <span>Диалог #{selectedId}</span>
            </div>
            <button
              type="button"
              className="btn sm btn-ghost"
              disabled={busy || !thread}
              onClick={() => void toggleStatus(thread?.conversation.status === 'open' ? 'closed' : 'open')}
            >
              {thread?.conversation.status === 'open' ? 'Закрыть' : 'Открыть'}
            </button>
          </div>
          <div className="support-messages" aria-live="polite">
            {error ? <div className="support-error" role="alert">{error}</div> : null}
            {loadingThread && !thread ? <div className="support-empty">Загрузка переписки…</div> : null}
            {thread?.items.map((message) => (
              <article
                key={message.id}
                className={`support-message ${message.sender === 'analyst' ? 'is-analyst' : 'is-client'}`}
              >
                <div className="support-message-text">{message.text}</div>
                <footer>
                  <time>{formatTime(message.createdAt)}</time>
                  <DeliveryLabel message={message} />
                </footer>
              </article>
            ))}
            {thread && thread.items.length === 0 ? (
              <div className="support-empty">Сообщений пока нет</div>
            ) : null}
            <div ref={endRef} />
          </div>
          {thread?.conversation.status === 'open' ? (
            <form className="support-composer" onSubmit={(event) => void sendReply(event)}>
              <textarea
                className="input"
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                placeholder="Ответ клиенту…"
                aria-label="Ответ клиенту"
                maxLength={4000}
                disabled={busy}
                rows={2}
              />
              <button type="submit" className="ai-send-btn" disabled={busy || !reply.trim()} aria-label="Отправить ответ">
                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <path d="M4 10h11.5m0 0L10.5 5m5 5l-5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </form>
          ) : (
            <div className="support-closed-note">Диалог закрыт. Откройте его, чтобы ответить клиенту.</div>
          )}
        </>
      ) : null}

      {view === 'new' ? (
        <form className="support-new-form" onSubmit={(event) => void createConversation(event)}>
          <div className="support-thread-toolbar">
            <button type="button" className="btn sm btn-ghost" onClick={() => setView('list')}>
              Назад
            </button>
            <strong>Новый диалог</strong>
          </div>
          {error ? <div className="support-error" role="alert">{error}</div> : null}
          <label>
            ID аккаунта
            <input
              className="input"
              type="number"
              min={1}
              step={1}
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              required
              aria-label="ID аккаунта"
            />
          </label>
          <label>
            Первое сообщение
            <textarea
              className="input"
              value={initialMessage}
              onChange={(event) => setInitialMessage(event.target.value)}
              placeholder="Сообщение клиенту…"
              maxLength={4000}
              rows={4}
              required
              disabled={busy}
            />
          </label>
          <button type="submit" className="btn primary" disabled={busy || !initialMessage.trim()}>
            {busy ? 'Отправка…' : 'Начать диалог'}
          </button>
        </form>
      ) : null}
    </div>
  )
}
