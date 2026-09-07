"""Provenance API (design.md section 6).

- ``POST /api/provenance/build`` (admin): build the daily Merkle root and anchor it.
- ``GET /api/provenance/verify/{notice_id}``: recompute the notice hash + Merkle
  root and report tamper status. ``?tamper=true`` simulates tampered content for
  the demo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.schemas import (
    MerkleBuildRequest,
    MerkleBuildResponse,
    VerifyResponse,
)
from finalsay.services import provenance

router = APIRouter(prefix="/api/provenance", tags=["provenance"])


@router.post(
    "/build",
    response_model=MerkleBuildResponse,
    dependencies=[Depends(require_role("admin"))],
)
def build_daily_root(
    payload: MerkleBuildRequest | None = None,
    db: Session = Depends(get_db),
) -> MerkleBuildResponse:
    day = (
        payload.day
        if payload and payload.day
        else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    try:
        result = provenance.build_daily_merkle(db, day)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    db.commit()
    return MerkleBuildResponse(
        root_id=result.root_id,
        day=day,
        root_hash=result.root_hash,
        anchor_kind=result.anchor_kind,
        anchor_ref=result.anchor_ref,
        leaf_count=result.leaf_count,
    )


@router.get("/verify/{notice_id}", response_model=VerifyResponse)
def verify(
    notice_id: int,
    tamper: bool = Query(False, description="Simulate tampered content (demo)."),
    db: Session = Depends(get_db),
) -> VerifyResponse:
    result = provenance.verify_notice(db, notice_id, tamper=tamper)
    if not result.ok and result.details.get("error"):
        # Distinguish "not found / no proof" from a genuine tamper mismatch.
        if "not found" in result.details["error"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.details["error"],
            )
    return VerifyResponse(**result.as_dict())
