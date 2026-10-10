"""Workflow, clearance gate, mutations and audit for WorkSync.

All decisions live here; the frontend never recomputes them. Every mutation
runs through ``mutate`` which orders: access check -> idempotency replay ->
version checks -> business rules -> persist (change + audit + idempotency
record in one transaction).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import scheduler
from auth import require_role
from db import connect, many, one, transaction
from errors import (ApiError, forbidden, invalid, invalid_state, not_found, stale_plan,
                    stale_version)
from scheduler import Job, human

IST = timezone(timedelta(hours=5, minutes=30))
REVIEW_HOURS = 48
DONE_STATES = ("DONE",)
LIVE = "execution_status <> 'CANCELLED'"

# Fixed, resident-safe phrases. Free text entered by staff is never published.
PUBLIC_REASONS = {
    "NO_SEQUENTIAL_PLAN": "No workable sequence of dates has been found yet; the departments are reviewing.",
    "UNASSESSABLE": "Planning information is incomplete or outside what this demo can plan; the case is under review.",
    "CONTRACTOR_REJECTED": "A contractor could not accept the proposed dates; the plan is under review.",
    "DEPARTMENT_REJECTED": "A department did not approve the plan; it is under review.",
    "TIMEOUT": "A review deadline passed without a full response; the plan needs review.",
    "KEPT_BLOCKED": "The plan is being kept on hold while it is reviewed.",
    "INCIDENT": "Work is on hold while a reported issue is reviewed.",
    "FAILED_INSPECTION": "Work is on hold after an inspection did not pass.",
    "DELAY": "Work finished later than planned; the case is under review.",
    "MATERIAL_CHANGE_AFTER_START": "Registered work changed after work began; the case is under review.",
}


# ------------------------------------------------------------------ time
def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def real_now() -> str:
    return iso(datetime.now(timezone.utc))


def hmac_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def d2s(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def s2d(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


def clock(conn: sqlite3.Connection) -> dict:
    return one(conn, "SELECT date, version FROM demo_clock WHERE id = 1")


def today(conn: sqlite3.Connection) -> date:
    return s2d(clock(conn)["date"])


def demo_now(conn: sqlite3.Connection) -> datetime:
    """The demo clock only moves by explicit advance: 08:00 Asia/Kolkata on the demo date."""
    return datetime.combine(today(conn), time(8, 0), tzinfo=IST).astimezone(timezone.utc)


def review_deadline(conn: sqlite3.Connection) -> str:
    return iso(demo_now(conn) + timedelta(hours=REVIEW_HOURS))


# ----------------------------------------------------------------- audit
def audit(conn, user: Optional[dict], action: str, reason: Optional[str] = None, case_id: Optional[str] = None,
          road_id: Optional[str] = None, project_id: Optional[str] = None, details: Optional[dict] = None,
          org_id: Optional[str] = None) -> None:
    """Append one audit row. ``org_id`` says which organisation it belongs to (defaults to the actor's own),
    which is how a head of department sees everything their team did."""
    org = org_id if org_id is not None else (user.get("org_id") if user else None)
    conn.execute(
        "INSERT INTO audit(recorded_at, actor_user_id, actor_name, action, reason, case_id, road_id, project_id, details_json, org_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (real_now(), user["id"] if user else None, user["name"] if user else "System", action, reason,
         case_id, road_id, project_id, json.dumps(details or {}, default=str), org))


# ------------------------------------------------------------- loaders
def get_road(conn, road_id: str) -> dict:
    r = one(conn, "SELECT * FROM roads WHERE id = ?", (road_id,))
    if not r:
        raise not_found("Road")
    return r


def get_org(conn, org_id: str) -> dict:
    o = one(conn, "SELECT * FROM orgs WHERE id = ?", (org_id,))
    if not o:
        raise not_found("Organisation")
    return o


def org_names(conn) -> Dict[str, str]:
    return {o["id"]: o["name"] for o in many(conn, "SELECT id, name FROM orgs")}


def get_project(conn, project_id: str) -> dict:
    p = one(conn, "SELECT * FROM projects WHERE id = ?", (project_id,))
    if not p:
        raise not_found("Project")
    return p


def get_case(conn, case_id: str) -> dict:
    c = one(conn, "SELECT * FROM cases WHERE id = ?", (case_id,))
    if not c:
        raise not_found("Case")
    return c


def live_projects(conn, case_id: str) -> List[dict]:
    return many(conn, "SELECT * FROM projects WHERE case_id = ? AND %s ORDER BY id" % LIVE, (case_id,))


def case_started(conn, case_id: str) -> bool:
    return bool(one(conn, "SELECT 1 AS x FROM projects WHERE case_id = ? AND execution_status IN ('IN_PROGRESS','DONE')",
                    (case_id,)))


def plan_row(conn, case_id: str, version: Optional[int] = None) -> Optional[dict]:
    if version is None:
        row = one(conn, "SELECT * FROM plans WHERE case_id = ? ORDER BY plan_version DESC LIMIT 1", (case_id,))
    else:
        row = one(conn, "SELECT * FROM plans WHERE case_id = ? AND plan_version = ?", (case_id, version))
    if not row:
        return None
    row["messages"] = json.loads(row.pop("messages_json"))
    row["violations"] = json.loads(row.pop("violations_json"))
    row["schedule"] = json.loads(row.pop("schedule_json"))
    row["excluded"] = json.loads(row.pop("excluded_json"))
    return row


def current_plan(conn, case: dict) -> Optional[dict]:
    """The plan row matching the case's current plan_version."""
    if case["plan_version"] < 1:
        return None
    return plan_row(conn, case["id"], case["plan_version"])


def latest_inspection(conn, project_id: str, kind: str) -> Optional[dict]:
    return one(conn, "SELECT * FROM inspections WHERE project_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
               (project_id, kind))


def inspection_kind_for(project: dict) -> str:
    return "UTILITY_RELEASE" if project["kind"] == "UTILITY" else "FINAL_SURFACE"


def inspection_status(conn, project: dict) -> str:
    insp = latest_inspection(conn, project["id"], inspection_kind_for(project))
    return insp["result"] if insp else "PENDING"


def hold_code(conn, case: dict) -> Optional[str]:
    """Why new starts are blocked for the whole case (None if no hold)."""
    if case.get("hold_reason"):
        return case["hold_reason"]
    if one(conn, "SELECT 1 AS x FROM incidents WHERE case_id = ? AND status = 'OPEN'", (case["id"],)):
        return "INCIDENT"
    for p in live_projects(conn, case["id"]):
        if p["execution_status"] == "DONE" and inspection_status(conn, p) == "FAIL":
            return "FAILED_INSPECTION"
    return None


def protected_until(conn, road_id: str, exclude_case_id: Optional[str]) -> Optional[date]:
    row = one(conn,
              "SELECT MAX(actual_end) AS e FROM projects WHERE road_id = ? AND kind = 'RESURFACING' "
              "AND execution_status = 'DONE' AND actual_end IS NOT NULL AND (case_id IS NULL OR case_id <> ?)",
              (road_id, exclude_case_id or ""))
    if row and row["e"]:
        return s2d(row["e"]) + timedelta(days=scheduler.PROTECTED_DAYS)
    return None


def to_job(p: dict) -> Job:
    return Job(id=p["id"], kind=p["kind"], earliest_start=s2d(p["earliest_start"]), deadline=s2d(p["deadline"]),
               duration=p["duration_days"], title=p["title"])


def consent_state(conn, case: dict, plan: Optional[dict]) -> dict:
    """Who has answered the exact current plan version and who is still pending."""
    if not plan or plan["outcome"] != scheduler.PLAN_FOUND:
        return {"responses": [], "approvals": [], "pending_responses": [], "pending_approvals": [],
                "required_departments": []}
    pv = plan["plan_version"]
    projects = {p["id"]: p for p in live_projects(conn, case["id"])}
    names = org_names(conn)
    responses = many(conn, "SELECT * FROM responses WHERE case_id = ? AND plan_version = ? ORDER BY id", (case["id"], pv))
    approvals = many(conn, "SELECT * FROM approvals WHERE case_id = ? AND plan_version = ? ORDER BY id", (case["id"], pv))
    answered = {r["project_id"] for r in responses}
    pending_resp = []
    owners = set()
    for item in plan["schedule"]:
        p = projects.get(item["project_id"])
        if not p:
            continue
        owners.add(p["owner_org_id"])
        if p["id"] not in answered:
            pending_resp.append({"project_id": p["id"], "title": p["title"], "contractor_id": p["assigned_contractor_id"],
                                 "contractor_name": names.get(p["assigned_contractor_id"])})
    approved = {a["org_id"] for a in approvals}
    pending_appr = [{"org_id": o, "org_name": names.get(o)} for o in sorted(owners) if o not in approved]
    return {"responses": responses, "approvals": approvals, "pending_responses": pending_resp,
            "pending_approvals": pending_appr, "required_departments": sorted(owners)}


# ------------------------------------------------------- case plumbing
def update_case(conn, case_id: str, **fields) -> None:
    sets = ", ".join("%s = ?" % k for k in fields)
    conn.execute("UPDATE cases SET %s%s version = version + 1 WHERE id = ?" % (sets, "," if sets else ""),
                 tuple(fields.values()) + (case_id,))


def update_project(conn, project_id: str, **fields) -> None:
    sets = ", ".join("%s = ?" % k for k in fields)
    conn.execute("UPDATE projects SET %s%s version = version + 1 WHERE id = ?" % (sets, "," if sets else ""),
                 tuple(fields.values()) + (project_id,))


def bump_road(conn, road_id: str, registry: bool) -> None:
    conn.execute("UPDATE roads SET version = version + 1%s WHERE id = ?"
                 % (", registry_version = registry_version + 1" if registry else ""), (road_id,))


def ensure_case(conn, road_id: str) -> Tuple[dict, bool]:
    """One active coordination case per road; repeated detection never duplicates it."""
    case = one(conn, "SELECT * FROM cases WHERE road_id = ? AND status <> 'COMPLETED'", (road_id,))
    if case:
        return case, False
    base = "case-" + road_id.split("road-", 1)[-1]
    case_id, n = base, 1
    while one(conn, "SELECT 1 AS x FROM cases WHERE id = ?", (case_id,)):
        n += 1
        case_id = "%s-%d" % (base, n)
    conn.execute("INSERT INTO cases(id, road_id, status, version, plan_version, created_at) VALUES (?,?,?,?,?,?)",
                 (case_id, road_id, "DRAFT", 1, 0, real_now()))
    conn.execute("UPDATE projects SET case_id = ? WHERE road_id = ? AND case_id IS NULL AND %s" % LIVE,
                 (case_id, road_id))
    return get_case(conn, case_id), True


def on_scope_change(conn, user: Optional[dict], case_id: str, why: str) -> dict:
    """Registered planning inputs changed. Before execution, earlier consent stops counting
    (history is kept); after execution starts the case goes on a review hold."""
    case = get_case(conn, case_id)
    if case_started(conn, case_id):
        if not case["hold_reason"]:
            update_case(conn, case_id, hold_reason="MATERIAL_CHANGE_AFTER_START")
        else:
            update_case(conn, case_id)
        audit(conn, user, "REVIEW_HOLD_PLACED", why, case_id=case_id, road_id=case["road_id"])
        return {"invalidated": False, "hold": True, "status": case["status"]}
    if case["status"] != "DRAFT":
        update_case(conn, case_id, status="DRAFT", review_deadline_at=None, public_reason=None)
        audit(conn, user, "CONSENT_INVALIDATED", why, case_id=case_id, road_id=case["road_id"],
              details={"previous_status": case["status"], "plan_version": case["plan_version"]})
        return {"invalidated": True, "hold": False, "status": "DRAFT"}
    update_case(conn, case_id)
    return {"invalidated": False, "hold": False, "status": "DRAFT"}


def run_assessment(conn, user: Optional[dict], case: dict) -> Tuple[dict, int]:
    projects = live_projects(conn, case["id"])
    started = [p["id"] for p in projects if p["execution_status"] in ("IN_PROGRESS", "DONE")]
    result = scheduler.assess([to_job(p) for p in projects], today(conn),
                              protected_until(conn, case["road_id"], case["id"]), started)
    by_id = {p["id"]: p for p in projects}
    schedule = [{"project_id": i["project_id"], "start": d2s(i["start"]), "end": d2s(i["end"]),
                 "project_version": by_id[i["project_id"]]["version"],
                 "material_version": by_id[i["project_id"]]["material_version"]} for i in result["schedule"]]
    next_version = case["plan_version"] + 1
    conn.execute(
        "INSERT INTO plans(case_id, plan_version, outcome, messages_json, violations_json, schedule_json,"
        " excluded_json, horizon_end, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (case["id"], next_version, result["outcome"], json.dumps(result["messages"]),
         json.dumps(result["violations"], default=str), json.dumps(schedule), json.dumps(result["excluded"]),
         d2s(result["horizon_end"]), user["id"] if user else None, real_now()))
    return result, next_version


