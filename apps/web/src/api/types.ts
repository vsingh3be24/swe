// Response/request shapes mirrored from backend/finalsay/schemas.py.

export type Role = 'student' | 'reviewer' | 'admin' | 'issuer'

export const RELATIONSHIP_LABELS = [
  'consistent',
  'contradictory',
  'superseded',
  'corrected',
  'extended',
  'cancelled',
  'unresolved',
] as const

export type RelationshipLabel = (typeof RELATIONSHIP_LABELS)[number]

export interface UserOut {
  id: number
  email: string
  role: Role
  display_name: string | null
}

export interface Token {
  access_token: string
  token_type: string
}

export interface NoticeFieldOut {
  field_name: string
  value: string | null
  confidence: number | null
}

export interface NoticeSummary {
  id: number
  kind: string
  institution_id: number | null
  issuer: string | null
  notice_date: string | null
  deadline: string | null
  audience: string | null
  source_url: string | null
  sha256: string | null
}

export interface NoticeDetail extends NoticeSummary {
  action: string | null
  redacted_text: string | null
  fields: NoticeFieldOut[]
}

export interface CandidateOut {
  notice: NoticeSummary
  score: number
}

export interface ComparisonResponse {
  submission_id: number
  candidate_id: number | null
  edge_id: number
  label: RelationshipLabel
  confidence: number
  rationale: string
  model: string
  status: string
  gated: boolean
  review_case_id: number | null
}

export interface VerifyResponse {
  ok: boolean
  tamper: boolean
  details: Record<string, unknown>
}

export interface InstitutionOut {
  id: number
  name: string
  slug: string
  source_url: string | null
  active: boolean
}

export interface FetchResponse {
  created: number
  skipped: number
  institutions: Array<Record<string, unknown>>
}

export interface ReviewQueueItem {
  case_id: number
  edge_id: number
  status: string
  label: RelationshipLabel
  confidence: number
  rationale: string | null
  submission: NoticeSummary
  candidate: NoticeSummary | null
}

export interface ResolveResponse {
  case_id: number
  edge_id: number
  label: RelationshipLabel
  edge_status: string
  case_status: string
}

export interface BenchmarkPairOut {
  id: number
  submission_id: number
  official_id: number
  gold_label: string | null
  submission_text: string | null
  official_text: string | null
}

export interface KappaResponse {
  kappa: number
  annotators: string[]
  pairs_compared: number
  per_label: Record<string, unknown>
}
