import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../lib/api'
import { useLiveGeneration } from '../lib/live'
import type { CustomerPage, CustomerSummary } from '../types'
import {
  EmptyState,
  ErrorBox,
  Loading,
  RiskBadge,
  ScoreCell,
  formatEur,
} from '../components/ui'

type SortDir = 'asc' | 'desc'

const COLUMNS: Array<{
  key: string
  label: string
  numeric?: boolean
  width?: string
}> = [
  { key: 'id', label: 'ID', numeric: true },
  { key: 'email', label: 'Email' },
  { key: 'riskScore', label: 'Риск' },
  { key: 'balance', label: 'Баланс', numeric: true },
  { key: 'totalReplenished', label: 'Всего пополнено', numeric: true },
]

const PAGE_SIZE = 25

export default function CustomersPage() {
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState<CustomerPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const sortBy = params.get('sortBy') ?? 'riskScore'
  const sortDir = (params.get('sortDir') as SortDir) ?? 'desc'
  const riskCategory = params.get('riskCategory') ?? ''
  const serviceStatus = params.get('serviceStatus') ?? ''
  const page = Number(params.get('page') ?? '1')
  const searchParam = params.get('search') ?? ''
  const [search, setSearch] = useState(searchParam)

  // Keep the local search box in sync when the URL changes (e.g. back button).
  useEffect(() => {
    setSearch(searchParam)
  }, [searchParam])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await api.customers({
        search: searchParam || undefined,
        riskCategory: riskCategory || undefined,
        serviceStatus: serviceStatus || undefined,
        sortBy,
        sortDir,
        page,
        pageSize: PAGE_SIZE,
      })
      setData(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить клиентов')
    } finally {
      setLoading(false)
    }
  }, [searchParam, riskCategory, serviceStatus, sortBy, sortDir, page])

  useEffect(() => {
    void load()
  }, [load])

  // Keep the visible page in step with a newly published generation.
  useLiveGeneration(load)

  function update(next: Record<string, string | null>) {
    const merged = new URLSearchParams(params)
    Object.entries(next).forEach(([key, value]) => {
      if (value === null || value === '') merged.delete(key)
      else merged.set(key, value)
    })
    setParams(merged, { replace: true })
  }

  function toggleSort(key: string) {
    if (sortBy === key) {
      update({ sortDir: sortDir === 'asc' ? 'desc' : 'asc', page: '1' })
    } else {
      update({ sortBy: key, sortDir: key === 'email' ? 'asc' : 'desc', page: '1' })
    }
  }

  function submitSearch(e: React.FormEvent) {
    e.preventDefault()
    update({ search: search.trim() || null, page: '1' })
  }

  const activeFilters = useMemo(
    () => [riskCategory && 'риск', serviceStatus && 'статус', searchParam && 'поиск'].filter(Boolean),
    [riskCategory, serviceStatus, searchParam],
  )

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Клиенты</h1>
          <p>
            Поиск, фильтрация и сортировка по реальным полям источника. Числовые поля сортируются
            численно, email — по строке без учёта регистра.
          </p>
        </div>
        <div className="hint">
          {data ? `${data.total} записей` : ''}
          {activeFilters.length ? ` · активны: ${activeFilters.join(', ')}` : ''}
        </div>
      </div>

      <section className="card">
        <form className="toolbar" onSubmit={submitSearch}>
          <input
            className="input search"
            type="search"
            placeholder="Поиск по email или ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Поиск клиентов"
          />
          <button className="btn" type="submit">
            Найти
          </button>

          <select
            className="select"
            value={riskCategory}
            onChange={(e) => update({ riskCategory: e.target.value || null, page: '1' })}
            aria-label="Фильтр по категории риска"
          >
            <option value="">Все уровни риска</option>
            <option value="high">Высокий</option>
            <option value="medium">Средний</option>
            <option value="low">Низкий</option>
            <option value="insufficient_data">Недостаточно данных</option>
            <option value="not_applicable">Не применимо</option>
          </select>

          <select
            className="select"
            value={serviceStatus}
            onChange={(e) => update({ serviceStatus: e.target.value || null, page: '1' })}
            aria-label="Фильтр по статусу услуги"
          >
            <option value="">Любой статус услуги</option>
            <option value="active">Активна</option>
            <option value="prolong_wait">Ожидает продления</option>
            <option value="suspended">Приостановлена</option>
            <option value="blocked">Заблокирована</option>
            <option value="deleted">Удалена</option>
          </select>

          {activeFilters.length ? (
            <button
              type="button"
              className="btn sm"
              onClick={() => {
                setSearch('')
                setParams(new URLSearchParams(), { replace: true })
              }}
            >
              Сбросить
            </button>
          ) : null}
        </form>

        {error ? <ErrorBox>{error}</ErrorBox> : null}
        {loading ? (
          <Loading label="Загрузка клиентов…" />
        ) : !data || data.items.length === 0 ? (
          <EmptyState>
            Ничего не найдено. Измените условия поиска или сбросьте фильтры.
          </EmptyState>
        ) : (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    {COLUMNS.map((col) => (
                      <th
                        key={col.key}
                        className={`sortable${col.numeric ? ' num' : ''}`}
                        onClick={() => toggleSort(col.key)}
                        aria-sort={
                          sortBy === col.key
                            ? sortDir === 'asc'
                              ? 'ascending'
                              : 'descending'
                            : 'none'
                        }
                        title={`Сортировать по «${col.label}»`}
                      >
                        {col.label}
                        {sortBy === col.key ? (
                          <span className="sort-ind">{sortDir === 'asc' ? '▲' : '▼'}</span>
                        ) : null}
                      </th>
                    ))}
                    <th className="num">Услуги</th>
                    <th>Уровень</th>
                    <th className="num">Выручка под риском</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((customer: CustomerSummary) => (
                    <tr key={customer.id}>
                      <td className="num">
                        <Link to={`/customers/${customer.id}`} className="cell-primary">
                          {customer.id}
                        </Link>
                      </td>
                      <td>
                        <span className="cell-primary">{customer.email}</span>
                      </td>
                      <td>
                        <ScoreCell
                          score={customer.riskScore}
                          category={customer.riskCategory}
                        />
                      </td>
                      <td className="num">{formatEur(customer.balance.eur)}</td>
                      <td className="num">{formatEur(customer.totalReplenished.eur)}</td>
                      <td className="num">
                        {customer.serviceCount}
                        <span className="cell-sub">
                          {' '}
                          / {customer.eligibleServiceCount} в прогнозе
                        </span>
                      </td>
                      <td>
                        <RiskBadge
                          category={customer.riskCategory}
                          label={customer.riskCategoryLabel}
                        />
                      </td>
                      <td className="num">{formatEur(customer.revenueAtRisk.eur)}</td>
                      <td>
                        <Link className="btn sm" to={`/customers/${customer.id}`}>
                          Карточка
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="pager">
              <span>
                Страница {data.page} из {data.pages} · всего {data.total} клиентов
              </span>
              <div className="pager-actions">
                <button
                  className="btn sm"
                  disabled={data.page <= 1}
                  onClick={() => update({ page: String(data.page - 1) })}
                >
                  ← Назад
                </button>
                <button
                  className="btn sm"
                  disabled={data.page >= data.pages}
                  onClick={() => update({ page: String(data.page + 1) })}
                >
                  Вперёд →
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
