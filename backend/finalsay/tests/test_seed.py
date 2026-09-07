"""Seed tests: idempotent (stable row counts on re-run) and every taxonomy
label is present among the seeded submissions."""

from __future__ import annotations

from sqlalchemy import func, select

from finalsay.models import (
    RELATIONSHIP_LABELS,
    BenchmarkAnnotation,
    BenchmarkPair,
    Institution,
    Notice,
    RelationEdge,
    User,
)
from finalsay.seed import seed as seed_module
from finalsay.seed.seed import load_gold_submissions, seed


from finalsay.models import AnchorBlock, MerkleProof, MerkleRoot
from finalsay.services import provenance


def _counts(db):
    return {
        "institutions": db.scalar(select(func.count(Institution.id))),
        "users": db.scalar(select(func.count(User.id))),
        "official": db.scalar(
            select(func.count(Notice.id)).where(Notice.kind == "official")
        ),
        "submissions": db.scalar(
            select(func.count(Notice.id)).where(Notice.kind == "submission")
        ),
        "benchmark_pairs": db.scalar(select(func.count(BenchmarkPair.id))),
        "benchmark_annotations": db.scalar(select(func.count(BenchmarkAnnotation.id))),
        "merkle_roots": db.scalar(select(func.count(MerkleRoot.id))),
        "merkle_proofs": db.scalar(select(func.count(MerkleProof.id))),
        "anchor_blocks": db.scalar(select(func.count(AnchorBlock.id))),
    }


def test_seed_is_idempotent(db_session):
    seed(db_session)
    first = _counts(db_session)

    seed(db_session)
    second = _counts(db_session)

    assert first == second, (first, second)
    # Sanity: the design targets ~40 officials * 3 institutions and ~60 submissions.
    assert first["institutions"] == 3
    assert first["official"] == 120
    assert first["submissions"] >= 60
    assert first["users"] == 4


def test_every_taxonomy_label_present_in_gold(db_session):
    seed(db_session)
    gold = load_gold_submissions()
    gold_labels = {g["gold_label"] for g in gold}
    for label in RELATIONSHIP_LABELS:
        assert label in gold_labels, f"missing gold label {label}"


def test_every_taxonomy_label_present_in_edges(db_session):
    seed(db_session)
    edge_labels = {e.label for e in db_session.scalars(select(RelationEdge)).all()}
    # The mock model reproduces every gold label deterministically.
    for label in RELATIONSHIP_LABELS:
        assert label in edge_labels, f"missing predicted label {label}"


def test_demo_users_have_all_roles(db_session):
    seed(db_session)
    roles = {u.role for u in db_session.scalars(select(User)).all()}
    assert roles == {"student", "reviewer", "admin", "issuer"}


def test_fresh_seed_verifies_a_notice(db_session):
    """A freshly seeded DB builds the daily Merkle root, so a seeded notice
    verifies (ok=true) with no out-of-band admin step (acceptance A-2)."""
    seed(db_session)

    # Every seeded notice should have a proof and verify successfully.
    assert db_session.scalar(select(func.count(MerkleRoot.id))) >= 1
    proof_count = db_session.scalar(select(func.count(MerkleProof.id)))
    notice_count = db_session.scalar(select(func.count(Notice.id)))
    assert proof_count == notice_count

    a_notice = db_session.scalars(select(Notice).order_by(Notice.id)).first()
    result = provenance.verify_notice(db_session, a_notice.id)
    assert result.ok is True, result.details
    assert result.tamper is False


def test_benchmark_has_two_annotators(db_session):
    seed(db_session)
    annotators = {
        a.annotator for a in db_session.scalars(select(BenchmarkAnnotation)).all()
    }
    assert len(annotators) == 2
    assert annotators == set(seed_module.dataset.BENCHMARK_ANNOTATORS)
