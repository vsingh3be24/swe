"""Ingestion tests: adapter/fetch idempotency by content hash, student submit
returns a classified result, sources CRUD, and the issuer publish stub."""

from __future__ import annotations

from fastapi.testclient import TestClient

from finalsay.models import Notice
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
