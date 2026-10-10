"""Sign-in, public/staff separation, public roads and complaints."""
import re
import sqlite3
from pathlib import Path

import seed


def api_db():
    import os
    return os.environ["WORKSYNC_DB"]


def login(api, username, password):
    return api.c.post("/api/v1/auth/login", json={"username": username, "password": password})


# --------------------------------------------------------------- sign-in
def test_valid_credentials_return_a_session_and_the_right_user(api):
    r = login(api, "water.dept", "Water@Dept26")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer" and len(body["token"]) > 30 and body["expires_at"].endswith("Z")
    assert body["user"]["role"] == "DEPARTMENT" and body["user"]["org_id"] == "water"
    assert "password" not in r.text and "hash" not in r.text.lower()
    me = api.c.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + body["token"]})
    assert me.status_code == 200 and me.json()["id"] == "u-water"


def test_wrong_password_unknown_user_and_case_are_all_refused_alike(api):
    wrong = login(api, "water.dept", "Water@Dept27")
    unknown = login(api, "nobody", "whatever")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()                                   # no hint which part was wrong
    assert wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert login(api, "water.dept", "water@dept26").status_code == 401       # password is case-sensitive
    assert login(api, "  WATER.DEPT ", "Water@Dept26").status_code == 200    # username is not


def test_repeated_failures_lock_that_username_for_a_while(api):
    for _ in range(5):
        assert login(api, "admin", "bad").status_code == 401
    locked = login(api, "admin", "Admin@Work26")                             # even the right password is refused now
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert login(api, "roads.dept", "Roads@Dept26").status_code == 200       # other accounts unaffected


def test_passwords_are_stored_hashed_never_in_plain_text(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT username, password_hash FROM users").fetchall()
    conn.close()
    plain = {u: p for u, p in seed.CREDENTIALS.values()}
    for username, stored in rows:
        assert stored.startswith("pbkdf2_sha256$") and plain[username] not in stored
    assert len({stored for _, stored in rows}) == len(rows)                  # salted: no two hashes alike


def test_demo_credentials_file_matches_the_seed(db_path):
    text = (Path(__file__).resolve().parent.parent / "DEMO_CREDENTIALS.md").read_text()
    for username, password in seed.CREDENTIALS.values():
        assert "`%s`" % username in text and "`%s`" % password in text


def test_logout_ends_the_session(api):
    token = api.token("u-water")
    h = {"Authorization": "Bearer " + token}
    assert api.c.get("/api/v1/projects", headers=h).status_code == 200
    assert api.c.post("/api/v1/auth/logout", headers=h).status_code == 200
    assert api.c.get("/api/v1/projects", headers=h).status_code == 401


def test_expired_session_is_refused(api, db_path):
    token = api.token("u-water")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE sessions SET expires_at = '2020-01-01T00:00:00Z'")
    conn.commit(); conn.close()
    assert api.c.get("/api/v1/projects", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_the_old_demo_header_no_longer_grants_anything(api):
    r = api.c.get("/api/v1/projects", headers={"X-Demo-User": "u-admin"})
    assert r.status_code == 401
    r = api.c.post("/api/v1/demo/clock/advance", json={"expected_version": 1, "days": 1},
                   headers={"X-Demo-User": "u-admin", "Idempotency-Key": "k"})
    assert r.status_code == 401


# ------------------------------------- the public cannot reach staff views
STAFF_GETS = ["/projects", "/cases", "/cases/case-market", "/cases/case-market/audit", "/projects/water-1/gate",
              "/complaints", "/auth/me"]
STAFF_POSTS = [("/projects", {}), ("/projects/water-1/start", {"expected_version": 1, "plan_version": 1}),
               ("/cases/case-market/approvals", {"expected_version": 1, "plan_version": 1, "decision": "APPROVE"}),
               ("/cases/case-market/responses", {"expected_version": 1, "plan_version": 1, "project_id": "water-1", "decision": "ACCEPT"}),
               ("/cases/case-market/review", {"expected_version": 1, "action": "KEEP_BLOCKED", "reason": "x"}),
               ("/projects/water-1/inspections", {"expected_version": 1, "kind": "UTILITY_RELEASE", "result": "PASS", "notes": "x"}),
               ("/roads/road-market/declarations", {"expected_version": 1, "mode": "NO_PLANNED_WORK", "covers_from": "2026-11-01", "covers_through": "2027-06-30", "valid_until": "2027-02-28"}),
               ("/demo/clock/advance", {"expected_version": 1, "days": 1}),
               ("/complaints/CMP-2026-0001/status", {"expected_version": 1, "status": "RESOLVED", "note": "x"}),
               ("/auth/logout", {})]


def test_every_staff_endpoint_refuses_anonymous_callers(api):
    for path in STAFF_GETS:
        r = api.c.get("/api/v1" + path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    for path, body in STAFF_POSTS:
        r = api.c.post("/api/v1" + path, json=body, headers={"Idempotency-Key": "anon-1"})
        assert r.status_code == 401, path
    r = api.c.patch("/api/v1/projects/water-1", json={"expected_version": 1, "duration_days": 9}, headers={"Idempotency-Key": "anon-2"})
    assert r.status_code == 401
    # nothing changed
    assert api.project("water-1")["duration_days"] == 5


def test_public_endpoints_work_without_signing_in_and_leak_no_staff_details(api):
    for path in ("/bootstrap", "/roads", "/complaints/public", "/roads/road-market/public", "/roads/road-temple/public", "/roads/road-station/public"):
        r = api.c.get("/api/v1" + path)
        assert r.status_code == 200, path
        text = r.text.lower()
        for secret in ("water.dept", "password", "token", "asha nair", "priya sharma", "u-admin", "inspector.nisha",
                       "contact_detail", "tracking_hash"):
            assert secret not in text, (path, secret)


def test_only_departments_and_the_coordinator_can_open_the_complaints_inbox(api):
    assert api.get("/complaints", "u-aqua").status_code == 403
    assert api.get("/complaints", "u-inspector").status_code == 403
    assert api.get("/complaints", "u-water").status_code == 200
    assert api.get("/complaints", "u-admin").status_code == 200


# ------------------------------------------------------------ public roads
def test_public_roads_list_has_coordinates_and_safe_summaries(api):
    items = api.c.get("/api/v1/roads").json()["items"]
    by_id = {r["id"]: r for r in items}
    assert set(by_id) == {"road-market", "road-temple", "road-station"}
    assert all(-90 <= r["lat"] <= 90 and -180 <= r["lng"] <= 180 for r in items)
    assert by_id["road-market"]["work_count"] == 3 and by_id["road-station"]["work_count"] == 0
    assert {w["title"] for w in by_id["road-market"]["works"]} >= {"Water main repair", "Final road surface"}