def apply_plan_outcome(conn, user: Optional[dict], case: dict, result: dict, plan_version: int) -> None:
    if result["outcome"] == scheduler.PLAN_FOUND:
        update_case(conn, case["id"], plan_version=plan_version, status="CONTRACTOR_REVIEW",
                    review_deadline_at=review_deadline(conn), public_reason=None)
    else:
        update_case(conn, case["id"], plan_version=plan_version, status="BLOCKED", review_deadline_at=None,
                    public_reason=PUBLIC_REASONS[result["outcome"]])
    audit(conn, user, "PLAN_GENERATED", None, case_id=case["id"], road_id=case["road_id"],
          details={"plan_version": plan_version, "outcome": result["outcome"], "messages": result["messages"]})


def complete_case_if_done(conn, user: Optional[dict], case_id: str) -> bool:
    case = get_case(conn, case_id)
    if case["status"] not in ("APPROVED",) or hold_code(conn, case):
        return False
    plan = current_plan(conn, case)
    if not plan or plan["outcome"] != scheduler.PLAN_FOUND:
        return False
    projects = {p["id"]: p for p in live_projects(conn, case_id)}
    included = [projects[i["project_id"]] for i in plan["schedule"] if i["project_id"] in projects]
    if not included:
        return False
    for p in included:
        if p["execution_status"] != "DONE" or inspection_status(conn, p) != "PASS":
            return False
    update_case(conn, case_id, status="COMPLETED", completed_on=d2s(today(conn)), review_deadline_at=None,
                public_reason=None)
    audit(conn, user, "CASE_COMPLETED", None, case_id=case_id, road_id=case["road_id"])
    # Registered work outside the review horizon stays on the road; give it a fresh case.
    leftovers = one(conn, "SELECT 1 AS x FROM projects WHERE case_id = ? AND execution_status = 'PLANNED'", (case_id,))
    if leftovers:
        conn.execute("UPDATE projects SET case_id = NULL WHERE case_id = ? AND execution_status = 'PLANNED'", (case_id,))
        ensure_case(conn, case["road_id"])
    return True


def close_case_if_empty(conn, user: Optional[dict], case_id: str) -> None:
    case = get_case(conn, case_id)
    if case["status"] == "COMPLETED" or live_projects(conn, case_id):
        return
    update_case(conn, case_id, status="COMPLETED", completed_on=d2s(today(conn)), review_deadline_at=None,
                public_reason="All registered work in this case was cancelled before it started.")
    audit(conn, user, "CASE_CLOSED_EMPTY", None, case_id=case_id, road_id=case["road_id"])


