import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import type { Role } from '../api/types'

interface NavItem {
  to: string
  label: string
  roles: Role[]
}

// Role-aware navigation: only links the signed-in role can use are shown.
const NAV: NavItem[] = [
  { to: '/submit', label: 'Submit', roles: ['student'] },
  { to: '/notices', label: 'Notices', roles: ['student', 'reviewer', 'admin', 'issuer'] },
  { to: '/alerts', label: 'Alerts', roles: ['student'] },
  { to: '/reviewer/queue', label: 'Queue', roles: ['reviewer', 'admin'] },
  { to: '/reviewer/benchmark', label: 'Benchmark', roles: ['reviewer', 'admin'] },
  { to: '/admin/sources', label: 'Sources', roles: ['admin'] },
  { to: '/issuer/publish', label: 'Publish', roles: ['issuer'] },
]

export default function NavBar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const onLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="navbar">
      <div className="nav-inner">
        <Link to="/" className="brand">
          FinalSay
        </Link>
        <nav className="nav-links">
          {user &&
            NAV.filter((item) => item.roles.includes(user.role)).map((item) => (
              <NavLink key={item.to} to={item.to} className="nav-link">
                {item.label}
              </NavLink>
            ))}
        </nav>
        <div className="nav-user">
          {user ? (
            <>
              <span className="muted">
                {user.display_name || user.email} ({user.role})
              </span>
              <button className="btn-secondary" onClick={onLogout}>
                Log out
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className="nav-link">
                Log in
              </NavLink>
              <NavLink to="/register" className="nav-link">
                Register
              </NavLink>
            </>
          )}
        </div>
      </div>
    </header>
  )
}
