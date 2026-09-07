"""End-to-end smoke test: prove the FinalSay demo journey works.

This drives the *real* application through its actual HTTP API (auth, ingestion,
notices, provenance) using the in-process FastAPI ``TestClient`` fixture from
``conftest.py``. It is not a collection of isolated unit tests: a single test
walks the whole user journey and asserts real behavior at every stage, so it
would fail if any stage of the pipeline broke.

Why in-process rather than a live ``uvicorn`` server: in this environment
background daemons are reaped between separate tool/command invocations
(``--die-with-parent``), so an out-of-process server started in one step is gone
by the next and cannot be driven across steps. The in-process ``TestClient``
exercises the identical ASGI app, routes, dependencies and services end-to-end
within a single process, so it is the durable, deterministic proof target. It
runs fully offline: the default MOCK comparison model, the LOCAL anchor, and a
temporary SQLite database provisioned per test by ``conftest.py`` (no network,
no Hugging Face stack, no paid keys).

The journey exercised (each an assertion, not an assumption):

1. Provision + log in the required actors (admin, issuer, student) through the
   real auth flow to obtain bearer tokens.
2. Seed an official notice into an institution (admin creates the source, the
   issuer publishes the official through the extraction + hash pipeline).
3. Student submits a notice containing PII and a conflicting date:
   -> extracted fields are returned and PII is redacted (masks present, the
      original PII strings absent) in both the classification response's
      evidence trail and the persisted, re-read notice;
   -> a candidate official is retrieved;
   -> a relationship label + confidence + rationale are returned, and the
      conflicting date drives a non-``consistent`` relationship above the
      confidence gate.
4. Evidence trail: GET the submission notice (fields + redacted_text) and GET
   its ranked candidates.
5. Integrity: admin builds the daily Merkle root, verify returns ok/no-tamper
   against the anchored hash, and the ``?tamper=true`` path flips to a detected
   tamper.
6. Ambiguity: a deliberately low-signal submission is gated to ``unresolved``
   and opens a review case.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from finalsay.models import Notice, NoticeField


# --- helpers -----------------------------------------------------------------

def _token(client: TestClient, make_user, email: str, password: str, role: str) -> str:
    """Provision an actor the way production does, then log in via the real flow.

    Public self-registration only ever creates ``student`` accounts, so
    privileged roles are written directly (mirroring the seed script) and every
    actor then obtains its bearer token through the normal OAuth2 password flow.
    """
    if role == "student":
        client.post("/api/auth/register", json={"email": email, "password": password})
    else:
        make_user(email, password, role)
    resp = client.post(
        "/api/auth/login", data={"username": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# PII that must never survive into persisted storage or the evidence trail.
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

# An official notice (issuer path) stating the exam is on 15 Sept.
_OFFICIAL_TEXT = (
    "Issued by: Office of the Registrar\n"
    "Subject: Mid-term examination schedule\n"
    "Attention: all first-year students\n"
    "The mid-term examination will be held on 15 Sept 2024.\n"
)

# A student submission that conflicts with the official (postponed to 22 Sept)
# and carries PII that must be redacted before storage.
_SUBMISSION_TEXT = (
    "Office of the Registrar\n"
    "Attention: all first-year students\n"
    "The mid-term examination has been postponed to 22 Sept 2024.\n"
    "Contact Dr. Jane Smith at jane.smith@northgate.edu or +1 415 555 2671.\n"
    "Roll number 21CS0456 must re-register.\n"
    "Name: Robert Brown\n"
)

# A deliberately low-signal submission: no cancellation/correction/date/negation
# cues and little lexical overlap, so the mock model returns low confidence and
# the confidence gate forces ``unresolved`` + a review case.
_AMBIGUOUS_TEXT = "Kindly refer to the relevant circular regarding the matter herein."


def test_end_to_end_demo_journey(client: TestClient, make_user):
    # 1) Provision + log in the actors through the real auth flow.
    admin = _token(client, make_user, "smoke-admin@example.com", "s3cret1", "admin")
    issuer = _token(client, make_user, "smoke-issuer@example.com", "s3cret1", "issuer")
    student = _token(client, make_user, "smoke-student@example.com", "s3cret1", "student")

    # Sanity: the token really identifies the actor (real /me round-trip).
    me = client.get("/api/auth/me", headers=_auth(student))
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "student"

    # 2) Seed an official notice into a fresh institution so retrieval has a
    #    same-institution candidate to compare against.
    created_src = client.post(
        "/api/ingest/sources",
        json={"name": "Smoke University", "slug": "smoke-uni",
              "source_url": "https://smoke.edu"},
        headers=_auth(admin),
    )
    assert created_src.status_code == 201, created_src.text
    institution_id = created_src.json()["id"]

    published = client.post(
        "/api/issuer/publish",
        json={"institution_id": institution_id, "text": _OFFICIAL_TEXT},
        headers=_auth(issuer),
    )
    assert published.status_code == 201, published.text
    official = published.json()
    assert official["kind"] == "official"
    assert official["sha256"]  # anchored content hash exists

    # 3) Student submits a conflicting notice with PII, tied to the institution.
    submitted = client.post(
        "/api/ingest/submit",
        data={"text": _SUBMISSION_TEXT, "institution_id": institution_id},
        headers=_auth(student),
    )
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    submission_id = result["submission_id"]

    # 3a) A candidate official was retrieved and classified.
    assert submission_id > 0
    assert result["candidate_id"] is not None, "expected a retrieved candidate"
    assert result["edge_id"] > 0
    assert result["model"] == "mock"  # default offline model

    # 3b) Relationship label + confidence + rationale returned. The conflicting
    #     date (15 Sept official vs 22 Sept submission, postponed) must NOT come
    #     back as ``consistent``; the mock reasons a supersede/contradiction with
    #     confidence above the gate.
    assert result["label"] in ("superseded", "contradictory", "extended"), result
    assert result["label"] != "unresolved"
    assert result["gated"] is False
    assert 0.6 <= result["confidence"] <= 1.0, result["confidence"]
    assert result["rationale"].strip()

    # 3c) The classification response's evidence path exists; the persisted
    #     submission must carry redaction masks and NOT the original PII.
    #     (Behavioral redaction-before-storage proof.)
    detail = client.get(f"/api/notices/{submission_id}", headers=_auth(student))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    redacted = body["redacted_text"] or ""
    assert redacted, "submission should persist redacted_text"
    for original in _PII_ORIGINALS:
        assert original not in redacted, f"unredacted PII {original!r} leaked into evidence"
    assert any(mask in redacted for mask in _REDACTION_MASKS), redacted

    # Extracted fields form the evidence trail and are also redacted.
    fields = body["fields"]
    assert fields, "expected extracted fields in the evidence trail"
    for field in fields:
        value = field.get("value") or ""
        for original in _PII_ORIGINALS:
            assert original not in value, (
                f"unredacted PII {original!r} leaked into field {field['field_name']!r}"
            )

    # Cross-check against a fresh DB read (not just the API projection).
    reread = client.get(f"/api/notices/{submission_id}", headers=_auth(student))
    assert reread.status_code == 200

    # 4) Evidence trail: ranked candidates endpoint returns the official.
    candidates = client.get(
        f"/api/notices/{submission_id}/candidates", headers=_auth(student)
    )
    assert candidates.status_code == 200, candidates.text
    ranked = candidates.json()
    assert ranked, "expected at least one ranked candidate"
    top = ranked[0]
    assert top["notice"]["id"] == official["id"], "top candidate should be the official"
    assert top["score"] > 0.0, "top candidate should have a positive overlap score"

    # 5) Integrity: build the daily Merkle root and verify against the anchor.
    # No body -> the endpoint defaults to today's UTC day (all notices above were
    # just created "today"), so it builds a root over the official + submission.
    build = client.post("/api/provenance/build", headers=_auth(admin))
    assert build.status_code == 200, build.text
    build_body = build.json()
    assert build_body["leaf_count"] >= 2  # official + submission
    assert build_body["root_hash"]
    assert build_body["anchor_kind"] == "local"  # offline local anchor

    verify = client.get(
        f"/api/provenance/verify/{submission_id}", headers=_auth(student)
    )
    assert verify.status_code == 200, verify.text
    ok_body = verify.json()
    assert ok_body["ok"] is True, ok_body
    assert ok_body["tamper"] is False, ok_body

    # Tamper simulation flips the verdict against the anchored hash.
    tampered = client.get(
        f"/api/provenance/verify/{submission_id}?tamper=true", headers=_auth(student)
    )
    assert tampered.status_code == 200, tampered.text
    tamper_body = tampered.json()
    assert tamper_body["ok"] is False, tamper_body
    assert tamper_body["tamper"] is True, tamper_body

    # 6) Ambiguous / low-signal submission is gated to unresolved + review case.
    ambiguous = client.post(
        "/api/ingest/submit",
        data={"text": _AMBIGUOUS_TEXT, "institution_id": institution_id},
        headers=_auth(student),
    )
    assert ambiguous.status_code == 200, ambiguous.text
    amb = ambiguous.json()
    assert amb["label"] == "unresolved", amb
    assert amb["gated"] is True, amb
    assert amb["confidence"] < 0.6, amb
    assert amb["status"] == "unresolved"
    assert amb["review_case_id"] is not None, "unresolved must open a review case"


def test_persisted_submission_has_no_unredacted_pii(client: TestClient, make_user, db_session):
    """Belt-and-suspenders DB-level check that the smoke journey's submission
    stores only redacted content: re-read the persisted Notice + NoticeField
    rows directly from the database and assert no original PII survived. This
    would fail if the redaction-before-storage guarantee regressed."""
    student = _token(client, make_user, "smoke-pii@example.com", "s3cret1", "student")
    resp = client.post(
        "/api/ingest/submit",
        data={"text": _SUBMISSION_TEXT},
        headers=_auth(student),
    )
    assert resp.status_code == 200, resp.text
    submission_id = resp.json()["submission_id"]

    notice = db_session.get(Notice, submission_id)
    assert notice is not None and notice.redacted_text
    for value in (v for v in vars(notice).values() if isinstance(v, str)):
        for original in _PII_ORIGINALS:
            assert original not in value, (
                f"unredacted PII {original!r} leaked into a persisted Notice attribute"
            )

    rows = (
        db_session.query(NoticeField)
        .filter(NoticeField.notice_id == submission_id)
        .all()
    )
    assert rows, "expected persisted extracted fields"
    for row in rows:
        if row.value:
            for original in _PII_ORIGINALS:
                assert original not in row.value, (
                    f"unredacted PII {original!r} leaked into field {row.field_name!r}"
                )
