"""Ingestion API (module 1, design.md section 4).

- ``POST /api/ingest/submit``: a student submits a notice as a multipart file
  (image/pdf) OR JSON ``{text}``. Runs extraction -> provenance hash ->
  comparison and returns the classified result. Image input with no OCR engine
  degrades to HTTP 422 asking for pasted text (graceful degradation, R2.1).
- ``POST /api/ingest/fetch`` (admin): runs the three institution adapters
  synchronously and upserts official notices by content hash (idempotent).
- ``GET/POST /api/ingest/sources`` (admin): CRUD over ``institution`` rows.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.models import Institution, User
from finalsay.schemas import (
    ComparisonResponse,
    FetchResponse,
    InstitutionCreate,
    InstitutionOut,
)
from finalsay.services import comparison
from finalsay.services import ingestion
from finalsay.services.extraction import OcrUnavailable

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
_PDF_TYPES = {"application/pdf"}


# Submitting a notice for verification is a Student action in the scope note.
# We gate it to ``student`` (the primary actor) plus ``admin`` (operational
# override / demo convenience) rather than any authenticated role, keeping the
# per-actor route model consistent. Reviewers and issuers have their own routes.
@router.post("/submit", response_model=ComparisonResponse)
async def submit(
    text: str | None = Form(default=None),
    institution_id: int | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("student", "admin")),
) -> ComparisonResponse:
    """Ingest a student submission (upload or paste) and classify it."""
    pdf_bytes: bytes | None = None
    image_bytes: bytes | None = None

    if file is not None:
        data = await file.read()
        content_type = (file.content_type or "").lower()
        if content_type in _PDF_TYPES or (file.filename or "").lower().endswith(".pdf"):
            pdf_bytes = data
        elif content_type in _IMAGE_TYPES or (file.filename or "").lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp")
        ):
            image_bytes = data
        else:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported file type; upload a PDF or image, or paste text.",
            )
    elif not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either a file (pdf/image) or pasted text.",
        )

    try:
        submission = ingestion.create_submission(
            db,
            text=text,
            pdf_bytes=pdf_bytes,
            image_bytes=image_bytes,
            institution_id=institution_id,
            submitted_by=current_user.id,
        )
    except OcrUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    outcome = comparison.classify_submission(db, submission)
    db.commit()

    return ComparisonResponse(
        submission_id=submission.id,
        candidate_id=outcome.candidate.id if outcome.candidate else None,
        edge_id=outcome.edge.id,
        label=outcome.label,
        confidence=outcome.confidence,
        rationale=outcome.rationale,
        model=outcome.edge.model or "",
        status=outcome.edge.status,
        gated=outcome.gated,
        review_case_id=outcome.review_case.id if outcome.review_case else None,
    )


@router.post(
    "/fetch",
    response_model=FetchResponse,
    dependencies=[Depends(require_role("admin"))],
)
def fetch(db: Session = Depends(get_db)) -> FetchResponse:
    """Run all adapters and upsert official notices by content hash (idempotent)."""
    summary = ingestion.fetch_all(db)
    db.commit()
    return FetchResponse(**summary)


@router.get(
    "/sources",
    response_model=list[InstitutionOut],
    dependencies=[Depends(require_role("admin"))],
)
def list_sources(db: Session = Depends(get_db)) -> list[Institution]:
    return list(db.scalars(select(Institution).order_by(Institution.id)).all())


@router.post(
    "/sources",
    response_model=InstitutionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("admin"))],
)
def create_source(
    payload: InstitutionCreate, db: Session = Depends(get_db)
) -> Institution:
    existing = db.scalar(
        select(Institution).where(Institution.slug == payload.slug)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"institution slug '{payload.slug}' already exists",
        )
    institution = Institution(
        name=payload.name,
        slug=payload.slug,
        source_url=payload.source_url,
        active=payload.active,
    )
    db.add(institution)
    db.commit()
    db.refresh(institution)
    return institution
