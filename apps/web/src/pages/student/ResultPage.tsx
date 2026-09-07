import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, errorMessage } from '../../api/client'
import type {
  CandidateOut,
  ComparisonResponse,
  NoticeDetail,
  VerifyResponse,
} from '../../api/types'
import { loadResult } from '../../api/resultCache'
import LabelBadge from '../../components/LabelBadge'

// The result / evidence-trail screen for a submission: shows the relationship
// label + confidence, the extracted fields (evidence), the matched candidate,
// the model rationale, and an integrity-check button.
export default function ResultPage() {
  const { id } = useParams<{ id: string }>()
  const submissionId = Number(id)

  const [submission, setSubmission] = useState<NoticeDetail | null>(null)
  const [candidates, setCandidates] = useState<CandidateOut[]>([])
  const [verify, setVerify] = useState<VerifyResponse | null>(null)
  const [outcome, setOutcome] = useState<ComparisonResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [verifying, setVerifying] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [sub, cands] = await Promise.all([
        api.get<NoticeDetail>(`/notices/${submissionId}`),
        api.get<CandidateOut[]>(`/notices/${submissionId}/candidates`),
      ])
      setSubmission(sub.data)
      setCandidates(cands.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [submissionId])

  useEffect(() => {
    void load()
    setOutcome(loadResult(submissionId))
  }, [load, submissionId])

  const runVerify = async (tamper: boolean) => {
    setVerifying(true)
    setError('')
    try {
      const res = await api.get<VerifyResponse>(
        `/provenance/verify/${submissionId}`,
        { params: { tamper } },
      )
      setVerify(res.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setVerifying(false)
    }
  }

  if (loading) return <p className="muted">Loading result…</p>
  if (error && !submission) return <p className="error">{error}</p>
  if (!submission) return <p className="muted">No submission found.</p>

  const topCandidate = candidates[0]

  return (
    <div className="stack">
      <div className="card">
        <h1>Verification result</h1>
        <p className="muted">Submission #{submission.id}</p>
        {outcome ? (
          <div className="stack-sm">
            <p className="result-head">
              <LabelBadge label={outcome.label} />
              <span className="confidence">
                confidence {(outcome.confidence * 100).toFixed(0)}%
              </span>
              {outcome.gated && <span className="tag">routed to review</span>}
            </p>
            <p>
              <strong>Rationale:</strong> {outcome.rationale}
            </p>
            <p className="muted">
              Model: {outcome.model || 'mock'} · edge status: {outcome.status}
            </p>
          </div>
        ) : (
          <p className="muted">
            The relationship label is shown right after submitting. Re-submit from{' '}
            <Link to="/submit">Submit</Link> to see it again.
          </p>
        )}
        {topCandidate ? (
          <p>
            Matched against official notice <strong>#{topCandidate.notice.id}</strong>{' '}
            (lexical score {topCandidate.score.toFixed(3)}).
          </p>
        ) : (
          <p className="muted">No candidate official notice was found for this submission.</p>
        )}
      </div>

      <div className="card">
        <h2>Extracted fields (evidence)</h2>
        {submission.fields.length === 0 ? (
          <p className="muted">No fields extracted.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Value</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {submission.fields.map((f) => (
                <tr key={f.field_name}>
                  <td>{f.field_name}</td>
                  <td>{f.value ?? <span className="muted">—</span>}</td>
                  <td>{f.confidence != null ? f.confidence.toFixed(2) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {submission.redacted_text && (
          <>
            <h3>Redacted text</h3>
            <pre className="pre">{submission.redacted_text}</pre>
          </>
        )}
      </div>

      {topCandidate && (
        <div className="card">
          <h2>Closest official notice</h2>
          <dl className="kv">
            <dt>Issuer</dt>
            <dd>{topCandidate.notice.issuer ?? '—'}</dd>
            <dt>Date</dt>
            <dd>{topCandidate.notice.notice_date ?? '—'}</dd>
            <dt>Deadline</dt>
            <dd>{topCandidate.notice.deadline ?? '—'}</dd>
            <dt>Audience</dt>
            <dd>{topCandidate.notice.audience ?? '—'}</dd>
          </dl>
          <Link to={`/notices`}>Browse all official notices</Link>
        </div>
      )}

      <div className="card">
        <h2>Document integrity</h2>
        <p className="muted">
          Recompute the SHA-256 hash and check the Merkle proof against the anchored root.
        </p>
        <div className="row">
          <button disabled={verifying} onClick={() => runVerify(false)}>
            Verify integrity
          </button>
          <button
            className="btn-secondary"
            disabled={verifying}
            onClick={() => runVerify(true)}
          >
            Simulate tamper
          </button>
        </div>
        {verify && (
          <div className={verify.tamper ? 'banner banner-bad' : 'banner banner-ok'}>
            {verify.tamper ? (
              <strong>Tamper detected — integrity check failed.</strong>
            ) : verify.ok ? (
              <strong>Integrity verified — hash and Merkle proof match.</strong>
            ) : (
              <strong>Unable to verify (no proof yet). Ask an admin to build the daily root.</strong>
            )}
            <pre className="pre">{JSON.stringify(verify.details, null, 2)}</pre>
          </div>
        )}
      </div>

      {error && <p className="error">{error}</p>}
    </div>
  )
}
