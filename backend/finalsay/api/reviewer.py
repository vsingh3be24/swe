"""Reviewer console API (module 5, design.md section 8).

- ``GET /api/reviewer/queue`` lists open unresolved cases with the edge and both
  notices.
- ``POST /api/reviewer/cases/{id}/resolve {label}`` sets the edge label, marks
  the edge ``confirmed`` (label unchanged) or ``corrected`` (label changed), and
  closes the review case.
- Benchmark: ``GET /api/reviewer/benchmark/pairs``,
  ``POST /api/reviewer/benchmark/annotate {pair_id, annotator, label}``,
  ``GET /api/reviewer/benchmark/kappa`` (Cohen's kappa + per-label counts).
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.models import (
    RELATIONSHIP_LABELS,
    BenchmarkAnnotation,
    BenchmarkPair,
    Notice,
    RelationEdge,
    ReviewCase,
    User,
)
from finalsay.schemas import (
    BenchmarkAnnotateRequest,
    BenchmarkPairOut,
    KappaResponse,
    NoticeSummary,
    ResolveRequest,
    ResolveResponse,
    ReviewQueueItem,
)
from finalsay.services.kappa import cohen_kappa, per_label_counts

router = APIRouter(prefix="/api/reviewer", tags=["reviewer"])


@router.get(
    "/queue",
    response_model=list[ReviewQueueItem],
    dependencies=[Depends(require_role("reviewer", "admin"))],
)
def queue(db: Session = Depends(get_db)) -> list[ReviewQueueItem]:
    cases = db.scalars(
        select(ReviewCase).where(ReviewCase.status == "open").order_by(ReviewCase.id)
    ).all()

    items: list[ReviewQueueItem] = []
    for case in cases:
        edge = db.get(RelationEdge, case.edge_id)
        if edge is None:
            continue
        submission = db.get(Notice, edge.src_notice_id)
        candidate = db.get(Notice, edge.dst_notice_id)
        # For a no-candidate edge, src == dst; show no candidate in that case.
        candidate_summary = (
            NoticeSummary.model_validate(candidate)
            if candidate is not None and candidate.id != edge.src_notice_id
            else None
        )
        items.append(
            ReviewQueueItem(
                case_id=case.id,
                edge_id=edge.id,
                status=case.status,
                label=edge.label,
                confidence=edge.confidence,
                rationale=edge.rationale,
                submission=NoticeSummary.model_validate(submission),
                candidate=candidate_summary,
            )
        )
    return items


@router.post(
    "/cases/{case_id}/resolve",
    response_model=ResolveResponse,
    dependencies=[Depends(require_role("reviewer", "admin"))],
)
def resolve(
    case_id: int,
    payload: ResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer", "admin")),
) -> ResolveResponse:
    if payload.label not in RELATIONSHIP_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"label must be one of {RELATIONSHIP_LABELS}",
        )
    case = db.get(ReviewCase, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"review case {case_id} not found",
        )
    edge = db.get(RelationEdge, case.edge_id)
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="edge for review case not found",
        )

    # "confirmed" when the reviewer keeps the model's label, "corrected" otherwise.
    edge_status = "confirmed" if payload.label == edge.label else "corrected"
    edge.label = payload.label
    edge.status = edge_status

    case.status = "closed"
    case.resolved_by = current_user.id
    case.resolved_label = payload.label
    db.commit()

    return ResolveResponse(
        case_id=case.id,
        edge_id=edge.id,
        label=edge.label,
        edge_status=edge.status,
        case_status=case.status,
    )


@router.get(
    "/benchmark/pairs",
    response_model=list[BenchmarkPairOut],
    dependencies=[Depends(require_role("reviewer", "admin"))],
)
def benchmark_pairs(db: Session = Depends(get_db)) -> list[BenchmarkPair]:
    return list(db.scalars(select(BenchmarkPair).order_by(BenchmarkPair.id)).all())


@router.post(
    "/benchmark/annotate",
    response_model=BenchmarkPairOut,
    dependencies=[Depends(require_role("reviewer", "admin"))],
)
def benchmark_annotate(
    payload: BenchmarkAnnotateRequest, db: Session = Depends(get_db)
) -> BenchmarkPair:
    if payload.label not in RELATIONSHIP_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"label must be one of {RELATIONSHIP_LABELS}",
        )
    pair = db.get(BenchmarkPair, payload.pair_id)
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"benchmark pair {payload.pair_id} not found",
        )
    # Upsert: one annotation per (pair, annotator).
    existing = db.scalar(
        select(BenchmarkAnnotation).where(
            BenchmarkAnnotation.pair_id == payload.pair_id,
            BenchmarkAnnotation.annotator == payload.annotator,
        )
    )
    if existing is not None:
        existing.label = payload.label
    else:
        db.add(
            BenchmarkAnnotation(
                pair_id=payload.pair_id,
                annotator=payload.annotator,
                label=payload.label,
            )
        )
    db.commit()
    db.refresh(pair)
    return pair


@router.get(
    "/benchmark/kappa",
    response_model=KappaResponse,
    dependencies=[Depends(require_role("reviewer", "admin"))],
)
def benchmark_kappa(db: Session = Depends(get_db)) -> KappaResponse:
    return compute_benchmark_kappa(db)


def compute_benchmark_kappa(db: Session) -> KappaResponse:
    """Compute Cohen's kappa across the two most-active benchmark annotators.

    Only pairs annotated by both selected annotators are compared.
    """
    annotations = db.scalars(select(BenchmarkAnnotation)).all()

    by_annotator: dict[str, dict[int, str]] = defaultdict(dict)
    for annotation in annotations:
        by_annotator[annotation.annotator][annotation.pair_id] = annotation.label

    # Pick the two annotators with the most annotations for the comparison.
    annotators = sorted(
        by_annotator, key=lambda a: len(by_annotator[a]), reverse=True
    )[:2]
    if len(annotators) < 2:
        return KappaResponse(
            kappa=0.0, annotators=annotators, pairs_compared=0, per_label={}
        )

    a_name, b_name = annotators[0], annotators[1]
    shared = sorted(set(by_annotator[a_name]) & set(by_annotator[b_name]))
    labels_a = [by_annotator[a_name][pid] for pid in shared]
    labels_b = [by_annotator[b_name][pid] for pid in shared]

    return KappaResponse(
        kappa=round(cohen_kappa(labels_a, labels_b), 6),
        annotators=[a_name, b_name],
        pairs_compared=len(shared),
        per_label=per_label_counts(labels_a, labels_b),
    )
