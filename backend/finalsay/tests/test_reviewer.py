"""Reviewer tests: resolve updates edge + closes case; queue lists unresolved
cases; Cohen's kappa matches a hand-computed value; benchmark annotate flow."""

from __future__ import annotations

from fastapi.testclient import TestClient

from finalsay.models import Notice, RelationEdge, ReviewCase
from finalsay.services import comparison
from finalsay.services.kappa import cohen_kappa


def _token(client, make_user, email, password, role):
    # Public register only creates students; privileged roles are provisioned
    # directly (as the seed does), then authenticated via the normal flow.
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


# --- Cohen's kappa math -------------------------------------------------------

def test_kappa_hand_computed_value():
    """Hand-computed example.

    A = [yes, yes, no, no, yes], B = [yes, no, no, no, yes].
    observed agreement p_o = 4/5 = 0.8.
    marginals: A(yes)=3/5, A(no)=2/5; B(yes)=2/5, B(no)=3/5.
    p_e = (0.6*0.4) + (0.4*0.6) = 0.24 + 0.24 = 0.48.
    kappa = (0.8 - 0.48) / (1 - 0.48) = 0.32 / 0.52 = 0.6153846...
    """
    a = ["yes", "yes", "no", "no", "yes"]
    b = ["yes", "no", "no", "no", "yes"]
    assert abs(cohen_kappa(a, b) - 0.6153846153846154) < 0.001


def test_kappa_perfect_agreement():
    a = ["consistent", "superseded", "cancelled"]
    assert abs(cohen_kappa(a, a) - 1.0) < 1e-9


# --- Reviewer resolve ---------------------------------------------------------

def _make_unresolved_case(db):
    """Create a submission that gates to unresolved (no candidate -> unresolved)."""
    submission = Notice(
        kind="submission",
        institution_id=999,
        redacted_text="An ambiguous circular with unclear details.",
    )
    db.add(submission)
    db.flush()
    outcome = comparison.classify_submission(db, submission)
    db.commit()
    assert outcome.review_case is not None
    return outcome.review_case, outcome.edge


def test_resolve_updates_edge_and_closes_case(client: TestClient, db_session, make_user):
    case, edge = _make_unresolved_case(db_session)

    reviewer = _token(client, make_user, "rev1@example.com", "s3cret1", "reviewer")
    resp = client.post(
        f"/api/reviewer/cases/{case.id}/resolve",
        json={"label": "superseded"},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "superseded"
    assert body["edge_status"] == "corrected"  # changed from unresolved
    assert body["case_status"] == "closed"

    db_session.expire_all()
    refreshed_edge = db_session.get(RelationEdge, edge.id)
    refreshed_case = db_session.get(ReviewCase, case.id)
    assert refreshed_edge.label == "superseded"
    assert refreshed_edge.status == "corrected"
    assert refreshed_case.status == "closed"
    assert refreshed_case.resolved_label == "superseded"


def test_resolve_confirmed_when_label_unchanged(client: TestClient, db_session, make_user):
    case, edge = _make_unresolved_case(db_session)
    reviewer = _token(client, make_user, "rev2@example.com", "s3cret1", "reviewer")
    resp = client.post(
        f"/api/reviewer/cases/{case.id}/resolve",
        json={"label": "unresolved"},
        headers=_auth(reviewer),
    )
    assert resp.status_code == 200
    assert resp.json()["edge_status"] == "confirmed"


def test_queue_lists_open_cases(client: TestClient, db_session, make_user):
    _make_unresolved_case(db_session)
    reviewer = _token(client, make_user, "rev3@example.com", "s3cret1", "reviewer")
    resp = client.get("/api/reviewer/queue", headers=_auth(reviewer))
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) >= 1
    assert items[0]["status"] == "open"
    assert "submission" in items[0]


def test_queue_requires_reviewer_role(client: TestClient, make_user):
    student = _token(client, make_user, "stud7@example.com", "s3cret1", "student")
    resp = client.get("/api/reviewer/queue", headers=_auth(student))
    assert resp.status_code == 403


# --- Benchmark + kappa endpoint ----------------------------------------------

def test_benchmark_annotate_and_kappa(client: TestClient, db_session, make_user):
    # Build two benchmark pairs from two submissions and two officials.
    officials, subs = [], []
    for i in range(2):
        off = Notice(kind="official", institution_id=1, redacted_text=f"official {i}")
        sub = Notice(kind="submission", institution_id=1, redacted_text=f"submission {i}")
        db_session.add_all([off, sub])
        db_session.flush()
        officials.append(off)
        subs.append(sub)
    from finalsay.models import BenchmarkPair

    pairs = []
    for off, sub in zip(officials, subs):
        pair = BenchmarkPair(submission_id=sub.id, official_id=off.id)
        db_session.add(pair)
        db_session.flush()
        pairs.append(pair)
    db_session.commit()

    reviewer = _token(client, make_user, "rev4@example.com", "s3cret1", "reviewer")

    # Two annotators agree on both pairs -> kappa 1.0 (single class handled).
    for pair in pairs:
        for annotator in ("ann_a", "ann_b"):
            resp = client.post(
                "/api/reviewer/benchmark/annotate",
                json={"pair_id": pair.id, "annotator": annotator, "label": "consistent"},
                headers=_auth(reviewer),
            )
            assert resp.status_code == 200, resp.text

    listing = client.get("/api/reviewer/benchmark/pairs", headers=_auth(reviewer))
    assert listing.status_code == 200
    assert len(listing.json()) == 2

    kappa_resp = client.get("/api/reviewer/benchmark/kappa", headers=_auth(reviewer))
    assert kappa_resp.status_code == 200, kappa_resp.text
    body = kappa_resp.json()
    assert body["pairs_compared"] == 2
    assert body["kappa"] == 1.0
    assert set(body["annotators"]) == {"ann_a", "ann_b"}
