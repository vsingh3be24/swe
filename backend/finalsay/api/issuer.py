"""Issuer API (Tier 2 stub, design.md section 9).

``POST /api/issuer/publish`` (role ``issuer``, synthetic accounts only) creates
an ``official`` notice attributed to the issuer's institution and runs it
through the extraction + provenance hash pipeline. This is clearly a stub: it
trusts the caller and is only for demonstrating the issuer actor path (GC-6).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.models import Institution, User
from finalsay.schemas import IssuerPublishRequest, NoticeDetail
from finalsay.services import ingestion

router = APIRouter(prefix="/api/issuer", tags=["issuer"])


@router.post("/publish", response_model=NoticeDetail, status_code=status.HTTP_201_CREATED)
def publish(
    payload: IssuerPublishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("issuer")),
):
    institution: Institution | None = None
    if payload.institution_id is not None:
        institution = db.get(Institution, payload.institution_id)
    elif payload.institution_slug is not None:
        institution = db.scalar(
            select(Institution).where(Institution.slug == payload.institution_slug)
        )
    else:
        # Default to the first institution so the demo path always works.
        institution = db.scalar(select(Institution).order_by(Institution.id))

    if institution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no institution found to attribute the notice to",
        )

    notice = ingestion.publish_official(
        db,
        text=payload.text,
        institution=institution,
        source_url=payload.source_url,
    )
    db.commit()
    db.refresh(notice)
    return notice
