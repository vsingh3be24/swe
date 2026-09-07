"""Provenance tests: Merkle proofs verify for all leaves, tamper detection,
and the local anchor hash chain links via prev_hash."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from finalsay.models import AnchorBlock, Notice
from finalsay.services import provenance


def _make_notice(db, idx: int) -> Notice:
    notice = Notice(
        kind="official",
        issuer=f"Office {idx}",
        notice_date=f"2024-09-{idx:02d}",
        redacted_text=f"Official notice number {idx} content.",
    )
    db.add(notice)
    db.flush()
    return notice


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_merkle_proof_verifies_for_all_leaves(db_session):
    # Use an odd count to exercise the duplicate-last-leaf path.
    notices = [_make_notice(db_session, i) for i in range(1, 6)]
    db_session.commit()

    result = provenance.build_daily_merkle(db_session, _today())
    db_session.commit()
    assert result.leaf_count == 5

    for notice in notices:
        verify = provenance.verify_notice(db_session, notice.id)
        assert verify.ok is True, verify.details
        assert verify.tamper is False


def test_tampered_content_flips_tamper_flag(db_session):
    notices = [_make_notice(db_session, i) for i in range(1, 4)]
    db_session.commit()
    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    target = notices[0]

    # Simulated tamper via the demo flag.
    simulated = provenance.verify_notice(db_session, target.id, tamper=True)
    assert simulated.ok is False
    assert simulated.tamper is True

    # Real tamper: mutate stored content after the root was built.
    target.redacted_text = "This content was altered after anchoring."
    db_session.flush()
    real = provenance.verify_notice(db_session, target.id)
    assert real.ok is False
    assert real.tamper is True


def test_local_anchor_chain_prev_hash_links(db_session):
    # Two separate days -> two anchor blocks chained by prev_hash.
    _make_notice(db_session, 1)
    db_session.commit()
    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    _make_notice(db_session, 2)
    db_session.commit()
    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    blocks = db_session.scalars(
        select(AnchorBlock).order_by(AnchorBlock.index)
    ).all()
    assert len(blocks) >= 2
    assert blocks[0].prev_hash is None
    # Each block's prev_hash equals the previous block's this_hash.
    for prev, curr in zip(blocks, blocks[1:]):
        assert curr.prev_hash == prev.this_hash


def test_default_anchor_is_local(db_session):
    _make_notice(db_session, 1)
    db_session.commit()
    result = provenance.build_daily_merkle(db_session, _today())
    assert result.anchor_kind == "local"


def test_structured_field_edit_is_tamper_detectable(db_session):
    """A targeted edit to deadline/audience/action (without touching
    redacted_text) must fail verification: the canonical hash covers them."""
    notice = Notice(
        kind="official",
        issuer="Registrar",
        notice_date="15 Sep",
        deadline="20 Sep",
        audience="all students",
        action="Exam scheduled on 15 Sep.",
        redacted_text="Exam scheduled on 15 Sep for all students.",
    )
    db_session.add(notice)
    db_session.flush()
    db_session.commit()

    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    ok = provenance.verify_notice(db_session, notice.id)
    assert ok.ok is True, ok.details

    # Edit only the deadline column (redacted_text is unchanged).
    notice.deadline = "28 Sep"
    db_session.flush()
    tampered = provenance.verify_notice(db_session, notice.id)
    assert tampered.ok is False
    assert tampered.tamper is True


def test_leaf_index_is_positional_on_duplicate_hashes(db_session):
    """Two notices with identical content (identical hash) must get distinct,
    positional leaf indices, not the first-match index from list.index()."""
    for _ in range(3):
        dup = Notice(
            kind="submission",
            issuer="",
            notice_date="",
            redacted_text="Identical ambiguous circular text.",
        )
        db_session.add(dup)
    db_session.flush()
    db_session.commit()

    from finalsay.models import MerkleProof

    provenance.build_daily_merkle(db_session, _today())
    db_session.commit()

    proofs = db_session.scalars(select(MerkleProof).order_by(MerkleProof.id)).all()
    indices = sorted(p.leaf_index for p in proofs)
    assert indices == [0, 1, 2], indices
