import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../../api/client'
import { saveResult } from '../../api/resultCache'
import type { ComparisonResponse, InstitutionOut } from '../../api/types'

// Student submission: paste text and/or upload a PDF/image. Posts multipart to
// /api/ingest/submit and navigates to the result once classified.
export default function SubmitPage() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [institutionId, setInstitutionId] = useState<string>('')
  const [institutions, setInstitutions] = useState<InstitutionOut[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    // Institutions are useful context; the source list endpoint is admin-only,
    // so we fall back silently to a free submission if it is not available.
    api
      .get<InstitutionOut[]>('/ingest/sources')
      .then((res) => setInstitutions(res.data))
      .catch(() => setInstitutions([]))
  }, [])

  const onSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    if (!text.trim() && !file) {
      setError('Provide pasted text or upload a PDF/image.')
      return
    }
    setBusy(true)
    try {
      const form = new FormData()
      if (text.trim()) form.append('text', text)
      if (file) form.append('file', file)
      if (institutionId) form.append('institution_id', institutionId)
      const res = await api.post<ComparisonResponse>('/ingest/submit', form)
      saveResult(res.data)
      navigate(`/result/${res.data.submission_id}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="narrow">
      <div className="card">
        <h1>Submit a notice</h1>
        <p className="muted">
          Paste the text of a forwarded notice, or upload a PDF or image. If OCR is
          unavailable in this environment, image uploads return a friendly error asking you
          to paste the text instead.
        </p>
        <form onSubmit={onSubmit}>
          <label>
            Notice text
            <textarea
              rows={10}
              value={text}
              placeholder="Paste the notice text here…"
              onChange={(ev) => setText(ev.target.value)}
            />
          </label>
          <label>
            Or upload a file (PDF / image)
            <input
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,application/pdf,image/*"
              onChange={(ev) => setFile(ev.target.files?.[0] ?? null)}
            />
          </label>
          {institutions.length > 0 && (
            <label>
              Institution (optional)
              <select
                value={institutionId}
                onChange={(ev) => setInstitutionId(ev.target.value)}
              >
                <option value="">Auto-detect</option>
                {institutions.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Analyzing…' : 'Submit and verify'}
          </button>
        </form>
      </div>
    </div>
  )
}
