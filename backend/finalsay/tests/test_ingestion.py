"""Ingestion tests: adapter/fetch idempotency by content hash, student submit
returns a classified result, sources CRUD, and the issuer publish stub."""

from __future__ import annotations

from fastapi.testclient import TestClient

from finalsay.models import Notice, NoticeField
from finalsay.services import ingestion


def _token(client, make_user, email, password, role):
    # Public register only creates students; provision privileged roles the way
    # the seed does (directly), then log in through the normal flow.
    if role == "student":
        client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
    else:
        make_user(email, password, role)
    resp = client.post(
        "/api/auth/login", data={"username": email, "password": password}
    )
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_fetch_all_is_idempotent_by_hash(db_session):
    first = ingestion.fetch_all(db_session)
    db_session.commit()
    officials_1 = db_session.query(Notice).filter(Notice.kind == "official").count()

    second = ingestion.fetch_all(db_session)
    db_session.commit()
    officials_2 = db_session.query(Notice).filter(Notice.kind == "official").count()

    assert first["created"] > 0
    assert officials_1 == officials_2  # no duplicates on re-run
    assert second["created"] == 0
    assert second["skipped"] == officials_1


def test_admin_fetch_endpoint_no_duplicates(client: TestClient, make_user):
    token = _token(client, make_user, "admin1@example.com", "s3cret1", "admin")
    r1 = client.post("/api/ingest/fetch", headers=_auth(token))
    assert r1.status_code == 200, r1.text
    created_1 = r1.json()["created"]
    assert created_1 > 0

    r2 = client.post("/api/ingest/fetch", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["created"] == 0

    # Confirm the browse endpoint sees a stable count.
    listing = client.get("/api/notices", headers=_auth(token))
    assert listing.status_code == 200
    assert len(listing.json()) == created_1


def test_fetch_requires_admin(client: TestClient, make_user):
    student = _token(client, make_user, "stud2@example.com", "s3cret1", "student")
    resp = client.post("/api/ingest/fetch", headers=_auth(student))
    assert resp.status_code == 403


def test_submit_paste_returns_classified_result(client: TestClient, make_user):
    admin = _token(client, make_user, "admin2@example.com", "s3cret1", "admin")
    client.post("/api/ingest/fetch", headers=_auth(admin))

    student = _token(client, make_user, "stud3@example.com", "s3cret1", "student")
    resp = client.post(
        "/api/ingest/submit",
        data={
            "text": "The mid-term examination has been cancelled until further notice.",
        },
        headers=_auth(student),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submission_id"] > 0
    assert body["edge_id"] > 0
    assert body["label"] in (
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
    )
    assert "cancel" in body["rationale"].lower() or body["label"] == "unresolved"


def test_submit_without_input_is_422(client: TestClient, make_user):
    student = _token(client, make_user, "stud4@example.com", "s3cret1", "student")
    resp = client.post("/api/ingest/submit", data={}, headers=_auth(student))
    assert resp.status_code == 422


def test_submit_image_without_ocr_engine_is_422(client: TestClient, make_user):
    """With no Tesseract engine, image upload degrades to 422 asking for text."""
    student = _token(client, make_user, "stud5@example.com", "s3cret1", "student")
    # A tiny fake PNG payload; extraction should raise OcrUnavailable -> 422.
    files = {"file": ("scan.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}
    resp = client.post("/api/ingest/submit", files=files, headers=_auth(student))
    assert resp.status_code == 422, resp.text


def test_sources_crud(client: TestClient, make_user):
    admin = _token(client, make_user, "admin3@example.com", "s3cret1", "admin")

    created = client.post(
        "/api/ingest/sources",
        json={"name": "Test Uni", "slug": "test-uni", "source_url": "https://t.edu"},
        headers=_auth(admin),
    )
    assert created.status_code == 201, created.text
    assert created.json()["slug"] == "test-uni"

    # Duplicate slug -> 409.
    dup = client.post(
        "/api/ingest/sources",
        json={"name": "Test Uni", "slug": "test-uni"},
        headers=_auth(admin),
    )
    assert dup.status_code == 409

    listing = client.get("/api/ingest/sources", headers=_auth(admin))
    assert listing.status_code == 200
    assert any(i["slug"] == "test-uni" for i in listing.json())


def test_issuer_publish_creates_official(client: TestClient, make_user):
    admin = _token(client, make_user, "admin4@example.com", "s3cret1", "admin")
    client.post(
        "/api/ingest/sources",
        json={"name": "Issuer Uni", "slug": "issuer-uni"},
        headers=_auth(admin),
    )

    issuer = _token(client, make_user, "issuer1@example.com", "s3cret1", "issuer")
    resp = client.post(
        "/api/issuer/publish",
        json={
            "institution_slug": "issuer-uni",
            "text": "Issued by: Issuer Uni\nSubject: Holiday\nDate: 5 May\nCampus closed on 5 May.",
        },
        headers=_auth(issuer),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "official"
    assert body["redacted_text"]
    assert body["sha256"]

    # A student cannot publish.
    student = _token(client, make_user, "stud6@example.com", "s3cret1", "student")
    forbidden = client.post(
        "/api/issuer/publish",
        json={"institution_slug": "issuer-uni", "text": "x"},
        headers=_auth(student),
    )
    assert forbidden.status_code == 403


# --- Retention / redaction-before-storage (scope note §1, §6; GC-5, R2.4-R2.8) ---

# Original PII strings that MUST never survive into persisted storage.
_PII_ORIGINALS = (
    "jane.smith@northgate.edu",  # email
    "555 2671",  # phone fragment
    "21CS0456",  # roll / registration number
    "Jane Smith",  # honorific name
    "Robert Brown",  # labelled name
)
_REDACTION_MASKS = (
    "[REDACTED_EMAIL]",
    "[REDACTED_PHONE]",
    "[REDACTED_ID]",
    "[REDACTED_NAME]",
)
_PII_TEXT = (
    "Office of the Registrar\n"
    "Attention: all first-year students\n"
    "The mid-term exam is postponed to 22 Sept 2024.\n"
    "Contact Dr. Jane Smith at jane.smith@northgate.edu or +1 415 555 2671.\n"
    "Roll number 21CS0456 must re-register.\n"
    "Name: Robert Brown\n"
)


def test_persisted_submission_holds_only_redacted_text_no_unredacted_original(db_session):
    """Behavioral proof of the retention policy: after actually persisting a notice
    ingested from PII-containing text and re-reading it from the DB, the stored
    redacted_text and every stored NoticeField value must contain the redaction
    masks and NOT the original PII, and no persisted attribute may hold the
    unredacted original. This test would FAIL if an unredacted original were ever
    stored.
    """
    created = ingestion.create_submission(db_session, text=_PII_TEXT)
    db_session.commit()
    notice_id = created.id

    # Expunge everything so the assertions run against a fresh DB read, not the
    # in-memory object we just built.
    db_session.expunge_all()

    notice = db_session.get(Notice, notice_id)
    assert notice is not None

    # redacted_text is the persisted text and carries masks, not the PII.
    assert notice.redacted_text
    for original in _PII_ORIGINALS:
        assert original not in notice.redacted_text
    assert any(mask in notice.redacted_text for mask in _REDACTION_MASKS)

    # No persisted column/attribute on the Notice holds the unredacted original.
    # (Structural guarantee: there is no unredacted-original column.) Scan every
    # persisted string attribute and the raw DB columns to be certain.
    persisted_strings = [
        value for value in vars(notice).values() if isinstance(value, str)
    ]
    for value in persisted_strings:
        for original in _PII_ORIGINALS:
            assert original not in value, (
                f"unredacted PII {original!r} leaked into a persisted Notice attribute"
            )
    column_names = {c.name for c in Notice.__table__.columns}
    assert not any(
        "unredact" in name or name in {"raw_text", "original_text", "original"}
        for name in column_names
    ), "Notice table must not have an unredacted-original column"

    # Every stored NoticeField value is redacted too (fields parsed from redacted
    # text), so no identifier leaks through the structured extraction.
    fields = db_session.query(NoticeField).filter(NoticeField.notice_id == notice_id).all()
    assert fields, "expected extracted fields to be persisted"
    for row in fields:
        if row.value:
            for original in _PII_ORIGINALS:
                assert original not in row.value, (
                    f"unredacted PII {original!r} leaked into stored field {row.field_name!r}"
                )


def test_persisted_official_holds_only_redacted_text(db_session):
    """Same retention guarantee via the official upsert path (upsert_official ->
    _apply_extraction / _store_fields), re-read from the DB."""
    institution = ingestion.get_or_create_institution(
        db_session, "northgate", "Northgate University", "https://northgate.edu"
    )
    from finalsay.adapters.base import RawNotice

    raw = RawNotice(
        text=_PII_TEXT,
        source_url="https://northgate.edu/notices/1",
        institution_slug="northgate",
    )
    notice, created = ingestion.upsert_official(db_session, raw, institution)
    db_session.commit()
    assert created
    notice_id = notice.id
    db_session.expunge_all()

    reread = db_session.get(Notice, notice_id)
    assert reread is not None and reread.redacted_text
    for original in _PII_ORIGINALS:
        assert original not in reread.redacted_text
        assert original not in (reread.action or "")
        assert original not in (reread.issuer or "")
    assert any(mask in reread.redacted_text for mask in _REDACTION_MASKS)
