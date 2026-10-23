import { useState, useRef, useEffect } from 'react'
import { NavLink } from 'react-router-dom'

interface EcosystemProduct {
  title: string
  desc: string
  url: string
  badge?: string
  external?: boolean
  icon: JSX.Element
}

const PRODUCTS: EcosystemProduct[] = [
  {
    title: 'Aéza Sentinel',
    desc: 'Анализ оттока клиентов и выручки под риском',
    url: '/',
    badge: 'Активен',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <path d="m9 12 2 2 4-4" />
      </svg>
    ),
  },
  {
    title: 'Виртуальные серверы',
    desc: 'Быстрые NVMe VPS на базе мощных AMD Ryzen',
    url: 'https://aeza.net/virtual-servers',
    external: true,
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="20" height="8" x="2" y="2" rx="2" />
        <rect width="20" height="8" x="2" y="14" rx="2" />
        <line x1="6" x2="6.01" y1="6" y2="6" />
        <line x1="6" x2="6.01" y1="18" y2="18" />
      </svg>
    ),
  },
  {
    title: 'Выделенные серверы',
    desc: 'Физические серверы с каналом до 25 Гбит/с',
    url: 'https://aeza.net/dedicated-servers',
    external: true,
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <line x1="8" y1="21" x2="16" y2="21" />
        <line x1="12" y1="17" x2="12" y2="21" />
      </svg>
    ),
  },
  {
    title: 'Защита от DDoS',
    desc: 'L3-L7 фильтрация трафика в реальном времени',
    url: 'https://aeza.net/ddos-protection',
    external: true,
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
  },
  {
    title: 'Личный кабинет',
    desc: 'Управление услугами, биллингом и DNS',
    url: 'https://my.aeza.net',
    external: true,
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    ),
  },
]

export function AezaLogoDropdown() {
  const [open, setOpen] = useState(false)
  const timerRef = useRef<number | null>(null)

  function handleMouseEnter() {
    if (timerRef.current) clearTimeout(timerRef.current)
    setOpen(true)
  }

  function handleMouseLeave() {
    timerRef.current = window.setTimeout(() => {
      setOpen(false)
    }, 220)
  }

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return (
    <div
      className={`brand-dropdown-wrapper ${open ? 'is-open' : ''}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div className="brand" role="button" tabIndex={0} aria-haspopup="true" aria-expanded={open}>
        <div className="brand-logo-frame">
          <svg className="aeza-official-glyph" viewBox="0 0 37 36" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path
              d="M.51 10.443v14.184c0 2.107 0 3.16.178 4.036a8.894 8.894 0 0 0 6.948 6.948c.876.178 1.93.178 4.036.178h13.022c3.155 0 4.732 0 6.002-.439a8.005 8.005 0 0 0 4.953-4.953c.439-1.27.439-2.847.439-6.002V10.443c0-1.242 0-1.863-.062-2.385A8.894 8.894 0 0 0 28.24.274C27.72.212 27.098.212 25.857.212H10.675c-3.048 0-4.572 0-5.783.473a6.893 6.893 0 0 0-3.909 3.91C.511 5.804.511 7.35.511 10.442Z"
              fill="currentColor"
              className="aeza-glyph-bg"
            />
            <rect x="1.4" y="1.101" width="31.13" height="31.13" rx="6.671" fill="var(--surface)" />
            <path
              d="M14.823 28.082c2.33 0 3.839-1.017 4.609-2.484h.123v2.186h4.147V17.15c0-3.757-3.182-5.338-6.693-5.338-3.777 0-6.262 1.806-6.867 4.68l4.044.329c.298-1.047 1.232-1.817 2.802-1.817 1.489 0 2.34.75 2.34 2.043v.061c0 1.017-1.077 1.15-3.818 1.417-3.12.287-5.923 1.334-5.923 4.855 0 3.12 2.228 4.702 5.236 4.702Zm1.252-3.018c-1.345 0-2.31-.626-2.31-1.827 0-1.232 1.016-1.838 2.556-2.053.955-.134 2.515-.36 3.039-.709v1.674c0 1.652-1.366 2.915-3.285 2.915Z"
              fill="var(--n-900)"
            />
          </svg>
        </div>
        <span className="brand-name">Aéza</span>
        <span className="brand-sub">Sentinel</span>
        <svg
          className={`brand-chevron ${open ? 'rotated' : ''}`}
          viewBox="0 0 20 20"
          fill="currentColor"
          width="16"
          height="16"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </div>

      <div className={`brand-dropdown-menu ${open ? 'show' : ''}`}>
        <div className="brand-dropdown-header">
          <span className="header-label">Экосистема Aéza</span>
          <a href="https://aeza.net" target="_blank" rel="noreferrer" className="header-link">
            aeza.ru ↗
          </a>
        </div>
        <div className="brand-dropdown-grid">
          {PRODUCTS.map((prod) =>
            prod.external ? (
              <a
                key={prod.title}
                href={prod.url}
                target="_blank"
                rel="noreferrer"
                className="brand-dropdown-item"
              >
                <div className="item-icon">{prod.icon}</div>
                <div className="item-content">
                  <div className="item-title">
                    {prod.title}
                    <span className="external-mark">↗</span>
                  </div>
                  <div className="item-desc">{prod.desc}</div>
                </div>
              </a>
            ) : (
              <NavLink
                key={prod.title}
                to={prod.url}
                className="brand-dropdown-item is-current"
                onClick={() => setOpen(false)}
              >
                <div className="item-icon active">{prod.icon}</div>
                <div className="item-content">
                  <div className="item-title">
                    {prod.title}
                    {prod.badge && <span className="item-badge">{prod.badge}</span>}
                  </div>
                  <div className="item-desc">{prod.desc}</div>
                </div>
              </NavLink>
            ),
          )}
        </div>
      </div>
    </div>
  )
}
