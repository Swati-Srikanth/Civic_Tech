"""Read models: bootstrap, public road view, internal lists/details, audit.

Every response is computed on the server (including ``allowed_actions``); the
frontend only displays it.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import scheduler
import service as svc
from db import many, one
from errors import forbidden, not_found
from service import PUBLIC_REASONS, d2s, s2d

POLICY = {
    "label": "Demo policy, not statutory rules",
    "utility_gap_days": scheduler.UTILITY_GAP_DAYS,
    "surface_gap_days": scheduler.SURFACE_GAP_DAYS,
    "inspection_wait_days": 3,
    "review_horizon_days": scheduler.HORIZON_DAYS,
    "protected_surface_days": scheduler.PROTECTED_DAYS,
    "review_deadline_hours": svc.REVIEW_HOURS,
    "max_utilities": scheduler.MAX_UTILITIES,
    "max_resurfacing": scheduler.MAX_RESURFACING,
    "timezone": "Asia/Kolkata",
}


# ------------------------------------------------------------- bootstrap
def global_actions(user: Optional[dict]) -> List[str]:
    if not user:
        return []
    out = []
    if user["role"] == "DEPARTMENT":
        out.append("CREATE_PROJECT")
    if user["role"] in ("DEPARTMENT", "ADMIN"):
        out += ["VIEW_COMPLAINTS", "TRIAGE_COMPLAINT"]
    if user["role"] == "ADMIN":
        out.append("CREATE_SCENARIO")
    return out


def bootstrap(conn, user: Optional[dict]) -> dict:
    """Public callers get only what a resident may see. No staff names, roles or organisations are listed."""
    import complaints
    import google
    clk = svc.clock(conn)
    out = {
        "roads": many(conn, "SELECT id, name, lat, lng, version FROM roads ORDER BY name"),
        "clock": {"date": clk["date"], "version": clk["version"], "label": "Simulated demo date (Asia/Kolkata)"},
        "policy": POLICY,
        "complaint_categories": complaints.category_list(conn),
        "google_client_id": google.client_id(),
        "current_user": user,
        "allowed_actions": global_actions(user),
        "contractors": [],
        "departments": [],
    }
    if user:
        orgs = many(conn, "SELECT id, name, kind FROM orgs ORDER BY name")
        out["contractors"] = [{"id": o["id"], "name": o["name"]} for o in orgs if o["kind"] == "CONTRACTOR"]
        out["departments"] = [{"id": o["id"], "name": o["name"]} for o in orgs if o["kind"] == "DEPARTMENT"]
    return out


def public_roads(conn) -> dict:
    """Every road with its coordinates and a resident-safe summary. Distances are computed in the browser,
    so a resident's location never has to be sent to this server."""
    items = []
    for r in many(conn, "SELECT id, name, lat, lng, area_label FROM roads ORDER BY name"):
        view = public_road(conn, r["id"])
        works = [{"id": c["id"], "title": c["title"], "kind": c["kind"], "execution_status": c["execution_status"],
                  "case_status": c["case_status"]} for c in view["projects"]
                 if c["execution_status"] != "CANCELLED"]
        items.append({"id": r["id"], "name": r["name"], "lat": r["lat"], "lng": r["lng"], "area_label": r["area_label"],
                      "work_count": len(works),
                      "in_progress_count": sum(1 for w in works if w["execution_status"] == "IN_PROGRESS"),
                      "notices": view["notices"][:2], "works": works[:5]})
    return {"items": items}


# ------------------------------------------------------------ projects
def _plan_item(plan: Optional[dict], project_id: str) -> Optional[dict]:
    if not plan or plan["outcome"] != scheduler.PLAN_FOUND:
        return None
    return next((i for i in plan["schedule"] if i["project_id"] == project_id), None)


def project_actions(user: dict, p: dict, case: Optional[dict]) -> List[str]:
    a: List[str] = []
    role, org = user["role"], user["org_id"]
    if role == "DEPARTMENT" and org == p["owner_org_id"] and p["execution_status"] == "PLANNED":
        a += ["EDIT_PROJECT", "CANCEL_PROJECT"]
    if role == "CONTRACTOR" and org == p["assigned_contractor_id"]:
        if p["execution_status"] == "PLANNED" and case and case["status"] == "APPROVED":
            a.append("START_PROJECT")
        if p["execution_status"] == "IN_PROGRESS":
            a.append("FINISH_PROJECT")
    return a


