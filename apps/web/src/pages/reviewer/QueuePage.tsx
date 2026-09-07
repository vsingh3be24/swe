import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../../api/client'
import type { ReviewQueueItem } from '../../api/types'
import LabelBadge from '../../components/LabelBadge'

// Unresolved review queue (GET /api/reviewer/queue).
export default function QueuePage() {
  const [items, setItems] = useState<ReviewQueueItem[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get<ReviewQueueItem[]>('/reviewer/queue')
      .then((res) => setItems(res.data))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="stack">
      <div className="card">
        <h1>Review queue</h1>
        <p className="muted">Unresolved cases awaiting a reviewer decision.</p>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : items.length === 0 ? (
          <p className="muted">The queue is empty. Nice work.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Submission</th>
                <th>Candidate</th>
                <th>Current label</th>
                <th>Confidence</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.case_id}>
                  <td>#{it.case_id}</td>
                  <td>#{it.submission.id}</td>
                  <td>{it.candidate ? `#${it.candidate.id}` : '—'}</td>
                  <td>
                    <LabelBadge label={it.label} />
                  </td>
                  <td>{(it.confidence * 100).toFixed(0)}%</td>
                  <td>
                    <Link to={`/reviewer/case/${it.case_id}`}>Open</Link>
                  </td>
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
