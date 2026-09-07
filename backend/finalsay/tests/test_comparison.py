"""Comparison tests: the 22-vs-15 Sept case, confidence gating to unresolved +
review_case creation, and relation-edge persistence with rationale."""

from __future__ import annotations

from sqlalchemy import select

from finalsay.models import RelationEdge, ReviewCase, Notice
from finalsay.models_iface.comparison_model import (
    MockComparisonModel,
    get_comparison_model,
)
from finalsay.services import comparison


def test_default_comparison_model_is_mock():
    model = get_comparison_model()
    assert model.name == "mock"


def test_postponed_22_vs_15_sept_not_consistent():
    model = MockComparisonModel()
    label, confidence, rationale = model.classify(
        "The exam is on 15 Sept.",
        "The exam is postponed to 22 Sept.",
    )
    assert label in ("contradictory", "superseded"), (label, rationale)
    assert label != "consistent"
    assert 0.0 <= confidence <= 1.0
    assert rationale


def _make_notice(db, kind, text, institution_id=1, action=None, audience=None):
    notice = Notice(
        kind=kind,
        institution_id=institution_id,
        issuer="Registrar",
        redacted_text=text,
        action=action,
        audience=audience,
    )
    db.add(notice)
    db.flush()
    return notice


def test_low_confidence_yields_unresolved_and_review_case(db_session):
    official = _make_notice(
        db_session,
        "official",
        "Library will operate on holiday hours next week.",
    )
    submission = _make_notice(
        db_session,
        "submission",
        "Cafeteria menu features seasonal vegetables.",
    )
    db_session.commit()

    # Deterministic low-confidence model to trigger gating.
    class _LowConf(MockComparisonModel):
        def classify(self, premise, hypothesis):
            return ("consistent", 0.3, "weak signal")

    outcome = comparison.classify_submission(
        db_session, submission, model=_LowConf(), threshold=0.6
    )
    db_session.commit()

    assert outcome.label == "unresolved"
    assert outcome.gated is True
    assert outcome.review_case is not None

    # A review_case row exists and points at the edge.
    cases = db_session.scalars(select(ReviewCase)).all()
    assert len(cases) == 1
    assert cases[0].edge_id == outcome.edge.id
    assert cases[0].status == "open"

    # The edge is persisted with rationale/model/status.
    edge = db_session.get(RelationEdge, outcome.edge.id)
    assert edge.label == "unresolved"
    assert edge.status == "unresolved"
    assert edge.model == "mock"
    assert edge.rationale
    assert "threshold" in edge.rationale.lower()


def test_high_confidence_persists_edge_without_review_case(db_session):
    official = _make_notice(
        db_session,
        "official",
        "The exam is scheduled on 15 Sept for all students.",
        action="exam on 15 Sept",
    )
    submission = _make_notice(
        db_session,
        "submission",
        "The exam is postponed to 22 Sept for all students.",
        action="exam postponed to 22 Sept",
    )
    db_session.commit()

    outcome = comparison.classify_submission(db_session, submission, threshold=0.6)
    db_session.commit()

    assert outcome.candidate is not None
    assert outcome.candidate.id == official.id
    assert outcome.label in ("contradictory", "superseded")
    assert outcome.review_case is None

    edge = db_session.get(RelationEdge, outcome.edge.id)
    assert edge.src_notice_id == submission.id
    assert edge.dst_notice_id == official.id
    assert edge.status == "auto"
    assert edge.rationale


def test_no_candidate_routes_to_unresolved(db_session):
    # Submission with no official notices in its institution.
    submission = _make_notice(
        db_session, "submission", "Some standalone submission.", institution_id=99
    )
    db_session.commit()

    outcome = comparison.classify_submission(db_session, submission)
    db_session.commit()

    assert outcome.label == "unresolved"
    assert outcome.review_case is not None