def project_extra_actions(conn, user: dict, p: dict) -> List[str]:
    a: List[str] = []
    if user["role"] == "INSPECTOR" and p["execution_status"] == "DONE" and \
            svc.inspection_status(conn, p) != "PASS" and p["finished_by_user_id"] != user["id"]:
        a.append("INSPECT_PROJECT")
    related = (user["role"] in ("INSPECTOR", "ADMIN")
               or (user["role"] == "DEPARTMENT" and user["org_id"] == p["owner_org_id"])
               or (user["role"] == "CONTRACTOR" and user["org_id"] == p["assigned_contractor_id"]))
    if related and p["execution_status"] != "CANCELLED":
        a.append("REPORT_INCIDENT")
    return a


def _people(conn) -> Dict[str, str]:
    return {u["id"]: u["name"] for u in many(conn, "SELECT id, name FROM users")}


def project_out(conn, p: dict, user: dict, names: Dict[str, str], road_names: Dict[str, str],
                case: Optional[dict] = None, plan: Optional[dict] = None, people: Optional[Dict[str, str]] = None) -> dict:
    people = people if people is not None else _people(conn)
    if case is None and p["case_id"]:
        case = svc.get_case(conn, p["case_id"])
    if plan is None and case:
        plan = svc.current_plan(conn, case)
    item = _plan_item(plan, p["id"]) if case and case["status"] != "DRAFT" else None
    label = None
    if item:
        label = "CONFIRMED" if case["status"] in ("APPROVED", "COMPLETED") else "PROPOSED"
    return {
        "id": p["id"], "title": p["title"], "purpose": p["purpose"], "road_id": p["road_id"],
        "road_name": road_names.get(p["road_id"]), "kind": p["kind"],
        "assigned_contractor_id": p["assigned_contractor_id"],
        "assigned_contractor_name": names.get(p["assigned_contractor_id"]),
        "earliest_start": p["earliest_start"], "deadline": p["deadline"], "duration_days": p["duration_days"],
        "version": p["version"], "material_version": p["material_version"],
        "owner_org_id": p["owner_org_id"], "owner_org_name": names.get(p["owner_org_id"]),
        "case_id": p["case_id"], "case_status": case["status"] if case else None,
        "case_version": case["version"] if case else None, "plan_version": case["plan_version"] if case else None,
        "execution_status": p["execution_status"], "actual_start": p["actual_start"], "actual_end": p["actual_end"],
        "inspection_status": svc.inspection_status(conn, p), "verified_on": p["verified_on"],
        "pcc_number": p["pcc_number"], "plan_start": item["start"] if item else None,
        "plan_end": item["end"] if item else None, "date_label": label,
        "lead_user_id": p["lead_user_id"], "lead_name": people.get(p["lead_user_id"]),
        "created_by_name": people.get(p["created_by"]), "created_at": p["created_at"], "cancel_reason": p["cancel_reason"],
        "allowed_actions": project_actions(user, p, case) + project_extra_actions(conn, user, p),
    }


def road_names(conn) -> Dict[str, str]:
    return {r["id"]: r["name"] for r in many(conn, "SELECT id, name FROM roads")}


def visible_project_rows(conn, user: dict, road_id: Optional[str], state: Optional[str] = None,
                         q: Optional[str] = None) -> List[dict]:
    where, params = [], []
    if road_id:
        where.append("road_id = ?")
        params.append(road_id)
    if state == "active":
        where.append("execution_status IN ('PLANNED','IN_PROGRESS')")
    elif state == "done":
        where.append("execution_status = 'DONE'")
    elif state == "cancelled":
        where.append("execution_status = 'CANCELLED'")
    elif state == "past":
        where.append("execution_status IN ('DONE','CANCELLED')")
    if user["role"] == "DEPARTMENT":
        where.append("owner_org_id = ?")
        params.append(user["org_id"])
    elif user["role"] == "CONTRACTOR":
        where.append("assigned_contractor_id = ?")
        params.append(user["org_id"])
    sql = "SELECT * FROM projects%s ORDER BY road_id, earliest_start, id" % (" WHERE " + " AND ".join(where) if where else "")
    rows = many(conn, sql, tuple(params))
    if q and q.strip():
        rn = road_names(conn)
        words = q.lower().split()
        rows = [r for r in rows if all(w in " ".join([r["id"], r["title"], r["purpose"], rn.get(r["road_id"], ""), r["execution_status"],
                                                        r["pcc_number"] or "", r["cancel_reason"] or ""]).lower() for w in words)]
    return rows


