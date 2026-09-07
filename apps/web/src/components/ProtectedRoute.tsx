import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import type { Role } from '../api/types'

interface Props {
  children: ReactNode
  roles?: Role[]
}

// Gate a route behind authentication and, optionally, one or more roles.
export default function ProtectedRoute({ children, roles }: Props) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <p className="muted">Loading…</p>
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  if (roles && !roles.includes(user.role)) {
    return (
      <div className="card">
        <h2>Not authorized</h2>
        <p className="muted">
          This area requires one of these roles: {roles.join(', ')}. You are signed in as{' '}
          <strong>{user.role}</strong>.
        </p>
      </div>
    )
  }
  return <>{children}</>
}