def sweep_due_reviews(conn, user: Optional[dict] = None) -> List[str]:
    """Silence never means approval: overdue review stages become BLOCKED."""
    now = iso(demo_now(conn))
    due = many(conn, "SELECT * FROM cases WHERE status IN ('CONTRACTOR_REVIEW','DEPARTMENT_REVIEW') "
                     "AND review_deadline_at IS NOT NULL AND review_deadline_at <= ?", (now,))
    for c in due:
        update_case(conn, c["id"], status="BLOCKED", review_deadline_at=None, public_reason=PUBLIC_REASONS["TIMEOUT"])
        audit(conn, None, "REVIEW_TIMEOUT", "The 48-hour review deadline passed without a full response.",
              case_id=c["id"], road_id=c["road_id"],
              details={"was": c["status"], "plan_version": c["plan_version"], "deadline_at": c["review_deadline_at"]})
    return [c["id"] for c in due]


def sweep_command_time() -> List[str]:
    """Used by the periodic task and before every mutation (command-time deadline check):
    overdue review stages are blocked, and complaints whose promised date was missed are escalated."""
    import complaints
    conn = connect()
    try:
        now = iso(demo_now(conn))
        reviews_due = one(conn, "SELECT 1 AS x FROM cases WHERE status IN ('CONTRACTOR_REVIEW','DEPARTMENT_REVIEW') "
                                "AND review_deadline_at IS NOT NULL AND review_deadline_at <= ?", (now,))
        if not reviews_due and not complaints.escalation_due(conn):
            return []
        with transaction(conn):
            blocked = sweep_due_reviews(conn)
            complaints.escalate_overdue(conn)
            return blocked
    finally:
        conn.close()


# ------------------------------------------------------- mutate wrapper
def payload_hash(action: str, payload: Any) -> str:
    return hashlib.sha256(json.dumps({"a": action, "p": payload}, sort_keys=True, default=str).encode()).hexdigest()


def mutate(user: dict, key: str, action: str, payload: Any, authorize: Callable, perform: Callable,
           status: int = 200) -> Tuple[int, dict, bool]:
    try:
        sweep_command_time()
    except sqlite3.OperationalError:
        pass  # contention here must not hide the real request; it will be retried by the next command
    conn = connect()
    try:
        with transaction(conn):
            ctx = authorize(conn)                                   # 1. current access first
            digest = payload_hash(action, payload)
            prior = one(conn, "SELECT * FROM idempotency WHERE user_id = ? AND key = ?", (user["id"], key))
            if prior:                                               # 2. matching replay
                if prior["action"] != action or prior["payload_hash"] != digest:
                    raise ApiError(409, "IDEMPOTENCY_MISMATCH",
                                   "This Idempotency-Key was already used for a different request. "
                                   "Use a new key for a new or changed action.")
                return prior["status_code"], json.loads(prior["response_json"]), True
            body = perform(conn, ctx)                               # 3. versions, rules, persist
            body["recorded_at"] = real_now()
            conn.execute("INSERT INTO idempotency(user_id, key, action, payload_hash, status_code, response_json, recorded_at)"
                         " VALUES (?,?,?,?,?,?,?)",
                         (user["id"], key, action, digest, status, json.dumps(body, default=str), body["recorded_at"]))
            return status, body, False
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc) or "busy" in str(exc):
            raise ApiError(503, "DATABASE_BUSY", "The database is busy. Please retry the same request.")
        raise
    finally:
        conn.close()


def check_version(actual: int, expected: int, what: str) -> None:
    if actual != expected:
        raise stale_version(what)


def check_plan_version(case: dict, plan_version: int) -> None:
    if case["plan_version"] != plan_version:
        raise stale_plan()


def field_error(field: str, message: str) -> dict:
    return {"field": field, "message": message}


# ------------------------------------------------------------ projects
def authorize_create_project(user: dict, body) -> Callable:
    def run(conn):
        require_role(user, "DEPARTMENT")
        org = get_org(conn, user["org_id"])
        if org["project_kind"] != body.kind:
            raise forbidden("%s registers %s work only." % (org["name"], (org["project_kind"] or "no").lower()))
        get_road(conn, body.road_id)
        contractor = one(conn, "SELECT id FROM orgs WHERE id = ? AND kind = 'CONTRACTOR'", (body.assigned_contractor_id,))
        if not contractor:
            raise invalid("Choose a valid contractor.", [field_error("assigned_contractor_id", "Unknown contractor.")])
        return {}
    return run


def create_project(conn, user: dict, body, project_id: Optional[str] = None) -> dict:
    failures = []
    if body.earliest_start > body.deadline:
        failures.append(field_error("deadline", "Deadline must be on or after the earliest start."))
    if failures:
        raise invalid("Check the highlighted fields.", failures)
    pid = project_id or "proj-" + uuid.uuid4().hex[:8]
    case, created = ensure_case(conn, body.road_id)
    conn.execute(
        "INSERT INTO projects(id, title, purpose, road_id, kind, owner_org_id, assigned_contractor_id, earliest_start,"
        " deadline, duration_days, case_id, created_by, lead_user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, body.title, body.purpose, body.road_id, body.kind, user["org_id"], body.assigned_contractor_id,
         d2s(body.earliest_start), d2s(body.deadline), body.duration_days, case["id"], user["id"], user["id"], real_now()))
    bump_road(conn, body.road_id, registry=True)
    effect = on_scope_change(conn, user, case["id"], "New work registered on this road.")
    audit(conn, user, "PROJECT_REGISTERED", None, case_id=case["id"], road_id=body.road_id, project_id=pid,
          details={"title": body.title, "kind": body.kind, "case_created": created})
    case = get_case(conn, case["id"])
    return {"id": pid, "version": 1, "material_version": 1, "case_id": case["id"], "case_version": case["version"],
            "case_status": case["status"], "case_created": created, "consent_invalidated": effect["invalidated"],
            "message": "Project registered. It was added to the coordination case for this road."}


def authorize_owner_project(user: dict, project_id: str) -> Callable:
    def run(conn):
        require_role(user, "DEPARTMENT")
        p = get_project(conn, project_id)
        if p["owner_org_id"] != user["org_id"]:
            raise forbidden("Only the owning department can change this project.")
        return {"project": p}
    return run


MATERIAL_FIELDS = ("earliest_start", "deadline", "duration_days", "assigned_contractor_id")
REGISTRY_FIELDS = ("earliest_start", "deadline", "duration_days")


def patch_project(conn, user: dict, ctx: dict, body) -> dict:
    p = ctx["project"]
    if p["execution_status"] != "PLANNED":
        raise ApiError(409, "WORK_STARTED", "Work on this project has started or ended, so its plan can no longer be edited.")
    check_version(p["version"], body.expected_version, "project")
    changes: Dict[str, Any] = {}
    for f in ("title", "purpose", "assigned_contractor_id", "earliest_start", "deadline", "duration_days"):
        if f in body.model_fields_set and getattr(body, f) is not None:
            value = getattr(body, f)
            value = d2s(value) if isinstance(value, date) else value
            if value != p[f]:
                changes[f] = value
    if not changes:
        raise invalid("Nothing was changed.", [field_error("expected_version", "Change at least one field.")])
    if "assigned_contractor_id" in changes and not one(
            conn, "SELECT 1 AS x FROM orgs WHERE id = ? AND kind = 'CONTRACTOR'", (changes["assigned_contractor_id"],)):
        raise invalid("Choose a valid contractor.", [field_error("assigned_contractor_id", "Unknown contractor.")])
    earliest = changes.get("earliest_start", p["earliest_start"])
    deadline = changes.get("deadline", p["deadline"])
    if earliest > deadline:
        raise invalid("Check the highlighted fields.", [field_error("deadline", "Deadline must be on or after the earliest start.")])
    material = any(f in changes for f in MATERIAL_FIELDS)
    registry = any(f in changes for f in REGISTRY_FIELDS)
    extra = ", material_version = material_version + 1" if material else ""
    sets = ", ".join("%s = ?" % k for k in changes)
    conn.execute("UPDATE projects SET %s, version = version + 1%s WHERE id = ?" % (sets, extra),
                 tuple(changes.values()) + (p["id"],))
    effect = None
    if material:
        if registry:
            bump_road(conn, p["road_id"], registry=True)
        effect = on_scope_change(conn, user, p["case_id"], "Planning details of '%s' changed." % p["title"])
    audit(conn, user, "PROJECT_EDITED", None, case_id=p["case_id"], road_id=p["road_id"], project_id=p["id"],
          details={"changes": changes, "material": material})
    fresh = get_project(conn, p["id"])
    case = get_case(conn, p["case_id"])
    return {"id": p["id"], "version": fresh["version"], "material_version": fresh["material_version"],
            "case_id": p["case_id"], "case_version": case["version"], "case_status": case["status"],
            "invalidated_case": ({"id": case["id"], "version": case["version"], "status": case["status"]}
                                 if effect and (effect["invalidated"] or effect["hold"]) else None),
            "message": ("Saved. Earlier responses and approvals no longer count; fresh ones are needed."
                        if effect and effect["invalidated"] else
                        "Saved. The case is on a review hold because work has already started."
                        if effect and effect["hold"] else "Saved.")}


