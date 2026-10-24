import { useState, type FormEvent } from 'react'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ErrorBox } from '../components/ui'
import { ThemeToggle } from '../lib/theme'
import { AezaWordmark } from '../components/AezaLogo'

export default function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
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
      <div className="presswall-bg is-full" aria-hidden="true" />
      <ThemeToggle className="login-theme-toggle" />
      <form className="login-card" onSubmit={onSubmit}>
        <div style={{ marginBottom: 16 }}>
          <AezaWordmark />
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
      </form>
    </div>
  )
}
