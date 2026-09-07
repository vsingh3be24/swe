import { useEffect, useState } from 'react'
import { api, errorMessage } from '../../api/client'
import type { NoticeDetail, NoticeSummary } from '../../api/types'

// Browse official notices (GET /api/notices) and drill into detail + fields.
export default function NoticesPage() {
  const [notices, setNotices] = useState<NoticeSummary[]>([])
  const [selected, setSelected] = useState<NoticeDetail | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get<NoticeSummary[]>('/notices', { params: { kind: 'official' } })
      .then((res) => setNotices(res.data))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  const openDetail = async (noticeId: number) => {
    setError('')
    try {
      const res = await api.get<NoticeDetail>(`/notices/${noticeId}`)
      setSelected(res.data)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Official notices</h1>
        <p className="muted">Verified notices fetched from the connected institutions.</p>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : notices.length === 0 ? (
          <p className="muted">
            No official notices yet. An admin can trigger a fetch from the Sources screen.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Issuer</th>
                <th>Date</th>
                <th>Deadline</th>
                <th>Audience</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {notices.map((n) => (
                <tr key={n.id}>
                  <td>{n.id}</td>
                  <td>{n.issuer ?? '—'}</td>
                  <td>{n.notice_date ?? '—'}</td>
                  <td>{n.deadline ?? '—'}</td>
                  <td>{n.audience ?? '—'}</td>
                  <td>
                    <button className="btn-secondary" onClick={() => openDetail(n.id)}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {error && <p className="error">{error}</p>}
      </div>

      {selected && (
        <div className="card">
          <h2>Notice #{selected.id}</h2>
          <dl className="kv">
            <dt>Issuer</dt>
            <dd>{selected.issuer ?? '—'}</dd>
            <dt>Date</dt>
            <dd>{selected.notice_date ?? '—'}</dd>
            <dt>Deadline</dt>
            <dd>{selected.deadline ?? '—'}</dd>
            <dt>Audience</dt>
            <dd>{selected.audience ?? '—'}</dd>
            <dt>Action</dt>
            <dd>{selected.action ?? '—'}</dd>
            <dt>Source</dt>
            <dd>
              {selected.source_url ? (
                <a href={selected.source_url} target="_blank" rel="noreferrer">
                  {selected.source_url}
                </a>
              ) : (
                '—'
              )}
            </dd>
            <dt>SHA-256</dt>
            <dd className="mono">{selected.sha256 ?? '—'}</dd>
          </dl>
          {selected.redacted_text && (
            <>
              <h3>Redacted text</h3>
              <pre className="pre">{selected.redacted_text}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}
