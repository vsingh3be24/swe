"""Notices API (design.md sections 4/7).

- ``GET /api/notices`` lists official notices (optionally filtered by institution).
- ``GET /api/notices/{id}`` returns a notice with its extracted fields (evidence).
- ``GET /api/notices/{submission_id}/candidates`` returns ranked official
  candidates for a submission (the same retrieval used by comparison).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.auth import get_current_user
from finalsay.db import get_db
from finalsay.models import Notice, User
from finalsay.schemas import CandidateOut, NoticeDetail, NoticeSummary
from finalsay.services import comparison

router = APIRouter(prefix="/api/notices", tags=["notices"])


@router.get("", response_model=list[NoticeSummary])
def list_notices(
    institution_id: int | None = Query(default=None),
    kind: str = Query(default="official"),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[Notice]:
    query = select(Notice).where(Notice.kind == kind).order_by(Notice.id.desc())
    if institution_id is not None:
        query = query.where(Notice.institution_id == institution_id)
    return list(db.scalars(query).all())


@router.get("/{notice_id}", response_model=NoticeDetail)
def notice_detail(
    notice_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Notice:
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notice {notice_id} not found",
        )
    return notice


@router.get("/{submission_id}/candidates", response_model=list[CandidateOut])
def candidates(
    submission_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[CandidateOut]:
    submission = db.get(Notice, submission_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notice {submission_id} not found",
        )
    ranked = comparison.retrieve_candidates(db, submission)
    return [
        CandidateOut(notice=NoticeSummary.model_validate(c.notice), score=c.score)
        for c in ranked
    ]
