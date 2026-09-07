import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../../api/client'
import type { FetchResponse, InstitutionOut } from '../../api/types'

// Admin: list institution sources, add a new one, and trigger a synchronous
// fetch of official notices from all adapters.
export default function SourcesPage() {
  const [sources, setSources] = useState<InstitutionOut[]>([])
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get<InstitutionOut[]>('/ingest/sources')
      setSources(res.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const addSource = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    setMessage('')
    setBusy(true)
    try {
      await api.post('/ingest/sources', {
        name,
        slug,
        source_url: sourceUrl || null,
        active: true,
      })
      setName('')
      setSlug('')
      setSourceUrl('')
      setMessage('Source added.')
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const triggerFetch = async () => {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const res = await api.post<FetchResponse>('/ingest/fetch')
      setMessage(
        `Fetch complete: ${res.data.created} created, ${res.data.skipped} already present.`,
      )
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Institution sources</h1>
        <div className="row">
          <button onClick={triggerFetch} disabled={busy}>
            {busy ? 'Working…' : 'Trigger fetch'}
          </button>
        </div>
        {message && <p className="banner banner-ok">{message}</p>}
        {error && <p className="error">{error}</p>}
        {loading ? (
          <p className="muted">Loading…</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Slug</th>
                <th>Source URL</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.id}>
                  <td>{s.id}</td>
                  <td>{s.name}</td>
                  <td>{s.slug}</td>
                  <td>{s.source_url ?? '—'}</td>
                  <td>{s.active ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Add a source</h2>
        <form onSubmit={addSource}>
          <label>
            Name
            <input value={name} onChange={(ev) => setName(ev.target.value)} required />
          </label>
          <label>
            Slug
            <input value={slug} onChange={(ev) => setSlug(ev.target.value)} required />
          </label>
          <label>
            Source URL (optional)
            <input value={sourceUrl} onChange={(ev) => setSourceUrl(ev.target.value)} />
          </label>
          <button type="submit" disabled={busy}>
            Add source
          </button>
        </form>
      </div>
    </div>
  )
}
