import { useState, type FormEvent } from 'react'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ErrorBox } from '../components/ui'
import { ThemeToggle } from '../lib/theme'

export default function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('analyst@aeza.test')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email.trim(), password)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось выполнить вход')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <ThemeToggle className="login-theme-toggle" />
      <form className="login-card" onSubmit={onSubmit}>
        <div className="brand" style={{ marginBottom: 14 }}>
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
          Aéza
          <span className="brand-sub">Sentinel</span>
        </div>
        <h1>Вход в аналитическую панель</h1>
        <p className="sub">Анализ риска оттока клиентов и выручки под риском</p>

        {error ? <ErrorBox>{error}</ErrorBox> : null}

        <div className="field" style={{ marginTop: error ? 14 : 0 }}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            className="input"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="password">Пароль</label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        <button className="btn primary" style={{ width: '100%', marginTop: 6 }} disabled={busy}>
          {busy ? 'Вход…' : 'Войти'}
        </button>
        <p className="hint" style={{ marginTop: 14 }}>
          Демо-доступ задаётся переменными окружения <code>AEZA_ADMIN_EMAIL</code> и{' '}
          <code>AEZA_ADMIN_PASSWORD</code> (см. README).
        </p>
      </form>
    </div>
  )
}
