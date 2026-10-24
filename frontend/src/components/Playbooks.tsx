import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { PlaybookItem, PlaybookList, RecommendationState } from '../types'
import { ErrorBox, Loading, formatDateTime } from './ui'

/**
 * Retention Playbooks.
 *
 * The status is a workflow fact stored by the backend, not a UI preference and
 * not an analytical signal. Changing it never alters a score, an exposure or
 * the model settings, so the component only ever talks to the two playbook
 * endpoints and never touches the rest of the customer payload.
 *
 * The UI shows the outcome only after the server confirms it: the optimistic
 * value is replaced by the response, and a failure restores the previous state
 * with a retry affordance rather than pretending the save succeeded.
 */

const STATE_LABELS: Record<RecommendationState, string> = {
  new: 'Новая',
  in_progress: 'В работе',
  done: 'Выполнена',
}

/** Allowed transitions. ``done`` can be reopened because a retention action
 *  may turn out to be premature. */
const NEXT_ACTIONS: Record<RecommendationState, { to: RecommendationState; label: string }[]> = {
  new: [
    { to: 'in_progress', label: 'Взять в работу' },
    { to: 'done', label: 'Отметить выполненной' },
  ],
  in_progress: [
    { to: 'done', label: 'Отметить выполненной' },
    { to: 'new', label: 'Вернуть в новые' },
  ],
  done: [{ to: 'in_progress', label: 'Вернуть в работу' }],
}

function PlaybookRow({
  customerId,
  item,
  onChanged,
}: {
  customerId: number
  item: PlaybookItem
  onChanged: (updated: PlaybookItem) => void
}) {
  const [saving, setSaving] = useState<RecommendationState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [lastAttempt, setLastAttempt] = useState<RecommendationState | null>(null)

  async function move(to: RecommendationState) {
    setSaving(to)
    setError(null)
    setSaved(false)
    setLastAttempt(to)
    try {
      const response = await api.setPlaybookStatus(customerId, item.code, to)
      onChanged({
        ...item,
        status: response.status,
        statusUpdatedAt: response.updatedAt,
        statusUpdatedBy: response.updatedBy,
      })
      setSaved(true)
    } catch (err) {
      // Keep the previous status: nothing is shown as saved until confirmed.
      setError(err instanceof ApiError ? err.detail : 'Не удалось сохранить статус')
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className={`rec prio-${item.priority} playbook state-${item.status}`}>
      <div className="rec-title">
        {item.title}
        <span className={`badge state-${item.status}`}>{STATE_LABELS[item.status]}</span>
      </div>
      <div className="rec-detail">{item.detail}</div>

      <div className="playbook-foot">
        {item.statusUpdatedAt ? (
          <span className="hint">
            Обновлено {formatDateTime(item.statusUpdatedAt)}
            {item.statusUpdatedBy ? ` · ${item.statusUpdatedBy}` : ''}
          </span>
        ) : (
          <span className="hint">Статус не изменялся</span>
        )}
        <span className="spacer" />
        {NEXT_ACTIONS[item.status].map((action) => (
          <button
            key={action.to}
            type="button"
            className="btn sm"
            disabled={saving !== null}
            onClick={() => move(action.to)}
          >
            {saving === action.to ? 'Сохранение…' : action.label}
          </button>
        ))}
      </div>

      {error ? (
        <div className="playbook-error" role="alert">
          {error}{' '}
          <button
            type="button"
            className="btn sm"
            onClick={() => lastAttempt && move(lastAttempt)}
          >
            Повторить
          </button>
        </div>
      ) : null}
      {saved ? <div className="hint playbook-saved">Статус сохранён.</div> : null}
    </div>
  )
}

export default function Playbooks({ customerId }: { customerId: number }) {
  const [data, setData] = useState<PlaybookList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await api.playbooks(customerId))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить рекомендации')
    } finally {
      setLoading(false)
    }
  }, [customerId])

  useEffect(() => {
    load()
  }, [load])

  function replace(updated: PlaybookItem) {
    setData((current) =>
      current
        ? { ...current, items: current.items.map((i) => (i.code === updated.code ? updated : i)) }
        : current,
    )
  }

  if (loading) return <Loading label="Загрузка рекомендаций…" />
  if (error) return <ErrorBox>{error}</ErrorBox>
  if (!data) return null

  if (!data.items.length) {
    return <p className="hint">Действия не требуются: значимых сигналов риска нет.</p>
  }

  return (
    <>
      <div className="rec-list">
        {data.items.map((item) => (
          <PlaybookRow key={item.code} customerId={customerId} item={item} onChanged={replace} />
        ))}
      </div>
      <div className="notice" style={{ marginTop: 12 }}>
        {data.note}
      </div>
    </>
  )
}
