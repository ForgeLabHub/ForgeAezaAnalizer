import { Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { AnalysisProvider, GenerationControl, useAnalysis } from './lib/realtime'
import { Loading } from './components/ui'
import { ThemeToggle } from './lib/theme'
import { AezaLogo } from './components/AezaLogo'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import PriorityPage from './pages/PriorityPage'
import CustomersPage from './pages/CustomersPage'
import CustomerDetailPage from './pages/CustomerDetailPage'
import SettingsPage from './pages/SettingsPage'
import DataSourcePage from './pages/DataSourcePage'

function Shell({ children }: { children: React.ReactNode }) {
  const { email, logout } = useAuth()
  const { pinnedGeneration, maxGeneration, setPinnedGeneration } = useAnalysis()
  const navigate = useNavigate()

  async function onLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <AezaLogo />
        <nav className="app-nav">
          <NavLink to="/" end>
            Дашборд
          </NavLink>
          <NavLink to="/priority">Приоритеты</NavLink>
          <NavLink to="/customers">Клиенты</NavLink>
          <NavLink to="/settings">Модель и сценарии</NavLink>
          <NavLink to="/data">Данные и качество</NavLink>
        </nav>
        <div className="header-user">
          <GenerationControl />
          <span className="email">{email}</span>
          <ThemeToggle />
          <button type="button" className="btn sm" onClick={onLogout}>
            Выйти
          </button>
        </div>
      </header>
      {pinnedGeneration !== null ? (
        <div className="archive-bar" role="status">
          <span>
            Просмотр архивного расчёта: <strong>поколение #{pinnedGeneration}</strong>
            {maxGeneration && maxGeneration !== pinnedGeneration
              ? ` (актуальное — #${maxGeneration})`
              : ''}
          </span>
          <button
            type="button"
            className="btn sm"
            onClick={() => setPinnedGeneration(null)}
          >
            Вернуться к Live
          </button>
        </div>
      ) : null}
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
    <AnalysisProvider>
      <Shell>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/priority" element={<PriorityPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/data" element={<DataSourcePage />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Shell>
    </AnalysisProvider>
  )
}
