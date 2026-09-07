"""Targeted Postgres verification (not part of the default pytest run).

Exercises real FinalSay behavior against whatever database
``FINALSAY_DATABASE_URL`` points at (used to verify the PostgreSQL path,
design.md section 8). Run as a standalone module AFTER ``create_all`` + seed:

    FINALSAY_DATABASE_URL=postgresql+psycopg2://finalsay:finalsay@127.0.0.1:5432/finalsay \
        .venv/bin/python -m finalsay.tests.pg_smoke

It intentionally does NOT go through conftest.py (which pins a temp SQLite URL
before import), so it honors the external FINALSAY_DATABASE_URL. It prints the
engine URL, runs a fresh submit/classify and a Merkle build+verify (ok then
tamper flip) against the live database, and exits non-zero on any failure.
"""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from finalsay.db import SessionLocal, engine
from finalsay.models import Notice, User
from finalsay.services import comparison, ingestion, provenance


def main() -> int:
    print(f"[pg_smoke] engine.url = {engine.url}")
    assert engine.url.get_backend_name() == "postgresql", (
        f"expected postgresql backend, got {engine.url.get_backend_name()}"
    )

    db = SessionLocal()
    try:
        # 1) A fresh submit/classify against a seeded institution.
        institution_id = db.scalar(select(func.min(Notice.institution_id)))
        assert institution_id is not None, "no seeded notices found"
        student = db.scalar(select(User).where(User.role == "student"))

        submission = ingestion.create_submission(
            db,
            text=(
                "Heads up: the library extended its hours for finals week and "
                "the deadline to return borrowed laptops is next Friday."
            ),
            institution_id=institution_id,
            submitted_by=student.id if student else None,
        )
        db.flush()
        outcome = comparison.classify_submission(db, submission)
        db.commit()
        print(
            f"[pg_smoke] classify -> label={outcome.label!r} "
            f"confidence={outcome.confidence:.2f} gated={outcome.gated}"
        )
        assert outcome.label in {
            "consistent",
            "conflicting",
            "unrelated",
            "unresolved",
        }, f"unexpected label {outcome.label!r}"

        # 2) Merkle build + verify against a seeded official notice (ok path)
        #    then the tamper path (must flip to not-ok).
        provenance.build_all_missing_roots(db)
        db.commit()
        notice_id = db.scalar(
            select(Notice.id).where(Notice.kind == "official").order_by(Notice.id)
        )
        ok = provenance.verify_notice(db, notice_id, tamper=False)
        bad = provenance.verify_notice(db, notice_id, tamper=True)
        print(
            f"[pg_smoke] verify notice {notice_id}: ok.ok={ok.ok} "
            f"tamper.ok={bad.ok} tamper.tamper={bad.tamper}"
        )
        assert ok.ok is True, f"expected verify ok, got {ok.details}"
        assert bad.ok is False and bad.tamper is True, (
            f"expected tamper flip, got {bad.details}"
        )

        # 3) Report a few counts straight from Postgres.
        counts = {
            "official_notices": db.scalar(
                select(func.count(Notice.id)).where(Notice.kind == "official")
            ),
            "submissions": db.scalar(
                select(func.count(Notice.id)).where(Notice.kind == "submission")
            ),
            "users": db.scalar(select(func.count(User.id))),
        }
        print(f"[pg_smoke] live counts: {counts}")
    finally:
        db.close()

    print("[pg_smoke] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
