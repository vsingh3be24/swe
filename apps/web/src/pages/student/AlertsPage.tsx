import { useEffect, useMemo, useState } from 'react'
import { api, errorMessage } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import type { NoticeSummary } from '../../api/types'

// Alerts screen. Subscriptions are per-issuer toggles persisted client-side
// (the prototype has no push backend); the feed itself is real data pulled from
// GET /api/notices, filtered to the issuers the student subscribed to.
function subsKey(userId: number) {
  return `finalsay_alert_subs_${userId}`
}

export default function AlertsPage() {
  const { user } = useAuth()
  const [notices, setNotices] = useState<NoticeSummary[]>([])
  const [subs, setSubs] = useState<Record<string, boolean>>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (user) {
      try {
        setSubs(JSON.parse(localStorage.getItem(subsKey(user.id)) || '{}'))
      } catch {
        setSubs({})
      }
    }
    api
      .get<NoticeSummary[]>('/notices', { params: { kind: 'official' } })
      .then((res) => setNotices(res.data))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [user])

  const issuers = useMemo(() => {
    const set = new Set<string>()
    notices.forEach((n) => n.issuer && set.add(n.issuer))
    return Array.from(set).sort()
  }, [notices])

  const toggle = (issuer: string) => {
    if (!user) return
    const next = { ...subs, [issuer]: !subs[issuer] }
    setSubs(next)
    localStorage.setItem(subsKey(user.id), JSON.stringify(next))
  }

  const feed = useMemo(
    () => notices.filter((n) => n.issuer && subs[n.issuer]),
    [notices, subs],
  )

  return (
    <div className="stack">
      <div className="card">
        <h1>Alerts</h1>
        <p className="muted">
          Subscribe to issuers to build a personalized feed of their latest official
          notices.
        </p>
        <p className="muted">
          <strong>Prototype stub:</strong> subscriptions are stored in this
          browser only (localStorage). There is no server-side subscription or
          push/email delivery yet, so choices do not sync across devices or
          persist if you clear site data. The feed below is real data from{' '}
          <code>GET /api/notices</code>.
        </p>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : issuers.length === 0 ? (
          <p className="muted">No issuers available yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Issuer</th>
                <th>Subscribed</th>
              </tr>
            </thead>
            <tbody>
              {issuers.map((issuer) => (
                <tr key={issuer}>
                  <td>{issuer}</td>
                  <td>
                    <label className="switch">
                      <input
                        type="checkbox"
                        checked={!!subs[issuer]}
                        onChange={() => toggle(issuer)}
                      />
                      {subs[issuer] ? 'On' : 'Off'}
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {error && <p className="error">{error}</p>}
      </div>

      <div className="card">
        <h2>Your feed</h2>
        {feed.length === 0 ? (
          <p className="muted">Subscribe to an issuer above to see notices here.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Issuer</th>
                <th>Date</th>
                <th>Audience</th>
              </tr>
            </thead>
            <tbody>
              {feed.map((n) => (
                <tr key={n.id}>
                  <td>{n.id}</td>
                  <td>{n.issuer}</td>
                  <td>{n.notice_date ?? '—'}</td>
                  <td>{n.audience ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
