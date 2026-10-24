import { useCallback, useEffect, useState } from 'react'

import { api } from '../lib/api'
import type { CustomerDetail, RetentionAction } from '../types'

const STATUS_LABELS: Record<string, string> = {
  open: 'Открыто',
  in_progress: 'В работе',
  done: 'Выполнено',
  dismissed: 'Отклонено',
}

const NEXT_STATUSES: Record<string, { value: 'in_progress' | 'done' | 'dismissed'; label: string }[]> = {
  open: [
    { value: 'in_progress', label: 'Взять в работу' },
    { value: 'done', label: 'Выполнено' },
    { value: 'dismissed', label: 'Отклонить' },
  ],
  in_progress: [
    { value: 'done', label: 'Выполнено' },
    { value: 'dismissed', label: 'Отклонить' },
  ],
  done: [],
  dismissed: [],
}

export function RetentionActions({ customer }: { customer: CustomerDetail }) {
  const [actions, setActions] = useState<RetentionAction[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyCode, setBusyCode] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const payload = await api.actions(customer.id)
      setActions(payload.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить действия')
    }
  }, [customer.id])

  useEffect(() => {
    void reload()
  }, [reload])

  const confirmedCodes = new Set(actions.map((a) => a.code))

  async function confirm(code: string, serviceId?: number) {
    setBusyCode(code)
    setError(null)
    try {
      await api.confirmAction(customer.id, code, serviceId)
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить действие')
    } finally {
      setBusyCode(null)
    }
  }

  async function move(actionId: number, status: 'in_progress' | 'done' | 'dismissed') {
    setError(null)
    try {
      await api.updateAction(actionId, { status })
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось изменить действие')
    }
  }

  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2>Рекомендации по удержанию</h2>
        </div>
        <div className="card-body">
          {customer.recommendations.length ? (
            <div className="rec-list">
              {customer.recommendations.map((rec) => (
                <div className={`rec prio-${rec.priority}`} key={rec.code}>
                  <div className="rec-title">{rec.title}</div>
                  <div className="rec-detail">{rec.detail}</div>
                  <div className="rec-actions">
                    {confirmedCodes.has(rec.code) ? (
                      <span className="rec-done">✓ Подтверждено аналитиком</span>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={busyCode === rec.code}
                        onClick={() => void confirm(rec.code)}
                      >
                        {busyCode === rec.code ? 'Сохраняем…' : 'Взять в работу'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="hint">Действия не требуются: значимых сигналов риска нет.</p>
          )}
          <div className="notice" style={{ marginTop: 12 }}>
            Рекомендации основаны на наблюдаемых сигналах и не гарантируют предотвращение
            оттока. Система не отправляет сообщения клиентам и не изменяет их аккаунты.
            Действие сохраняется только после подтверждения человеком.
          </div>
        </div>
      </section>

      {actions.length ? (
        <section className="card" id="retention-actions">
          <div className="card-head">
            <h2>Подтверждённые действия</h2>
            <span className="hint">{actions.length} шт.</span>
          </div>
          <div className="card-body">
            <div className="action-list">
              {actions.map((action) => (
                <div className={`action-item status-${action.status}`} key={action.id}>
                  <div className="action-main">
                    <div className="action-title">
                      <span className={`chip status-chip-${action.status}`}>
                        {STATUS_LABELS[action.status] ?? action.status}
                      </span>
                      {action.title}
                      {action.serviceId ? <span className="mono"> · услуга #{action.serviceId}</span> : null}
                    </div>
                    {action.note ? <div className="action-note">{action.note}</div> : null}
                    <div className="hint">
                      {action.createdBy} · {new Date(action.createdAt).toLocaleString('ru-RU')}
                    </div>
                  </div>
                  {NEXT_STATUSES[action.status]?.length ? (
                    <div className="action-buttons">
                      {NEXT_STATUSES[action.status].map((option) => (
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          key={option.value}
                          onClick={() => void move(action.id, option.value)}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {error ? <div className="notice warn">{error}</div> : null}
    </>
  )
}
