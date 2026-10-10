"""Complaints: routing by department, duplicates and priority, promised dates and escalation, the resident's
timeline, confirm/reopen, public feed privacy, optional Google sign-in, and registering streets."""
import os
import re
import sqlite3
import time

import pytest

import complaints
import google

BASE = (13.088, 80.279)           # a point; ~111 m per 0.001 degree of latitude
NEAR = (13.089, 80.279)           # ~111 m away: the same problem
FAR = (13.091, 80.279)            # ~333 m away: a different problem
LONG = "Street light is out and the cable is hanging low near the bus stop."


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(complaints, "COMPLAINT_LIMIT", 10000)


def report(api, category="ELECTRICAL", at=BASE, key=None, token=None, **extra):
    body = {"category": category, "description": extra.pop("description", LONG)}
    if at:
        body["lat"], body["lng"] = at
    body.update(extra)
    headers = {"Idempotency-Key": key or "rep-%d-%s" % (api.n, time.time_ns())}
    api.n += 1
    if token:
        headers["Authorization"] = "Bearer " + token
    return api.c.post("/api/v1/complaints", json=body, headers=headers)


def track(api, out, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    return api.c.post("/api/v1/complaints/track", json={"reference": out["id"], "code": out["tracking_code"]}, headers=headers)


def inbox(api, user, **params):
    r = api.get("/complaints", user, params=params or None)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def update(api, user, item, status, **extra):
    return api.post("/complaints/%s/status" % item["id"], user, dict({"expected_version": item["version"], "status": status}, **extra))


def messages(view):
    return [e["message"] for e in view["timeline"]]


# ------------------------------------------------------- reporting + timeline
def test_anyone_can_report_without_an_account_and_gets_a_routed_receipt(api):
    r = report(api, contact_name="A. Resident", contact_detail="resident@example.com")
    assert r.status_code == 201
    out = r.json()
    assert re.fullmatch(r"CMP-2026-\d{4}", out["id"]) and re.fullmatch(r"[0-9A-F]{10}", out["tracking_code"])
    assert out["department_name"] == "Power Department" and out["other_reports"] == 0 and out["priority"] == "NORMAL"
    view = track(api, out).json()
    assert view["status"] == "NEW" and view["department_name"] == "Power Department"
    assert messages(view) == ["We received your report.", "Sent to the Power Department."]
    assert "description" not in view and "contact" not in str(view).lower() and "lat" not in view


def test_unroutable_categories_wait_for_the_coordinator(api):
    out = report(api, "NOISE_DUST").json()
    assert out["department_name"] is None
    assert "coordinator" in messages(track(api, out).json())[1]


def test_tracking_needs_both_reference_and_code_and_is_throttled(api):
    out = report(api).json()
    assert api.c.post("/api/v1/complaints/track", json={"reference": out["id"], "code": "0000000000"}).status_code == 404
    assert api.c.post("/api/v1/complaints/track", json={"reference": "CMP-2026-9999", "code": out["tracking_code"]}).status_code == 404
    assert api.c.post("/api/v1/complaints/track", json={"reference": out["id"].lower(), "code": out["tracking_code"].lower()}).status_code == 200
    codes = [api.c.post("/api/v1/complaints/track", json={"reference": out["id"], "code": "%010X" % i}).status_code for i in range(16)]
    assert codes[-1] == 429


def test_validation_and_location_privacy(api, db_path):
    assert report(api, description="short").status_code == 422
    assert report(api, category="NOPE").status_code == 422
    assert report(api, road_id="road-nowhere").status_code == 422
    assert report(api, at=None, lat=13.0).status_code == 422
    assert report(api, lat=123.0, lng=80.0, at=None).status_code == 422
    assert report(api, at=(13.08789, 80.27851)).status_code == 201
    conn = sqlite3.connect(db_path)
    lat, lng, key = conn.execute("SELECT lat, lng, client_key FROM complaints").fetchone()
    conn.close()
    assert (lat, lng) == (13.088, 80.279) and "testclient" not in key and len(key) == 24


def test_rate_limit_and_idempotent_submission(api, monkeypatch):
    a = report(api, key="same"); b = report(api, key="same")
    assert a.json() == b.json() and b.headers["idempotent-replay"] == "true"
    monkeypatch.setattr(complaints, "COMPLAINT_LIMIT", 3)
    assert report(api).status_code == 201 and report(api).status_code == 201
    r = report(api)
    assert r.status_code == 429 and r.json()["error"]["code"] == "TOO_MANY_COMPLAINTS"


# --------------------------------------------- only the right department sees it
def test_an_electrical_problem_is_visible_only_to_power_and_the_coordinator(api):
    out = report(api, "ELECTRICAL").json()
    assert [i["category"] for i in inbox(api, "u-power")] == ["ELECTRICAL"]
    assert [i["category"] for i in inbox(api, "u-power-head")] == ["ELECTRICAL"]
    assert [i["category"] for i in inbox(api, "u-admin")] == ["ELECTRICAL"]
    for other in ("u-water", "u-telecom", "u-roads"):
        assert inbox(api, other) == []
        item = inbox(api, "u-admin")[0]
        r = update(api, other, item, "ACKNOWLEDGED")
        assert r.status_code == 404                                   # they cannot even tell it exists
    assert api.get("/complaints", "u-aqua").status_code == 403         # contractors
    assert api.get("/complaints", "u-inspector").status_code == 403    # inspectors
    assert api.get("/complaints").status_code == 401                   # the public
    assert track(api, out).status_code == 200


def test_each_category_goes_to_its_own_department(api):
    for cat, dept in (("WATER", "u-water"), ("TELECOM", "u-telecom"), ("ROAD_DAMAGE", "u-roads"), ("ELECTRICAL", "u-power")):
        report(api, cat, at=None, road_id=None)
    for user, cat in (("u-water", "WATER"), ("u-telecom", "TELECOM"), ("u-roads", "ROAD_DAMAGE"), ("u-power", "ELECTRICAL")):
        assert [i["category"] for i in inbox(api, user)] == [cat], user
    assert len(inbox(api, "u-admin")) == 4


def test_coordinator_assigns_unrouted_complaints(api):
    report(api, "SAFETY_HAZARD")
    assert inbox(api, "u-roads") == [] and len(inbox(api, "u-admin")) == 1
    item = inbox(api, "u-admin")[0]
    assert item["department_id"] is None and "ASSIGN_COMPLAINT" in item["allowed_actions"]
    assert api.post("/complaints/%s/assign" % item["id"], "u-roads", {"expected_version": item["version"], "department_id": "roads"}).status_code == 403
    assert api.post("/complaints/%s/assign" % item["id"], "u-admin", {"expected_version": item["version"], "department_id": "con-aqua"}).status_code == 422
    r = api.post("/complaints/%s/assign" % item["id"], "u-admin", {"expected_version": item["version"], "department_id": "roads"})
    assert r.status_code == 200
    assert len(inbox(api, "u-roads")) == 1 and inbox(api, "u-water") == []


# ----------------------------------------------------- duplicates and priority
def test_repeat_reports_of_the_same_problem_raise_priority_and_group_together(api):
    first = report(api, at=BASE).json()
    assert inbox(api, "u-power")[0]["priority"] == "NORMAL"
    second = report(api, at=NEAR).json()
    assert second["other_reports"] == 1 and second["priority"] == "HIGH"
    item = inbox(api, "u-power")[0]
    assert len(inbox(api, "u-power")) == 1 and item["report_count"] == 2 and item["priority"] == "HIGH"
    assert "2 people reported the same problem" in item["priority_reason"]
    # the first reporter is told that more people reported it
    assert any("More people reported this same problem, so it now has high priority." == m for m in messages(track(api, first).json()))
    assert any("grouped with theirs" in m for m in messages(track(api, second).json()))
    report(api, at=BASE); report(api, at=NEAR)
    item = inbox(api, "u-power")[0]
    assert item["report_count"] == 4 and item["priority"] == "URGENT"


def test_different_category_or_far_away_is_a_different_problem(api):
    report(api, "ELECTRICAL", at=BASE)
    report(api, "ELECTRICAL", at=FAR)
    report(api, "WATER", at=BASE)
    assert len(inbox(api, "u-power")) == 2 and len(inbox(api, "u-water")) == 1
    assert all(i["priority"] == "NORMAL" for i in inbox(api, "u-power"))


def test_reports_without_a_position_group_by_street_and_urgent_problems_come_first(api):
    report(api, "WATER", at=None, road_id="road-market")
    report(api, "WATER", at=None, road_id="road-market")
    report(api, "WATER", at=FAR)                      # a separate, single report
    items = inbox(api, "u-water")
    assert [i["report_count"] for i in items] == [2, 1] and [i["priority"] for i in items] == ["HIGH", "NORMAL"]
    safety = report(api, "SAFETY_HAZARD", at=None).json()
    hazard = next(i for i in inbox(api, "u-admin") if i["category"] == "SAFETY_HAZARD")
    assert hazard["priority"] == "HIGH" and "safety hazard" in hazard["priority_reason"].lower()
    assert track(api, safety).json()["priority"] == "HIGH"


def test_the_priority_filter_and_status_filter_work(api):
    report(api, at=BASE); report(api, at=NEAR); report(api, "ELECTRICAL", at=FAR)
    assert len(inbox(api, "u-power", priority="HIGH")) == 1 and len(inbox(api, "u-power", priority="NORMAL")) == 1
    assert len(inbox(api, "u-power", status="NEW")) == 2 and inbox(api, "u-power", status="RESOLVED") == []


# ------------------------------------------ promises, resolution, resident action
def test_a_department_must_promise_a_time_and_everyone_in_the_group_is_told(api):
    a = report(api, at=BASE).json(); b = report(api, at=NEAR).json()
    item = inbox(api, "u-power")[0]
    r = update(api, "u-power", item, "IN_PROGRESS")
    assert r.status_code == 422 and r.json()["error"]["failures"][0]["field"] == "resolve_in_days"
    assert update(api, "u-power", item, "IN_PROGRESS", resolve_in_days=999).status_code == 422
    assert update(api, "u-power", item, "IN_PROGRESS", resolve_in_days=5, note="A crew is booked.").status_code == 200
    for out in (a, b):
        view = track(api, out).json()
        assert view["status"] == "IN_PROGRESS" and view["committed_days"] == 5 and view["promised_by"] == "2026-11-13"
        assert any("will resolve this within 5 days, by 13 Nov 2026" in m for m in messages(view))
    # a later duplicate joins a problem that is already being worked on and sees the promise
    c = report(api, at=BASE).json()
    view = track(api, c).json()
    assert view["status"] == "IN_PROGRESS" and view["promised_by"] == "2026-11-13"
    assert any("will resolve this within" in m for m in messages(view))


def test_resolving_requires_a_message_and_the_resident_can_confirm_or_reopen(api):
    out = report(api).json()
    item = inbox(api, "u-power")[0]
    r = update(api, "u-power", item, "RESOLVED")
    assert r.status_code == 422 and r.json()["error"]["failures"][0]["field"] == "note"
    assert update(api, "u-power", item, "RESOLVED", note="The cable was replaced.").status_code == 200
    view = track(api, out).json()
    assert view["status"] == "RESOLVED" and view["can_respond"] is True and view["public_note"] == "The cable was replaced."
    assert update(api, "u-power", inbox(api, "u-power", status="RESOLVED")[0], "ACKNOWLEDGED").status_code == 409   # staff cannot undo it
    # a wrong code is refused (and counts towards throttling)
    bad = api.c.post("/api/v1/complaints/respond", json={"reference": out["id"], "action": "CONFIRM_FIXED", "code": "0000000000"})
    assert bad.status_code == 404
    ok = api.c.post("/api/v1/complaints/respond", json={"reference": out["id"], "action": "CONFIRM_FIXED", "code": out["tracking_code"]})
    assert ok.status_code == 200 and ok.json()["status"] == "CONFIRMED_FIXED"
    assert track(api, out).json()["status_text"] == "Confirmed fixed"
    again = api.c.post("/api/v1/complaints/respond", json={"reference": out["id"], "action": "REOPEN", "code": out["tracking_code"]})
    assert again.status_code == 409


def test_reopening_returns_it_to_the_department_with_higher_priority(api):
    a = report(api, at=BASE).json(); b = report(api, at=NEAR).json()
    item = inbox(api, "u-power")[0]
    update(api, "u-power", item, "IN_PROGRESS", resolve_in_days=3)
    update(api, "u-power", inbox(api, "u-power")[0], "RESOLVED", note="Replaced.")
    r = api.c.post("/api/v1/complaints/respond", json={"reference": a["id"], "action": "REOPEN", "code": a["tracking_code"], "note": "Still dark."})
    assert r.status_code == 200 and r.json()["status"] == "REOPENED"
    item = inbox(api, "u-power")[0]
    assert item["status"] == "REOPENED" and item["priority"] in ("HIGH", "URGENT") and item["due_on"] is None
    assert "reopened" in item["priority_reason"].lower()
    for out in (a, b):                                                 # everyone in the group is told
        assert track(api, out).json()["status"] == "REOPENED"
    assert any("not fixed" in m for m in messages(track(api, b).json()))


# ------------------------------------------------------------ escalation
def test_missing_the_promised_date_escalates_to_the_head_with_high_priority(api):
    out = report(api).json()
    update(api, "u-power", inbox(api, "u-power")[0], "IN_PROGRESS", resolve_in_days=5)
    api.advance(5)                                                     # 13 Nov: due today, not yet late
    assert inbox(api, "u-power")[0]["escalation_level"] == 0 and inbox(api, "u-power")[0]["days_left"] == 0
    api.advance(1)                                                     # 14 Nov: missed
    item = inbox(api, "u-power")[0]
    assert item["escalation_level"] == 1 and item["priority"] == "HIGH" and item["overdue"] is True
    assert item["escalation_text"] == "With the head of the Power Department"
    view = track(api, out).json()
    assert view["priority"] == "HIGH" and view["escalation_text"] == "With the head of the Power Department"
    assert any("escalated to the head of the Power Department" in m and "high priority" in m for m in messages(view))
    # ordinary staff may no longer act on it; the head and the coordinator can
    assert update(api, "u-power", item, "RESOLVED", note="Done.").status_code == 403
    assert update(api, "u-power-head", item, "RESOLVED", note="Fixed by the head's crew.").status_code == 200
    assert track(api, out).json()["status"] == "RESOLVED"


def test_a_complaint_resolved_in_time_is_never_escalated(api):
    out = report(api).json()
    update(api, "u-power", inbox(api, "u-power")[0], "IN_PROGRESS", resolve_in_days=5)
    update(api, "u-power", inbox(api, "u-power")[0], "RESOLVED", note="Replaced early.")
    api.advance(30)
    view = track(api, out).json()
    assert view["status"] == "RESOLVED" and view["escalation_text"] is None
    assert not any("escalated" in m for m in messages(view))


def test_the_head_can_set_a_new_promise_and_missing_it_goes_to_the_coordinator(api):
    out = report(api).json()
    update(api, "u-power", inbox(api, "u-power")[0], "IN_PROGRESS", resolve_in_days=2)
    api.advance(3)
    item = inbox(api, "u-power-head")[0]
    assert item["escalation_level"] == 1
    # ordinary staff cannot re-promise; the head can
    assert update(api, "u-power", item, "IN_PROGRESS", resolve_in_days=2).status_code in (403, 409)
    assert update(api, "u-power-head", item, "IN_PROGRESS", resolve_in_days=2).status_code == 200
    api.advance(2)                                                     # the head's promise is due, not late
    assert inbox(api, "u-power-head")[0]["escalation_level"] == 1
    api.advance(1)                                                     # and now it is missed
    item = inbox(api, "u-admin")[0]
    assert item["escalation_level"] == 2 and item["priority"] == "URGENT" and item["escalation_text"] == "With the coordinator"
    assert any("escalated to the coordinator and marked urgent" in m for m in messages(track(api, out).json()))


def test_a_head_who_does_nothing_for_two_days_hands_it_to_the_coordinator(api):
    report(api)
    update(api, "u-power", inbox(api, "u-power")[0], "IN_PROGRESS", resolve_in_days=1)
    api.advance(2)                                                     # missed: level 1
    assert inbox(api, "u-admin")[0]["escalation_level"] == 1
    api.advance(2)                                                     # still inside the head's grace period
    assert inbox(api, "u-admin")[0]["escalation_level"] == 1
    api.advance(1)
    item = inbox(api, "u-admin")[0]
    assert item["escalation_level"] == 2 and item["priority"] == "URGENT"


def test_escalation_also_runs_when_the_command_is_not_the_clock(api, db_path):
    report(api)
    update(api, "u-power", inbox(api, "u-power")[0], "IN_PROGRESS", resolve_in_days=1)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE demo_clock SET date = '2026-12-01'"); conn.commit(); conn.close()
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT escalation_level FROM complaints").fetchone()[0] == 0     # a plain read changes nothing
    conn.close()
    inbox(api, "u-water")
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT escalation_level FROM complaints").fetchone()[0] == 0
    conn.close()
    assert api.post("/roads", "u-water", {"name": "Any Lane", "lat": 1.0, "lng": 1.0}).status_code == 201   # any command
    conn = sqlite3.connect(db_path)
    level = conn.execute("SELECT escalation_level FROM complaints").fetchone()[0]
    conn.close()
    assert level == 1                                                  # its command-time check escalated the missed promise


# ------------------------------------------------------------- public feed
def test_the_public_feed_shows_problems_but_no_personal_details(api):
    out = report(api, contact_name="Ravi K", contact_detail="ravi@example.com", location_text="Flat 4B, Rose Apartments").json()
    report(api, at=NEAR)
    r = api.c.get("/api/v1/complaints/public")
    assert r.status_code == 200
    text = r.text
    for secret in ("Ravi", "ravi@example.com", "Rose Apartments", out["id"], out["tracking_code"], LONG, "description"):
        assert secret not in text, secret
    item = r.json()["items"][0]
    assert item["report_count"] == 2 and item["priority"] == "HIGH" and item["category_label"].startswith("Electrical")
    assert item["lat"] == 13.088 and item["status_text"] == "Received" and item["fixed"] is False
    assert len(item["id"]) == 12
    # closed-without-action reports are not shown at all
    update(api, "u-admin", inbox(api, "u-admin")[0], "REJECTED", note="Not a municipal matter.")
    assert api.c.get("/api/v1/complaints/public").json()["items"] == []


def test_the_public_feed_marks_fixed_problems(api):
    out = report(api).json()
    update(api, "u-power", inbox(api, "u-power")[0], "RESOLVED", note="Replaced.")
    item = api.c.get("/api/v1/complaints/public").json()["items"][0]
    assert item["fixed"] is True and item["status_text"].startswith("Marked resolved")


# ------------------------------------------------------ streets and the sample
def test_staff_register_streets_and_the_same_place_is_reused(api):
    body = {"name": "Garden Lane", "lat": 13.2, "lng": 80.3}
    r = api.post("/roads", "u-water", body)
    assert r.status_code == 201 and r.json()["created"] is True and r.json()["id"].startswith("road-garden-lane")
    again = api.post("/roads", "u-roads", dict(body, lat=13.2005))
    assert again.json()["created"] is False and again.json()["id"] == r.json()["id"]
    assert api.post("/roads", "u-water", dict(body, lat=13.3)).json()["created"] is True      # same name, far away
    assert api.post("/roads", "u-aqua", body).status_code == 403 and api.post("/roads", "u-inspector", body).status_code == 403
    assert api.c.post("/api/v1/roads", json=body, headers={"Idempotency-Key": "x"}).status_code == 401
    conn = sqlite3.connect(os.environ["WORKSYNC_DB"])
    depts = [x[0] for x in conn.execute("SELECT org_id FROM road_expected_depts WHERE road_id = ? ORDER BY org_id", (r.json()["id"],))]
    conn.close()
    assert depts == ["power", "telecom", "water"]
    # and work can then be registered there
    p = api.post("/projects", "u-water", {"title": "Pipe", "purpose": "Renew", "road_id": r.json()["id"], "kind": "UTILITY",
                                          "assigned_contractor_id": "con-aqua", "earliest_start": "2026-11-09",
                                          "deadline": "2026-11-30", "duration_days": 3})
    assert p.status_code == 201


@pytest.fixture()
def empty_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import main, seed
    from tests.conftest import Api
    path = str(tmp_path / "empty.db")
    monkeypatch.setenv("WORKSYNC_DB", path)
    monkeypatch.setenv("WORKSYNC_PBKDF2_ROUNDS", "1000")
    seed.seed_database(path, reset=True)
    with TestClient(main.app) as c:
        yield Api(c)


def test_a_fresh_install_has_no_streets_works_or_complaints(empty_api):
    assert empty_api.c.get("/api/v1/roads").json()["items"] == []
    assert empty_api.c.get("/api/v1/complaints/public").json()["items"] == []
    assert empty_api.get("/projects", "u-admin").json()["items"] == []
    boot = empty_api.get("/bootstrap").json()
    assert boot["roads"] == [] and len(boot["complaint_categories"]) == 9
    assert {c["id"]: c["department_name"] for c in boot["complaint_categories"]}["ELECTRICAL"] == "Power Department"


def test_the_sample_scenario_is_admin_only_opt_in_and_once(empty_api):
    body = {"lat": 28.6139, "lng": 77.2090}
    assert empty_api.post("/demo/scenario", "u-water", body).status_code == 403
    assert empty_api.c.post("/api/v1/demo/scenario", json=body, headers={"Idempotency-Key": "k"}).status_code == 401
    r = empty_api.post("/demo/scenario", "u-admin", body)
    assert r.status_code == 201 and "invented" in r.json()["message"]
    roads = empty_api.c.get("/api/v1/roads").json()["items"]
    assert {x["id"] for x in roads} == {"road-market", "road-temple", "road-station", "road-old-mill"}
    assert all(abs(x["lat"] - 28.6139) < 0.05 and abs(x["lng"] - 77.2090) < 0.05 for x in roads)   # built around that point
    assert empty_api.post("/demo/scenario", "u-admin", body).status_code == 409


def test_departments_heads_are_flagged_at_sign_in(api):
    r = api.c.post("/api/v1/auth/login", json={"username": "power.head", "password": "PowerHead@26"})
    assert r.status_code == 200 and r.json()["user"]["is_head"] is True and r.json()["user"]["org_id"] == "power"
    r = api.c.post("/api/v1/auth/login", json={"username": "power.dept", "password": "Power@Dept26"})
    assert r.json()["user"]["is_head"] is False


# --------------------------------------------------- optional Google sign-in
GOOD = {"aud": "client-123.apps.googleusercontent.com", "iss": "https://accounts.google.com", "sub": "g-1",
        "email": "ana@example.com", "email_verified": "true", "name": "Ana Resident", "exp": str(int(time.time()) + 600)}


@pytest.fixture()
def google_on(monkeypatch):
    monkeypatch.setenv("WORKSYNC_GOOGLE_CLIENT_ID", GOOD["aud"])
    box = {"info": dict(GOOD)}
    monkeypatch.setattr(google, "fetch_tokeninfo", lambda credential: box["info"])
    return box


def google_login(api, sub="g-1"):
    r = api.c.post("/api/v1/auth/google", json={"credential": "x" * 40})
    return r


def test_google_sign_in_is_off_until_configured(api, monkeypatch):
    monkeypatch.delenv("WORKSYNC_GOOGLE_CLIENT_ID", raising=False)
    r = api.c.post("/api/v1/auth/google", json={"credential": "x" * 40})
    assert r.status_code == 503 and r.json()["error"]["code"] == "GOOGLE_NOT_CONFIGURED"
    assert api.get("/bootstrap").json()["google_client_id"] is None


def test_google_sign_in_rejects_tokens_not_issued_to_us(api, google_on):
    assert api.get("/bootstrap").json()["google_client_id"] == GOOD["aud"]
    for change in ({"aud": "someone-else"}, {"iss": "https://evil.example"}, {"exp": "1"}, {"email_verified": "false"}, {"sub": ""}):
        google_on["info"] = dict(GOOD, **change)
        assert google_login(api).status_code == 401, change
    google_on["info"] = dict(GOOD)
    assert google_login(api).status_code == 200


def test_resident_sessions_are_separate_from_staff_sessions(api, google_on):
    r = google_login(api)
    out = r.json()
    assert out["resident"]["email"] == "ana@example.com" and "token" in out
    h = {"Authorization": "Bearer " + out["token"]}
    assert api.c.get("/api/v1/auth/resident/me", headers=h).status_code == 200
    # a resident token opens no staff door at all
    for path in ("/projects", "/cases", "/complaints", "/auth/me", "/cases/case-market"):
        assert api.c.get("/api/v1" + path, headers=h).status_code == 401, path
    assert api.c.post("/api/v1/roads", json={"name": "X road", "lat": 1, "lng": 1}, headers=dict(h, **{"Idempotency-Key": "k"})).status_code == 401
    # and a staff token is not a resident
    assert api.c.get("/api/v1/me/complaints", headers={"Authorization": "Bearer " + api.token("u-admin")}).status_code == 401
    assert api.c.get("/api/v1/me/complaints").status_code == 401
    assert api.c.post("/api/v1/auth/resident/logout", headers=h).status_code == 200
    assert api.c.get("/api/v1/auth/resident/me", headers=h).status_code == 401


def test_a_signed_in_resident_sees_only_their_own_reports_and_can_act_without_the_code(api, google_on):
    token = google_login(api).json()["token"]
    mine = report(api, token=token).json()
    guest = report(api, "WATER", at=FAR).json()
    items = api.c.get("/api/v1/me/complaints", headers={"Authorization": "Bearer " + token}).json()["items"]
    assert [i["reference"] for i in items] == [mine["id"]]
    assert items[0]["timeline"][0]["message"] == "We received your report."
    # tracking with the session needs no code; a guest's report is not theirs
    h = {"Authorization": "Bearer " + token}
    assert api.c.post("/api/v1/complaints/track", json={"reference": mine["id"], "code": "ZZZZZZZZZZ"}, headers=h).status_code == 200
    assert api.c.post("/api/v1/complaints/track", json={"reference": guest["id"], "code": "ZZZZZZZZZZ"}, headers=h).status_code == 404
    update(api, "u-power", inbox(api, "u-power")[0], "RESOLVED", note="Replaced.")
    r = api.c.post("/api/v1/complaints/respond", json={"reference": mine["id"], "action": "CONFIRM_FIXED"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED_FIXED"
    # a different Google user cannot act on it
    google_on["info"] = dict(GOOD, sub="g-2", email="bob@example.com")
    other = google_login(api).json()["token"]
    assert api.c.get("/api/v1/me/complaints", headers={"Authorization": "Bearer " + other}).json()["items"] == []
    assert api.c.post("/api/v1/complaints/track", json={"reference": mine["id"], "code": "ZZZZZZZZZZ"},
                      headers={"Authorization": "Bearer " + other}).status_code == 404


def test_signing_in_twice_with_google_is_the_same_resident(api, google_on):
    a = google_login(api).json()["resident"]["id"]
    b = google_login(api).json()["resident"]["id"]
    assert a == b


def test_unreachable_google_falls_back_gracefully(api, monkeypatch):
    monkeypatch.setenv("WORKSYNC_GOOGLE_CLIENT_ID", "client")
    import urllib.error
    def boom(*a, **k): raise urllib.error.URLError("offline")
    monkeypatch.setattr(google.urllib.request, "urlopen", boom)
    r = api.c.post("/api/v1/auth/google", json={"credential": "x" * 40})
    assert r.status_code == 503 and r.json()["error"]["code"] == "GOOGLE_UNAVAILABLE"


# ----------------------------------------------- example problems in every case
def test_the_sample_scenario_includes_an_example_complaint_for_every_situation(empty_api):
    r = empty_api.post("/demo/scenario", "u-admin", {"lat": 28.6139, "lng": 77.2090})
    assert r.status_code == 201
    samples = r.json()["complaints"]
    assert len(samples) == 18 and all(s["case"] and re.fullmatch(r"[0-9A-F]{10}", s["code"]) for s in samples)

    items = empty_api.get("/complaints", "u-admin").json()["items"]
    assert len(items) == 21                                           # four electrical reports are one problem
    assert {i["status"] for i in items} == {"NEW", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CONFIRMED_FIXED", "REOPENED", "REJECTED"}
    assert {i["priority"] for i in items} == {"NORMAL", "HIGH", "URGENT"}
    assert {i["escalation_level"] for i in items} == {0, 1, 2}
    assert max(i["report_count"] for i in items) == 4
    assert any(i["department_id"] is None for i in items) and {i["department_id"] for i in items} >= {"water", "power", "telecom", "roads"}
    cats = {i["category"] for i in items}
    assert cats == set(complaints.CATEGORIES)                         # every category has an example
    on_track = [i for i in items if i["status"] == "IN_PROGRESS" and not i["overdue"]]
    assert on_track and on_track[0]["days_left"] == 5
    overdue = [i for i in items if i["escalation_level"] >= 1]
    assert {i["escalation_level"] for i in overdue} == {1, 2}

    # each department sees only its own examples; the unrouted ones are the coordinator's alone
    for user, dept in (("u-water", "water"), ("u-power", "power"), ("u-telecom", "telecom"), ("u-roads", "roads")):
        mine = empty_api.get("/complaints", user).json()["items"]
        assert mine and all(i["department_id"] == dept for i in mine), user
    # the heads see the escalated ones; the unrouted ones are the coordinator's alone
    assert any(i["escalation_level"] == 1 for i in empty_api.get("/complaints", "u-water-head").json()["items"])

    # the returned codes really work, and the resolved example can be confirmed by its "resident"
    resolved = next(s for s in samples if s["case"].startswith("Marked resolved"))
    view = empty_api.c.post("/api/v1/complaints/track", json={"reference": resolved["reference"], "code": resolved["code"]}).json()
    assert view["status"] == "RESOLVED" and view["can_respond"] is True
    ok = empty_api.c.post("/api/v1/complaints/respond", json={"reference": resolved["reference"], "code": resolved["code"], "action": "CONFIRM_FIXED"})
    assert ok.status_code == 200
    reopened = next(s for s in samples if s["case"].startswith("Reopened"))
    v = empty_api.c.post("/api/v1/complaints/track", json={"reference": reopened["reference"], "code": reopened["code"]}).json()
    assert v["status"] == "REOPENED" and any("not fixed" in e["message"] for e in v["timeline"])
    escalated = next(s for s in samples if s["case"].startswith("Promise missed"))
    v = empty_api.c.post("/api/v1/complaints/track", json={"reference": escalated["reference"], "code": escalated["code"]}).json()
    assert v["escalation_text"] == "With the head of the Water Department" and v["priority"] == "HIGH"

    # and the public feed shows them without a single personal detail
    feed = empty_api.c.get("/api/v1/complaints/public").json()["items"]
    assert len(feed) == 20 and any(f["fixed"] for f in feed)          # the rejected one is not shown
    assert "tracking" not in str(feed).lower() and "CMP-" not in str(feed)


def test_every_category_offers_examples_the_report_form_can_use(api):
    cats = api.get("/bootstrap").json()["complaint_categories"]
    assert {c["id"] for c in cats} == set(complaints.CATEGORIES)
    for c in cats:
        assert c["examples"] and all(len(e) >= 10 for e in c["examples"]), c["id"]       # each is long enough to submit as is
    # an example can be submitted exactly as written
    for c in cats:
        r = report(api, c["id"], at=None, description=c["examples"][0])
        assert r.status_code == 201, (c["id"], r.text)