def cancel_project(conn, user: dict, ctx: dict, body) -> dict:
    p = ctx["project"]
    if p["execution_status"] != "PLANNED":
        raise ApiError(409, "WORK_STARTED", "Physical work has started, so this project cannot be cancelled. "
                                              "An existing trench or restoration obligation is never deleted.")
    check_version(p["version"], body.expected_version, "project")
    update_project(conn, p["id"], execution_status="CANCELLED", cancel_reason=body.reason)
    bump_road(conn, p["road_id"], registry=True)
    effect = on_scope_change(conn, user, p["case_id"], "Project '%s' was cancelled." % p["title"])
    audit(conn, user, "PROJECT_CANCELLED", body.reason, case_id=p["case_id"], road_id=p["road_id"], project_id=p["id"])
    close_case_if_empty(conn, user, p["case_id"])
    case = get_case(conn, p["case_id"])
    return {"id": p["id"], "version": p["version"] + 1, "case_id": p["case_id"], "case_version": case["version"],
            "case_status": case["status"], "message": "Project cancelled."}


# ----------------------------------------------------------- case access
def case_participant(conn, user: dict, case: dict) -> bool:
    if user["role"] in ("ADMIN", "INSPECTOR"):
        return True
    rows = many(conn, "SELECT owner_org_id, assigned_contractor_id FROM projects WHERE case_id = ?", (case["id"],))
    if user["role"] == "DEPARTMENT":
        if any(r["owner_org_id"] == user["org_id"] for r in rows):
            return True
        return bool(one(conn, "SELECT 1 AS x FROM road_expected_depts WHERE road_id = ? AND org_id = ?",
                        (case["road_id"], user["org_id"])))
    return any(r["assigned_contractor_id"] == user["org_id"] for r in rows)


def authorize_case_read(user: dict, case_id: str) -> Callable:
    def run(conn):
        case = get_case(conn, case_id)
        if not case_participant(conn, user, case):
            raise forbidden("You are not part of this coordination case.")
        return case
    return run


def authorize_generate_plan(user: dict, case_id: str) -> Callable:
    def run(conn):
        case = get_case(conn, case_id)
        if user["role"] == "ADMIN":
            return {"case": case}
        require_role(user, "DEPARTMENT")
        if not any(p["owner_org_id"] == user["org_id"] for p in live_projects(conn, case_id)):
            raise forbidden("Only a department with work in this case (or an administrator) can generate its plan.")
        return {"case": case}
    return run


def generate_plan(conn, user: dict, ctx: dict, body) -> dict:
    case = ctx["case"]
    check_version(case["version"], body.expected_version, "case")
    if case["status"] != "DRAFT":
        raise invalid_state("A plan can only be generated while the case is being prepared (status %s)." % case["status"])
    if not live_projects(conn, case["id"]):
        raise invalid("There is no registered work in this case.")
    result, version = run_assessment(conn, user, case)
    apply_plan_outcome(conn, user, case, result, version)
    fresh = get_case(conn, case["id"])
    msg = {"PLAN_FOUND": "Plan version %d created. Contractors have 48 hours to respond." % version,
           "NO_SEQUENTIAL_PLAN": "No sequential plan meets every stated deadline. The assessment was saved and the case needs review.",
           "UNASSESSABLE": "This case cannot be assessed yet. The reasons were saved and the case needs review."}[result["outcome"]]
    return {"id": case["id"], "version": fresh["version"], "case_id": case["id"], "plan_version": version,
            "status": fresh["status"], "outcome": result["outcome"], "messages": result["messages"], "message": msg}


# ------------------------------------------------------------ responses
def authorize_respond(user: dict, case_id: str, project_id: str) -> Callable:
    def run(conn):
        require_role(user, "CONTRACTOR")
        case = get_case(conn, case_id)
        p = one(conn, "SELECT * FROM projects WHERE id = ? AND case_id = ?", (project_id, case_id))
        if not p:
            raise not_found("Project in this case")
        if p["assigned_contractor_id"] != user["org_id"]:
            raise forbidden("Only the assigned contractor can respond for this project.")
        return {"case": case, "project": p}
    return run


def respond(conn, user: dict, ctx: dict, body) -> dict:
    case, p = ctx["case"], ctx["project"]
    check_plan_version(case, body.plan_version)
    check_version(case["version"], body.expected_version, "case")
    if case["status"] != "CONTRACTOR_REVIEW":
        raise invalid_state("This case is not waiting for contractor responses (status %s)." % case["status"])
    plan = current_plan(conn, case)
    item = next((i for i in plan["schedule"] if i["project_id"] == p["id"]), None) if plan else None
    if not item:
        raise invalid("This project is not part of the current plan.")
    if one(conn, "SELECT 1 AS x FROM responses WHERE case_id = ? AND plan_version = ? AND project_id = ?",
           (case["id"], case["plan_version"], p["id"])):
        raise ApiError(409, "DUPLICATE_RESPONSE", "A response for this project and plan version was already recorded.")
    failures = []
    if body.decision == "REJECT" and not body.reason:
        failures.append(field_error("reason", "Give a reason when you cannot do these dates."))
    if body.decision == "COUNTERPROPOSE":
        if not body.earliest_start:
            failures.append(field_error("earliest_start", "Enter the later start date you can do."))
        elif d2s(body.earliest_start) <= p["earliest_start"]:
            failures.append(field_error("earliest_start", "The new earliest start must be later than %s." % p["earliest_start"]))
        elif d2s(body.earliest_start) > p["deadline"]:
            failures.append(field_error("earliest_start", "The new earliest start cannot be after the deadline of %s." % p["deadline"]))
    elif body.earliest_start:
        failures.append(field_error("earliest_start", "A start date is only used when suggesting a later start."))
    if failures:
        raise invalid("Check the highlighted fields.", failures)

    conn.execute("INSERT INTO responses(case_id, plan_version, project_id, decision, reason, earliest_start, user_id, recorded_at)"
                 " VALUES (?,?,?,?,?,?,?,?)",
                 (case["id"], case["plan_version"], p["id"], body.decision, body.reason, d2s(body.earliest_start),
                  user["id"], real_now()))
    audit(conn, user, "CONTRACTOR_" + body.decision, body.reason, case_id=case["id"], road_id=case["road_id"],
          project_id=p["id"], details={"plan_version": case["plan_version"], "earliest_start": d2s(body.earliest_start)})
    message = "Response recorded."
    if body.decision == "REJECT":
        update_case(conn, case["id"], status="BLOCKED", review_deadline_at=None, public_reason=PUBLIC_REASONS["CONTRACTOR_REJECTED"])
        message = "Response recorded. The plan is blocked until it is reviewed."
    elif body.decision == "COUNTERPROPOSE":
        update_project(conn, p["id"], earliest_start=d2s(body.earliest_start))
        conn.execute("UPDATE projects SET material_version = material_version + 1 WHERE id = ?", (p["id"],))
        bump_road(conn, case["road_id"], registry=True)
        fresh_case = get_case(conn, case["id"])
        result, version = run_assessment(conn, user, fresh_case)
        apply_plan_outcome(conn, user, fresh_case, result, version)
        message = ("Later start recorded. A new plan (version %d) needs fresh responses from every contractor." % version
                   if result["outcome"] == scheduler.PLAN_FOUND else
                   "Later start recorded, but no sequential plan fits all deadlines. The case needs review.")
    else:
        state = consent_state(conn, case, plan)  # reads the rows including the one just inserted
        if not state["pending_responses"]:
            update_case(conn, case["id"], status="DEPARTMENT_REVIEW", review_deadline_at=review_deadline(conn))
            message = "Response recorded. All contractors accepted; departments now have 48 hours to approve."
        else:
            update_case(conn, case["id"])
    fresh = get_case(conn, case["id"])
    return {"id": case["id"], "version": fresh["version"], "case_id": case["id"], "plan_version": fresh["plan_version"],
            "status": fresh["status"], "message": message}


