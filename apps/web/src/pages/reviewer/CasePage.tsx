import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, errorMessage } from '../../api/client'
import {
  RELATIONSHIP_LABELS,
  type NoticeDetail,
  type RelationshipLabel,
  type ResolveResponse,
  type ReviewQueueItem,
} from '../../api/types'
import LabelBadge from '../../components/LabelBadge'

// A single review case: confirm or correct the relationship label. The backend
// has no per-case GET, so we pull the queue and pick the matching case.
export default function CasePage() {
  const { id } = useParams<{ id: string }>()
  const caseId = Number(id)
  const navigate = useNavigate()

  const [item, setItem] = useState<ReviewQueueItem | null>(null)
  const [submission, setSubmission] = useState<NoticeDetail | null>(null)
  const [candidate, setCandidate] = useState<NoticeDetail | null>(null)
  const [label, setLabel] = useState<RelationshipLabel>('consistent')
  const [resolved, setResolved] = useState<ResolveResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const queue = await api.get<ReviewQueueItem[]>('/reviewer/queue')
      const found = queue.data.find((c) => c.case_id === caseId) ?? null
      setItem(found)
      if (found) {
        setLabel(found.label)
        const detailReqs: Promise<unknown>[] = [
          api
            .get<NoticeDetail>(`/notices/${found.submission.id}`)
            .then((r) => setSubmission(r.data)),
        ]
        if (found.candidate) {
          detailReqs.push(
            api
              .get<NoticeDetail>(`/notices/${found.candidate.id}`)
              .then((r) => setCandidate(r.data)),
          )
        }
        await Promise.all(detailReqs)
      }
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => {
    void load()
  }, [load])

  const resolve = async () => {
    setBusy(true)
    setError('')
    try {
      const res = await api.post<ResolveResponse>(`/reviewer/cases/${caseId}/resolve`, {
        label,
      })
      setResolved(res.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="muted">Loading case…</p>
  if (resolved) {
    return (
      <div className="stack">
        <div className="card">
          <h1>Case #{resolved.case_id} resolved</h1>
          <p>
            Edge now labeled <LabelBadge label={resolved.label} /> (edge status:{' '}
            {resolved.edge_status}, case: {resolved.case_status}).
          </p>
          <button onClick={() => navigate('/reviewer/queue')}>Back to queue</button>
        </div>
      </div>
    )
  }
  if (!item) {
    return (
      <div className="card">
        <h1>Case not found</h1>
        <p className="muted">
          Case #{caseId} is not in the open queue (it may already be resolved).
        </p>
        <button onClick={() => navigate('/reviewer/queue')}>Back to queue</button>
      </div>
    )
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Review case #{item.case_id}</h1>
        <p>
          Model suggested <LabelBadge label={item.label} /> at{' '}
          {(item.confidence * 100).toFixed(0)}% confidence.
        </p>
        {item.rationale && (
          <p>
            <strong>Rationale:</strong> {item.rationale}
          </p>
        )}
      </div>

      <div className="two-col">
        <div className="card">
          <h2>Submission #{item.submission.id}</h2>
          {submission?.redacted_text ? (
            <pre className="pre">{submission.redacted_text}</pre>
          ) : (
            <p className="muted">No text.</p>
          )}
        </div>
        <div className="card">
          <h2>Candidate {item.candidate ? `#${item.candidate.id}` : ''}</h2>
          {item.candidate ? (
            candidate?.redacted_text ? (
              <pre className="pre">{candidate.redacted_text}</pre>
            ) : (
              <p className="muted">Loading…</p>
            )
          ) : (
            <p className="muted">No candidate official notice.</p>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Confirm or correct</h2>
        <label>
          Relationship label
          <select
            value={label}
            onChange={(ev) => setLabel(ev.target.value as RelationshipLabel)}
          >
            {RELATIONSHIP_LABELS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <p className="muted">
          Keeping the current label marks the edge <strong>confirmed</strong>; choosing a
          different one marks it <strong>corrected</strong>.
        </p>
        {error && <p className="error">{error}</p>}
        <button onClick={resolve} disabled={busy}>
          {busy ? 'Saving…' : 'Resolve case'}
        </button>
      </div>
    </div>
  )
}
