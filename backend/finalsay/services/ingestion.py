"""Ingestion service (module 1, design.md section 4).

Shared helpers used by the ingestion, issuer and seed code paths:

- ``upsert_official`` runs a raw notice through extraction (which redacts and
  extracts fields) and upserts a ``official`` notice keyed by its content hash,
  so re-running a fetch adds no duplicates (idempotent, R1 / GC).
- ``create_submission`` runs the same extraction pipeline for a student
  submission and stores the resulting ``submission`` notice.

Only redacted text and extracted fields are ever persisted (GC-5, R2.4).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.adapters.base import RawNotice, get_adapters
from finalsay.models import Institution, Notice, NoticeField
from finalsay.services import extraction
from finalsay.services.extraction import ExtractionResult
from finalsay.services.provenance import sha256_notice


def _store_fields(db: Session, notice: Notice, result: ExtractionResult) -> None:
    """Replace a notice's stored fields with the freshly extracted ones."""
    for stale in list(notice.fields):
        db.delete(stale)
    for name, (value, confidence) in result.fields.items():
        db.add(
            NoticeField(
                notice_id=notice.id,
                field_name=name,
                value=value,
                confidence=confidence,
            )
        )


def _apply_extraction(notice: Notice, result: ExtractionResult) -> None:
    """Copy extracted fields onto the notice columns and compute its hash."""
    notice.redacted_text = result.redacted_text
    notice.issuer = result.field_value("issuer")
    notice.notice_date = result.field_value("date")
    notice.deadline = result.field_value("deadline")
    notice.audience = result.field_value("audience")
    notice.action = result.field_value("action")
    notice.sha256 = sha256_notice(
        notice.redacted_text,
        notice.issuer,
        notice.notice_date,
        notice.deadline,
        notice.audience,
        notice.action,
    )


def get_or_create_institution(
    db: Session, slug: str, name: str, source_url: str | None = None
) -> Institution:
    """Return the institution with ``slug``, creating it if absent (idempotent)."""
    institution = db.scalar(select(Institution).where(Institution.slug == slug))
    if institution is None:
        institution = Institution(slug=slug, name=name, source_url=source_url)
        db.add(institution)
        db.flush()
    return institution


def upsert_official(
    db: Session, raw: RawNotice, institution: Institution
) -> tuple[Notice, bool]:
    """Upsert an official notice from a raw notice, keyed by content hash.

    Returns ``(notice, created)`` where ``created`` is ``False`` when an
    identical notice already existed (idempotent re-fetch).
    """
    result = extraction.extract(text=raw.text)
    digest = sha256_notice(
        result.redacted_text,
        result.field_value("issuer"),
        result.field_value("date"),
        result.field_value("deadline"),
        result.field_value("audience"),
        result.field_value("action"),
    )
    existing = db.scalar(
        select(Notice).where(
            Notice.kind == "official",
            Notice.institution_id == institution.id,
            Notice.sha256 == digest,
        )
    )
    if existing is not None:
        return existing, False

    notice = Notice(
        kind="official",
        institution_id=institution.id,
        source_url=raw.source_url,
        retrieved_at=datetime.now(timezone.utc),
    )
    db.add(notice)
    db.flush()
    _apply_extraction(notice, result)
    _store_fields(db, notice, result)
    db.flush()
    return notice, True


def fetch_all(db: Session) -> dict:
    """Run all adapters synchronously and upsert their notices by content hash.

    Idempotent: a second call with unchanged fixtures creates no new rows.
    Returns a summary dict with per-institution created/skipped counts.
    """
    summary: dict = {"created": 0, "skipped": 0, "institutions": []}
    for adapter in get_adapters():
        institution = get_or_create_institution(
            db, adapter.slug, adapter.name, adapter.base_url
        )
        created = skipped = 0
        for raw in adapter.fetch():
            _notice, was_created = upsert_official(db, raw, institution)
            if was_created:
                created += 1
            else:
                skipped += 1
        summary["created"] += created
        summary["skipped"] += skipped
        summary["institutions"].append(
            {
                "slug": adapter.slug,
                "name": adapter.name,
                "created": created,
                "skipped": skipped,
            }
        )
    return summary


def create_submission(
    db: Session,
    *,
    text: str | None = None,
    pdf_bytes: bytes | None = None,
    image_bytes: bytes | None = None,
    institution_id: int | None = None,
    submitted_by: int | None = None,
) -> Notice:
    """Extract a student submission and persist it as a ``submission`` notice."""
    result = extraction.extract(text=text, pdf_bytes=pdf_bytes, image_bytes=image_bytes)
    notice = Notice(
        kind="submission",
        institution_id=institution_id,
        submitted_by=submitted_by,
        retrieved_at=datetime.now(timezone.utc),
    )
    db.add(notice)
    db.flush()
    _apply_extraction(notice, result)
    _store_fields(db, notice, result)
    db.flush()
    return notice


def publish_official(
    db: Session,
    *,
    text: str,
    institution: Institution,
    source_url: str | None = None,
) -> Notice:
    """Publish an official notice for the issuer stub (extraction + hash)."""
    raw = RawNotice(
        text=text,
        source_url=source_url or f"{(institution.source_url or '').rstrip('/')}/issued",
        institution_slug=institution.slug,
    )
    notice, _created = upsert_official(db, raw, institution)
    return notice