# ------------------------------------------------------------ approvals
def authorize_approve(user: dict, case_id: str) -> Callable:
    def run(conn):
        require_role(user, "DEPARTMENT")
        case = get_case(conn, case_id)
        plan = current_plan(conn, case)
        owners = {p["owner_org_id"] for p in live_projects(conn, case_id)}
        if user["org_id"] not in owners:
            raise forbidden("Only a department that owns work in this plan can approve it.")
        return {"case": case, "plan": plan}
    return run


def approve(conn, user: dict, ctx: dict, body) -> dict:
    case, plan = ctx["case"], ctx["plan"]
    check_plan_version(case, body.plan_version)
    check_version(case["version"], body.expected_version, "case")
    if case["status"] != "DEPARTMENT_REVIEW":
        raise invalid_state("This case is not waiting for department approval (status %s)." % case["status"])
    state = consent_state(conn, case, plan)
    if user["org_id"] not in state["required_departments"]:
        raise forbidden("Your department has no work in the current plan.")
    if one(conn, "SELECT 1 AS x FROM approvals WHERE case_id = ? AND plan_version = ? AND org_id = ?",
           (case["id"], case["plan_version"], user["org_id"])):
        raise ApiError(409, "DUPLICATE_APPROVAL", "Your department already answered this plan version.")
    if body.decision == "REJECT" and not body.reason:
        raise invalid("Check the highlighted fields.", [field_error("reason", "Give a reason for rejecting the plan.")])
    conn.execute("INSERT INTO approvals(case_id, plan_version, org_id, decision, reason, user_id, recorded_at)"
                 " VALUES (?,?,?,?,?,?,?)",
                 (case["id"], case["plan_version"], user["org_id"], body.decision, body.reason, user["id"], real_now()))
    audit(conn, user, "DEPARTMENT_" + body.decision, body.reason, case_id=case["id"], road_id=case["road_id"],
          details={"plan_version": case["plan_version"], "org_id": user["org_id"]})
    if body.decision == "REJECT":
        update_case(conn, case["id"], status="BLOCKED", review_deadline_at=None, public_reason=PUBLIC_REASONS["DEPARTMENT_REJECTED"])
        message = "Rejection recorded. The plan is blocked until it is reviewed."
    else:
        state = consent_state(conn, case, plan)
        if not state["pending_approvals"]:
            update_case(conn, case["id"], status="APPROVED", review_deadline_at=None, public_reason=None)
            message = "Approved. Every required department has approved this exact plan; start checks still apply."
            audit(conn, None, "PLAN_APPROVED", None, case_id=case["id"], road_id=case["road_id"],
                  details={"plan_version": case["plan_version"]})
        else:
            update_case(conn, case["id"])
            message = "Approval recorded. Waiting for the remaining departments."
    fresh = get_case(conn, case["id"])
    return {"id": case["id"], "version": fresh["version"], "case_id": case["id"], "plan_version": fresh["plan_version"],
            "status": fresh["status"], "message": message}


def authorize_admin_case(user: dict, case_id: str) -> Callable:
    def run(conn):
        require_role(user, "ADMIN")
        return {"case": get_case(conn, case_id)}
    return run


def review_case(conn, user: dict, ctx: dict, body) -> dict:
    case = ctx["case"]
    check_version(case["version"], body.expected_version, "case")
    if case["status"] == "COMPLETED":
        raise invalid_state("This case is already completed.")
    started = case_started(conn, case["id"])
    if body.action == "REQUEST_REVISION":
        if started:
            raise invalid("Replanning after work has started is not supported in this demo. The case stays on hold.",
                          code="REPLAN_UNSUPPORTED")
        if case["status"] == "DRAFT":
            raise invalid_state("The case is already being prepared.")
        update_case(conn, case["id"], status="DRAFT", review_deadline_at=None, public_reason=None, hold_reason=None)
        conn.execute("UPDATE incidents SET status = 'REVIEWED' WHERE case_id = ? AND status = 'OPEN'", (case["id"],))
        message = "Revision requested. The case returned to preparation; history is kept and fresh consent is needed."
    else:
        if not started and case["status"] != "BLOCKED":
            update_case(conn, case["id"], status="BLOCKED", review_deadline_at=None, public_reason=PUBLIC_REASONS["KEPT_BLOCKED"])
        else:
            update_case(conn, case["id"])
        message = "The case stays blocked. No approval was granted."
    audit(conn, user, "ADMIN_" + body.action, body.reason, case_id=case["id"], road_id=case["road_id"],
          details={"previous_status": case["status"]})
    fresh = get_case(conn, case["id"])
    return {"id": case["id"], "version": fresh["version"], "case_id": case["id"], "status": fresh["status"],
            "message": message}


# ------------------------------------------------------------------ gate
def _blk(code: str, message: str, org: Optional[str] = None, nxt: Optional[str] = None) -> dict:
    return {"code": code, "message": message, "responsible_org_id": org, "next_action": nxt}


def coverage_problem(conn, road: dict, org_id: str, names: Dict[str, str], horizon_end: Optional[date],
                     now: date) -> Optional[dict]:
    name = names.get(org_id, org_id)
    decl = one(conn, "SELECT * FROM declarations WHERE road_id = ? AND org_id = ? ORDER BY id DESC LIMIT 1",
               (road["id"], org_id))
    if not decl:
        return _blk("COVERAGE_MISSING", "%s has not confirmed its planned work." % name, org_id,
                    "Request its declaration.")
    known = {p["id"] for p in many(conn, "SELECT id FROM projects WHERE road_id = ? AND owner_org_id = ? AND %s"
                                   % LIVE, (road["id"], org_id))}
    declared = set(json.loads(decl["known_project_ids_json"]))
    if decl["registry_version"] != road["registry_version"] or not known <= declared:
        return _blk("COVERAGE_STALE", "%s's declaration is out of date because registered work on this road changed." % name,
                    org_id, "Ask it to submit a new declaration.")
    if s2d(decl["valid_until"]) < now:
        return _blk("COVERAGE_EXPIRED", "%s's declaration expired on %s." % (name, human(s2d(decl["valid_until"]))), org_id,
                    "Ask it to submit a new declaration.")
    if s2d(decl["covers_from"]) > now or (horizon_end and s2d(decl["covers_through"]) < horizon_end):
        return _blk("COVERAGE_SHORT", "%s's declaration does not cover all work through %s." % (
            name, human(horizon_end) if horizon_end else "the review horizon"), org_id,
            "Ask it to declare a longer period.")
    if decl["mode"] == "NO_PLANNED_WORK":
        open_known = [p for p in many(conn, "SELECT id FROM projects WHERE road_id = ? AND owner_org_id = ? AND %s "
                                            "AND execution_status <> 'DONE'" % LIVE, (road["id"], org_id))]
        if open_known:
            return _blk("COVERAGE_CONTRADICTED", "%s declared no planned work, but work is registered." % name, org_id,
                        "Ask it to submit a correct declaration.")
    return None


