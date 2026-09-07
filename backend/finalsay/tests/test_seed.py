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
    # Scope-note sections 1/7: the labelled benchmark is 300+ double-annotated
    # pairs (two annotator rows per pair -> >= 600 annotations).
    assert first["benchmark_pairs"] >= 300
    assert first["benchmark_annotations"] >= 600
    assert first["benchmark_annotations"] == 2 * first["benchmark_pairs"]


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


def test_benchmark_gold_covers_every_label(db_session):
    """Gold benchmark labels span the full 7-label taxonomy, including the
    deliberately ambiguous ``unresolved`` bucket (scope note section 7)."""
    seed(db_session)
    gold_labels = {
        p.gold_label for p in db_session.scalars(select(BenchmarkPair)).all()
    }
    for label in RELATIONSHIP_LABELS:
        assert label in gold_labels, f"benchmark missing gold label {label}"
    assert "unresolved" in gold_labels


def test_benchmark_kappa_is_realistic_db(db_session):
    """The kappa reported by the reviewer API over the two most-active
    annotators is substantial-but-imperfect: strictly > 0 and strictly < 1.0
    (genuine, non-trivial annotator disagreement, not perfect agreement)."""
    from finalsay.api.reviewer import compute_benchmark_kappa

    seed(db_session)
    result = compute_benchmark_kappa(db_session)
    assert result.pairs_compared >= 300
    assert set(result.annotators) == set(seed_module.dataset.BENCHMARK_ANNOTATORS)
    assert 0.0 < result.kappa < 1.0


def test_benchmark_kappa_is_realistic_harness():
    """The harness kappa (computed directly from the generated triples) is also
    strictly between 0 and 1, and lands in the intended substantial band."""
    from finalsay.eval.harness import benchmark_kappa

    kappa = benchmark_kappa()
    assert 0.0 < kappa < 1.0
    # Intended substantial-but-imperfect band from the deterministic generator.
    assert 0.55 <= kappa <= 0.85


def test_benchmark_triples_deterministic_and_large():
    """The generated triple set is >= 300 and generation is pure/deterministic
    (re-generating yields an identical list)."""
    from finalsay.seed.dataset import (
        BENCHMARK_TRIPLES,
        generate_benchmark_triples,
    )

    assert len(BENCHMARK_TRIPLES) >= 300
    assert generate_benchmark_triples() == generate_benchmark_triples()
    assert list(BENCHMARK_TRIPLES) == generate_benchmark_triples()
