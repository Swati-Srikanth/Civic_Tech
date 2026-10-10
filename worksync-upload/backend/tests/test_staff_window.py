"""The staff window: overview, team oversight, staff assignment, history and search, per-project history, activity trail, CSV."""
import csv
import io
import os
import sqlite3
import time

import pytest

import complaints


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(complaints, "COMPLAINT_LIMIT", 10000)


@pytest.fixture()
def sample(tmp_path, monkeypatch):
    """A fresh install with the coordinator's sample works, example complaints and past records created."""
    from fastapi.testclient import TestClient
    import main, seed
    from tests.conftest import Api
    path = str(tmp_path / "staff.db")
    monkeypatch.setenv("WORKSYNC_DB", path)
    monkeypatch.setenv("WORKSYNC_PBKDF2_ROUNDS", "1000")
    seed.seed_database(path, reset=True)
    with TestClient(main.app) as c:
        api = Api(c)
        r = api.post("/demo/scenario", "u-admin", {"lat": 13.0617, "lng": 80.2693})
        assert r.status_code == 201, r.text
        api.samples = r.json()["complaints"]
        yield api


def items(api, user, **params):
    r = api.get("/complaints", user, params=params or None)
    assert r.status_code == 200, r.text
    return r.json()


def mine(api, user, out):
    """The inbox item holding the complaint a test has just filed."""
    return next(i for i in items(api, user)["items"] if out["id"] in i["references"])


def report(api, category="ELECTRICAL", lat=13.2, lng=80.5, text="A fresh fault that needs somebody to look at it today."):
    r = api.c.post("/api/v1/complaints", json={"category": category, "description": text, "lat": lat, "lng": lng},
                   headers={"Idempotency-Key": "w-%d-%d" % (api.n, time.time_ns())})
    api.n += 1
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ overview
def test_overview_is_for_departments_and_the_coordinator_only(sample):
    assert sample.c.get("/api/v1/overview").status_code == 401
    for u in ("u-aqua", "u-inspector"):
        assert sample.get("/overview", u).status_code == 403
    for u in ("u-water", "u-water-head", "u-admin"):
        assert sample.get("/overview", u).status_code == 200


def test_overview_numbers_describe_the_departments_own_work(sample):
    o = sample.get("/overview", "u-power").json()
    assert o["scope"]["department_id"] == "power" and o["scope"]["is_overseer"] is False
    c = o["complaints"]
    assert c["total"] == c["open"] + c["closed"] and c["open"] >= 2
    assert c["escalated"] >= 1 and c["urgent"] >= 1
    assert {x["category"] for x in c["by_category"]} == {"ELECTRICAL"}                     # Power never sees water or telecom
    assert o["recent_activity"] and all(a["actor_user_id"] == "u-power" for a in o["recent_activity"])      # staff see only their own actions
    head_feed = sample.get("/overview", "u-power-head").json()["recent_activity"]
    assert {a["actor_user_id"] for a in head_feed} - {"u-power-head"}                                         # a head sees the team's
    # the head sees the department's whole picture; the coordinator sees every department
    head = sample.get("/overview", "u-power-head").json()
    assert head["scope"]["is_overseer"] is True and head["complaints"]["total"] == c["total"]
    admin = sample.get("/overview", "u-admin").json()
    assert admin["scope"]["department_name"] == "All departments"
    assert admin["complaints"]["total"] > c["total"] and admin["complaints"]["unrouted"] == 5
    assert admin["complaints"]["avg_resolution_days"] is not None
    only = sample.get("/overview", "u-admin", params={"department_id": "water"}).json()
    assert only["scope"]["department_id"] == "water" and {x["category"] for x in only["complaints"]["by_category"]} == {"WATER"}
    # a department user cannot widen their own scope
    assert sample.get("/overview", "u-power", params={"department_id": "water"}).json()["scope"]["department_id"] == "power"


def test_overview_flags_what_needs_attention(sample):
    admin = sample.get("/overview", "u-admin").json()
    kinds = {a["kind"] for a in admin["needs_attention"]}
    assert "complaint" in kinds
    assert any("escalated" in a["reason"].lower() or "missed" in a["reason"].lower() for a in admin["needs_attention"])
    assert admin["projects"]["total"] >= 6 and admin["projects"]["done"] == 2 and admin["projects"]["cancelled"] == 1


