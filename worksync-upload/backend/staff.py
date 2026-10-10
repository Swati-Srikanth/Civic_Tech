"""The staff window beyond a single task: an overview, the department's team and what each person is working on,
an activity trail, per-project history, project assignment and CSV export.

Who sees what:
* ADMIN (the coordinator): every department.
* A department HEAD: everything in their own department, every colleague, and what each is working on.
* Other department staff: their department's overview numbers, and only their own work and actions.
* Contractors and inspectors: none of this (they have their own project views).
"""
from __future__ import annotations

import csv
import io
import json
from typing import Callable, Dict, List, Optional

import auth
import complaints as cx
import service as svc
from db import many, one
from errors import ApiError, forbidden, invalid, invalid_state, not_found
from scheduler import human

CLOSED = ("RESOLVED", "CONFIRMED_FIXED", "REJECTED")


def scope_org(user: dict, department_id: Optional[str] = None) -> Optional[str]:
    """The organisation a person's numbers are about: their own, or (coordinator only) any or all."""
    if user["role"] == "ADMIN":
        return department_id or None
    if user["role"] == "DEPARTMENT":
        return user["org_id"]
    raise forbidden("This view is for municipal departments and the coordinator.")


def is_overseer(user: dict) -> bool:
    return user["role"] == "ADMIN" or (user["role"] == "DEPARTMENT" and bool(user.get("is_head")))


