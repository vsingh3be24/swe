import { useState } from 'react'
import { api, errorMessage } from '../../api/client'
import type { NoticeDetail } from '../../api/types'

// Issuer (Tier 2 stub): publish an official notice. Posts to /api/issuer/publish
// and shows the resulting hashed, field-extracted notice.
export default function PublishPage() {
  const [text, setText] = useState('')
  const [slug, setSlug] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [published, setPublished] = useState<NoticeDetail | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    setPublished(null)
    setBusy(true)
    try {
      const res = await api.post<NoticeDetail>('/issuer/publish', {
        text,
        institution_slug: slug || null,
        source_url: sourceUrl || null,
      })
      setPublished(res.data)
      setText('')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Publish official notice</h1>
        <p className="tag">Tier 2 stub — synthetic issuer accounts only.</p>
        <p className="muted">
          Publishes an official notice attributed to your institution, running it through
          the same extraction + SHA-256 provenance pipeline as fetched notices.
        </p>
        <form onSubmit={onSubmit}>
          <label>
            Notice text
            <textarea
              rows={8}
              value={text}
              onChange={(ev) => setText(ev.target.value)}
              placeholder="Enter the official notice text…"
              required
            />
          </label>
          <label>
            Institution slug (optional — defaults to the first institution)
            <input value={slug} onChange={(ev) => setSlug(ev.target.value)} />
          </label>
          <label>
            Source URL (optional)
            <input value={sourceUrl} onChange={(ev) => setSourceUrl(ev.target.value)} />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Publishing…' : 'Publish'}
          </button>
        </form>
      </div>

      {published && (
        <div className="card">
          <h2>Published notice #{published.id}</h2>
          <dl className="kv">
            <dt>Issuer</dt>
            <dd>{published.issuer ?? '—'}</dd>
            <dt>Date</dt>
            <dd>{published.notice_date ?? '—'}</dd>
            <dt>Deadline</dt>
            <dd>{published.deadline ?? '—'}</dd>
            <dt>Audience</dt>
            <dd>{published.audience ?? '—'}</dd>
            <dt>SHA-256</dt>
            <dd className="mono">{published.sha256 ?? '—'}</dd>
          </dl>
          {published.redacted_text && <pre className="pre">{published.redacted_text}</pre>}
        </div>
      )}
    </div>
  )
}
