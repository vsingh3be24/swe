import { useEffect, useState } from 'react'
import { api, errorMessage } from '../../api/client'
import type { NoticeSummary } from '../../api/types'

// Alerts screen — NON-INTERACTIVE placeholder.
//
// A real alerts feature (per-issuer subscriptions with push/email delivery) is
// out of scope for this prototype and has no backend. The earlier version stored
// subscription toggles in localStorage only, which was a half-working feature
// that never synced or delivered anything. That interactive-but-fake control has
// been removed. This screen now shows a clearly-labelled read-only preview of the
// most recent official notices (real data from GET /api/notices) so the intent of
// the screen is visible without pretending the alerts feature exists.
export default function AlertsPage() {
  const [notices, setNotices] = useState<NoticeSummary[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get<NoticeSummary[]>('/notices', { params: { kind: 'official' } })
      .then((res) => setNotices(res.data.slice(0, 10)))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="stack">
      <div className="card">
        <h1>Alerts</h1>
        <p className="muted">
          <strong>Not implemented in this prototype.</strong> A personalized
          alerts feature (subscribe to issuers and receive push/email updates)
          would live here. It requires a subscription and delivery backend that
          does not exist yet, so there is nothing interactive to configure on
          this screen.
        </p>
        <p className="muted">
          The read-only list below is a preview of the latest official notices
          (real data from <code>GET /api/notices</code>) to illustrate what an
          alerts feed would eventually draw from. It is not a real alerts feature
          and does not filter to any subscription.
        </p>
      </div>

      <div className="card">
        <h2>Recent official notices (read-only preview)</h2>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : notices.length === 0 ? (
          <p className="muted">No official notices available yet.</p>
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
              {notices.map((n) => (
                <tr key={n.id}>
                  <td>{n.id}</td>
                  <td>{n.issuer ?? '—'}</td>
                  <td>{n.notice_date ?? '—'}</td>
                  <td>{n.audience ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