# --------------------------------------------------------------------- team
def test_only_a_head_or_the_coordinator_can_see_the_team(sample):
    assert sample.get("/team", "u-water").status_code == 403
    assert sample.get("/team", "u-aqua").status_code == 403
    assert sample.c.get("/api/v1/team").status_code == 401
    team = sample.get("/team", "u-water-head").json()
    assert {m["id"] for m in team["items"]} == {"u-water", "u-water2", "u-water-head"}          # their own department only
    assert all(m["department_id"] == "water" for m in team["items"])
    everyone = sample.get("/team", "u-admin").json()["items"]
    assert len(everyone) == 12 and {m["department_id"] for m in everyone} == {"water", "telecom", "power", "roads"}


def test_the_head_sees_what_each_colleague_is_working_on(sample):
    members = {m["id"]: m for m in sample.get("/team", "u-water-head").json()["items"]}
    ravi = members["u-water2"]
    assert ravi["open_complaints"] >= 1 and ravi["resolved_total"] >= 1 and ravi["avg_resolution_days"] is not None
    assert ravi["completed_projects"] >= 1 and ravi["actions"] >= 1 and ravi["last_active"]
    detail = sample.get("/team/u-water2", "u-water-head").json()
    assert detail["member"]["name"] == "Ravi Menon"
    assert detail["open_complaints"] and detail["closed_complaints"] and detail["projects"] and detail["recent_actions"]
    assert any(p["id"] == "oldmill-water" for p in detail["projects"])
    # people can see their own work, not a colleague's, and not another department's
    assert sample.get("/team/u-water2", "u-water2").status_code == 200
    assert sample.get("/team/u-water2", "u-water").status_code == 403
    assert sample.get("/team/u-water2", "u-power-head").status_code == 403
    assert sample.get("/team/u-water2", "u-admin").status_code == 200
    assert sample.get("/team/u-aqua", "u-admin").status_code == 404                              # contractors are not department staff


# --------------------------------------------------------------- assignment
def test_staff_can_take_a_complaint_but_only_a_head_can_give_it_to_someone_else(sample):
    out = report(sample, "ELECTRICAL")
    item = mine(sample, "u-power", out)
    assert item["assigned_user_id"] is None and "ASSIGN_STAFF" in item["allowed_actions"]
    url = "/complaints/%s/assign-staff" % item["id"]
    assert sample.post(url, "u-power", {"expected_version": item["version"], "user_id": "u-power2"}).status_code == 403
    r = sample.post(url, "u-power", {"expected_version": item["version"], "user_id": "u-power"})
    assert r.status_code == 200 and "Meena Iyer" in r.json()["message"]
    item = mine(sample, "u-power", out)
    assert item["assigned_name"] == "Meena Iyer"
    # the head moves it to another colleague; wrong department / unknown person is refused
    assert sample.post(url, "u-power-head", {"expected_version": item["version"], "user_id": "u-water"}).status_code == 422
    assert sample.post(url, "u-power-head", {"expected_version": item["version"], "user_id": "u-nobody"}).status_code == 422
    r = sample.post(url, "u-power-head", {"expected_version": item["version"], "user_id": "u-power2"})
    assert r.status_code == 200
    item = mine(sample, "u-power", out)
    assert item["assigned_name"] == "Arjun Reddy"
    # a stale version is refused, other departments cannot touch it, and unassigning is for heads only
    assert sample.post(url, "u-power-head", {"expected_version": 1, "user_id": "u-power"}).status_code == 409
    assert sample.post(url, "u-water-head", {"expected_version": item["version"], "user_id": "u-water"}).status_code == 404
    assert sample.post(url, "u-power", {"expected_version": item["version"], "user_id": None}).status_code == 403
    assert sample.post(url, "u-power-head", {"expected_version": item["version"], "user_id": None}).status_code == 200


def test_staff_names_are_internal_the_resident_sees_only_the_team(sample):
    out = report(sample, "ELECTRICAL")
    item = mine(sample, "u-power", out)
    sample.post("/complaints/%s/assign-staff" % item["id"], "u-power-head", {"expected_version": item["version"], "user_id": "u-power2"})
    item = mine(sample, "u-power", out)
    sample.post("/complaints/%s/status" % item["id"], "u-power2", {"expected_version": item["version"], "status": "ACKNOWLEDGED"})
    view = sample.c.post("/api/v1/complaints/track", json={"reference": out["id"], "code": out["tracking_code"]}).json()
    text = str(view)
    assert "Arjun" not in text and "Reddy" not in text and "u-power2" not in text
    assert any("member of the Power Department team is now looking after your report" in e["message"] for e in view["timeline"])
    # staff do see who did what
    staff_item = mine(sample, "u-power-head", out)
    assert any(e["actor_name"] == "Arjun Reddy" for e in staff_item["timeline"])