def compute_gate(conn, project: dict) -> dict:
    """Pure read: eligibility to start this project now, with every current blocker.

    Every check that does not depend on the plan's dates (finished utilities, release inspections,
    declarations) is evaluated even when the plan is missing, so the result never implies a pass
    that was not actually checked.
    """
    names = org_names(conn)
    now = today(conn)
    case = get_case(conn, project["case_id"])
    road = get_road(conn, project["road_id"])
    blockers: List[dict] = []
    base = {"project_id": project["id"], "version": project["version"], "plan_version": case["plan_version"],
            "not_an_authorisation": True}
    if project["execution_status"] != "PLANNED":
        what = {"IN_PROGRESS": "Work on this project has already started.", "DONE": "This project is already finished.",
                "CANCELLED": "This project was cancelled."}[project["execution_status"]]
        return dict(base, eligible=False, blockers=[_blk("NOT_STARTABLE", what)])

    status = case["status"]
    # A case that went back to preparation has no current plan, whatever older versions exist.
    plan = current_plan(conn, case) if status != "DRAFT" else None
    state = consent_state(conn, case, plan)
    if status != "APPROVED":
        msgs = {
            "DRAFT": ("The coordination plan has not been generated yet.", project["owner_org_id"], "Generate the plan."),
            "CONTRACTOR_REVIEW": ("Contractors have not all accepted the proposed dates.",
                                  (state["pending_responses"][0]["contractor_id"] if state["pending_responses"] else None),
                                  "Pending contractors must respond."),
            "DEPARTMENT_REVIEW": ("Departments have not all approved the plan.",
                                  (state["pending_approvals"][0]["org_id"] if state["pending_approvals"] else None),
                                  "Pending departments must approve."),
            "BLOCKED": ("The plan needs review before work can start.", None, "An administrator must review the case."),
            "COMPLETED": ("This coordination case is already completed.", None, None),
        }
        m, org, nxt = msgs[status]
        blockers.append(_blk("PLAN_NOT_APPROVED", m, org, nxt))

    hold = hold_code(conn, case)
    if hold:
        blockers.append(_blk("CASE_ON_HOLD", PUBLIC_REASONS[hold] + " New starts are blocked.", None,
                             "An administrator must review the case."))

    all_projects = {p["id"]: p for p in many(conn, "SELECT * FROM projects WHERE case_id = ?", (case["id"],))}
    live = {pid: p for pid, p in all_projects.items() if p["execution_status"] != "CANCELLED"}
    item = None
    if plan and plan["outcome"] == scheduler.PLAN_FOUND:
        item = next((i for i in plan["schedule"] if i["project_id"] == project["id"]), None)
        # consent for this exact plan version
        if status == "APPROVED" and (state["pending_responses"] or state["pending_approvals"]
                                     or any(r["decision"] != "ACCEPT" for r in state["responses"])
                                     or any(a["decision"] != "APPROVE" for a in state["approvals"])):
            blockers.append(_blk("CONSENT_INCOMPLETE", "Consent for the current plan version is incomplete.", None,
                                 "Collect fresh responses and approvals."))
        # plan inputs unchanged and no new relevant project (inventory re-read)
        for i in plan["schedule"]:
            p = live.get(i["project_id"])
            if not p or p["material_version"] != i.get("material_version"):
                blockers.append(_blk("PLAN_OUTDATED", "Planning details changed after this plan was made.",
                                     project["owner_org_id"], "Generate and approve a fresh plan."))
                break
        started = [p["id"] for p in live.values() if p["execution_status"] in ("IN_PROGRESS", "DONE")]
        included, _, _ = scheduler.split_relevant([to_job(p) for p in live.values()], started)
        planned_ids = {i["project_id"] for i in plan["schedule"]}
        if any(j.id not in planned_ids for j in included):
            blockers.append(_blk("NEW_RELEVANT_PROJECT", "New registered work is not part of this plan yet.",
                                 project["owner_org_id"], "Generate and approve a fresh plan."))
        if item is None:
            blockers.append(_blk("NOT_IN_PLAN", "This project is not part of the current plan.", project["owner_org_id"], None))
    elif status == "APPROVED":
        blockers.append(_blk("PLAN_MISSING", "There is no workable plan for this case.", None, None))

    planned_start = s2d(item["start"]) if item else None
    if planned_start is None:
        blockers.append(_blk("NO_APPROVED_DATE", "There is no agreed start date for this project yet.",
                             project["owner_org_id"], "Generate a plan and have it approved."))
    elif now != planned_start:
        if now < planned_start:
            blockers.append(_blk("DATE_NOT_APPROVED_START", "The approved start date is %s; today's demo date is %s."
                                 % (human(planned_start), human(now)), project["assigned_contractor_id"],
                                 "Start on the approved date."))
        else:
            blockers.append(_blk("APPROVED_START_PASSED", "The approved start date (%s) has passed. "
                                 "Starting later needs an administrator review." % human(planned_start), None,
                                 "An administrator must review the case."))

    # Utilities in planned order when a plan exists, otherwise by earliest start.
    if plan and plan["outcome"] == scheduler.PLAN_FOUND:
        order = [i["project_id"] for i in plan["schedule"] if i["project_id"] in live]
    else:
        order = [p["id"] for p in sorted(live.values(), key=lambda p: (p["earliest_start"], p["id"]))]

    if project["kind"] == "UTILITY":
        prot = protected_until(conn, project["road_id"], case["id"])
        if planned_start and prot and planned_start <= prot:
            blockers.append(_blk("PROTECTED_SURFACE", "This road was recently resurfaced; excavation is restricted until %s."
                                 % human(prot), None, "No waivers exist in this demo."))
        earlier = order[:order.index(project["id"])] if project["id"] in order else []
        for prev_id in earlier:
            prev = live[prev_id]
            if prev["kind"] != "UTILITY":
                continue
            if prev["execution_status"] != "DONE":
                blockers.append(_blk("PRIOR_UTILITY_NOT_DONE", "%s must finish before this work can start." % prev["title"],
                                     prev["assigned_contractor_id"], "Report that work finished."))
            elif now < s2d(prev["actual_end"]) + timedelta(days=scheduler.UTILITY_GAP_DAYS):
                blockers.append(_blk("SEPARATION_TOO_SHORT", "Utility work needs %d days after %s finished (%s)."
                                     % (scheduler.UTILITY_GAP_DAYS, prev["title"], human(s2d(prev["actual_end"]))), None,
                                     "Wait for the separation period."))
    else:
        last_end: Optional[date] = None
        last_inspection: Optional[date] = None
        for pid in order:
            u = live[pid]
            if u["kind"] != "UTILITY":
                continue
            dept = names.get(u["owner_org_id"], u["owner_org_id"])
            if u["execution_status"] != "DONE":
                blockers.append(_blk("UTILITY_NOT_COMPLETE", "%s's utility work ('%s') is not finished." % (dept, u["title"]),
                                     u["assigned_contractor_id"], "The contractor must report it finished."))
                blockers.append(_blk("INSPECTION_MISSING", "%s's release inspection has not happened yet because the work is not finished. "
                                     "The inspector must record it before paving can start." % dept, "inspectorate",
                                     "Record the release inspection after the work is finished."))
                continue
            if not (u["testing_complete"] and u["reinstatement_complete"]):
                blockers.append(_blk("UTILITY_DECLARATIONS_MISSING",
                                     "Testing and reinstatement are not both declared complete for '%s'." % u["title"],
                                     u["assigned_contractor_id"], "The contractor must declare both complete."))
            end = s2d(u["actual_end"])
            last_end = end if last_end is None or end > last_end else last_end
            insp = latest_inspection(conn, u["id"], "UTILITY_RELEASE")
            if not insp:
                blockers.append(_blk("INSPECTION_MISSING", "%s's release inspection is missing. The inspector must record it "
                                     "before paving can start." % dept, "inspectorate", "Record the release inspection."))
            elif insp["result"] != "PASS":
                blockers.append(_blk("INSPECTION_FAILED", "%s's release inspection did not pass." % dept, "inspectorate",
                                     "Repair, then record a new inspection."))
            elif s2d(insp["inspected_on"]) < end + timedelta(days=3):
                blockers.append(_blk("INSPECTION_TOO_EARLY", "%s's release inspection was recorded before the 3-day wait "
                                     "after the work finished." % dept, "inspectorate", "Record a new inspection."))
            else:
                d = s2d(insp["inspected_on"])
                last_inspection = d if last_inspection is None or d > last_inspection else last_inspection
        if last_end is not None and now < last_end + timedelta(days=scheduler.SURFACE_GAP_DAYS):
            blockers.append(_blk("SURFACE_SEPARATION", "Surfacing can start %d days after the last utility finish (%s)."
                                 % (scheduler.SURFACE_GAP_DAYS, human(last_end + timedelta(days=scheduler.SURFACE_GAP_DAYS))),
                                 None, "Wait for the separation period."))
        if last_inspection is not None and now < last_inspection + timedelta(days=1):
            blockers.append(_blk("INSPECTION_SAME_DAY", "Surfacing can start at least one day after the release inspection (%s)."
                                 % human(last_inspection + timedelta(days=1)), None, "Wait until the next day."))
        horizon_end = s2d(plan["horizon_end"]) if plan and plan.get("horizon_end") else None
        if horizon_end is None:
            _, _, horizon_end = scheduler.split_relevant([to_job(p) for p in live.values()])
        for dept_id in [r["org_id"] for r in many(conn, "SELECT org_id FROM road_expected_depts WHERE road_id = ? ORDER BY org_id",
                                                  (road["id"],))]:
            problem = coverage_problem(conn, road, dept_id, names, horizon_end, now)
            if problem:
                blockers.append(problem)
    return dict(base, eligible=not blockers, blockers=blockers)


