"""Comparison API (design.md section 7).

``POST /api/compare/{submission_id}``: run (or re-run) the configured
ComparisonModel against the best candidate official notice for a submission,
apply confidence gating, persist the relation edge, and return the outcome.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from finalsay.auth import get_current_user
from finalsay.db import get_db
from finalsay.models import Notice, User
from finalsay.schemas import ComparisonResponse
from finalsay.services import comparison

router = APIRouter(prefix="/api/compare", tags=["comparison"])


@router.post("/{submission_id}", response_model=ComparisonResponse)
def compare(
    submission_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ComparisonResponse:
    submission = db.get(Notice, submission_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"notice {submission_id} not found",
        )
    if submission.kind != "submission":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="comparison requires a submission notice",
        )

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
