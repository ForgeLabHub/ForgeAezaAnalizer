import { Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { Loading } from './components/ui'
import { ThemeToggle } from './lib/theme'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import CustomersPage from './pages/CustomersPage'
import CustomerDetailPage from './pages/CustomerDetailPage'
import SettingsPage from './pages/SettingsPage'

function Shell({ children }: { children: React.ReactNode }) {
  const { email, logout } = useAuth()
  const navigate = useNavigate()

  async function onLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            A
          </span>
          Aéza
          <span className="brand-sub">Churn Risk Analyzer</span>
        </div>
        <nav className="app-nav">
          <NavLink to="/" end>
            Дашборд
          </NavLink>
          <NavLink to="/customers">Клиенты</NavLink>
          <NavLink to="/settings">Настройки модели</NavLink>
        </nav>
        <div className="header-user">
          <span className="email">{email}</span>
          <ThemeToggle />
          <button type="button" className="btn sm" onClick={onLogout}>
            Выйти
          </button>
        </div>
      </header>
      <main className="page">{children}</main>
    </div>
  )
}

export default function App() {
  const { email, ready } = useAuth()

  if (!ready) {
    return (
      <div className="login-wrap">
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
    <Shell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/customers" element={<CustomersPage />} />
        <Route path="/customers/:id" element={<CustomerDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