def list_projects(conn, user: dict, road_id: Optional[str], state: Optional[str] = None, q: Optional[str] = None) -> dict:
    if road_id:
        svc.get_road(conn, road_id)
    names, rn, people = svc.org_names(conn), road_names(conn), _people(conn)
    rows = visible_project_rows(conn, user, road_id, state, q)
    if state in ("done", "cancelled", "past"):
        rows.sort(key=lambda r: (r["verified_on"] or r["actual_end"] or r["created_at"]), reverse=True)
    return {"items": [project_out(conn, p, user, names, rn, people=people) for p in rows]}


def get_project_detail(conn, user: dict, project_id: str) -> dict:
    p = svc.get_project(conn, project_id)
    visible = (user["role"] in ("ADMIN", "INSPECTOR")
               or (user["role"] == "DEPARTMENT" and (p["owner_org_id"] == user["org_id"]
                                                     or one(conn, "SELECT 1 AS x FROM road_expected_depts WHERE road_id = ? AND org_id = ?",
                                                            (p["road_id"], user["org_id"]))))
               or (user["role"] == "CONTRACTOR" and p["assigned_contractor_id"] == user["org_id"]))
    if not visible:
        raise forbidden("You cannot see this project.")
    return p


# ---------------------------------------------------------------- cases
def case_actions(conn, user: dict, case: dict, state: dict) -> List[str]:
    a: List[str] = []
    live = svc.live_projects(conn, case["id"])
    started = svc.case_started(conn, case["id"])
    if case["status"] == "DRAFT" and live and not started and (
            user["role"] == "ADMIN" or (user["role"] == "DEPARTMENT" and any(p["owner_org_id"] == user["org_id"] for p in live))):
        a.append("GENERATE_PLAN")
    if user["role"] == "CONTRACTOR" and case["status"] == "CONTRACTOR_REVIEW" and \
            any(r["contractor_id"] == user["org_id"] for r in state["pending_responses"]):
        a.append("RESPOND")
    if user["role"] == "DEPARTMENT" and case["status"] == "DEPARTMENT_REVIEW" and \
            any(r["org_id"] == user["org_id"] for r in state["pending_approvals"]):
        a.append("APPROVE_PLAN")
    if user["role"] == "ADMIN" and case["status"] not in ("DRAFT", "COMPLETED"):
        a.append("REVIEW_CASE")
    if user["role"] == "DEPARTMENT" and one(conn, "SELECT 1 AS x FROM road_expected_depts WHERE road_id = ? AND org_id = ?",
                                            (case["road_id"], user["org_id"])):
        a.append("DECLARE_WORKS")
    return a


def declaration_rows(conn, case: dict, plan: Optional[dict], names: Dict[str, str]) -> List[dict]:
    road = svc.get_road(conn, case["road_id"])
    horizon = s2d(plan["horizon_end"]) if plan and plan.get("horizon_end") else None
    out = []
    for r in many(conn, "SELECT org_id FROM road_expected_depts WHERE road_id = ? ORDER BY org_id", (road["id"],)):
        decl = one(conn, "SELECT * FROM declarations WHERE road_id = ? AND org_id = ? ORDER BY id DESC LIMIT 1", (road["id"], r["org_id"]))
        problem = svc.coverage_problem(conn, road, r["org_id"], names, horizon, svc.today(conn))
        out.append({"org_id": r["org_id"], "org_name": names.get(r["org_id"]),
                    "status": problem["code"] if problem else "CURRENT", "message": problem["message"] if problem else None,
                    "mode": decl["mode"] if decl else None, "covers_through": decl["covers_through"] if decl else None,
                    "valid_until": decl["valid_until"] if decl else None, "registry_version": decl["registry_version"] if decl else None})
    return out


