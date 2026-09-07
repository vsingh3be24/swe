"""Comparison (module 4, design.md section 7).

- Candidate retrieval: filter official notices by institution/audience when
  known, rank by token overlap, take top-K (K=5).
- ``classify_submission``: run the configured ComparisonModel against the best
  candidate, apply confidence gating (below ``FINALSAY_CONFIDENCE_THRESHOLD`` ->
  label forced to 'unresolved' and a ``review_case`` created), then persist a
  ``relation_edge`` with label, confidence, rationale, model name and status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.config import get_settings
from finalsay.models import Notice, RelationEdge, ReviewCase
from finalsay.models_iface.comparison_model import (
    ComparisonModel,
    get_comparison_model,
)

TOP_K = 5


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _submission_text(notice: Notice) -> str:
    parts = [notice.issuer or "", notice.action or "", notice.redacted_text or ""]
    return "\n".join(p for p in parts if p)


@dataclass
class Candidate:
    notice: Notice
    score: float


def retrieve_candidates(
    db: Session, submission: Notice, top_k: int = TOP_K
) -> list[Candidate]:
    """Return top-K official-notice candidates ranked by lexical overlap.

    Filters by same institution and (loosely) matching audience when known.
    """
    query = select(Notice).where(
        Notice.kind == "official", Notice.id != submission.id
    )
    if submission.institution_id is not None:
        query = query.where(Notice.institution_id == submission.institution_id)

    officials = db.scalars(query).all()

    sub_tokens = _tokens(_submission_text(submission))
    aud_tokens = _tokens(submission.audience)

    scored: list[Candidate] = []
    for official in officials:
        score = _overlap(sub_tokens, _tokens(_submission_text(official)))
        if aud_tokens and _tokens(official.audience) & aud_tokens:
            score += 0.1  # small boost for matching audience
        scored.append(Candidate(notice=official, score=score))

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:top_k]


@dataclass
class ComparisonOutcome:
    edge: RelationEdge
    candidate: Notice | None
    label: str
    confidence: float
    rationale: str
    gated: bool
    review_case: ReviewCase | None


def classify_submission(
    db: Session,
    submission: Notice,
    model: ComparisonModel | None = None,
    threshold: float | None = None,
) -> ComparisonOutcome:
    """Classify a submission against its best candidate and persist the edge.

    Applies confidence gating (GC-4): when confidence is below the threshold the
    label is forced to 'unresolved' and a review_case is created. The relation
    edge is always persisted with label, confidence, rationale, model and status.
    """
    settings = get_settings()
    model = model or get_comparison_model()
    threshold = settings.confidence_threshold if threshold is None else threshold

    candidates = retrieve_candidates(db, submission)
    best = candidates[0].notice if candidates else None

    if best is None:
        # No official notice to compare against -> route to reviewer.
        label, confidence, rationale = (
            "unresolved",
            0.0,
            "No candidate official notice was found for comparison.",
        )
        gated = True
    else:
        premise = _submission_text(best)
        hypothesis = _submission_text(submission)
        label, confidence, rationale = model.classify(premise, hypothesis)
        # Confidence gating (GC-4): never force a guess below the threshold.
        gated = confidence < threshold
        if gated:
            rationale = (
                f"{rationale} Confidence {confidence:.2f} is below the "
                f"threshold {threshold:.2f}; routed to reviewer."
            )
            label = "unresolved"

    status = "unresolved" if label == "unresolved" else "auto"
    edge = RelationEdge(
        src_notice_id=submission.id,
        dst_notice_id=best.id if best is not None else submission.id,
        label=label,
        confidence=confidence,
        rationale=rationale,
        model=model.name,
        status=status,
    )
    db.add(edge)
    db.flush()

    review_case: ReviewCase | None = None
    if label == "unresolved":
        review_case = ReviewCase(
            edge_id=edge.id,
            status="open",
            assigned_role="reviewer",
        )
        db.add(review_case)
        db.flush()

    return ComparisonOutcome(
        edge=edge,
        candidate=best,
        label=label,
        confidence=confidence,
        rationale=rationale,
        gated=gated,
        review_case=review_case,
    )