def _mean(xs: List[int]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _activity_rows(conn, org: Optional[str], actor_id: Optional[str], limit: int, offset: int = 0) -> List[dict]:
    where, params = ["action NOT IN ('SIGNED_IN','SIGNED_OUT')"], []                   # sign-ins are not work
    if org:
        where.append("(org_id = ? OR project_id IN (SELECT id FROM projects WHERE owner_org_id = ?))")
        params += [org, org]
    if actor_id:
        where.append("actor_user_id = ?")
        params.append(actor_id)
    sql = "SELECT id, recorded_at, actor_user_id, actor_name, action, reason, case_id, project_id, road_id, details_json, org_id FROM audit"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = many(conn, sql + " ORDER BY id DESC LIMIT ? OFFSET ?", tuple(params) + (limit, offset))
    out = []
    for r in rows:
        d = json.loads(r.pop("details_json") or "{}")
        r["reference"] = d.get("reference")
        r["detail"] = d.get("to_name") or d.get("title") or d.get("name")
        out.append(r)
    return out


# ---------------------------------------------------------------- overview
def overview(conn, user: dict, department_id: Optional[str] = None) -> dict:
    org = scope_org(user, department_id)
    names = svc.org_names(conn)
    probs = cx.list_for_staff(conn, user, scope="all")["items"]
    if org and user["role"] == "ADMIN":
        probs = [p for p in probs if p["department_id"] == org]
    open_p = [p for p in probs if p["status"] in cx.OPEN]
    closed_p = [p for p in probs if p["status"] not in cx.OPEN]
    cats = {}
    for p in probs:
        c = cats.setdefault(p["category"], {"category": p["category"], "label": p["category_label"], "open": 0, "closed": 0})
        c["open" if p["status"] in cx.OPEN else "closed"] += 1
    attention = []
    for p in open_p:
        reasons = []
        if p["escalation_level"]:
            reasons.append(p["escalation_text"] or "escalated")
        if p["overdue"]:
            reasons.append("promised date missed")
        if p["priority"] in ("URGENT", "HIGH"):
            reasons.append(p["priority_text"].lower())
        if p["department_id"] and not p["assigned_user_id"]:
            reasons.append("nobody is working on it yet")
        if not p["department_id"]:
            reasons.append("not yet sent to a department")
        if reasons:
            attention.append({"kind": "complaint", "id": p["id"], "title": p["category_label"], "department_name": p["department_name"],
                              "priority": p["priority"], "reason": "; ".join(reasons).capitalize(), "assigned_name": p["assigned_name"]})
    attention.sort(key=lambda a: (-cx.PRIORITIES.index(a["priority"]), a["title"]))

    # projects in scope
    sql = "SELECT * FROM projects" + (" WHERE owner_org_id = ?" if org else "") + " ORDER BY id"
    projects = many(conn, sql, (org,) if org else ())
    by_exec = {k: 0 for k in ("PLANNED", "IN_PROGRESS", "DONE", "CANCELLED")}
    for p in projects:
        by_exec[p["execution_status"]] += 1
    by_case: Dict[str, int] = {}
    holds = 0
    for p in projects:
        if p["case_id"] and p["execution_status"] not in ("DONE", "CANCELLED"):
            case = svc.get_case(conn, p["case_id"])
            by_case[case["status"]] = by_case.get(case["status"], 0) + 1
            reason = None
            if case["status"] == "BLOCKED":
                reason = "Its coordination plan needs review"
            elif svc.hold_code(conn, case):
                holds += 1
                reason = "On hold: " + svc.PUBLIC_REASONS[svc.hold_code(conn, case)].rstrip(".").lower()
            if reason:
                attention.append({"kind": "project", "id": p["id"], "title": p["title"], "department_name": names.get(p["owner_org_id"]),
                                  "priority": "HIGH", "reason": reason, "assigned_name": None})
    mine_c = [p for p in open_p if p["assigned_user_id"] == user["id"]]
    mine_p = [p for p in projects if p["lead_user_id"] == user["id"] and p["execution_status"] in ("PLANNED", "IN_PROGRESS")]
    return {
        "scope": {"department_id": org, "department_name": names.get(org) if org else "All departments",
                  "is_overseer": is_overseer(user)},
        "complaints": {
            "open": len(open_p), "urgent": sum(1 for p in open_p if p["priority"] == "URGENT"),
            "high": sum(1 for p in open_p if p["priority"] == "HIGH"), "overdue": sum(1 for p in open_p if p["overdue"]),
            "escalated": sum(1 for p in open_p if p["escalation_level"] >= 1),
            "unassigned": sum(1 for p in open_p if p["department_id"] and not p["assigned_user_id"]),
            "unrouted": sum(1 for p in open_p if not p["department_id"]),
            "awaiting_confirmation": sum(1 for p in probs if p["status"] == "RESOLVED"),
            "reopened": sum(1 for p in probs if p["status"] == "REOPENED"),
            "closed": len(closed_p), "total": len(probs),
            "avg_resolution_days": _mean([p["resolution_days"] for p in probs if p["resolution_days"] is not None]),
            "by_category": sorted(cats.values(), key=lambda c: -(c["open"] + c["closed"])),
        },
        "projects": {"total": len(projects), **{k.lower(): v for k, v in by_exec.items()},
                     "awaiting_agreement": by_case.get("CONTRACTOR_REVIEW", 0) + by_case.get("DEPARTMENT_REVIEW", 0),
                     "agreed": by_case.get("APPROVED", 0), "blocked": by_case.get("BLOCKED", 0), "on_hold": holds},
        "needs_attention": attention[:10],
        "my_work": {"open_complaints": len(mine_c), "overdue": sum(1 for p in mine_c if p["overdue"]), "active_projects": len(mine_p)},
        "recent_activity": _activity_rows(conn, org, None if is_overseer(user) else user["id"], 10),
    }


# -------------------------------------------------------------------- team
def _staff_users(conn, org: Optional[str]) -> List[dict]:
    sql = ("SELECT u.id, u.name, u.org_id, u.is_head, o.name AS org_name FROM users u JOIN orgs o ON o.id = u.org_id "
           "WHERE u.role = 'DEPARTMENT'" + (" AND u.org_id = ?" if org else "") + " ORDER BY o.name, u.is_head DESC, u.name")
    return many(conn, sql, (org,) if org else ())


def _member_stats(conn, u: dict, probs: List[dict], projects: List[dict]) -> dict:
    mine = [p for p in probs if p["assigned_user_id"] == u["id"]]
    open_m = [p for p in mine if p["status"] in cx.OPEN]
    last = one(conn, "SELECT MAX(recorded_at) AS t, "
                     "SUM(CASE WHEN action NOT IN ('SIGNED_IN','SIGNED_OUT') THEN 1 ELSE 0 END) AS n FROM audit WHERE actor_user_id = ?", (u["id"],))
    last["n"] = last["n"] or 0
    led = [p for p in projects if p["lead_user_id"] == u["id"]]
    return {
        "id": u["id"], "name": u["name"], "is_head": bool(u["is_head"]), "department_id": u["org_id"], "department_name": u["org_name"],
        "open_complaints": len(open_m), "overdue": sum(1 for p in open_m if p["overdue"]),
        "escalated": sum(1 for p in open_m if p["escalation_level"] >= 1),
        "awaiting_confirmation": sum(1 for p in mine if p["status"] == "RESOLVED"),
        "resolved_total": sum(1 for p in mine if p["resolved_on"]),
        "avg_resolution_days": _mean([p["resolution_days"] for p in mine if p["resolution_days"] is not None]),
        "active_projects": sum(1 for p in led if p["execution_status"] in ("PLANNED", "IN_PROGRESS")),
        "completed_projects": sum(1 for p in led if p["execution_status"] == "DONE"),
        "actions": last["n"], "last_active": last["t"],
    }


def team(conn, user: dict, department_id: Optional[str] = None) -> dict:
    if not is_overseer(user):
        raise forbidden("Only the head of department or the coordinator can see the whole team.")
    org = scope_org(user, department_id)
    probs = cx.list_for_staff(conn, user, scope="all")["items"]
    projects = many(conn, "SELECT * FROM projects")
    members = [_member_stats(conn, u, probs, projects) for u in _staff_users(conn, org)]
    unassigned = [p for p in probs if p["status"] in cx.OPEN and p["department_id"] and not p["assigned_user_id"]
                  and (org is None or p["department_id"] == org)]
    return {"items": members, "unassigned_complaints": len(unassigned),
            "unassigned_projects": sum(1 for p in projects if not p["lead_user_id"] and p["execution_status"] in ("PLANNED", "IN_PROGRESS")
                                       and (org is None or p["owner_org_id"] == org))}


def team_member(conn, user: dict, user_id: str) -> dict:
    u = one(conn, "SELECT u.id, u.name, u.org_id, u.is_head, o.name AS org_name FROM users u JOIN orgs o ON o.id = u.org_id "
                  "WHERE u.id = ? AND u.role = 'DEPARTMENT'", (user_id,))
    if not u:
        raise not_found("Staff member")
    allowed = user["id"] == u["id"] or user["role"] == "ADMIN" or (user["role"] == "DEPARTMENT" and user.get("is_head") and user["org_id"] == u["org_id"])
    if not allowed:
        raise forbidden("You can see your own work. The head of department and the coordinator can see everyone's.")
    probs = [p for p in cx.list_for_staff(conn, user, scope="all")["items"] if p["assigned_user_id"] == u["id"]]
    projects = many(conn, "SELECT * FROM projects WHERE lead_user_id = ? ORDER BY id", (u["id"],))
    names, rn = svc.org_names(conn), {r["id"]: r["name"] for r in many(conn, "SELECT id, name FROM roads")}
    return {
        "member": _member_stats(conn, u, cx.list_for_staff(conn, user, scope="all")["items"], many(conn, "SELECT * FROM projects")),
        "open_complaints": [{"id": p["id"], "category_label": p["category_label"], "priority": p["priority"], "priority_text": p["priority_text"],
                             "status_text": p["status_text"], "due_on": p["due_on"], "overdue": p["overdue"], "escalation_text": p["escalation_text"],
                             "report_count": p["report_count"], "days_open": p["days_open"]} for p in probs if p["status"] in cx.OPEN],
        "closed_complaints": [{"id": p["id"], "category_label": p["category_label"], "status_text": p["status_text"], "resolved_on": p["resolved_on"],
                               "resolution_days": p["resolution_days"]} for p in probs if p["status"] not in cx.OPEN][:15],
        "projects": [{"id": p["id"], "title": p["title"], "road_name": rn.get(p["road_id"]), "execution_status": p["execution_status"],
                      "case_id": p["case_id"], "verified_on": p["verified_on"]} for p in projects],
        "recent_actions": _activity_rows(conn, None, u["id"], 20),
    }


# ---------------------------------------------------------------- activity
def activity(conn, user: dict, limit: int = 50, offset: int = 0, user_id: Optional[str] = None,
             department_id: Optional[str] = None) -> dict:
    org = scope_org(user, department_id)
    if user_id:
        if not is_overseer(user) and user_id != user["id"]:
            raise forbidden("You can see your own actions. The head of department and the coordinator can see everyone's.")
        actor = user_id
    else:
        actor = None if is_overseer(user) else user["id"]
    return {"items": _activity_rows(conn, org, actor, min(max(limit, 1), 200), max(offset, 0)), "everyone": actor is None}


# --------------------------------------------------------- project history
def project_history(conn, user: dict, project_id: str, project_visible: Callable) -> dict:
    p = project_visible(conn, user, project_id)
    people = {u["id"]: u["name"] for u in many(conn, "SELECT id, name FROM users")}
    names = svc.org_names(conn)
    events: List[dict] = []
    for a in many(conn, "SELECT id, recorded_at, actor_name, action, reason, details_json FROM audit WHERE project_id = ? ORDER BY id", (project_id,)):
        events.append({"at": a["recorded_at"], "kind": "ACTIVITY", "who": a["actor_name"], "what": a["action"], "note": a["reason"]})
    for i in many(conn, "SELECT * FROM inspections WHERE project_id = ? ORDER BY id", (project_id,)):
        events.append({"at": i["recorded_at"], "kind": "INSPECTION", "who": people.get(i["inspector_user_id"], "Inspector"),
                       "what": "%s inspection: %s (on %s)" % ("Release" if i["kind"] == "UTILITY_RELEASE" else "Final surface", i["result"], human(svc.s2d(i["inspected_on"]))),
                       "note": i["notes"]})
    for i in many(conn, "SELECT * FROM incidents WHERE project_id = ? ORDER BY id", (project_id,)):
        events.append({"at": i["recorded_at"], "kind": "INCIDENT", "who": people.get(i["reporter_user_id"], "Reporter"),
                       "what": "Reported: " + i["kind"].replace("_", " ").lower(), "note": i["description"]})
    for r in many(conn, "SELECT * FROM responses WHERE project_id = ? ORDER BY id", (project_id,)):
        events.append({"at": r["recorded_at"], "kind": "CONSENT", "who": names.get(p["assigned_contractor_id"]),
                       "what": "Contractor %s (plan version %d)" % (r["decision"].lower(), r["plan_version"]), "note": r["reason"]})
    if p["case_id"]:
        for a in many(conn, "SELECT * FROM approvals WHERE case_id = ? AND org_id = ? ORDER BY id", (p["case_id"], p["owner_org_id"])):
            events.append({"at": a["recorded_at"], "kind": "CONSENT", "who": names.get(a["org_id"]),
                           "what": "Department %s (plan version %d)" % (a["decision"].lower(), a["plan_version"]), "note": a["reason"]})
    events.sort(key=lambda e: e["at"])
    return {"project": {"id": p["id"], "title": p["title"], "execution_status": p["execution_status"], "created_by": people.get(p["created_by"]),
                        "lead": people.get(p["lead_user_id"]), "created_at": p["created_at"], "actual_start": p["actual_start"],
                        "actual_end": p["actual_end"], "verified_on": p["verified_on"], "pcc_number": p["pcc_number"],
                        "cancel_reason": p["cancel_reason"]},
            "events": events}


def authorize_assign_project(user: dict, project_id: str, target_id: Optional[str]) -> Callable:
    def run(conn):
        auth.require_role(user, "DEPARTMENT", "ADMIN")
        p = svc.get_project(conn, project_id)
        if user["role"] == "DEPARTMENT" and p["owner_org_id"] != user["org_id"]:
            raise forbidden("Only the owning department can assign its staff to a project.")
        if user["role"] == "DEPARTMENT" and not user.get("is_head") and (target_id != user["id"]):
            raise forbidden("Only the head of department or the coordinator can give a project to someone else. Staff can take one for themselves.")
        return {"project": p}
    return run


def assign_project(conn, user: dict, ctx: dict, body) -> dict:
    p = ctx["project"]
    svc.check_version(p["version"], body.expected_version, "project")
    if p["execution_status"] in ("DONE", "CANCELLED"):
        raise invalid_state("This project is finished; its lead can no longer change.")
    target = None
    if body.user_id:
        target = one(conn, "SELECT id, name, org_id, role FROM users WHERE id = ?", (body.user_id,))
        if not target or target["role"] != "DEPARTMENT" or target["org_id"] != p["owner_org_id"]:
            raise invalid("Choose someone from the owning department.", [svc.field_error("user_id", "That person is not in this project's department.")])
    svc.update_project(conn, p["id"], lead_user_id=target["id"] if target else None)
    svc.audit(conn, user, "PROJECT_LEAD_ASSIGNED" if target else "PROJECT_LEAD_REMOVED", None, case_id=p["case_id"], road_id=p["road_id"],
              project_id=p["id"], org_id=p["owner_org_id"], details={"to_name": target["name"] if target else None, "title": p["title"]})
    return {"id": p["id"], "version": p["version"] + 1, "case_id": p["case_id"],
            "message": ("%s now leads this project." % target["name"]) if target else "No one leads this project now."}


# --------------------------------------------------------------- CSV export
def _safe(v) -> str:
    """Neutralise spreadsheet formula injection: a cell that starts with = + - @ is stored as text."""
    t = "" if v is None else str(v)
    return ("'" + t) if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t


def _csv(header: List[str], rows: List[List]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_safe(v) for v in r])
    return buf.getvalue()


