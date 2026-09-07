import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../../api/client'
import {
  RELATIONSHIP_LABELS,
  type BenchmarkPairOut,
  type KappaResponse,
  type RelationshipLabel,
} from '../../api/types'

// Two-annotator benchmark screen: annotate the same pairs under two annotator
// identities and view the Cohen's kappa agreement report.
export default function BenchmarkPage() {
  const [pairs, setPairs] = useState<BenchmarkPairOut[]>([])
  const [kappa, setKappa] = useState<KappaResponse | null>(null)
  const [annotator, setAnnotator] = useState('reviewer_a')
  const [drafts, setDrafts] = useState<Record<number, RelationshipLabel>>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState<number | null>(null)

  const loadKappa = useCallback(async () => {
    try {
      const res = await api.get<KappaResponse>('/reviewer/benchmark/kappa')
      setKappa(res.data)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    api
      .get<BenchmarkPairOut[]>('/reviewer/benchmark/pairs')
      .then((res) => setPairs(res.data))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
    void loadKappa()
  }, [loadKappa])

  const annotate = async (pairId: number) => {
    const label = drafts[pairId] ?? 'consistent'
    setSavingId(pairId)
    setError('')
    try {
      await api.post('/reviewer/benchmark/annotate', {
        pair_id: pairId,
        annotator,
        label,
      })
      await loadKappa()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSavingId(null)
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Benchmark annotation</h1>
        <p className="muted">
          Two annotators label the same pairs; Cohen's kappa measures agreement. Switch the
          annotator identity to record a second opinion on the same pairs.
        </p>
        <label>
          Annotating as
          <select value={annotator} onChange={(ev) => setAnnotator(ev.target.value)}>
            <option value="reviewer_a">reviewer_a</option>
            <option value="reviewer_b">reviewer_b</option>
          </select>
        </label>
      </div>

      <div className="card">
        <h2>Cohen's kappa</h2>
        {kappa ? (
          <>
            <p className="result-head">
              <span className="kappa">{kappa.kappa.toFixed(4)}</span>
              <span className="muted">
                {kappa.annotators.join(' vs ') || 'not enough annotators'} ·{' '}
                {kappa.pairs_compared} shared pairs
              </span>
            </p>
            <pre className="pre">{JSON.stringify(kappa.per_label, null, 2)}</pre>
          </>
        ) : (
          <p className="muted">No kappa report yet.</p>
        )}
      </div>

      <div className="card">
        <h2>Pairs</h2>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : pairs.length === 0 ? (
          <p className="muted">No benchmark pairs seeded.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th>Submission</th>
                <th>Official</th>
                <th>Gold</th>
                <th>Your label</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((p) => (
                <tr key={p.id}>
                  <td>#{p.id}</td>
                  <td>#{p.submission_id}</td>
                  <td>#{p.official_id}</td>
                  <td>{p.gold_label ?? '—'}</td>
                  <td>
                    <select
                      value={drafts[p.id] ?? 'consistent'}
                      onChange={(ev) =>
                        setDrafts({
                          ...drafts,
                          [p.id]: ev.target.value as RelationshipLabel,
                        })
                      }
                    >
                      {RELATIONSHIP_LABELS.map((l) => (
                        <option key={l} value={l}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button
                      className="btn-secondary"
                      disabled={savingId === p.id}
                      onClick={() => annotate(p.id)}
                    >
                      {savingId === p.id ? 'Saving…' : 'Save'}
                    </button>
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
