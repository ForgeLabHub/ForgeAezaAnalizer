import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type {
  TelegramLinkCode,
  TelegramNotificationKind,
  TelegramStatus,
  TelegramSubscription,
} from '../types'
import { ErrorBox, Loading, formatDateTime } from '../components/ui'

/**
 * Telegram integration management.
 *
 * This screen is the *only* place a chat can be linked: the link code is issued
 * here for an authenticated session and redeemed by the bot, so a Telegram
 * username never becomes an identity. Nothing on this page sends customer data —
 * it configures the channel and can send one test message built from the current
 * calculation.
 */

const KIND_LABELS: Record<TelegramNotificationKind, string> = {
  high_risk: 'Клиент перешёл в высокий риск',
  exposure_jump: 'Резкий рост выручки под риском',
  new_action: 'Новая рекомендация по удержанию',
  data_quality: 'Проблема качества данных',
  daily_digest: 'Ежедневная сводка',
}

export default function TelegramPage() {
  const [status, setStatus] = useState<TelegramStatus | null>(null)
  const [subscription, setSubscription] = useState<TelegramSubscription | null>(null)
  const [linkCode, setLinkCode] = useState<TelegramLinkCode | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const current = await api.telegramStatus()
      setStatus(current)
      if (current.enabled && current.linked) {
        setSubscription(await api.telegramSubscription())
      } else {
        setSubscription(null)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить состояние интеграции')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label)
    setError(null)
    setNotice(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Действие не выполнено')
    } finally {
      setBusy(null)
    }
  }

  const createCode = () =>
    run('code', async () => {
      const issued = await api.telegramLinkCode()
      setLinkCode(issued)
      setNotice('Код создан. Отправьте его боту командой /start <КОД>.')
    })

  const disconnect = () =>
    run('disconnect', async () => {
      const result = await api.telegramDisconnect()
      setLinkCode(null)
      setNotice(`Отключено чатов: ${result.disconnected}. Уведомления больше не отправляются.`)
      await load()
    })

  const toggleKind = (kind: TelegramNotificationKind) =>
    run('kinds', async () => {
      if (!subscription) return
      const next = subscription.kinds.includes(kind)
        ? subscription.kinds.filter((k) => k !== kind)
        : [...subscription.kinds, kind]
      setSubscription(await api.telegramPatchSubscription({ kinds: next }))
      setNotice('Настройки сохранены.')
    })

  const toggleDigest = () =>
    run('digest', async () => {
      if (!subscription) return
      setSubscription(
        await api.telegramPatchSubscription({ dailyDigest: !subscription.dailyDigest }),
      )
      setNotice('Настройки сохранены.')
    })

  const setThreshold = (key: 'riskScore' | 'exposureEur', value: number) =>
    run('thresholds', async () => {
      setSubscription(await api.telegramPatchSubscription({ thresholds: { [key]: value } }))
      setNotice('Порог сохранён.')
    })

  const sendTest = () =>
    run('test', async () => {
      const result = await api.telegramSendTest()
      setNotice(result.detail)
    })

  if (loading) return <Loading label="Загрузка интеграции Telegram…" />
  if (!status) return <ErrorBox>{error ?? 'Состояние недоступно'}</ErrorBox>

  if (!status.enabled) {
    return (
      <div className="stack">
        <div className="page-head">
          <div>
            <h1>Telegram</h1>
            <p>Уведомления о риске оттока в Telegram.</p>
          </div>
        </div>
        <div className="notice">
          <strong>Интеграция отключена.</strong> {status.detail}
          <div className="hint" style={{ marginTop: 8 }}>
            Включите её переменными <code>TELEGRAM_ENABLED=1</code>,{' '}
            <code>TELEGRAM_BOT_TOKEN</code> и <code>TELEGRAM_WEBHOOK_SECRET</code> на сервере.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Telegram</h1>
          <p>
            Подключение чата и настройка уведомлений. Уведомления строятся на текущем
            расчёте — отдельного источника данных у бота нет.
          </p>
        </div>
        <div className="hint">
          {status.linked ? `Подключено: ${status.chatId}` : 'Чат не подключён'}
        </div>
      </div>

      {error ? <ErrorBox>{error}</ErrorBox> : null}
      {notice ? <div className="notice info">{notice}</div> : null}

      <section className="card">
        <div className="card-head">
          <h2>Подключение</h2>
          <span className="hint">Код действует ограниченное время и используется один раз</span>
        </div>
        <div className="card-body">
          {status.linked ? (
            <>
              <p>
                Чат <code>{status.chatId}</code>
                {status.username ? ` (@${status.username})` : ''} подключён
                {status.linkedAt ? ` ${formatDateTime(status.linkedAt)}` : ''}.
              </p>
              <div className="row" style={{ marginTop: 10 }}>
                <button type="button" className="btn" disabled={busy !== null} onClick={sendTest}>
                  {busy === 'test' ? 'Отправка…' : 'Отправить тестовое уведомление'}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={busy !== null}
                  onClick={disconnect}
                >
                  {busy === 'disconnect' ? 'Отключение…' : 'Отключить Telegram'}
                </button>
              </div>
            </>
          ) : (
            <>
              <ol className="hint" style={{ paddingLeft: 18, lineHeight: 1.8 }}>
                <li>Создайте код подключения кнопкой ниже.</li>
                <li>
                  Откройте бота в Telegram и отправьте <code>/start &lt;КОД&gt;</code>.
                </li>
                <li>После подтверждения настройте типы уведомлений на этой странице.</li>
              </ol>
              <div className="row" style={{ marginTop: 10 }}>
                <button type="button" className="btn primary" disabled={busy !== null} onClick={createCode}>
                  {busy === 'code' ? 'Создание…' : 'Создать код подключения'}
                </button>
              </div>
            </>
          )}

          {linkCode ? (
            <div className="notice" style={{ marginTop: 12 }}>
              <div className="hint">Код подключения (показан один раз):</div>
              <div className="mono" style={{ fontSize: 20, margin: '6px 0', letterSpacing: 2 }}>
                {linkCode.code}
              </div>
              <div className="hint">
                Действует до {formatDateTime(linkCode.expiresAt)}. {linkCode.botHint}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      {subscription ? (
        <section className="card">
          <div className="card-head">
            <h2>Уведомления</h2>
            <span className="hint">Что и когда присылать</span>
          </div>
          <div className="card-body">
            <div className="stack" style={{ gap: 8 }}>
              {(Object.keys(KIND_LABELS) as TelegramNotificationKind[]).map((kind) => (
                <label key={kind} className="row" style={{ gap: 10, alignItems: 'center' }}>
                  <input
                    type="checkbox"
                    checked={subscription.kinds.includes(kind)}
                    disabled={busy !== null}
                    onChange={() => toggleKind(kind)}
                  />
                  <span>{KIND_LABELS[kind]}</span>
                </label>
              ))}
              <label className="row" style={{ gap: 10, alignItems: 'center', marginTop: 6 }}>
                <input
                  type="checkbox"
                  checked={subscription.dailyDigest}
                  disabled={busy !== null}
                  onChange={toggleDigest}
                />
                <span>Ежедневная сводка одним сообщением</span>
              </label>
            </div>

            <div className="row" style={{ marginTop: 14, gap: 20, flexWrap: 'wrap' }}>
              <div className="field" style={{ maxWidth: 220 }}>
                <label htmlFor="tg-risk">Порог балла риска</label>
                <input
                  id="tg-risk"
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  defaultValue={subscription.thresholds.riskScore}
                  disabled={busy !== null}
                  onBlur={(event) => {
                    const value = Number(event.target.value)
                    if (Number.isFinite(value) && value !== subscription.thresholds.riskScore) {
                      void setThreshold('riskScore', value)
                    }
                  }}
                />
              </div>
              <div className="field" style={{ maxWidth: 220 }}>
                <label htmlFor="tg-exposure">Порог роста выручки, €</label>
                <input
                  id="tg-exposure"
                  className="input"
                  type="number"
                  min={0}
                  step={1}
                  defaultValue={subscription.thresholds.exposureEur}
                  disabled={busy !== null}
                  onBlur={(event) => {
                    const value = Number(event.target.value)
                    if (Number.isFinite(value) && value !== subscription.thresholds.exposureEur) {
                      void setThreshold('exposureEur', value)
                    }
                  }}
                />
              </div>
            </div>

            <div className="notice" style={{ marginTop: 14 }}>
              Балл риска — взвешенная эвристика, а не вероятность оттока. Уведомления не
              изменяют расчёт, настройки модели и данные клиентов.
            </div>
          </div>
        </section>
      ) : null}
    </div>
  )
}