def authorize_assigned_contractor(user: dict, project_id: str) -> Callable:
    def run(conn):
        require_role(user, "CONTRACTOR")
        p = get_project(conn, project_id)
        if p["assigned_contractor_id"] != user["org_id"]:
            raise forbidden("Only the assigned contractor can do this for the project.")
        return {"project": p}
    return run


def start_project(conn, user: dict, ctx: dict, body) -> dict:
    p = ctx["project"]
    case = get_case(conn, p["case_id"])
    check_plan_version(case, body.plan_version)
    check_version(p["version"], body.expected_version, "project")
    gate = compute_gate(conn, p)                      # re-reads current inventory inside this transaction
    if not gate["eligible"]:
        raise ApiError(422, "GATE_BLOCKED", "This project cannot start yet: %s" % gate["blockers"][0]["message"],
                       gate["blockers"])
    now = today(conn)
    pcc = None
    fields = {"execution_status": "IN_PROGRESS", "actual_start": d2s(now)}
    if p["kind"] == "RESURFACING":
        n = one(conn, "SELECT value FROM counters WHERE name = 'pcc'")
        number = (n["value"] if n else 0) + 1
        conn.execute("INSERT INTO counters(name, value) VALUES ('pcc', ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                     (number,))
        pcc = "PCC-%d-%04d" % (now.year, number)
        fields["pcc_number"] = pcc
    update_project(conn, p["id"], **fields)
    update_case(conn, case["id"])
    audit(conn, user, "SURFACING_STARTED_PCC_ISSUED" if pcc else "WORK_STARTED",
          "Contractor reported start on %s." % human(now), case_id=case["id"], road_id=p["road_id"], project_id=p["id"],
          details={"pcc_number": pcc, "plan_version": case["plan_version"]})
    return {"id": p["id"], "version": p["version"] + 1, "case_id": case["id"], "pcc_number": pcc,
            "actual_start": d2s(now),
            "message": ("Surfacing started. Certificate %s was issued." % pcc) if pcc else "Work started."}


def finish_project(conn, user: dict, ctx: dict, body) -> dict:
    p = ctx["project"]
    check_version(p["version"], body.expected_version, "project")
    if p["execution_status"] != "IN_PROGRESS":
        raise invalid_state("Only work that is in progress can be reported finished.")
    case = get_case(conn, p["case_id"])
    failures = []
    if p["kind"] == "UTILITY":
        if not body.testing_complete:
            failures.append(field_error("testing_complete", "Confirm that testing is complete."))
        if not body.reinstatement_complete:
            failures.append(field_error("reinstatement_complete", "Confirm that reinstatement is complete."))
    now = today(conn)
    plan = current_plan(conn, case)
    item = next((i for i in (plan["schedule"] if plan else []) if i["project_id"] == p["id"]), None)
    late = bool(item and now > s2d(item["end"]))
    if late and not body.delay_reason:
        failures.append(field_error("delay_reason", "Finished after the planned end (%s). Explain the delay." % item["end"]))
    if failures:
        raise invalid("Check the highlighted fields.", failures)
    update_project(conn, p["id"], execution_status="DONE", actual_end=d2s(now), finished_by_user_id=user["id"],
                   testing_complete=1 if body.testing_complete else 0,
                   reinstatement_complete=1 if body.reinstatement_complete else 0,
                   delay_reason=body.delay_reason if late else None)
    if late:
        update_case(conn, case["id"], hold_reason="DELAY")
    else:
        update_case(conn, case["id"])
    audit(conn, user, "WORK_FINISHED", body.delay_reason if late else None, case_id=case["id"], road_id=p["road_id"],
          project_id=p["id"], details={"actual_end": d2s(now), "late": late})
    complete_case_if_done(conn, user, case["id"])
    return {"id": p["id"], "version": p["version"] + 1, "case_id": case["id"], "actual_end": d2s(now),
            "message": ("Finish recorded. The delay put the case on a review hold." if late
                        else "Finish recorded. It still needs an inspection before it counts as verified.")}


# ----------------------------------------------------------- inspections
def authorize_inspector(user: dict, project_id: str) -> Callable:
    def run(conn):
        require_role(user, "INSPECTOR")
        return {"project": get_project(conn, project_id)}
    return run


def record_inspection(conn, user: dict, ctx: dict, body) -> dict:
    p = ctx["project"]
    check_version(p["version"], body.expected_version, "project")
    if body.kind != inspection_kind_for(p):
        raise invalid("Wrong inspection type for this project.",
                      [field_error("kind", "Use %s for %s work." % (inspection_kind_for(p), p["kind"].lower()))])
    if p["execution_status"] != "DONE":
        raise invalid_state("Only finished work can be inspected.")
    if p["finished_by_user_id"] == user["id"]:
        raise forbidden("An inspector cannot verify evidence they submitted themselves.")
    now = today(conn)
    prior = latest_inspection(conn, p["id"], body.kind)
    if prior and prior["result"] == "PASS":
        raise ApiError(409, "ALREADY_VERIFIED", "This work already passed its inspection.")
    if body.kind == "UTILITY_RELEASE" and now < s2d(p["actual_end"]) + timedelta(days=3):
        raise invalid("Too early to inspect.", [field_error(
            "kind", "Release inspection is possible from %s (3 days after the work finished)."
            % human(s2d(p["actual_end"]) + timedelta(days=3)))], code="INSPECTION_TOO_EARLY")
    cur = conn.execute("INSERT INTO inspections(project_id, kind, result, notes, inspected_on, inspector_user_id, recorded_at)"
                       " VALUES (?,?,?,?,?,?,?)",
                       (p["id"], body.kind, body.result, body.notes, d2s(now), user["id"], real_now()))
    fields = {"verified_on": d2s(now)} if body.result == "PASS" else {}
    update_project(conn, p["id"], **fields)
    case = get_case(conn, p["case_id"])
    update_case(conn, case["id"])
    audit(conn, user, "INSPECTION_" + body.result, body.notes, case_id=case["id"], road_id=p["road_id"], project_id=p["id"],
          details={"kind": body.kind, "inspection_id": cur.lastrowid})
    completed = complete_case_if_done(conn, user, case["id"]) if body.result == "PASS" else False
    return {"id": p["id"], "version": p["version"] + 1, "case_id": case["id"], "inspection_id": cur.lastrowid,
            "case_completed": completed,
            "message": ("Inspection passed." + (" The coordination case is complete." if completed else ""))
                       if body.result == "PASS" else "Inspection failed. The case is on hold until a new inspection passes."}


# ---------------------------------------------------------- declarations
def authorize_declare(user: dict, road_id: str) -> Callable:
    def run(conn):
        require_role(user, "DEPARTMENT")
        road = get_road(conn, road_id)
        if not one(conn, "SELECT 1 AS x FROM road_expected_depts WHERE road_id = ? AND org_id = ?", (road_id, user["org_id"])):
            raise forbidden("Only a utility department expected on this road can declare its planned work.")
        return {"road": road}
    return run


def declare(conn, user: dict, ctx: dict, body) -> dict:
    road = ctx["road"]
    check_version(road["version"], body.expected_version, "road")
    now = today(conn)
    failures = []
    if body.covers_from > body.covers_through:
        failures.append(field_error("covers_through", "The covered period must end on or after it begins."))
    if body.valid_until < now:
        failures.append(field_error("valid_until", "The declaration must be valid from today onward."))
    if failures:
        raise invalid("Check the highlighted fields.", failures)
    known = many(conn, "SELECT id, execution_status FROM projects WHERE road_id = ? AND owner_org_id = ? AND %s ORDER BY id"
                 % LIVE, (road["id"], user["org_id"]))
    if body.mode == "NO_PLANNED_WORK" and any(k["execution_status"] != "DONE" for k in known):
        raise invalid("Your department has registered work on this road, so it cannot declare 'no planned work'.",
                      [field_error("mode", "Known project: %s" % k["id"]) for k in known if k["execution_status"] != "DONE"],
                      code="DECLARATION_CONTRADICTS_REGISTRY")
    cur = conn.execute(
        "INSERT INTO declarations(road_id, org_id, mode, covers_from, covers_through, valid_until, registry_version,"
        " known_project_ids_json, user_id, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (road["id"], user["org_id"], body.mode, d2s(body.covers_from), d2s(body.covers_through), d2s(body.valid_until),
         road["registry_version"], json.dumps([k["id"] for k in known]), user["id"], real_now()))
    bump_road(conn, road["id"], registry=False)
    case = one(conn, "SELECT id FROM cases WHERE road_id = ? AND status <> 'COMPLETED'", (road["id"],))
    audit(conn, user, "DECLARATION_RECORDED", None, case_id=case["id"] if case else None, road_id=road["id"],
          details={"org_id": user["org_id"], "mode": body.mode, "covers_through": d2s(body.covers_through),
                   "registry_version": road["registry_version"]})
    return {"id": road["id"], "version": road["version"] + 1, "declaration_id": cur.lastrowid,
            "registry_version": road["registry_version"], "case_id": case["id"] if case else None,
            "message": "Declaration recorded against the current registered work on this road."}


