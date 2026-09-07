import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { errorMessage } from '../api/client'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    setBusy(true)
    try {
      await register(email, password, displayName)
      navigate('/', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="narrow">
      <div className="card">
        <h1>Register</h1>
        <form onSubmit={onSubmit}>
          <label>
            Display name
            <input value={displayName} onChange={(ev) => setDisplayName(ev.target.value)} />
          </label>
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
            Password (min 6 characters)
            <input
              type="password"
              value={password}
              minLength={6}
              onChange={(ev) => setPassword(ev.target.value)}
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Creating…' : 'Create account'}
          </button>
        </form>
        <p className="muted">
          New accounts are created as <strong>students</strong>. Reviewer, admin
          and issuer accounts are provisioned by an administrator (use the seeded
          demo credentials to explore those roles).
        </p>
        <p className="muted">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  )
}