def case_detail(conn, user: dict, case_id: str) -> dict:
    case = svc.get_case(conn, case_id)
    if not svc.case_participant(conn, user, case):
        raise forbidden("You are not part of this coordination case.")
    names, rn = svc.org_names(conn), road_names(conn)
    latest = svc.plan_row(conn, case_id)
    plan = svc.current_plan(conn, case)
    state = svc.consent_state(conn, case, plan)
    projects = svc.live_projects(conn, case_id)
    by_id = {p["id"]: p for p in projects}
    show_schedule = plan is not None and plan["outcome"] == scheduler.PLAN_FOUND and case["status"] != "DRAFT"
    label = "CONFIRMED" if case["status"] in ("APPROVED", "COMPLETED") else "PROPOSED"
    schedule = []
    for i in (plan["schedule"] if show_schedule else []):
        p = by_id.get(i["project_id"])
        if not p:
            continue
        schedule.append({"project_id": p["id"], "project_version": p["version"], "title": p["title"], "kind": p["kind"],
                         "start": i["start"], "end": i["end"], "date_label": label,
                         "owner_org_id": p["owner_org_id"], "owner_org_name": names.get(p["owner_org_id"]),
                         "contractor_id": p["assigned_contractor_id"], "contractor_name": names.get(p["assigned_contractor_id"]),
                         "execution_status": p["execution_status"], "actual_start": p["actual_start"],
                         "actual_end": p["actual_end"], "inspection_status": svc.inspection_status(conn, p)})
    if latest and case["status"] != "DRAFT":
        assessment = {"outcome": latest["outcome"], "messages": latest["messages"], "violations": latest["violations"],
                      "plan_version": latest["plan_version"]}
    elif latest:
        assessment = {"outcome": None, "messages": ["The plan is being prepared again. Generate a new plan to continue."],
                      "violations": [], "plan_version": latest["plan_version"]}
    else:
        assessment = {"outcome": None, "messages": ["No plan has been generated yet."], "violations": [], "plan_version": 0}
    resp_out = []
    for r in state["responses"]:
        pr = by_id.get(r["project_id"])
        resp_out.append({"project_id": r["project_id"], "plan_version": r["plan_version"], "decision": r["decision"],
                         "reason": r["reason"], "earliest_start": r["earliest_start"], "recorded_at": r["recorded_at"],
                         "project_title": pr["title"] if pr else None,
                         "contractor_name": names.get(pr["assigned_contractor_id"]) if pr else None})
    appr_out = [{"org_id": a["org_id"], "plan_version": a["plan_version"], "decision": a["decision"], "reason": a["reason"],
                 "recorded_at": a["recorded_at"], "org_name": names.get(a["org_id"])} for a in state["approvals"]]
    hold = svc.hold_code(conn, case)
    expected = [r["org_id"] for r in many(conn, "SELECT org_id FROM road_expected_depts WHERE road_id = ? ORDER BY org_id", (case["road_id"],))]
    excluded = latest["excluded"] if latest else []
    incidents = many(conn, "SELECT id, project_id, kind, description, occurred_date, status, recorded_at FROM incidents "
                           "WHERE case_id = ? ORDER BY id", (case_id,))
    return {
        "id": case["id"], "road_id": case["road_id"], "road_name": rn.get(case["road_id"]),
        "version": case["version"], "status": case["status"], "plan_version": case["plan_version"],
        "deadline_at": case["review_deadline_at"], "assessment": assessment, "schedule": schedule,
        "responses": resp_out, "approvals": appr_out,
        "pending_responses": state["pending_responses"], "pending_approvals": state["pending_approvals"],
        "required_departments": state["required_departments"], "coverage_required": expected,
        "declarations": declaration_rows(conn, case, plan, names),
        "hold": bool(hold), "hold_reason": hold, "public_reason": PUBLIC_REASONS.get(hold) if hold else case["public_reason"],
        "excluded": excluded, "incidents": incidents,
        "horizon_end": (latest["horizon_end"] if latest else None),
        "projects": [project_out(conn, p, user, names, rn, case, plan) for p in projects],
        "cancelled_projects": [{"id": p["id"], "title": p["title"]} for p in
                               many(conn, "SELECT id, title FROM projects WHERE case_id = ? AND execution_status = 'CANCELLED'", (case_id,))],
        "completed_on": case["completed_on"], "audit_url": "/api/v1/cases/%s/audit" % case["id"],
        "allowed_actions": case_actions(conn, user, case, state),
    }


def list_cases(conn, user: dict, road_id: Optional[str]) -> dict:
    if road_id:
        svc.get_road(conn, road_id)
    names, rn = svc.org_names(conn), road_names(conn)
    items = []
    sql = "SELECT * FROM cases%s ORDER BY road_id, created_at, id" % (" WHERE road_id = ?" if road_id else "")
    for case in many(conn, sql, (road_id,) if road_id else ()):
        if not svc.case_participant(conn, user, case):
            continue
        plan = svc.current_plan(conn, case)
        state = svc.consent_state(conn, case, plan)
        hold = svc.hold_code(conn, case)
        items.append({"id": case["id"], "road_id": case["road_id"], "road_name": rn.get(case["road_id"]),
                      "status": case["status"], "version": case["version"], "plan_version": case["plan_version"],
                      "deadline_at": case["review_deadline_at"], "hold": bool(hold), "hold_reason": hold,
                      "project_count": len(svc.live_projects(conn, case["id"])),
                      "allowed_actions": case_actions(conn, user, case, state)})
    return {"items": items}


