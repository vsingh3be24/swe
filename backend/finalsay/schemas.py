"""Shared Pydantic v2 request/response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class HealthResponse(BaseModel):
    status: str = "ok"


# --- Auth ---

class UserRegister(BaseModel):
    # No ``role`` field: public self-registration always creates a student
    # account. Privileged roles are provisioned only by the seed script.
    email: EmailStr
    password: str = Field(min_length=6)
    display_name: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    display_name: str | None = None


# --- Provenance ---

class MerkleBuildRequest(BaseModel):
    day: str = Field(description="Day to build the Merkle root for (YYYY-MM-DD).")


class MerkleBuildResponse(BaseModel):
    root_id: int
    day: str
    root_hash: str
    anchor_kind: str
    anchor_ref: str
    leaf_count: int


class VerifyResponse(BaseModel):
    ok: bool
    tamper: bool
    details: dict


# --- Comparison ---

class ComparisonResponse(BaseModel):
    submission_id: int
    candidate_id: int | None = None
    edge_id: int
    label: str
    confidence: float
    rationale: str
    model: str
    status: str
    gated: bool
    review_case_id: int | None = None


# --- Notices ---

class NoticeFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field_name: str
    value: str | None = None
    confidence: float | None = None


class NoticeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    institution_id: int | None = None
    issuer: str | None = None
    notice_date: str | None = None
    deadline: str | None = None
    audience: str | None = None
    source_url: str | None = None
    sha256: str | None = None


class NoticeDetail(NoticeSummary):
    action: str | None = None
    redacted_text: str | None = None
    fields: list[NoticeFieldOut] = []


class CandidateOut(BaseModel):
    notice: NoticeSummary
    score: float


# --- Ingestion ---

class SubmitTextRequest(BaseModel):
    text: str = Field(min_length=1)
    institution_id: int | None = None


class FetchResponse(BaseModel):
    created: int
    skipped: int
    institutions: list[dict]


class InstitutionCreate(BaseModel):
    name: str
    slug: str
    source_url: str | None = None
    active: bool = True


class InstitutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    source_url: str | None = None
    active: bool


# --- Issuer ---

class IssuerPublishRequest(BaseModel):
    text: str = Field(min_length=1)
    institution_id: int | None = None
    institution_slug: str | None = None
    source_url: str | None = None


# --- Reviewer ---

class ReviewQueueItem(BaseModel):
    case_id: int
    edge_id: int
    status: str
    label: str
    confidence: float
    rationale: str | None = None
    submission: NoticeSummary
    candidate: NoticeSummary | None = None


class ResolveRequest(BaseModel):
    label: str


class ResolveResponse(BaseModel):
    case_id: int
    edge_id: int
    label: str
    edge_status: str
    case_status: str


class BenchmarkPairOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    submission_id: int
    official_id: int
    gold_label: str | None = None


class BenchmarkAnnotateRequest(BaseModel):
    pair_id: int
    annotator: str
    label: str


class KappaResponse(BaseModel):
    kappa: float
    annotators: list[str]
    pairs_compared: int
    per_label: dict
