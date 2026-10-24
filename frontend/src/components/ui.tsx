import type { ReactNode } from 'react'
import type { PriorityCategoryKey, QualitySeverity, RiskCategory, ValidationIssue } from '../types'

export const STATUS_LABELS: Record<string, string> = {
  active: 'Активна',
  suspended: 'Приостановлена',
  prolong_wait: 'Ожидает продления',
  blocked: 'Заблокирована',
  deleted: 'Удалена',
}

export const PRIORITY_SHORT_LABELS: Record<PriorityCategoryKey, string> = {
  operational_attention: 'Операционный контроль',
  high_risk_with_exposure: 'Высокий риск с экспозицией',
  high_risk_review: 'Высокий риск без экспозиции',
  data_quality_review: 'Проверка данных',
  normal_review: 'Плановый обзор',
}

export const QUALITY_SEVERITY_LABELS: Record<QualitySeverity, string> = {
  critical: 'Критично',
  warning: 'Предупреждение',
  info: 'Справка',
}

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

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const text = label ?? STATUS_LABELS[status] ?? status
  return <span className={`badge status-${status}`}>{text}</span>
}

export function PriorityBadge({
  category,
  title,
}: {
  category: PriorityCategoryKey | string
  title?: string
}) {
  const cls =
    category === 'operational_attention' || category === 'high_risk_with_exposure'
      ? 'risk-high'
      : category === 'high_risk_review' || category === 'data_quality_review'
        ? 'risk-medium'
        : 'neutral'
  const text =
    PRIORITY_SHORT_LABELS[category as PriorityCategoryKey] ?? category
  return (
    <span className={`badge ${cls}`} title={title}>
      <span className="dot" aria-hidden="true" />
      {text}
    </span>
  )
}

export function SeverityBadge({ level }: { level: QualitySeverity }) {
  const cls =
    level === 'critical' ? 'risk-high' : level === 'warning' ? 'risk-medium' : 'neutral'
  return (
    <span className={`badge ${cls}`}>
      <span className="dot" aria-hidden="true" />
      {QUALITY_SEVERITY_LABELS[level]}
    </span>
  )
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

/** Marks a record that cannot belong to a real customer. */
export function SyntheticTag({ title }: { title?: string | null }) {
  return (
    <span className="synthetic-tag" title={title ?? 'Синтетическая запись, не клиент Aéza'}>
      демо
    </span>
  )
}

/** Whole days between an ISO instant and now, or null when unparseable. */
export function daysSince(iso: string): number | null {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return Math.floor((Date.now() - d.getTime()) / 86_400_000)
}

/**
 * Timestamp strip that keeps three different times apart, because collapsing
 * them is exactly how a frozen snapshot comes to look freshly calculated:
 *
 * * `asOf` — the analysis reference date. Every "days left" and the horizon are
 *   measured from here, so a past `asOf` means the whole risk picture is frozen
 *   at that moment, not at the moment of viewing.
 * * `calculatedAt` — when the backend last recomputed the published generation.
 * * `capturedAt` — when the source snapshot itself was captured.
 */
export function FreshnessBanner({
  asOf,
  calculatedAt,
  capturedAt,
  horizonDays,
}: {
  asOf?: string | null
  calculatedAt?: string | null
  capturedAt?: string | null
  horizonDays?: number
}) {
  const age = asOf ? daysSince(asOf) : null
  const stale = age !== null && age >= 1

  return (
    <div className={`freshness${stale ? ' is-stale' : ''}`}>
      <div className="freshness-row">
        <span className="freshness-item">
          <span className="freshness-key">Дата расчёта</span>
          <span className="freshness-val">{asOf ? `${formatDateTime(asOf)} UTC` : '—'}</span>
        </span>
        <span className="freshness-item">
          <span className="freshness-key">Последний пересчёт</span>
          <span className="freshness-val">
            {calculatedAt ? `${formatDateTime(calculatedAt)} UTC` : '—'}
          </span>
        </span>
        <span className="freshness-item">
          <span className="freshness-key">Снимок получен</span>
          <span className="freshness-val">{capturedAt ? `${formatDateTime(capturedAt)} UTC` : '—'}</span>
        </span>
      </div>
      {stale ? (
        <p className="freshness-warn" role="status">
          <strong>Снимок не обновлялся {age} дн.</strong> Аналитика отсчитывается от{' '}
          {formatDateTime(asOf as string)} UTC, поэтому сроки продлений и горизонт{' '}
          {horizonDays ?? 30} дн. рассчитаны от этой даты, а не от текущего момента.
          Загрузите свежий снимок, чтобы пересчитать.
        </p>
      ) : (
        <p className="freshness-note">
          Даты продлений и горизонт отсчитываются от даты расчёта, а не от момента
          просмотра страницы.
        </p>
      )}
    </div>
  )
}

export function Loading({ label = 'Загрузка данных…' }: { label?: string }) {
  return (
    <div className="loading">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  )
}

export function ErrorBox({
  children,
  issues,
}: {
  children: ReactNode
  issues?: ValidationIssue[]
}) {
  return (
    <div className="error-box" role="alert">
      <div>{children}</div>
      {issues && issues.length > 0 ? (
        <ul className="error-issues">
          {issues.map((item, idx) => (
            <li key={idx}>
              <code>{item.loc.filter((part) => part !== 'body').join('.')}</code>: {item.msg}
            </li>
          ))}
        </ul>
      ) : null}
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

export function centsToEurString(cents: number | null | undefined): string | null {
  if (cents === null || cents === undefined || !Number.isFinite(cents)) return null
  const rounded = Math.round(cents)
  const sign = rounded < 0 ? '-' : ''
  const abs = Math.abs(rounded)
  const whole = Math.floor(abs / 100)
  const frac = String(abs % 100).padStart(2, '0')
  return `${sign}${whole}.${frac}`
}

export function formatEur(eur: string | null | undefined, withUnit = true): string {
  if (eur === null || eur === undefined || eur === '') return '—'
  const n = Number(eur)
  if (!Number.isFinite(n)) return eur
  const formatted = n.toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return withUnit ? `${formatted} €` : formatted
}

export function formatCents(cents: number | null | undefined, withUnit = true): string {
  return formatEur(centsToEurString(cents), withUnit)
}

export function formatSignedCents(cents: number | null | undefined): string {
  if (cents === null || cents === undefined || !Number.isFinite(cents)) return '—'
  if (cents === 0) return '0,00 €'
  const prefix = cents > 0 ? '+' : '−'
  return `${prefix}${formatCents(Math.abs(cents), true)}`
}

export function formatSignedNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value === 0) return (0).toFixed(digits)
  const prefix = value > 0 ? '+' : '−'
  return `${prefix}${Math.abs(value).toLocaleString('ru-RU', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

export function formatRelativePct(rel: number | null | undefined): string {
  if (rel === null || rel === undefined || !Number.isFinite(rel)) return '—'
  if (rel === 0) return '0,0%'
  const prefix = rel > 0 ? '+' : '−'
  return `${prefix}${(Math.abs(rel) * 100).toLocaleString('ru-RU', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
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

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

export function formatDays(days: number | null | undefined): string {
  if (days === null || days === undefined) return '—'
  const sign = days < 0 ? '−' : ''
  return `${sign}${Math.abs(days).toFixed(1)} дн.`
}
