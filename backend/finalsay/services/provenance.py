"""Provenance (module 3, design.md section 6).

- ``sha256_notice(redacted_text, issuer, notice_date, deadline, audience,
  action)``: canonical SHA-256 over the notice's redacted content and every
  stored, evidence-bearing field, so a targeted edit to any single column is
  tamper-detectable.
- ``build_daily_merkle(db, day)``: collect that day's notice hashes, build a
  binary Merkle tree (duplicate the last leaf on odd count), store a
  ``merkle_root`` and one ``merkle_proof`` per notice, and anchor the root via
  the configured Anchor interface.
- ``verify_notice(db, notice_id, tamper=False)``: recompute the notice hash,
  recompute the root from its stored proof, and compare against the stored root
  -> ``{ok, tamper, details}``. ``tamper=True`` simulates content tampering for
  the demo verification path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.models import MerkleProof, MerkleRoot, Notice
from finalsay.models_iface.anchor import get_anchor


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def sha256_notice(
    redacted_text: str | None,
    issuer: str | None,
    notice_date: str | None,
    deadline: str | None = None,
    audience: str | None = None,
    action: str | None = None,
) -> str:
    """Return the canonical SHA-256 hash of a notice's redacted content.

    The canonical form now covers every stored, evidence-bearing field
    (issuer, date, deadline, audience, action, redacted text) so a targeted edit
    to any one column is tamper-detectable, not just edits that also change
    ``redacted_text``. Fields are labelled and newline-joined so a value moving
    between columns cannot collide with another field's value.
    """
    canonical = "\n".join(
        [
            f"issuer:{(issuer or '').strip()}",
            f"date:{(notice_date or '').strip()}",
            f"deadline:{(deadline or '').strip()}",
            f"audience:{(audience or '').strip()}",
            f"action:{(action or '').strip()}",
            f"text:{(redacted_text or '').strip()}",
        ]
    )
    return _sha256_hex(canonical)


def hash_pair(left: str, right: str) -> str:
    """Hash two child node hashes into their parent (order-preserving)."""
    return _sha256_hex(left + right)


@dataclass
class MerkleBuildResult:
    root_id: int
    root_hash: str
    anchor_kind: str
    anchor_ref: str
    leaf_count: int


def _build_tree_with_proofs(
    leaves: list[str],
) -> tuple[str, list[list[dict]]]:
    """Build a binary Merkle tree from leaf hashes.

    Duplicates the last node on odd counts at every level. Returns the root
    hash and, per leaf index, the sibling proof path as a list of
    ``{"hash": ..., "position": "left"|"right"}`` dicts (bottom-up).
    """
    if not leaves:
        return _sha256_hex(""), []

    proofs: list[list[dict]] = [[] for _ in leaves]
    # index_map[i] = position of original leaf i within the current level.
    index_map = list(range(len(leaves)))
    level = list(leaves)

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # duplicate last node on odd count
        next_level: list[str] = []
        for i in range(0, len(level), 2):
            left, right = level[i], level[i + 1]
            parent = hash_pair(left, right)
            next_level.append(parent)
            for leaf_idx, pos in enumerate(index_map):
                if pos == i:
                    proofs[leaf_idx].append({"hash": right, "position": "right"})
                elif pos == i + 1:
                    proofs[leaf_idx].append({"hash": left, "position": "left"})
        # remap each original leaf to its parent's index in the next level.
        index_map = [pos // 2 for pos in index_map]
        level = next_level

    return level[0], proofs


def recompute_root_from_proof(leaf_hash: str, proof: list[dict]) -> str:
    """Recompute the Merkle root from a leaf hash and its sibling proof path."""
    current = leaf_hash
    for step in proof:
        sibling = step["hash"]
        if step["position"] == "left":
            current = hash_pair(sibling, current)
        else:
            current = hash_pair(current, sibling)
    return current


def _notices_for_day(db: Session, day: str) -> list[Notice]:
    """Return notices whose creation date (UTC) matches ``day`` (YYYY-MM-DD)."""
    notices = db.scalars(select(Notice).order_by(Notice.id)).all()
    return [n for n in notices if n.created_at.strftime("%Y-%m-%d") == day]


def build_daily_merkle(db: Session, day: str) -> MerkleBuildResult:
    """Build (or rebuild) the Merkle tree over ``day``'s notices and anchor it.

    Ensures every notice for the day has a stored SHA-256 and a Merkle proof.
    """
    notices = _notices_for_day(db, day)
    if not notices:
        raise ValueError(f"No notices found for day {day}")

    leaves: list[str] = []
    for notice in notices:
        digest = sha256_notice(
            notice.redacted_text,
            notice.issuer,
            notice.notice_date,
            notice.deadline,
            notice.audience,
            notice.action,
        )
        if notice.sha256 != digest:
            notice.sha256 = digest
        leaves.append(digest)

    root_hash, proofs = _build_tree_with_proofs(leaves)

    # Anchor the root before persisting the root row (GC-3: never blocks).
    anchor_ref = get_anchor(db).anchor(root_hash)

    root = MerkleRoot(
        day=day,
        root_hash=root_hash,
        anchor_kind=anchor_ref.kind,
        anchor_ref=anchor_ref.ref,
    )
    db.add(root)
    db.flush()

    # Clear any stale proofs for these notices, then store fresh ones. Use the
    # positional loop index as the leaf index: ``leaves.index(notice.sha256)``
    # would return the first matching position and collide whenever two notices
    # share a content hash (e.g. repeated ``unresolved`` submissions).
    for leaf_index, (notice, proof) in enumerate(zip(notices, proofs)):
        for stale in db.scalars(
            select(MerkleProof).where(MerkleProof.notice_id == notice.id)
        ).all():
            db.delete(stale)
        db.add(
            MerkleProof(
                notice_id=notice.id,
                root_id=root.id,
                proof_json=json.dumps(proof),
                leaf_index=leaf_index,
            )
        )
    db.flush()

    return MerkleBuildResult(
        root_id=root.id,
        root_hash=root_hash,
        anchor_kind=anchor_ref.kind,
        anchor_ref=anchor_ref.ref,
        leaf_count=len(notices),
    )


def build_all_missing_roots(db: Session) -> list[MerkleBuildResult]:
    """Build the daily Merkle root for every notice-day that lacks one.

    Idempotent: a day that already has a :class:`MerkleRoot` is skipped, so no
    duplicate roots, proofs, or anchor blocks are created on re-run. Used by the
    seed and the demo launcher so the student "Verify integrity" path returns
    ``ok=true`` out of the box (acceptance A-2).
    """
    notices = db.scalars(select(Notice)).all()
    days = sorted({n.created_at.strftime("%Y-%m-%d") for n in notices})

    results: list[MerkleBuildResult] = []
    for day in days:
        existing_root = db.scalar(
            select(MerkleRoot).where(MerkleRoot.day == day).limit(1)
        )
        if existing_root is not None:
            continue
        results.append(build_daily_merkle(db, day))
    return results


@dataclass
class VerifyResult:
    ok: bool
    tamper: bool
    details: dict

    def as_dict(self) -> dict:
        return {"ok": self.ok, "tamper": self.tamper, "details": self.details}


def verify_notice(db: Session, notice_id: int, tamper: bool = False) -> VerifyResult:
    """Recompute a notice's hash + Merkle root and compare to the stored root.

    When ``tamper=True`` the recomputed hash is deliberately altered to simulate
    tampered content, demonstrating the mismatch/tamper path for the demo.
    """
    notice = db.get(Notice, notice_id)
    if notice is None:
        return VerifyResult(
            ok=False,
            tamper=False,
            details={"error": f"notice {notice_id} not found"},
        )

    proof_row = db.scalar(
        select(MerkleProof)
        .where(MerkleProof.notice_id == notice_id)
        .order_by(MerkleProof.id.desc())
    )
    if proof_row is None:
        return VerifyResult(
            ok=False,
            tamper=False,
            details={"error": "no merkle proof stored; build the daily root first"},
        )

    root = db.get(MerkleRoot, proof_row.root_id)
    stored_root = root.root_hash if root else None

    recomputed_hash = sha256_notice(
        notice.redacted_text,
        notice.issuer,
        notice.notice_date,
        notice.deadline,
        notice.audience,
        notice.action,
    )
    if tamper:
        # Simulate tampered content: the recomputed leaf no longer matches.
        recomputed_hash = _sha256_hex(recomputed_hash + "::tampered")

    proof = json.loads(proof_row.proof_json)
    recomputed_root = recompute_root_from_proof(recomputed_hash, proof)

    matches = recomputed_root == stored_root and notice.sha256 == recomputed_hash
    return VerifyResult(
        ok=matches,
        tamper=not matches,
        details={
            "stored_hash": notice.sha256,
            "recomputed_hash": recomputed_hash,
            "stored_root": stored_root,
            "recomputed_root": recomputed_root,
            "leaf_index": proof_row.leaf_index,
            "anchor_kind": root.anchor_kind if root else None,
            "anchor_ref": root.anchor_ref if root else None,
            "simulated_tamper": tamper,
        },
    )
