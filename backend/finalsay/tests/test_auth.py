"""Auth flow tests: register -> login -> me, plus a require_role 403 path."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from finalsay.auth import require_role
from finalsay.db import get_db
from finalsay.main import create_app


def _register(client, email, password, role=None):
    """Register a public user. ``role`` is accepted for call-site readability but
    is intentionally ignored: public registration always yields a student. If a
    caller passes ``role`` it is still sent in the body to prove the server
    ignores it (self-assignment must not be possible)."""
    body = {"email": email, "password": password}
    if role is not None:
        body["role"] = role  # server must ignore this
    return client.post("/api/auth/register", json=body)


def _login(client, email, password):
    # OAuth2 password flow: form-encoded, username == email.
    return client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
    )


def test_health(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_login_me(client: TestClient):
    reg = _register(client, "student@example.com", "s3cret1", role="student")
    assert reg.status_code == 201, reg.text
    body = reg.json()
    assert body["email"] == "student@example.com"
    assert body["role"] == "student"

    login = _login(client, "student@example.com", "s3cret1")
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert token

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "student@example.com"


def test_duplicate_registration_conflicts(client: TestClient):
    assert _register(client, "dup@example.com", "s3cret1").status_code == 201
    assert _register(client, "dup@example.com", "s3cret1").status_code == 409


def test_login_wrong_password(client: TestClient):
    _register(client, "wrong@example.com", "s3cret1")
    resp = _login(client, "wrong@example.com", "nope")
    assert resp.status_code == 401


def test_me_requires_auth(client: TestClient):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_public_register_cannot_self_assign_privileged_role(client: TestClient):
    """A public registration that asks for a privileged role is downgraded to
    student, so the caller cannot reach role-protected routes (R7.1)."""
    for role in ("admin", "reviewer", "issuer"):
        email = f"claim-{role}@example.com"
        reg = _register(client, email, "s3cret1", role=role)
        assert reg.status_code == 201, reg.text
        assert reg.json()["role"] == "student", reg.text

        token = _login(client, email, "s3cret1").json()["access_token"]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["role"] == "student"

    # And the downgraded "admin" claimant is actually blocked from an admin route.
    admin_claim_token = _login(client, "claim-admin@example.com", "s3cret1").json()[
        "access_token"
    ]
    forbidden = client.post(
        "/api/ingest/fetch",
        headers={"Authorization": f"Bearer {admin_claim_token}"},
    )
    assert forbidden.status_code == 403, forbidden.text


def test_require_role_403_and_200(client: TestClient, make_user):
    """A student token is rejected (403) from an admin-only route but a
    seed-provisioned admin token is accepted (200)."""
    app: FastAPI = create_app()

    @app.get("/api/_test/admin-only")
    def admin_only(user=Depends(require_role("admin"))):
        return {"ok": True, "role": user.role}

    # Reuse the shared test DB session via the same override as the client fixture.
    from finalsay.db import SessionLocal

    def _override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db

    # Public register -> student; admin is provisioned directly (as the seed does).
    make_user("boss@example.com", "s3cret1", "admin")

    with TestClient(app) as tc:
        _register(tc, "stud@example.com", "s3cret1")

        student_token = _login(tc, "stud@example.com", "s3cret1").json()["access_token"]
        admin_token = _login(tc, "boss@example.com", "s3cret1").json()["access_token"]

        forbidden = tc.get(
            "/api/_test/admin-only",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert forbidden.status_code == 403, forbidden.text

        allowed = tc.get(
            "/api/_test/admin-only",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["role"] == "admin"

    app.dependency_overrides.clear()
