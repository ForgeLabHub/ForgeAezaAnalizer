import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError } from '../lib/api'
import type {
  ClientAccount,
  ClientMe,
  ClientService,
  ClientSupportMessage,
} from '../types'
import { ErrorBox, Loading, formatCents, STATUS_LABELS } from '../components/ui'

const TOKEN_KEY = 'aeza.telegram.clientToken'

interface TelegramWebApp {
  initData?: string
  colorScheme?: 'light' | 'dark'
  isExpanded?: boolean
  viewportHeight?: number
  ready?: () => void
  expand?: () => void
  close?: () => void
  onEvent?: (event: string, handler: () => void) => void
  offEvent?: (event: string, handler: () => void) => void
}

function webApp(): TelegramWebApp | null {
  const tg = (window as unknown as { Telegram?: { WebApp?: TelegramWebApp } }).Telegram
  return tg?.WebApp ?? null
}

function readInitData(): string | null {
  const data = webApp()?.initData
  return data && data.length > 0 ? data : null
}

function useTelegramChrome() {
  useEffect(() => {
    const app = webApp()
    if (!app) return
    app.ready?.()
    app.expand?.()
    document.documentElement.dataset.theme = app.colorScheme === 'dark' ? 'dark' : 'light'
    const applyHeight = () => {
      if (typeof app.viewportHeight === 'number' && app.viewportHeight > 0) {
        document.documentElement.style.setProperty('--tg-viewport-height', `${app.viewportHeight}px`)
      }
    }
    const applyTheme = () => {
      document.documentElement.dataset.theme = app.colorScheme === 'dark' ? 'dark' : 'light'
    }
    applyHeight()
    app.onEvent?.('themeChanged', applyTheme)
    app.onEvent?.('viewportChanged', applyHeight)
    return () => {
      app.offEvent?.('themeChanged', applyTheme)
      app.offEvent?.('viewportChanged', applyHeight)
    }
  }, [])
}

function money(value: { cents: number | null; eur: string | null } | undefined): string {
  if (!value || value.cents === null) return 'нет данных'
  return formatCents(value.cents)
}

function formatMoscow(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Europe/Moscow',
  }).format(date)
}

export default function MiniAppPage() {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(TOKEN_KEY))
  const [me, setMe] = useState<ClientMe | null>(null)
  const [account, setAccount] = useState<ClientAccount | null>(null)
  const [services, setServices] = useState<ClientService[]>([])
  const [thread, setThread] = useState<ClientSupportMessage[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const autoAuthAttempted = useRef(false)

  useTelegramChrome()

  const load = useCallback(async (active: string) => {
    setLoading(true)
    setError(null)
    try {
      const [who, acct, svc, support] = await Promise.all([
        api.clientMe(active),
        api.clientAccount(active),
        api.clientServices(active),
        api.clientSupport(active),
      ])
      setMe(who)
      setAccount(acct)
      setServices(svc.items)
      setThread(support.items)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        sessionStorage.removeItem(TOKEN_KEY)
        setToken(null)
      }
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить данные')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (token) void load(token)
  }, [token, load])

  async function authenticate() {
    const initData = readInitData()
    if (!initData) {
      setError('Откройте этот экран из Telegram: подписанные данные Mini App недоступны.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const session = await api.clientSession(initData)
      sessionStorage.setItem(TOKEN_KEY, session.accessToken)
      setToken(session.accessToken)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось выполнить вход')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!token && !autoAuthAttempted.current && readInitData()) {
      autoAuthAttempted.current = true
      void authenticate()
    }
  }, [token])

  useEffect(() => {
    if (!token) return
    let active = true
    const refreshSupport = async () => {
      try {
        const support = await api.clientSupport(token)
        if (active) setThread(support.items)
      } catch (err) {
        if (active && err instanceof ApiError && err.status === 401) {
          sessionStorage.removeItem(TOKEN_KEY)
          setToken(null)
          setError(err.detail)
        }
      }
    }
    const interval = window.setInterval(() => void refreshSupport(), 10000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [token])

  async function toggleConsent(enabled: boolean) {
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.clientConsent(token, enabled)
      setMe(current => (current ? { ...current, notificationsEnabled: result.notificationsEnabled } : current))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось изменить настройку')
    } finally {
      setBusy(false)
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!token || !message.trim()) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.clientSendSupport(token, message.trim())
      setThread(current => [...current, result.message])
      setMessage('')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось отправить сообщение')
    } finally {
      setBusy(false)
    }
  }

  function logout() {
    sessionStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setMe(null)
    setAccount(null)
    setServices([])
    setThread([])
    if (webApp()) webApp()?.close?.()
  }

  if (!token) {
    return (
      <div className="login-wrap">
        <div className="login-card">
          <h1>Aéza — личный кабинет</h1>
          <p className="sub">Вход выполняется из Telegram, без пароля.</p>
          {error ? <ErrorBox>{error}</ErrorBox> : null}
          <button className="btn primary" style={{ width: '100%', marginTop: 12 }} onClick={authenticate} disabled={busy}>
            {busy ? 'Проверка…' : 'Войти через Telegram'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="stack mini-app">
      <div className="page-head">
        <div>
          <h1>Личный кабинет</h1>
          {me ? <p className="sub">{me.email}</p> : null}
        </div>
        <button className="btn" onClick={logout}>Выйти</button>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}
      {loading ? <Loading label="Загрузка данных…" /> : null}

      <div className="row">
        <div className="metric">
          <div className="metric-label">Баланс</div>
          <div className="metric-value">{money(account?.balance)}</div>
        </div>
      </div>

      {me ? (
        <div className="notice row" style={{ justifyContent: 'space-between' }}>
          <span>Напоминания о продлении за 7 и 3 дня</span>
          <button className="btn sm" onClick={() => void toggleConsent(!me.notificationsEnabled)} disabled={busy}>
            {me.notificationsEnabled ? 'Выключить' : 'Включить'}
          </button>
        </div>
      ) : null}

      <section>
        <h2>Услуги</h2>
        {services.length === 0 ? (
          <div className="empty">Услуг не найдено.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Услуга</th>
                  <th>Статус</th>
                  <th>Цена</th>
                  <th>Окончание / ожидаемое продление</th>
                  <th>Автопродление</th>
                </tr>
              </thead>
              <tbody>
                {services.map(service => (
                  <tr key={service.id}>
                    <td>{service.name}</td>
                    <td>{STATUS_LABELS[service.status] ?? service.status}</td>
                    <td>{money(service.price)}</td>
                    <td>{formatMoscow(service.expiresAt)}</td>
                    <td>{service.autoProlong ? 'включено' : 'выключено'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2>Поддержка</h2>
        <div className="stack">
          {thread.length === 0 ? (
            <div className="empty">Сообщений пока нет.</div>
          ) : (
            thread.map(item => (
              <div key={item.id} className={`support-bubble is-${item.sender}`}>
                <div className="support-bubble-text">{item.text}</div>
                <div className="support-bubble-meta">{formatMoscow(item.createdAt)}</div>
              </div>
            ))
          )}
          <form className="row" onSubmit={send}>
            <input
              className="input"
              value={message}
              onChange={event => setMessage(event.target.value)}
              placeholder="Написать в поддержку"
              maxLength={4000}
            />
            <button className="btn primary" disabled={busy || !message.trim()}>Отправить</button>
          </form>
        </div>
      </section>
    </div>
  )
}