# -------------------------------------------------------------- incidents
def authorize_incident(user: dict, project_id: str) -> Callable:
    def run(conn):
        p = get_project(conn, project_id)
        allowed = (user["role"] in ("INSPECTOR", "ADMIN")
                   or (user["role"] == "DEPARTMENT" and user["org_id"] == p["owner_org_id"])
                   or (user["role"] == "CONTRACTOR" and user["org_id"] == p["assigned_contractor_id"]))
        if not allowed:
            raise forbidden("Only the responsible department or contractor, an inspector or an administrator can report this.")
        return {"project": p}
    return run


def report_incident(conn, user: dict, ctx: dict, body) -> dict:
    p = ctx["project"]
    check_version(p["version"], body.expected_version, "project")
    if p["execution_status"] == "CANCELLED":
        raise invalid_state("This project was cancelled.")
    cur = conn.execute("INSERT INTO incidents(project_id, case_id, kind, description, occurred_date, reporter_user_id, recorded_at)"
                       " VALUES (?,?,?,?,?,?,?)",
                       (p["id"], p["case_id"], body.kind, body.description, d2s(body.occurred_date), user["id"], real_now()))
    update_project(conn, p["id"])
    update_case(conn, p["case_id"])
    audit(conn, user, "INCIDENT_" + body.kind, body.description, case_id=p["case_id"], road_id=p["road_id"],
          project_id=p["id"], details={"incident_id": cur.lastrowid, "occurred_date": d2s(body.occurred_date)})
    return {"id": p["id"], "version": p["version"] + 1, "case_id": p["case_id"], "incident_id": cur.lastrowid,
            "message": "Report recorded. The case is on hold for administrator review. This does not authorise any work."}


# ------------------------------------------------------------ demo clock
def authorize_clock(user: dict, local_ok: bool) -> Callable:
    def run(conn):
        require_role(user, "ADMIN")
        if not local_ok:
            raise forbidden("The demo clock can be advanced only from the local machine.")
        return {}
    return run


def advance_clock(conn, user: dict, ctx: dict, body) -> dict:
    c = clock(conn)
    check_version(c["version"], body.expected_version, "demo clock")
    new_date = s2d(c["date"]) + timedelta(days=body.days)
    conn.execute("UPDATE demo_clock SET date = ?, version = version + 1 WHERE id = 1", (d2s(new_date),))
    audit(conn, user, "DEMO_CLOCK_ADVANCED", "Simulated time moved forward %d day(s)." % body.days,
          details={"from": c["date"], "to": d2s(new_date)})
    timed_out = sweep_due_reviews(conn)
    import complaints
    escalated = complaints.escalate_overdue(conn)
    return {"id": "demo-clock", "version": c["version"] + 1, "date": d2s(new_date), "timed_out_case_ids": timed_out,
            "escalated_complaints": escalated,
            "message": "Simulated date is now %s. This clock does not grant any approval." % human(new_date)
                       + (" %d review(s) timed out." % len(timed_out) if timed_out else "")
                       + (" %d complaint(s) were escalated because a promised date was missed." % len(escalated) if escalated else "")}


# ------------------------------------------------------------------ roads
SAME_ROAD_RADIUS_M = 150


def create_road(conn, user: Optional[dict], name: str, lat: float, lng: float, area_label: Optional[str] = None,
                road_id: Optional[str] = None) -> Tuple[dict, bool]:
    """Register a street at a place. A street with the same name within 150 m is reused, never duplicated."""
    for r in many(conn, "SELECT * FROM roads WHERE lower(name) = lower(?)", (name,)):
        if r["lat"] is not None and distance_m(lat, lng, r["lat"], r["lng"]) <= SAME_ROAD_RADIUS_M:
            return r, False
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "road"
    rid = road_id or "road-%s-%s" % (slug, secrets.token_hex(2))
    conn.execute("INSERT INTO roads(id, name, lat, lng, area_label) VALUES (?,?,?,?,?)",
                 (rid, name, round(lat, 5), round(lng, 5), area_label))
    # Every utility department is expected to confirm its planned work on every road.
    for o in many(conn, "SELECT id FROM orgs WHERE project_kind = 'UTILITY'"):
        conn.execute("INSERT OR IGNORE INTO road_expected_depts(road_id, org_id) VALUES (?,?)", (rid, o["id"]))
    audit(conn, user, "ROAD_REGISTERED", None, road_id=rid, details={"name": name})
    return get_road(conn, rid), True


def authorize_create_road(user: dict) -> Callable:
    def run(conn):
        require_role(user, "DEPARTMENT", "ADMIN")
        return {}
    return run


def register_road(conn, user: dict, ctx: dict, body) -> dict:
    road, created = create_road(conn, user, body.name, body.lat, body.lng, body.area_label)
    return {"id": road["id"], "version": road["version"], "case_id": None, "name": road["name"], "lat": road["lat"],
            "lng": road["lng"], "created": created,
            "message": "Location registered." if created else "That street is already registered here; it was reused."}
