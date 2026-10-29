import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'aeza-theme'

export function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
  }
  return 'light'
}

let themeTransitionTimer: number | undefined

function applyTheme(theme: Theme, animate: boolean) {
  const root = document.documentElement
  if (animate) {
    root.classList.add('theme-transition')
    if (themeTransitionTimer !== undefined) {
      window.clearTimeout(themeTransitionTimer)
    }
    themeTransitionTimer = window.setTimeout(() => {
      root.classList.remove('theme-transition')
      themeTransitionTimer = undefined
    }, 380)
  }
  root.dataset.theme = theme
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () => (document.documentElement.dataset.theme as Theme | undefined) ?? getInitialTheme(),
  )

  useEffect(() => {
    applyTheme(theme, false)
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      applyTheme(next, true)
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
      }
      return next
    })
  }, [])

  return { theme, toggle }
}

export function ThemeToggle({ className = '' }: { className?: string }) {
  const { theme, toggle } = useTheme()
  const isDark = theme === 'dark'
  const label = isDark ? 'Включить светлую тему' : 'Включить тёмную тему'
  return (
    <button
      type="button"
      className={`theme-toggle ${isDark ? 'is-dark' : 'is-light'} ${className}`.trim()}
      onClick={toggle}
      aria-label={label}
      title={label}
    >
      <span className="theme-icon theme-icon-sun" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      </span>
      <span className="theme-icon theme-icon-moon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      </span>
    </button>
  )
}
