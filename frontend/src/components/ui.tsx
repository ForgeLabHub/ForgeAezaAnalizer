import type { ReactNode } from 'react'
import type { RiskCategory } from '../types'

export function RiskBadge({ category, label }: { category: RiskCategory; label?: string }) {
  const text =
    label ??
    {
      low: 'Низкий',
      medium: 'Средний',
      high: 'Высокий',
      insufficient_data: 'Нет данных',
      not_applicable: 'Не применимо',
    }[category]
  return (
    <span className={`badge risk-${category}`}>
      <span className="dot" aria-hidden="true" />
      {text}
    </span>
  )
}

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return <span className={`badge status-${status}`}>{label}</span>
}

export function ScoreBar({ score, category }: { score: number | null; category: RiskCategory }) {
  const cls =
    category === 'high'
      ? 'high'
      : category === 'medium'
        ? 'medium'
        : category === 'low'
          ? 'low'
          : 'na'
  const width = score === null ? 0 : Math.max(2, Math.min(100, score))
  return (
    <span className={`score-bar ${cls}`} aria-hidden="true">
      <span style={{ width: `${width}%` }} />
    </span>
  )
}

export function ScoreCell({ score, category }: { score: number | null; category: RiskCategory }) {
  return (
    <div className="row" style={{ gap: 8 }}>
      {score === null ? (
        <span className="cell-sub">—</span>
      ) : (
        <span className="score">
          <span className="val">{score.toFixed(1)}</span>
          <span className="max">/100</span>
        </span>
      )}
      <ScoreBar score={score} category={category} />
    </div>
  )
}

export function Metric({
  label,
  value,
  unit,
  foot,
  accent,
  small,
}: {
  label: string
  value: ReactNode
  unit?: string
  foot?: ReactNode
  accent?: boolean
  small?: boolean
}) {
  return (
    <div className={`metric${accent ? ' is-accent' : ''}`}>
      <div className="metric-label">{label}</div>
      <div className={`metric-value${small ? ' sm' : ''}`}>
        {value}
        {unit ? <span className="metric-unit">{unit}</span> : null}
      </div>
      {foot ? <div className="metric-foot">{foot}</div> : null}
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Loading({ label = 'Загрузка данных…' }: { label?: string }) {
  return (
    <div className="loading">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  )
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="error-box" role="alert">
      {children}
    </div>
  )
}

/** Horizontal bar chart with explicit axis labels and a zero-safe scale. */
export function BarChart({
  rows,
  unit,
  emptyText = 'Нет данных для отображения',
}: {
  rows: Array<{ label: string; value: number; color?: string; title?: string }>
  unit?: string
  emptyText?: string
}) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  const hasData = rows.some((r) => r.value > 0)
  if (!rows.length || !hasData) return <EmptyState>{emptyText}</EmptyState>
  return (
    <div className="chart">
      {rows.map((row) => (
        <div className="chart-row" key={row.label} title={row.title ?? row.label}>
          <span className="label">{row.label}</span>
          <span className="track">
            <span
              style={{
                width: `${(row.value / max) * 100}%`,
                background: row.color ?? 'var(--brand-500)',
              }}
            />
          </span>
          <span className="value">{row.value}</span>
        </div>
      ))}
      <div className="chart-axis">
        <span>0</span>
        <span>
          {max}
          {unit ? ` ${unit}` : ''}
        </span>
      </div>
    </div>
  )
}

export function formatEur(eur: string, withUnit = true): string {
  const n = Number(eur)
  const formatted = n.toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return withUnit ? `${formatted} €` : formatted
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  })
}

export function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

export function formatDays(days: number | null): string {
  if (days === null) return '—'
  const sign = days < 0 ? '−' : ''
  return `${sign}${Math.abs(days).toFixed(1)} дн.`
}
