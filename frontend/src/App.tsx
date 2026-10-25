import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { AnalysisProvider, GenerationControl } from './lib/realtime'
import { Loading } from './components/ui'
import { PageStage, SlidingNav, type SlidingNavItem } from './components/motion'
import { ThemeToggle } from './lib/theme'
import { AezaLogo } from './components/AezaLogo'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import PriorityPage from './pages/PriorityPage'
import CustomersPage from './pages/CustomersPage'
import CustomerDetailPage from './pages/CustomerDetailPage'
import SettingsPage from './pages/SettingsPage'
import MiniAppPage from './pages/MiniAppPage'
import { AIAnalystWidget } from './components/AIAnalystPanel'

const NAV_ITEMS: SlidingNavItem[] = [
  { to: '/', label: 'Дашборд', end: true },
  { to: '/priority', label: 'Приоритеты' },
  { to: '/customers', label: 'Клиенты' },
  { to: '/settings', label: 'Модель и сценарии' },
]

function Shell({ children }: { children: React.ReactNode }) {
  const { email, logout } = useAuth()
  const navigate = useNavigate()
  const headerRef = useRef<HTMLElement | null>(null)
  const [headerHeight, setHeaderHeight] = useState(64)

  useEffect(() => {
    const el = headerRef.current
    if (!el) return
    const sync = () => setHeaderHeight(el.offsetHeight)
    sync()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(sync) : null
    ro?.observe(el)
    window.addEventListener('resize', sync)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', sync)
    }
  }, [])

  async function onLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div
      className="app-shell"
      style={{ '--header-offset': `${headerHeight}px` } as CSSProperties}
    >
      <header className="app-header" ref={headerRef}>
        <AezaLogo />
        <SlidingNav items={NAV_ITEMS} />
        <div className="header-user">
          <GenerationControl />
          <span className="email">{email}</span>
          <ThemeToggle />
          <button type="button" className="btn sm" onClick={onLogout}>
            Выйти
          </button>
        </div>
      </header>
      <div className="app-body">
        <div className="presswall-bg" aria-hidden="true" />
        <PageStage>{children}</PageStage>
      </div>
      <AIAnalystWidget />
    </div>
  )
}

export default function App() {
  const { email, ready } = useAuth()

  if (window.location.pathname.startsWith('/mini-app')) {
    return (
      <Routes>
        <Route path="/mini-app" element={<MiniAppPage />} />
        <Route path="/mini-app/*" element={<MiniAppPage />} />
      </Routes>
    )
  }

  if (!ready) {
    return (
      <div className="login-wrap">
        <div className="presswall-bg is-full" aria-hidden="true" />
        <Loading label="Проверка сессии…" />
      </div>
    )
  }

  if (!email) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <AnalysisProvider>
      <Shell>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/priority" element={<PriorityPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Shell>
    </AnalysisProvider>
  )
}