def test_whoever_first_works_on_a_complaint_becomes_the_one_working_on_it(sample):
    out = report(sample, "WATER")
    item = mine(sample, "u-water2", out)
    assert item["assigned_user_id"] is None
    sample.post("/complaints/%s/status" % item["id"], "u-water2", {"expected_version": item["version"], "status": "ACKNOWLEDGED"})
    again = mine(sample, "u-water2", out)
    assert again["assigned_name"] == "Ravi Menon"


# ----------------------------------------------------------- history + search
def test_history_lists_closed_complaints_with_who_handled_them_and_how_long_it_took(sample):
    hist = items(sample, "u-water-head", scope="closed")
    assert hist["total"] >= 3
    assert all(i["status"] in ("RESOLVED", "CONFIRMED_FIXED", "REJECTED") for i in hist["items"])
    done = [i for i in hist["items"] if i["resolution_days"] is not None]
    assert done and all(i["resolved_on"] and i["assigned_name"] for i in done)
    assert {i["resolution_days"] for i in done} >= {3, 8}
    open_only = items(sample, "u-water-head", scope="open")["items"]
    assert open_only and all(i["status"] in ("NEW", "ACKNOWLEDGED", "IN_PROGRESS", "REOPENED") for i in open_only)


def test_history_search_filters_and_pagination(sample):
    assert items(sample, "u-water-head", q="hydrant")["total"] == 1
    assert items(sample, "u-water-head", q="HYDRANT corner")["total"] == 1                       # case-insensitive, every word must match
    assert items(sample, "u-water-head", q="hydrant zebra")["total"] == 0
    assert items(sample, "u-admin", category="TELECOM")["total"] >= 2
    ravi = items(sample, "u-water-head", assigned="u-water2")
    assert ravi["total"] >= 2 and all(i["assigned_user_id"] == "u-water2" for i in ravi["items"])
    assert all(i["assigned_user_id"] is None for i in items(sample, "u-admin", assigned="none")["items"])
    page1 = items(sample, "u-admin", scope="closed", limit=3, offset=0)
    page2 = items(sample, "u-admin", scope="closed", limit=3, offset=3)
    assert len(page1["items"]) == 3 and page1["total"] == page2["total"] and not ({i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]})
    assert items(sample, "u-admin", opened_to="2000-01-01")["total"] == 0
    # search never crosses departments
    assert items(sample, "u-water", q="street light")["total"] == 0
    assert items(sample, "u-power", q="street light")["total"] >= 1


def test_the_project_list_has_a_history_view_with_search(sample):
    past = sample.get("/projects", "u-admin", params={"state": "past"}).json()["items"]
    assert {p["id"] for p in past} == {"oldmill-water", "oldmill-surface", "oldmill-telecom"}
    assert [p["execution_status"] for p in sample.get("/projects", "u-water", params={"state": "done"}).json()["items"]] == ["DONE"]
    assert sample.get("/projects", "u-telecom", params={"state": "cancelled"}).json()["items"][0]["cancel_reason"].startswith("The new housing block")
    assert {p["id"] for p in sample.get("/projects", "u-admin", params={"q": "sewer"}).json()["items"]} == {"oldmill-water", "oldmill-surface"}
    done = sample.get("/projects", "u-admin", params={"state": "done"}).json()["items"]
    assert all(p["lead_name"] for p in done) and done[0]["pcc_number"] or done[1]["pcc_number"]


