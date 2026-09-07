import { useState } from 'react'
import { useLocation, useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { errorMessage } from '../api/client'

const DEMO_USERS = [
  { email: 'student@finalsay.demo', password: 'student123', role: 'student' },
  { email: 'reviewer@finalsay.demo', password: 'reviewer123', role: 'reviewer' },
  { email: 'admin@finalsay.demo', password: 'admin123', role: 'admin' },
  { email: 'issuer@finalsay.demo', password: 'issuer123', role: 'issuer' },
]

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const from = (location.state as { from?: string } | null)?.from || '/'

  const doLogin = async (e: string, p: string) => {
    setError('')
    setBusy(true)
    try {
      await login(e, p)
      navigate(from, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="narrow">
      <div className="card">
        <h1>Log in</h1>
        <form
          onSubmit={(ev) => {
            ev.preventDefault()
            void doLogin(email, password)
          }}
        >
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(ev) => setEmail(ev.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(ev) => setPassword(ev.target.value)}
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Log in'}
          </button>
        </form>
        <p className="muted">
          No account? <Link to="/register">Register</Link>
        </p>
      </div>

      <div className="card">
        <h2>Demo accounts</h2>
        <p className="muted">Click a role to sign in with seeded credentials.</p>
        <table>
          <thead>
            <tr>
              <th>Role</th>
              <th>Email</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {DEMO_USERS.map((u) => (
              <tr key={u.email}>
                <td>{u.role}</td>
                <td>{u.email}</td>
                <td>
                  <button
                    className="btn-secondary"
                    disabled={busy}
                    onClick={() => {
                      setEmail(u.email)
                      setPassword(u.password)
                      void doLogin(u.email, u.password)
                    }}
                  >
                    Use
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