# --------------------------------------------------------------- public
CASE_WAITING = {
    "DRAFT": "The plan for this road is being prepared.",
    "CONTRACTOR_REVIEW": "Waiting for contractors to respond to the proposed dates.",
    "DEPARTMENT_REVIEW": "Waiting for departments to approve the plan.",
}


def public_road(conn, road_id: str) -> dict:
    road = svc.get_road(conn, road_id)
    names = svc.org_names(conn)
    case = one(conn, "SELECT * FROM cases WHERE road_id = ? AND status <> 'COMPLETED'", (road_id,))
    plan = svc.current_plan(conn, case) if case else None
    projects = many(conn, "SELECT * FROM projects WHERE road_id = ? ORDER BY earliest_start, id", (road_id,))
    latest = svc.plan_row(conn, case["id"]) if case else None
    excluded_ids = {e["project_id"] for e in (latest["excluded"] if latest else [])}
    cards = []
    for p in projects:
        pcase = case if case and p["case_id"] == case["id"] else (svc.get_case(conn, p["case_id"]) if p["case_id"] else None)
        pplan = plan if pcase and case and pcase["id"] == case["id"] else (svc.current_plan(conn, pcase) if pcase else None)
        item = _plan_item(pplan, p["id"]) if pcase and pcase["status"] != "DRAFT" else None
        confirmed = bool(item and pcase["status"] in ("APPROVED", "COMPLETED"))
        reason = None
        if p["execution_status"] == "CANCELLED":
            reason = "Cancelled before work started."
        elif p["execution_status"] == "DONE" and p["delay_reason"]:
            reason = "Finished later than planned."
        elif pcase and pcase["status"] not in ("COMPLETED",):
            hold = svc.hold_code(conn, pcase)
            if hold:
                reason = PUBLIC_REASONS[hold]
            elif pcase["public_reason"]:
                reason = pcase["public_reason"]
            elif p["id"] in excluded_ids:
                reason = "Outside the current review period; shown for information."
        cards.append({
            "id": p["id"], "title": p["title"], "purpose": p["purpose"], "kind": p["kind"],
            "owner_org_name": names.get(p["owner_org_id"]), "contractor_name": names.get(p["assigned_contractor_id"]),
            "execution_status": p["execution_status"], "case_status": pcase["status"] if pcase else None,
            "proposed_start": item["start"] if item else None, "proposed_end": item["end"] if item else None,
            "confirmed_start": item["start"] if confirmed else None, "confirmed_end": item["end"] if confirmed else None,
            "actual_start": p["actual_start"], "actual_end": p["actual_end"], "verified_on": p["verified_on"],
            "public_reason": reason,
        })
    notices: List[str] = []
    if case:
        hold = svc.hold_code(conn, case)
        if hold:
            notices.append(PUBLIC_REASONS[hold])
        elif case["public_reason"]:
            notices.append(case["public_reason"])
        elif case["status"] in CASE_WAITING and projects:
            notices.append(CASE_WAITING[case["status"]])
        if case["status"] == "APPROVED" and plan and plan["outcome"] == scheduler.PLAN_FOUND:
            has_surface = any(p["kind"] == "RESURFACING" and p["execution_status"] == "PLANNED" for p in projects)
            if has_surface:
                for r in many(conn, "SELECT org_id FROM road_expected_depts WHERE road_id = ? ORDER BY org_id", (road_id,)):
                    problem = svc.coverage_problem(conn, road, r["org_id"], names, s2d(plan["horizon_end"]), svc.today(conn))
                    if problem:
                        notices.append("Waiting for %s to confirm its planned work." % names.get(r["org_id"], r["org_id"]))
    clk = svc.clock(conn)
    return {"road": {"id": road["id"], "name": road["name"], "lat": road["lat"], "lng": road["lng"]},
            "as_of": {"date": clk["date"], "label": "Simulated demo date"},
            "case": ({"id": case["id"], "status": case["status"], "public_reason": notices[0] if notices else None}
                     if case else None),
            "projects": cards, "notices": notices,
            "footer": "Checks known registered work; cannot physically prevent unregistered excavation."}


# ---------------------------------------------------------------- audit
def audit_events(conn, user: dict, case_id: str) -> dict:
    case = svc.get_case(conn, case_id)
    if not svc.case_participant(conn, user, case):
        raise forbidden("You are not part of this coordination case.")
    rows = many(conn, "SELECT id, recorded_at, actor_name, action, reason FROM audit WHERE case_id = ? ORDER BY id", (case_id,))
    return {"items": rows}