def test_every_project_has_a_history_trail(sample):
    h = sample.get("/projects/oldmill-water/history", "u-water-head").json()
    assert h["project"]["lead"] == "Ravi Menon" and h["project"]["verified_on"]
    what = " | ".join(e["what"] for e in h["events"])
    for expected in ("PROJECT_REGISTERED", "WORK_STARTED", "WORK_FINISHED", "Release inspection: PASS"):
        assert expected in what
    assert [e["at"] for e in h["events"]] == sorted(e["at"] for e in h["events"])
    assert sample.get("/projects/oldmill-water/history", "u-inspector").status_code == 200
    assert sample.get("/projects/oldmill-water/history", "u-aqua").status_code == 200            # its own contractor
    assert sample.get("/projects/oldmill-water/history", "u-pave").status_code == 403            # another contractor
    assert sample.get("/projects/oldmill-water/history", "u-grid").status_code == 403
    assert sample.c.get("/api/v1/projects/oldmill-water/history").status_code == 401
    cancelled = sample.get("/projects/oldmill-telecom/history", "u-telecom").json()
    assert cancelled["project"]["cancel_reason"] and any(e["what"] == "PROJECT_CANCELLED" for e in cancelled["events"])


def test_a_head_can_choose_who_leads_a_project(sample):
    p = next(x for x in sample.get("/projects", "u-water").json()["items"] if x["id"] == "water-1")
    url = "/projects/water-1/assign-staff"
    assert p["lead_name"] == "Asha Nair"                                                     # whoever registered it leads it
    assert sample.post(url, "u-water", {"expected_version": p["version"], "user_id": "u-water2"}).status_code == 403
    assert sample.post(url, "u-power-head", {"expected_version": p["version"], "user_id": "u-power"}).status_code == 403
    assert sample.post(url, "u-water-head", {"expected_version": p["version"], "user_id": "u-power"}).status_code == 422
    r = sample.post(url, "u-water-head", {"expected_version": p["version"], "user_id": "u-water2"})
    assert r.status_code == 200 and "Ravi Menon" in r.json()["message"]
    assert sample.post(url, "u-water-head", {"expected_version": p["version"], "user_id": "u-water"}).status_code == 409   # stale
    assert sample.post("/projects/oldmill-water/assign-staff", "u-water-head", {"expected_version": 3, "user_id": "u-water"}).status_code == 409   # finished


# ----------------------------------------------------------------- activity
def test_the_activity_trail_shows_the_team_to_a_head_and_only_yourself_to_staff(sample):
    head = sample.get("/activity", "u-water-head").json()
    assert head["everyone"] is True
    actors = {a["actor_name"] for a in head["items"]}
    assert "Ravi Menon" in actors and "Asha Nair" in actors
    own = sample.get("/activity", "u-water2").json()
    assert own["everyone"] is False and {a["actor_name"] for a in own["items"]} == {"Ravi Menon"}
    assert sample.get("/activity", "u-water2", params={"user_id": "u-water"}).status_code == 403
    assert sample.get("/activity", "u-water-head", params={"user_id": "u-water2"}).status_code == 200
    # a department's trail does not include another department's staff
    assert not ({"Meena Iyer", "Arjun Reddy"} & {a["actor_name"] for a in head["items"]})
    assert sample.get("/activity", "u-aqua").status_code == 403
    assert sample.c.get("/api/v1/activity").status_code == 401
    assert len(sample.get("/activity", "u-admin", params={"limit": 5}).json()["items"]) == 5


# ---------------------------------------------------------------------- CSV
def test_csv_export_is_scoped_and_safe(sample):
    report(sample, "WATER", text="=HYPERLINK(\"http://evil.example\",\"click\") is how this one starts.")
    r = sample.c.get("/api/v1/export/complaints.csv", headers=sample.headers("u-water-head"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows and {x["department"] for x in rows} == {"Water Department"}                     # only their own department
    evil = next(x for x in rows if "HYPERLINK" in x["description"])
    assert evil["description"].startswith("'=")                                                 # spreadsheet formula neutralised
    admin_rows = list(csv.DictReader(io.StringIO(sample.c.get("/api/v1/export/complaints.csv", headers=sample.headers("u-admin")).text)))
    assert len(admin_rows) > len(rows) and "contact_detail" in admin_rows[0]
    assert sample.c.get("/api/v1/export/complaints.csv", headers=sample.headers("u-aqua")).status_code == 403
    assert sample.c.get("/api/v1/export/complaints.csv").status_code == 401
    p = sample.c.get("/api/v1/export/projects.csv", headers=sample.headers("u-inspector"))
    assert p.status_code == 200 and "oldmill-water" in p.text and "Ravi Menon" in p.text
    assert sample.c.get("/api/v1/export/projects.csv", headers=sample.headers("u-aqua")).status_code == 403