def complaints_csv(conn, user: dict) -> str:
    if user["role"] not in ("DEPARTMENT", "ADMIN"):
        raise forbidden("Complaints are handled by the responsible municipal department and the coordinator.")
    items = cx.list_for_staff(conn, user, scope="all")["items"]
    rows = []
    for p in items:
        for r in p["reports"]:
            rows.append([r["id"], p["id"], p["category_label"], p["department_name"], p["status_text"], p["priority_text"], p["report_count"],
                         p["opened_on"], p["resolved_on"], p["resolution_days"], p["assigned_name"], p["road_name"],
                         r["location_text"], r["description"], r["contact_name"], r["contact_detail"]])
    return _csv(["reference", "problem", "category", "department", "status", "priority", "reports_in_problem", "opened_on", "resolved_on",
                 "days_to_resolve", "assigned_to", "street", "location_note", "description", "contact_name", "contact_detail"], rows)


def projects_csv(conn, user: dict, visible_rows: Callable) -> str:
    if user["role"] not in ("DEPARTMENT", "ADMIN", "INSPECTOR"):
        raise forbidden("Project records are for departments, inspectors and the coordinator.")
    names, people = svc.org_names(conn), {u["id"]: u["name"] for u in many(conn, "SELECT id, name FROM users")}
    roads = {r["id"]: r["name"] for r in many(conn, "SELECT id, name FROM roads")}
    rows = []
    for p in visible_rows(conn, user, None):
        rows.append([p["id"], p["title"], p["kind"], roads.get(p["road_id"]), names.get(p["owner_org_id"]), names.get(p["assigned_contractor_id"]),
                     people.get(p["lead_user_id"]), p["execution_status"], p["earliest_start"], p["deadline"], p["actual_start"], p["actual_end"],
                     p["verified_on"], p["pcc_number"], p["cancel_reason"]])
    return _csv(["id", "title", "kind", "street", "department", "contractor", "lead_staff", "status", "earliest_start", "deadline",
                 "actual_start", "actual_end", "verified_on", "certificate", "cancel_reason"], rows)
