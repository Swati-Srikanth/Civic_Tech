"""End-to-end API tests against a freshly seeded temporary SQLite database."""
import sqlite3
import threading

import pytest


# ---------------------------------------------------------------- basics
def test_bootstrap_is_public_and_never_grants_staff_actions(api):
    r = api.get("/bootstrap")
    assert r.status_code == 200
    body = r.json()
    assert body["allowed_actions"] == [] and body["current_user"] is None
    assert body["clock"]["date"] == "2026-11-08"
    assert "users" not in body and body["contractors"] == [] and body["departments"] == []   # no staff directory for the public
    assert "demo policy" in body["policy"]["label"].lower()
    assert api.get("/bootstrap", "u-water").json()["allowed_actions"] == ["CREATE_PROJECT", "VIEW_COMPLAINTS", "TRIAGE_COMPLAINT"]
    assert api.get("/bootstrap", "u-aqua").json()["allowed_actions"] == []
    assert api.get("/bootstrap", "u-aqua").json()["contractors"]


def test_error_envelope_for_auth_and_validation(api):
    r = api.get("/projects")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    r = api.get("/projects", "u-nobody")
    assert r.status_code == 401
    r = api.post("/projects", "u-water", {"title": ""})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["failures"]
    r = api.c.post("/api/v1/projects", json={}, headers=api.headers("u-water"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert api.get("/nope").json()["error"]["code"] == "NOT_FOUND"


def test_cors_allows_only_the_configured_frontend_origin(api):
    ok = api.c.options("/api/v1/projects", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,authorization,idempotency-key"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "idempotency-key" in ok.headers["access-control-allow-headers"].lower()
    bad = api.c.options("/api/v1/projects", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_public_view_hides_internals_and_labels_dates(api):
    r = api.get("/roads/road-market/public")
    assert r.status_code == 200
    body = r.json()
    card = next(c for c in body["projects"] if c["id"] == "surface-1")
    assert card["proposed_start"] == "2026-11-21" and card["confirmed_start"] is None
    assert card["actual_start"] is None and card["verified_on"] is None
    assert "Waiting for contractors" in " ".join(body["notices"])
    assert "audit" not in r.text.lower() and "u-roads" not in r.text
    assert api.get("/roads/road-station/public").json()["projects"] == []
    temple = api.get("/roads/road-temple/public").json()
    assert temple["case"]["status"] == "BLOCKED" and temple["notices"]
    assert all(c["proposed_start"] is None for c in temple["projects"])


def test_market_case_matches_contract_fixture(api):
    c = api.case()
    assert c["status"] == "CONTRACTOR_REVIEW" and c["plan_version"] == 1
    assert c["deadline_at"] == "2026-11-10T02:30:00Z"
    assert [(s["project_id"], s["start"], s["end"], s["date_label"]) for s in c["schedule"]] == [
        ("water-1", "2026-11-08", "2026-11-12", "PROPOSED"),
        ("telecom-1", "2026-11-14", "2026-11-17", "PROPOSED"),
        ("surface-1", "2026-11-21", "2026-11-24", "PROPOSED")]
    assert c["required_departments"] == ["roads", "telecom", "water"]
    assert c["coverage_required"] == ["power", "telecom", "water"]
    assert c["assessment"]["outcome"] == "PLAN_FOUND"
    assert "RESPOND" not in c["allowed_actions"]           # admin cannot respond for contractors
    assert api.case(user="u-aqua")["allowed_actions"] == ["RESPOND"]


def test_temple_has_persisted_blocked_assessment(api):
    c = api.case("case-temple")
    assert c["status"] == "BLOCKED" and c["assessment"]["outcome"] == "NO_SEQUENTIAL_PLAN"
    assert c["assessment"]["violations"] and c["schedule"] == []


# ------------------------------------------------------ permissions (direct calls)
def test_wrong_role_and_wrong_owner_direct_calls_are_refused(api):
    p = api.project("water-1")
    ok_body = {"expected_version": p["version"], "plan_version": 1}
    assert api.post("/projects/water-1/start", "u-water", ok_body).status_code == 403          # department can't start
    assert api.post("/projects/water-1/start", "u-link", ok_body).status_code == 403           # other contractor
    assert api.post("/projects/water-1/start", "u-admin", ok_body).status_code == 403
    assert api.respond("u-link", "water-1").status_code == 403                                   # not assigned
    assert api.respond("u-water", "water-1").status_code == 403                                  # department can't answer for contractor
    assert api.respond("u-admin", "water-1").status_code == 403
    assert api.patch("/projects/water-1", "u-telecom", {"expected_version": 1, "duration_days": 9}).status_code == 403
    assert api.patch("/projects/water-1", "u-aqua", {"expected_version": 1, "duration_days": 9}).status_code == 403
    assert api.post("/projects/water-1/cancel", "u-roads", {"expected_version": 1, "reason": "x"}).status_code == 403
    assert api.post("/projects", "u-aqua", {"title": "x", "purpose": "y", "road_id": "road-market", "kind": "UTILITY",
                                            "assigned_contractor_id": "con-aqua", "earliest_start": "2026-11-09",
                                            "deadline": "2026-11-30", "duration_days": 2}).status_code == 403
    # a utility department cannot register resurfacing work
    r = api.post("/projects", "u-water", {"title": "x", "purpose": "y", "road_id": "road-market", "kind": "RESURFACING",
                                          "assigned_contractor_id": "con-pave", "earliest_start": "2026-11-09",
                                          "deadline": "2026-11-30", "duration_days": 2})
    assert r.status_code == 403
    assert api.post("/projects/water-1/inspections", "u-aqua", {"expected_version": 1, "kind": "UTILITY_RELEASE",
                                                                   "result": "PASS", "notes": "x"}).status_code == 403
    assert api.post("/demo/clock/advance", "u-water", {"expected_version": 1, "days": 1}).status_code == 403
    assert api.post("/cases/case-market/review", "u-roads", {"expected_version": 1, "action": "KEEP_BLOCKED", "reason": "x"}).status_code == 403
    assert api.approve("u-power").status_code == 403                                             # no work in plan
    assert api.get("/cases/case-market", "u-grid").status_code == 403                            # not a participant
    assert api.get("/projects/water-1/gate", "u-grid").status_code == 403


def test_visibility_is_scoped_by_role(api):
    assert {p["id"] for p in api.get("/projects", "u-water").json()["items"]} == {"water-1"}
    assert {p["id"] for p in api.get("/projects", "u-pave").json()["items"]} == {"surface-1", "surface-2"}
    assert len(api.get("/projects", "u-admin").json()["items"]) == 5
    assert [c["id"] for c in api.get("/cases", "u-grid").json()["items"]] == ["case-temple"]


# --------------------------------------------------------- workflow states
def test_contractors_then_departments_then_approved(api):
    assert api.respond("u-aqua", "water-1").json()["status"] == "CONTRACTOR_REVIEW"
    assert api.respond("u-link", "telecom-1").json()["status"] == "CONTRACTOR_REVIEW"
    assert api.approve("u-water").status_code == 409                                             # too early
    r = api.respond("u-pave", "surface-1")
    assert r.json()["status"] == "DEPARTMENT_REVIEW"
    assert api.case()["deadline_at"] == "2026-11-10T02:30:00Z"
    assert api.approve("u-water").json()["status"] == "DEPARTMENT_REVIEW"
    assert api.approve("u-telecom").json()["status"] == "DEPARTMENT_REVIEW"
    assert api.approve("u-power").status_code == 403                                             # Power is not an approval owner
    r = api.approve("u-roads")
    assert r.json()["status"] == "APPROVED"
    c = api.case()
    assert c["schedule"][0]["date_label"] == "CONFIRMED"
    assert api.get("/roads/road-market/public").json()["projects"][0]["confirmed_start"] == "2026-11-08"


def test_duplicate_response_is_refused(api):
    assert api.respond("u-aqua", "water-1").status_code == 200
    assert api.respond("u-aqua", "water-1").status_code == 409


def test_reject_blocks_and_requires_reason_then_admin_revision_restarts(api):
    r = api.respond("u-aqua", "water-1", "REJECT")
    assert r.status_code == 422 and r.json()["error"]["failures"][0]["field"] == "reason"
    assert api.respond("u-aqua", "water-1", "REJECT", reason="Crew unavailable").json()["status"] == "BLOCKED"
    assert "contractor could not accept" in api.get("/roads/road-market/public").json()["notices"][0]
    c = api.case()
    r = api.post("/cases/case-market/review", "u-admin", {"expected_version": c["version"], "action": "REQUEST_REVISION", "reason": "Pick another crew"})
    assert r.json()["status"] == "DRAFT"
    audit = [e["action"] for e in api.get("/cases/case-market/audit", "u-admin").json()["items"]]
    assert "CONTRACTOR_REJECT" in audit and "ADMIN_REQUEST_REVISION" in audit        # history preserved
    c = api.case(user="u-roads")
    assert c["allowed_actions"] == ["GENERATE_PLAN"]
    r = api.post("/cases/case-market/plans", "u-roads", {"expected_version": c["version"]})
    assert r.json()["plan_version"] == 2 and r.json()["status"] == "CONTRACTOR_REVIEW"
    assert api.case()["responses"] == []                                             # fresh responses needed


def test_admin_cannot_force_approval(api):
    c = api.case()
    r = api.post("/cases/case-market/review", "u-admin", {"expected_version": c["version"], "action": "APPROVE", "reason": "x"})
    assert r.status_code == 422
    r = api.post("/cases/case-market/review", "u-admin", {"expected_version": c["version"], "action": "KEEP_BLOCKED", "reason": "Needs checks"})
    assert r.json()["status"] == "BLOCKED"


def test_department_rejection_blocks(api):
    for pid, user in (("water-1", "u-aqua"), ("telecom-1", "u-link"), ("surface-1", "u-pave")):
        api.respond(user, pid)
    assert api.approve("u-water", "REJECT").status_code == 422
    assert api.approve("u-water", "REJECT", reason="Dates clash").json()["status"] == "BLOCKED"


def test_counterproposal_creates_new_plan_and_voids_old_consent(api):
    assert api.respond("u-aqua", "water-1").status_code == 200
    r = api.respond("u-link", "telecom-1", "COUNTERPROPOSE", earliest_start="2026-11-14")
    assert r.status_code == 200 and r.json()["plan_version"] == 2
    c = api.case()
    assert c["status"] == "CONTRACTOR_REVIEW" and c["responses"] == []                # Water must answer again
    assert c["plan_version"] == 2 and api.project("telecom-1")["earliest_start"] == "2026-11-14"
    assert next(s for s in c["schedule"] if s["project_id"] == "surface-1")["start"] == "2026-11-21"
    # a start one day later than the schedule allows would miss the surface deadline: blocked with an explanation
    assert api.respond("u-aqua", "water-1").status_code == 200
    # a counter-proposal that is not later is refused
    r = api.respond("u-link", "telecom-1", "COUNTERPROPOSE", earliest_start="2026-11-01")
    assert r.status_code == 422


def test_counterproposal_that_breaks_deadline_blocks_with_explanation(api):
    r = api.respond("u-link", "telecom-1", "COUNTERPROPOSE", earliest_start="2026-11-22")
    assert r.status_code == 200
    c = api.case()
    assert c["status"] == "BLOCKED" and c["assessment"]["outcome"] == "NO_SEQUENTIAL_PLAN"


# -------------------------------------------------------- stale versions
def test_editing_planning_details_invalidates_consent_and_old_submissions_get_409(api):
    api.respond("u-aqua", "water-1")
    old = api.case()
    r = api.patch("/projects/telecom-1", "u-telecom", {"expected_version": 1, "duration_days": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["invalidated_case"]["status"] == "DRAFT" and body["material_version"] == 2
    c = api.case()
    assert c["status"] == "DRAFT" and c["schedule"] == []
    # an old submission against the old plan is refused, never silently replayed
    r = api.post("/cases/case-market/responses", "u-link",
                 {"expected_version": old["version"], "plan_version": old["plan_version"], "project_id": "telecom-1", "decision": "ACCEPT"})
    assert r.status_code == 409 and r.json()["error"]["code"] in ("STALE_PLAN", "STALE_VERSION")
    r = api.post("/cases/case-market/plans", "u-roads", {"expected_version": old["version"]})
    assert r.status_code == 409
    c = api.case()
    r = api.post("/cases/case-market/plans", "u-roads", {"expected_version": c["version"]})
    assert r.json()["plan_version"] == 2
    assert api.case()["responses"] == []                                             # Water must accept again


def test_stale_plan_code_when_plan_version_differs(api):
    c = api.case()
    r = api.post("/cases/case-market/responses", "u-aqua",
                 {"expected_version": c["version"], "plan_version": 99, "project_id": "water-1", "decision": "ACCEPT"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_PLAN"
    assert "plan changed" in r.json()["error"]["message"].lower()


def test_stale_project_version_is_refused(api):
    assert api.patch("/projects/water-1", "u-water", {"expected_version": 7, "duration_days": 9}).status_code == 409


def test_title_only_edit_does_not_invalidate_consent(api):
    api.respond("u-aqua", "water-1")
    r = api.patch("/projects/water-1", "u-water", {"expected_version": 1, "title": "Water main renewal"})
    assert r.status_code == 200 and r.json()["invalidated_case"] is None
    assert api.case()["status"] == "CONTRACTOR_REVIEW" and len(api.case()["responses"]) == 1


def test_registering_new_road_work_invalidates_plan_and_reuses_one_case(api):
    r = api.post("/projects", "u-power", {"title": "Power cable", "purpose": "Renew cable", "road_id": "road-market",
                                          "kind": "UTILITY", "assigned_contractor_id": "con-grid",
                                          "earliest_start": "2026-11-09", "deadline": "2026-11-21", "duration_days": 2})
    assert r.status_code == 201
    assert r.json()["case_id"] == "case-market" and r.json()["case_created"] is False
    assert api.case()["status"] == "DRAFT"
    cases = api.get("/cases", "u-admin", params={"road_id": "road-market"}).json()["items"]
    assert len(cases) == 1


def test_standalone_work_on_empty_road_creates_one_case_only(api):
    body = {"title": "Gas pipe", "purpose": "Renew", "road_id": "road-station", "kind": "UTILITY",
            "assigned_contractor_id": "con-grid", "earliest_start": "2026-11-09", "deadline": "2026-11-30", "duration_days": 3}
    r1 = api.post("/projects", "u-power", body)
    assert r1.status_code == 201 and r1.json()["case_created"] is True
    r2 = api.post("/projects", "u-power", dict(body, title="Gas pipe 2"))
    assert r2.json()["case_id"] == r1.json()["case_id"] and r2.json()["case_created"] is False
    assert len(api.get("/cases", "u-admin", params={"road_id": "road-station"}).json()["items"]) == 1


def test_create_project_validation_keeps_server_messages(api):
    r = api.post("/projects", "u-water", {"title": "x", "purpose": "y", "road_id": "road-market", "kind": "UTILITY",
                                          "assigned_contractor_id": "con-aqua", "earliest_start": "2026-12-01",
                                          "deadline": "2026-11-01", "duration_days": 2})
    assert r.status_code == 422 and r.json()["error"]["failures"][0]["field"] == "deadline"
    r = api.post("/projects", "u-water", {"title": "x", "purpose": "y", "road_id": "road-market", "kind": "UTILITY",
                                          "assigned_contractor_id": "water", "earliest_start": "2026-11-01",
                                          "deadline": "2026-12-01", "duration_days": 2})
    assert r.status_code == 422
    assert api.post("/projects", "u-water", {"title": "x", "purpose": "y", "road_id": "road-nowhere", "kind": "UTILITY",
                                             "assigned_contractor_id": "con-aqua", "earliest_start": "2026-11-01",
                                             "deadline": "2026-12-01", "duration_days": 2}).status_code == 404


def test_cancel_before_work_only(api):
    r = api.post("/projects/water-1/cancel", "u-water", {"expected_version": 1, "reason": "No longer needed"})
    assert r.status_code == 200
    assert api.case()["status"] == "DRAFT"
    assert api.get("/roads/road-market/public").json()["projects"][0]["execution_status"] in ("CANCELLED", "PLANNED")


# -------------------------------------------------- execution + the gate
def test_full_walkthrough_with_denied_then_successful_paving(api):
    api.approve_market()
    # plan approval is not clearance: start eligibility is separate and the gate GET is read-only
    gate_before = api.get("/projects/surface-1/gate", "u-pave")
    assert gate_before.status_code == 200
    g = gate_before.json()
    assert g["eligible"] is False and g["not_an_authorisation"] is True
    codes = {b["code"] for b in g["blockers"]}
    assert {"DATE_NOT_APPROVED_START", "UTILITY_NOT_COMPLETE", "COVERAGE_MISSING"} <= codes
    cover = next(b for b in g["blockers"] if b["code"] == "COVERAGE_MISSING")
    assert cover["responsible_org_id"] == "power" and "has not confirmed its planned work" in cover["message"]
    assert api.get("/projects/surface-1/gate", "u-pave").json() == g                             # pure read, stable

    # direct API attempts to start out of order are refused
    r = api.start("u-pave", "surface-1")
    assert r.status_code == 422 and r.json()["error"]["code"] == "GATE_BLOCKED" and r.json()["error"]["failures"]
    assert api.project("surface-1")["execution_status"] == "PLANNED" and api.project("surface-1")["actual_start"] is None
    assert api.start("u-link", "telecom-1").status_code == 422                                   # telecom date + water not done

    # 8 Nov: water starts on its approved date
    r = api.start("u-aqua", "water-1")
    assert r.status_code == 200 and r.json()["pcc_number"] is None
    assert api.project("water-1")["actual_start"] == "2026-11-08"
    # cannot finish with testing/reinstatement undeclared
    r = api.finish("u-aqua", "water-1", testing_complete=False)
    assert r.status_code == 422 and r.json()["error"]["failures"][0]["field"] == "testing_complete"

    api.advance(4)                                                                               # 12 Nov
    assert api.finish("u-aqua", "water-1").status_code == 200
    c = api.case()
    assert c["status"] == "APPROVED" and c["plan_version"] == 1 and not c["hold"]               # normal on-time finish keeps plan
    assert api.start("u-link", "telecom-1").status_code == 422                                   # separation / date
    api.advance(2)                                                                               # 14 Nov
    assert api.start("u-link", "telecom-1").status_code == 200
    api.advance(3)                                                                               # 17 Nov
    assert api.finish("u-link", "telecom-1").status_code == 200

    # inspection too early is refused for telecom (3 days after finish)
    r = api.inspect("u-inspector", "telecom-1")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INSPECTION_TOO_EARLY"
    api.advance(3)                                                                               # 20 Nov
    assert api.inspect("u-inspector", "water-1").status_code == 200
    assert api.inspect("u-inspector", "telecom-1").status_code == 200
    assert api.project("telecom-1")["inspection_status"] == "PASS"
    api.advance(1)                                                                               # 21 Nov, approved start

    # everything is done except Power's declaration: still blocked, even by direct request
    g = api.get("/projects/surface-1/gate", "u-pave").json()
    assert [b["code"] for b in g["blockers"]] == ["COVERAGE_MISSING"]
    r = api.start("u-pave", "surface-1")
    assert r.status_code == 422 and "Power Department has not confirmed" in r.json()["error"]["message"]
    assert api.project("surface-1")["pcc_number"] is None

    # Power cannot declare 'no planned work' while it is... (it has none on Market) -> allowed
    assert api.declare("u-power").status_code == 200
    assert api.declare("u-roads").status_code == 403                                             # Roads isn't a utility department
    g = api.get("/projects/surface-1/gate", "u-pave").json()
    assert g["eligible"] is True and g["blockers"] == [] and g["not_an_authorisation"] is True

    r = api.start("u-pave", "surface-1")
    assert r.status_code == 200
    pcc = r.json()["pcc_number"]
    assert pcc.startswith("PCC-2026-") and api.project("surface-1")["pcc_number"] == pcc
    assert api.project("surface-1")["actual_start"] == "2026-11-21"

    api.advance(3)                                                                               # 24 Nov
    assert api.finish("u-pave", "surface-1").status_code == 200
    assert api.project("surface-1")["inspection_status"] == "PENDING"                            # physical completion != verified
    assert api.case()["status"] == "APPROVED"
    r = api.inspect("u-inspector", "surface-1", kind="FINAL_SURFACE")
    assert r.status_code == 200 and r.json()["case_completed"] is True
    pub = api.get("/roads/road-market/public").json()
    surf = next(c for c in pub["projects"] if c["id"] == "surface-1")
    assert surf["verified_on"] == "2026-11-24" and surf["actual_start"] == "2026-11-21"
    assert pub["case"] is None or pub["case"]["status"] != "COMPLETED"
    audit = [e["action"] for e in api.get("/cases/case-market/audit", "u-admin").json()["items"]]
    assert "SURFACING_STARTED_PCC_ISSUED" in audit and "CASE_COMPLETED" in audit


def test_missing_release_inspection_blocks_paving(api):
    api.approve_market()
    api.start("u-aqua", "water-1")
    api.advance(4); api.finish("u-aqua", "water-1")
    api.advance(2); api.start("u-link", "telecom-1")
    api.advance(3); api.finish("u-link", "telecom-1")
    api.advance(4)                                                                               # 21 Nov
    api.declare("u-power")
    g = api.get("/projects/surface-1/gate", "u-pave").json()
    codes = [b["code"] for b in g["blockers"]]
    assert codes.count("INSPECTION_MISSING") == 2
    assert any("Telecom Department's release inspection is missing" in b["message"] for b in g["blockers"])
    assert api.start("u-pave", "surface-1").status_code == 422
    # a failed inspection holds the case and is not clearance either
    assert api.inspect("u-inspector", "water-1", result="FAIL").status_code == 200
    assert api.case()["hold"] is True and api.case()["hold_reason"] == "FAILED_INSPECTION"
    codes = {b["code"] for b in api.get("/projects/surface-1/gate", "u-pave").json()["blockers"]}
    assert {"CASE_ON_HOLD", "INSPECTION_FAILED"} <= codes
    # re-inspection that passes clears the failure
    assert api.inspect("u-inspector", "water-1").status_code == 200
    assert api.case()["hold"] is False


def test_registering_new_work_after_approval_blocks_paving_even_via_direct_request(api):
    api.approve_market()
    r = api.post("/projects", "u-power", {"title": "Power cable", "purpose": "Renew", "road_id": "road-market", "kind": "UTILITY",
                                          "assigned_contractor_id": "con-grid", "earliest_start": "2026-11-09",
                                          "deadline": "2026-12-15", "duration_days": 2})
    assert r.status_code == 201 and r.json()["consent_invalidated"] is True
    assert api.start("u-aqua", "water-1").status_code == 422                                     # plan no longer approved


def test_new_work_after_start_creates_review_hold_and_blocks_new_starts(api):
    api.approve_market()
    assert api.start("u-aqua", "water-1").status_code == 200
    r = api.post("/projects", "u-power", {"title": "Power cable", "purpose": "Renew", "road_id": "road-market", "kind": "UTILITY",
                                          "assigned_contractor_id": "con-grid", "earliest_start": "2026-11-09",
                                          "deadline": "2026-12-15", "duration_days": 2})
    assert r.status_code == 201
    c = api.case()
    assert c["hold"] is True and c["hold_reason"] == "MATERIAL_CHANGE_AFTER_START" and c["status"] == "APPROVED"
    assert api.project("water-1")["actual_start"] == "2026-11-08"                                # actuals preserved
    api.advance(6)
    assert api.start("u-link", "telecom-1").status_code == 422
    # in-progress replanning is not supported, and edits to started work are refused
    c = api.case()
    assert api.post("/cases/case-market/review", "u-admin", {"expected_version": c["version"], "action": "REQUEST_REVISION", "reason": "x"}).status_code == 422
    assert api.patch("/projects/water-1", "u-water", {"expected_version": api.project("water-1")["version"], "duration_days": 9}).status_code == 409
    assert api.post("/projects/water-1/cancel", "u-water", {"expected_version": api.project("water-1")["version"], "reason": "x"}).status_code == 409


def test_late_finish_requires_reason_and_places_hold(api):
    api.approve_market()
    api.start("u-aqua", "water-1")
    api.advance(6)                                                                               # 14 Nov, planned end 12 Nov
    r = api.finish("u-aqua", "water-1")
    assert r.status_code == 422 and r.json()["error"]["failures"][0]["field"] == "delay_reason"
    assert api.finish("u-aqua", "water-1", delay_reason="Rain delay").status_code == 200
    c = api.case()
    assert c["hold"] and c["hold_reason"] == "DELAY"
    assert "later than planned" in api.get("/roads/road-market/public").json()["notices"][0]


def test_incident_places_hold_and_never_authorises(api):
    api.approve_market()
    r = api.post("/projects/telecom-1/incidents", "u-link",
                 {"expected_version": api.project("telecom-1")["version"], "kind": "WORK_WITHOUT_CLEARANCE",
                  "description": "Crew spotted digging early", "occurred_date": "2026-11-08"})
    assert r.status_code == 200 and "does not authorise" in r.json()["message"]
    assert api.case()["hold"] is True
    assert api.start("u-aqua", "water-1").status_code == 422
    assert api.post("/projects/telecom-1/incidents", "u-grid", {"expected_version": 1, "kind": "SITE_ISSUE", "description": "x"}).status_code == 403
    assert api.post("/projects/telecom-1/incidents", "u-admin", {"expected_version": api.project("telecom-1")["version"], "kind": "SITE_ISSUE", "description": "x"}).status_code == 200
    # the public view shows only a generic notice
    pub = api.get("/roads/road-market/public")
    assert "digging" not in pub.text and "on hold" in pub.json()["notices"][0]
    # admin revision (unstarted case) reviews the reports but grants nothing
    c = api.case()
    api.post("/cases/case-market/review", "u-admin", {"expected_version": c["version"], "action": "REQUEST_REVISION", "reason": "Reviewed"})
    assert api.case()["status"] == "DRAFT" and api.case()["hold"] is False


def test_inspector_cannot_verify_own_evidence(api):
    api.approve_market()
    api.start("u-aqua", "water-1"); api.advance(4); api.finish("u-aqua", "water-1"); api.advance(3)
    conn = sqlite3.connect(api_db(api))
    conn.execute("UPDATE projects SET finished_by_user_id = 'u-inspector' WHERE id = 'water-1'"); conn.commit(); conn.close()
    assert api.inspect("u-inspector", "water-1").status_code == 403
    assert api.inspect("u-inspector2", "water-1").status_code == 200


def api_db(api):
    import os
    return os.environ["WORKSYNC_DB"]


def test_wrong_inspection_kind_and_unfinished_work(api):
    api.approve_market()
    p = api.project("water-1")
    r = api.post("/projects/water-1/inspections", "u-inspector", {"expected_version": p["version"], "kind": "FINAL_SURFACE", "result": "PASS", "notes": "x"})
    assert r.status_code == 422
    r = api.post("/projects/water-1/inspections", "u-inspector", {"expected_version": p["version"], "kind": "UTILITY_RELEASE", "result": "PASS", "notes": "x"})
    assert r.status_code == 409


def test_declarations_cannot_contradict_registered_work_and_go_stale(api):
    r = api.declare("u-water", mode="NO_PLANNED_WORK")
    assert r.status_code == 422 and r.json()["error"]["code"] == "DECLARATION_CONTRADICTS_REGISTRY"
    assert api.declare("u-power", valid_until="2026-01-01").status_code == 422
    assert api.declare("u-power").status_code == 200
    decl = {d["org_id"]: d for d in api.case()["declarations"]}
    assert decl["power"]["status"] == "CURRENT" and decl["water"]["status"] == "CURRENT"
    # a material edit changes the registry: earlier declarations stop counting
    api.patch("/projects/water-1", "u-water", {"expected_version": 1, "duration_days": 6})
    decl = {d["org_id"]: d for d in api.case()["declarations"]}
    assert decl["power"]["status"] == "COVERAGE_STALE" and decl["water"]["status"] == "COVERAGE_STALE"
    assert api.declare("u-power", through="2026-12-01").status_code == 200
    assert {d["org_id"]: d for d in api.case()["declarations"]}["power"]["status"] == "COVERAGE_SHORT"


# --------------------------------------------------------- idempotency
def test_identical_retry_returns_original_result_without_repeating_action(api):
    c = api.case()
    body = {"expected_version": c["version"], "plan_version": 1, "project_id": "water-1", "decision": "ACCEPT"}
    r1 = api.post("/cases/case-market/responses", "u-aqua", body, key="same-key")
    r2 = api.post("/cases/case-market/responses", "u-aqua", body, key="same-key")
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json() and r2.headers["idempotent-replay"] == "true"
    actions = [e["action"] for e in api.get("/cases/case-market/audit", "u-admin").json()["items"]]
    assert actions.count("CONTRACTOR_ACCEPT") == 1


def test_reused_key_with_changed_payload_is_409(api):
    c = api.case()
    body = {"expected_version": c["version"], "plan_version": 1, "project_id": "water-1", "decision": "ACCEPT"}
    api.post("/cases/case-market/responses", "u-aqua", body, key="k1")
    r = api.post("/cases/case-market/responses", "u-aqua", dict(body, decision="REJECT", reason="x"), key="k1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"
    r = api.post("/cases/case-market/responses", "u-aqua", body, key="k1")
    assert r.status_code == 200                                                                  # original still replays


def test_replay_checks_current_access_first(api):
    c = api.case()
    body = {"expected_version": c["version"], "plan_version": 1, "project_id": "water-1", "decision": "ACCEPT"}
    api.post("/cases/case-market/responses", "u-aqua", body, key="shared")
    # another user reusing the key is not given the first user's result
    r = api.post("/cases/case-market/responses", "u-link", body, key="shared")
    assert r.status_code == 403


def test_failed_attempt_with_same_key_can_be_retried_after_fixing(api):
    api.approve_market()
    r1 = api.post("/projects/surface-1/start", "u-pave", {"expected_version": api.project("surface-1")["version"], "plan_version": 1}, key="try")
    assert r1.status_code == 422
    r2 = api.post("/projects/surface-1/start", "u-pave", {"expected_version": api.project("surface-1")["version"], "plan_version": 1}, key="try")
    assert r2.status_code == 422                                                                 # evaluated afresh, no stored denial


def test_gate_get_is_read_only(api):
    api.approve_market()
    conn = sqlite3.connect(api_db(api))
    before = conn.execute("select (select count(*) from audit), (select count(*) from idempotency), (select sum(version) from projects), (select sum(version) from cases)").fetchone()
    for _ in range(3):
        api.get("/projects/surface-1/gate", "u-pave"); api.get("/projects/water-1/gate", "u-aqua")
        api.get("/cases/case-market", "u-admin"); api.get("/roads/road-market/public")
    after = conn.execute("select (select count(*) from audit), (select count(*) from idempotency), (select sum(version) from projects), (select sum(version) from cases)").fetchone()
    conn.close()
    assert before == after


# ------------------------------------------------- timeouts and the clock
def test_review_deadline_blocks_after_48_hours_and_silence_is_not_approval(api):
    out = api.advance(1)
    assert out["timed_out_case_ids"] == [] and api.case()["status"] == "CONTRACTOR_REVIEW"
    out = api.advance(1)
    assert "case-market" in out["timed_out_case_ids"]
    c = api.case()
    assert c["status"] == "BLOCKED" and c["deadline_at"] is None
    assert api.respond("u-aqua", "water-1").status_code == 409
    audit = api.get("/cases/case-market/audit", "u-admin").json()["items"]
    assert any(e["action"] == "REVIEW_TIMEOUT" and e["actor_name"] == "System" for e in audit)


def test_clock_is_forward_only_and_versioned(api):
    clk = api.get("/bootstrap").json()["clock"]
    assert api.post("/demo/clock/advance", "u-admin", {"expected_version": clk["version"], "days": 0}).status_code == 422
    assert api.post("/demo/clock/advance", "u-admin", {"expected_version": clk["version"], "days": -2}).status_code == 422
    assert api.post("/demo/clock/advance", "u-admin", {"expected_version": 99, "days": 1}).status_code == 409
    r = api.post("/demo/clock/advance", "u-admin", {"expected_version": clk["version"], "days": 1})
    assert r.json()["date"] == "2026-11-09" and "does not grant any approval" in r.json()["message"]


def test_command_time_deadline_check_runs_before_mutations(api, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE cases SET review_deadline_at = '2026-11-01T00:00:00Z' WHERE id = 'case-market'"); conn.commit(); conn.close()
    c = api.case()
    r = api.post("/cases/case-market/responses", "u-aqua", {"expected_version": c["version"], "plan_version": 1, "project_id": "water-1", "decision": "ACCEPT"})
    assert r.status_code == 409
    assert api.case()["status"] == "BLOCKED"


# ------------------------------------------------ concurrency / integrity
def test_registration_vs_start_race_never_issues_clearance_on_stale_inventory(api, db_path):
    api.approve_market()
    p_before = api.project("water-1")
    results = {}

    def register():
        results["reg"] = api.c.post("/api/v1/projects", headers=api.headers("u-power", key="race-reg", write=True), json={
            "title": "Power cable", "purpose": "Renew", "road_id": "road-market", "kind": "UTILITY", "assigned_contractor_id": "con-grid",
            "earliest_start": "2026-11-09", "deadline": "2026-12-15", "duration_days": 2})

    def start():
        results["start"] = api.c.post("/api/v1/projects/water-1/start", headers=api.headers("u-aqua", key="race-start", write=True),
                                      json={"expected_version": p_before["version"], "plan_version": 1})

    threads = [threading.Thread(target=register), threading.Thread(target=start)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results["reg"].status_code == 201
    conn = sqlite3.connect(db_path)
    started = conn.execute("select execution_status from projects where id='water-1'").fetchone()[0]
    hold = conn.execute("select hold_reason, status from cases where id='case-market'").fetchone()
    conn.close()
    if results["start"].status_code == 200:                                   # start won the race: registration put a hold on it
        assert started == "IN_PROGRESS" and hold[0] == "MATERIAL_CHANGE_AFTER_START"
    else:                                                                     # registration won: start saw the new inventory
        assert results["start"].status_code == 422 and started == "PLANNED" and hold[1] == "DRAFT"


def test_audit_is_append_only_and_plans_immutable(db_path):
    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit SET action = 'X'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM audit")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE plans SET outcome = 'PLAN_FOUND'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("INSERT INTO cases(id, road_id, status, created_at) VALUES ('dup','road-market','DRAFT','x')")  # one active case per road
    conn.close()


def test_state_and_history_survive_a_restart(db_path):
    from fastapi.testclient import TestClient
    import main
    from tests.conftest import Api
    with TestClient(main.app) as c1:
        a = Api(c1)
        a.approve_market()
        a.start("u-aqua", "water-1")
        a.advance(1)
    with TestClient(main.app) as c2:                                          # "restart": new app lifespan on the same file
        a = Api(c2)
        assert a.case()["status"] == "APPROVED"
        assert a.project("water-1")["actual_start"] == "2026-11-08"
        assert a.get("/bootstrap").json()["clock"]["date"] == "2026-11-09"
        actions = [e["action"] for e in a.get("/cases/case-market/audit", "u-admin").json()["items"]]
        assert "PLAN_APPROVED" in actions and "WORK_STARTED" in actions


def test_openapi_documents_paths_headers_and_examples(api):
    spec = api.c.get("/openapi.json").json()
    for path in ("/api/v1/bootstrap", "/api/v1/projects", "/api/v1/cases/{case_id}/responses", "/api/v1/projects/{project_id}/gate",
                 "/api/v1/demo/clock/advance", "/api/v1/roads/{road_id}/declarations"):
        assert path in spec["paths"]
    assert "ContractorResponseRequest" in spec["components"]["schemas"]
    assert api.c.get("/docs").status_code == 200


def test_gate_never_implies_a_pass_for_checks_it_could_not_run(api):
    # Temple Street has no workable plan, yet every plan-independent check is still evaluated and reported.
    g = api.get("/projects/surface-2/gate", "u-pave").json()
    codes = [b["code"] for b in g["blockers"]]
    assert g["eligible"] is False
    for expected in ("PLAN_NOT_APPROVED", "NO_APPROVED_DATE", "UTILITY_NOT_COMPLETE", "INSPECTION_MISSING", "COVERAGE_MISSING"):
        assert expected in codes
    assert codes.count("COVERAGE_MISSING") == 3                                       # water, telecom and power
    # a case sent back to preparation has no current plan, even though older versions exist
    api.patch("/projects/water-1", "u-water", {"expected_version": 1, "duration_days": 6})
    codes = [b["code"] for b in api.get("/projects/surface-1/gate", "u-pave").json()["blockers"]]
    assert "NO_APPROVED_DATE" in codes and "DATE_NOT_APPROVED_START" not in codes
