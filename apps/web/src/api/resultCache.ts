import type { ComparisonResponse } from './types'

// The classification outcome is only returned by POST /ingest/submit; there is
// no GET endpoint that re-derives the relationship label for a submission. We
// cache the outcome in sessionStorage so the /result/:id page can show the
// label + confidence + rationale after navigation (and across a reload within
// the session).
const KEY = 'finalsay_results'

type Cache = Record<string, ComparisonResponse>

function read(): Cache {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || '{}') as Cache
  } catch {
    return {}
  }
}

export function saveResult(result: ComparisonResponse): void {
  const cache = read()
  cache[String(result.submission_id)] = result
  sessionStorage.setItem(KEY, JSON.stringify(cache))
}

export function loadResult(submissionId: number): ComparisonResponse | null {
  return read()[String(submissionId)] ?? null
}
