"""Public complaints: routing to the right department, duplicate grouping, priority, promised dates,
escalation to the head of department, a status timeline (the resident's notifications), and the resident's
own "confirm fixed / reopen" response.

Rules in one place:

* A complaint's *category* decides which department receives it (electrical -> Power, water -> Water, ...).
  Only that department's staff, its head and the coordinator (admin) can see or act on it. Categories that
  belong to no single department go to the coordinator, who assigns them.
* Reports of the same problem (same category, within 150 m, or same street when no position is known) are
  grouped. More reports means higher priority (2+ HIGH, 4+ URGENT). Staff act on the whole group at once and
  every reporter gets the update.
* When a department says "we will resolve this in N days", the promise is stored. If the date passes without
  a resolution the complaint goes to the head of department with HIGH priority; if the head's own promise is
  missed (or the head does nothing for two days) it goes to the coordinator as URGENT.
* Every change adds a timeline entry written in plain words. Residents see these as notifications.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import auth
import service as svc
from db import many, one
from errors import ApiError, forbidden, invalid, invalid_state, not_found
from scheduler import human

DUPLICATE_RADIUS_M = 150
HEAD_GRACE_DAYS = 2
COMPLAINT_LIMIT = 5
COMPLAINT_WINDOW_MINUTES = 10
MAX_PROMISE_DAYS = 60

# id -> (label, receiving department id or None for the coordinator, hazard)
CATEGORIES: Dict[str, dict] = {
    "WATER": {"label": "Water leak or pipe problem", "dept": "water", "hazard": False, "examples": [
        "A pipe has burst outside the market and water is flooding the road.",
        "Tap water has been brown with very low pressure since yesterday."]},
    "ELECTRICAL": {"label": "Electrical fault, street light or cable", "dept": "power", "hazard": False, "examples": [
        "The street light has been out for a week and a cable is hanging low near the bus stop.",
        "The transformer near the school gate is sparking when it rains."]},
    "TELECOM": {"label": "Telephone or internet cable problem", "dept": "telecom", "hazard": False, "examples": [
        "A telephone cable has fallen across the lane and vehicles are catching it.",
        "The cable duct cover is open and cables are lying exposed on the footpath."]},
    "ROAD_DAMAGE": {"label": "Road surface damage or pothole", "dept": "roads", "hazard": False, "examples": [
        "A large pothole at the junction that two-wheelers keep swerving around.",
        "The road sank after the pipe repair and now collects water."]},
    "SAFETY_HAZARD": {"label": "Safety hazard", "dept": None, "hazard": True, "examples": [
        "An open trench with no barrier or warning sign beside the footpath.",
        "A manhole cover is missing right next to the bus stop."]},
    "WORK_WITHOUT_NOTICE": {"label": "Work happening without notice", "dept": None, "hazard": False, "examples": [
        "A crew started digging at night with no notice board or permit displayed."]},
    "DELAY": {"label": "Work taking too long", "dept": None, "hazard": False, "examples": [
        "The trench has been open for three weeks and nobody is working on it."]},
    "NOISE_DUST": {"label": "Noise, dust or disruption", "dept": None, "hazard": False, "examples": [
        "Drilling starts at 6 a.m. every day and dust is covering the shops."]},
    "OTHER": {"label": "Something else", "dept": None, "hazard": False, "examples": [
        "Building material was left on the road after the work finished."]},
}

OPEN = ("NEW", "ACKNOWLEDGED", "IN_PROGRESS", "REOPENED")
STATUS_TEXT = {
    "NEW": "Received", "ACKNOWLEDGED": "Acknowledged", "IN_PROGRESS": "Work under way",
    "RESOLVED": "Marked resolved: please confirm", "CONFIRMED_FIXED": "Confirmed fixed",
    "REOPENED": "Reopened: not fixed", "REJECTED": "Closed without action",
}
STAFF_NEXT = {
    "NEW": {"ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "REJECTED"},
    "ACKNOWLEDGED": {"IN_PROGRESS", "RESOLVED", "REJECTED"},
    "IN_PROGRESS": {"RESOLVED", "REJECTED"},
    "REOPENED": {"ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "REJECTED"},
    "RESOLVED": set(), "CONFIRMED_FIXED": set(), "REJECTED": set(),
}
PRIORITIES = ["NORMAL", "HIGH", "URGENT"]
PRIORITY_TEXT = {"NORMAL": "Normal priority", "HIGH": "High priority", "URGENT": "Urgent"}
LEAD_ORDER = {"REOPENED": 0, "NEW": 1, "ACKNOWLEDGED": 2, "IN_PROGRESS": 3, "RESOLVED": 4, "CONFIRMED_FIXED": 5, "REJECTED": 6}


def category_list(conn) -> List[dict]:
    names = svc.org_names(conn)
    return [{"id": k, "label": v["label"], "department_id": v["dept"], "examples": v["examples"],
             "department_name": names.get(v["dept"]) if v["dept"] else None} for k, v in CATEGORIES.items()]


# ------------------------------------------------------------------ helpers
def _dept_name(conn, org_id: Optional[str]) -> str:
    return svc.org_names(conn).get(org_id, "coordinator") if org_id else "coordinator"


def _label(conn, org_id: Optional[str]) -> str:
    """Who is speaking in a timeline entry: an organisation, never a person."""
    return svc.org_names(conn).get(org_id, "Coordinator") if org_id else "Coordinator"


def add_event(conn, complaint_id: str, kind: str, message: str, actor_label: str, user: Optional[dict] = None) -> None:
    """A timeline entry. Residents see only ``actor_label`` (an office); staff also see which person acted."""
    conn.execute("INSERT INTO complaint_events(complaint_id, at, kind, message, actor_label, actor_user_id, actor_name) VALUES (?,?,?,?,?,?,?)",
                 (complaint_id, svc.real_now(), kind, message, actor_label, user["id"] if user else None, user["name"] if user else None))


def _members(conn, group_id: str, open_only: bool = True) -> List[dict]:
    sql = "SELECT * FROM complaints WHERE group_id = ?"
    if open_only:
        sql += " AND status IN ('NEW','ACKNOWLEDGED','IN_PROGRESS','REOPENED')"
    return many(conn, sql + " ORDER BY created_at, id", (group_id,))


def _set(conn, cid: str, **fields) -> None:
    sets = ", ".join("%s = ?" % k for k in fields)
    conn.execute("UPDATE complaints SET %s, version = version + 1, updated_at = ? WHERE id = ?" % sets,
                 tuple(fields.values()) + (svc.real_now(), cid))


def find_group(conn, category: str, road_id: Optional[str], lat: Optional[float], lng: Optional[float]) -> Optional[str]:
    """The group of an open report of the same problem, if any. Each problem is represented by its first open
    report, so reports cannot chain along a street into one ever-growing "problem"."""
    anchors: Dict[str, dict] = {}
    for c in many(conn, "SELECT * FROM complaints WHERE category = ? AND status IN ('NEW','ACKNOWLEDGED','IN_PROGRESS','REOPENED') "
                        "ORDER BY created_at, id", (category,)):
        anchors.setdefault(c["group_id"], c)
    for c in anchors.values():
        if lat is not None and c["lat"] is not None:
            if svc.distance_m(lat, lng, c["lat"], c["lng"]) <= DUPLICATE_RADIUS_M:
                return c["group_id"]
        elif road_id and c["road_id"] == road_id:
            return c["group_id"]
    return None


def recompute_priority(conn, group_id: str) -> Dict[str, int]:
    """Priority from how many people reported it, whether it was escalated or reopened, and whether it is a hazard."""
    members = _members(conn, group_id)
    if not members:
        return {"old": 0, "new": 0, "count": 0}
    old = max(PRIORITIES.index(m["priority"]) for m in members)
    count = len(members)
    level = max(m["escalation_level"] for m in members)
    reasons, rank = [], 0
    if CATEGORIES.get(members[0]["category"], {}).get("hazard"):
        rank = max(rank, 1)
        reasons.append("safety hazard")
    if count >= 4:
        rank = 2
        reasons.append("%d people reported the same problem" % count)
    elif count >= 2:
        rank = max(rank, 1)
        reasons.append("%d people reported the same problem" % count)
    if level >= 2:
        rank = 2
        reasons.append("escalated to the coordinator: the promised date was missed again")
    elif level == 1:
        rank = max(rank, 1)
        reasons.append("escalated to the head of department: the promised date was missed")
    if any(m["status"] == "REOPENED" for m in members):
        rank = max(rank, 1)
        reasons.append("reopened: a resident said it is not fixed")
    text = ("; ".join(reasons)).capitalize() if reasons else None
    for m in members:
        if m["priority"] != PRIORITIES[rank] or m["priority_reason"] != text:
            conn.execute("UPDATE complaints SET priority = ?, priority_reason = ? WHERE id = ?", (PRIORITIES[rank], text, m["id"]))
    return {"old": old, "new": rank, "count": count}


def _promise_text(conn, c: dict, speaker: Optional[str] = None) -> str:
    who = speaker or "The %s" % _dept_name(conn, c["department_id"])
    days = c["committed_days"]
    return "%s will resolve this within %d day%s, by %s." % (who, days, "" if days == 1 else "s", human(svc.s2d(c["due_on"])))


# ----------------------------------------------------------------- creating
def create(conn, body, ckey: str, resident: Optional[dict]) -> dict:
    """Anyone may report a problem; no sign-in. Rate-limited per client; no raw addresses are stored."""
    cutoff = svc.iso(datetime.now(timezone.utc) - timedelta(minutes=COMPLAINT_WINDOW_MINUTES))
    recent = one(conn, "SELECT COUNT(*) AS n FROM complaints WHERE client_key = ? AND created_at > ?", (ckey, cutoff))["n"]
    if recent >= COMPLAINT_LIMIT:
        raise ApiError(429, "TOO_MANY_COMPLAINTS", "You have sent several reports just now. Please wait a few minutes before sending another.")
    failures = []
    if body.category not in CATEGORIES:
        failures.append(svc.field_error("category", "Choose what kind of problem it is."))
    if body.road_id and not one(conn, "SELECT 1 AS x FROM roads WHERE id = ?", (body.road_id,)):
        failures.append(svc.field_error("road_id", "Choose a street from the list, or leave it empty."))
    if (body.lat is None) != (body.lng is None):
        failures.append(svc.field_error("lat", "Send both latitude and longitude, or neither."))
    if failures:
        raise invalid("Check the highlighted fields.", failures)

    n = one(conn, "SELECT value FROM counters WHERE name = 'complaint'")
    number = (n["value"] if n else 0) + 1
    conn.execute("INSERT INTO counters(name, value) VALUES ('complaint', ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value", (number,))
    reference = "CMP-%d-%04d" % (svc.today(conn).year, number)
    code = secrets.token_hex(5).upper()
    lat = round(body.lat, 3) if body.lat is not None else None      # ~100 m: enough to route it, no more
    lng = round(body.lng, 3) if body.lng is not None else None
    dept = CATEGORIES[body.category]["dept"]
    now = svc.real_now()

    gid = find_group(conn, body.category, body.road_id, lat, lng)
    lead = None
    status, committed, due, level, esc_on, esc_due = "NEW", None, None, 0, None, None
    if gid:
        lead = _members(conn, gid)[0]
        dept = lead["department_id"]
        if lead["status"] in ("ACKNOWLEDGED", "IN_PROGRESS", "REOPENED"):
            status = lead["status"]
        committed, due = lead["committed_days"], lead["due_on"]
        level, esc_on, esc_due = lead["escalation_level"], lead["escalated_on"], lead["escalated_due_on"]
    conn.execute(
        "INSERT INTO complaints(id, tracking_hash, category, department_id, description, road_id, location_text, lat, lng,"
        " contact_name, contact_detail, resident_id, status, group_id, committed_days, due_on, escalation_level, escalated_on,"
        " escalated_due_on, client_key, created_at, updated_at, opened_on, assigned_user_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (reference, hashlib.sha256(code.encode()).hexdigest(), body.category, dept, body.description, body.road_id,
         body.location_text, lat, lng, body.contact_name, body.contact_detail, resident["id"] if resident else None,
         status, gid or reference, committed, due, level, esc_on, esc_due, ckey, now, now, svc.d2s(svc.today(conn)),
         lead["assigned_user_id"] if lead else None))
    new = one(conn, "SELECT * FROM complaints WHERE id = ?", (reference,))

    add_event(conn, reference, "RECEIVED", "We received your report.", "WorkSync")
    if dept:
        add_event(conn, reference, "ROUTED", "Sent to the %s." % _dept_name(conn, dept), "WorkSync")
    else:
        add_event(conn, reference, "ROUTED", "Sent to the coordinator, who will pass it to the right department.", "WorkSync")
    others = 0
    if lead:
        others = len(_members(conn, gid)) - 1
        add_event(conn, reference, "GROUPED",
                  "%d other %s reported the same problem nearby. Your report was grouped with theirs." % (others, "person" if others == 1 else "people"),
                  "WorkSync")
        if status == "IN_PROGRESS" and due:
            add_event(conn, reference, "COMMITTED", _promise_text(conn, new), _label(conn, dept))
    effect = recompute_priority(conn, new["group_id"])
    if effect["new"] > effect["old"] and lead:
        for m in _members(conn, new["group_id"]):
            if m["id"] != reference:
                word = {"HIGH": "high priority", "URGENT": "urgent priority"}[PRIORITIES[effect["new"]]]
                add_event(conn, m["id"], "PRIORITY_RAISED", "More people reported this same problem, so it now has %s." % word, "WorkSync")
    svc.audit(conn, {"id": None, "name": "Member of the public"}, "COMPLAINT_RECEIVED", None, road_id=body.road_id, org_id=dept,
              details={"reference": reference, "category": body.category, "group": new["group_id"], "reports": effect["count"]})
    fresh = one(conn, "SELECT priority, department_id FROM complaints WHERE id = ?", (reference,))
    return {"id": reference, "version": 1, "case_id": None, "status": status, "tracking_code": code,
            "department_name": svc.org_names(conn).get(fresh["department_id"]) if fresh["department_id"] else None,
            "other_reports": others, "priority": fresh["priority"],
            "message": "Thank you. Your report was received. Keep your reference and tracking code to follow its progress."}


# ------------------------------------------------------------ staff access
def can_see(user: dict, c: dict) -> bool:
    if user["role"] == "ADMIN":
        return True
    return user["role"] == "DEPARTMENT" and c["department_id"] == user["org_id"]


def next_statuses(user: dict, c: dict) -> List[str]:
    """What this person may move the complaint to now. The same rule the server enforces in `triage`."""
    if c["status"] not in OPEN or not can_act(user, c):
        return []
    out = [x for x in ("ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "REJECTED") if x in STAFF_NEXT[c["status"]]]
    if c["status"] == "IN_PROGRESS" and (user["role"] == "ADMIN" or user.get("is_head")):
        out.insert(0, "IN_PROGRESS")                           # a new promise, only from the head or the coordinator
    return out


def can_act(user: dict, c: dict) -> bool:
    if user["role"] == "ADMIN":
        return True
    if user["role"] != "DEPARTMENT" or c["department_id"] != user["org_id"]:
        return False
    return c["escalation_level"] == 0 or bool(user.get("is_head"))


def _user_names(conn) -> Dict[str, str]:
    return {u["id"]: u["name"] for u in many(conn, "SELECT id, name FROM users")}


def _days_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if not a or not b:
        return None
    return (svc.s2d(b) - svc.s2d(a)).days


def _staff_item(conn, user: dict, members: List[dict], names: Dict[str, str], roads: Dict[str, str],
                people: Optional[Dict[str, str]] = None, with_timeline: bool = True) -> dict:
    people = people if people is not None else _user_names(conn)
    lead = sorted(members, key=lambda m: (LEAD_ORDER[m["status"]], m["created_at"], m["id"]))[0]
    today = svc.today(conn)
    due = svc.s2d(lead["due_on"])
    events = (many(conn, "SELECT id, at, kind, message, actor_label, actor_name FROM complaint_events WHERE complaint_id = ? ORDER BY id", (lead["id"],))
              if with_timeline else [])
    open_n = [m for m in members if m["status"] in OPEN]
    level = lead["escalation_level"]
    dept = names.get(lead["department_id"])
    actions = []
    if STAFF_NEXT[lead["status"]] and can_act(user, lead):
        actions.append("TRIAGE_COMPLAINT")
    if user["role"] == "ADMIN" and lead["status"] in OPEN:
        actions.append("ASSIGN_COMPLAINT")
    if lead["status"] in OPEN and lead["department_id"] and can_assign_staff(user, lead, None):
        actions.append("ASSIGN_STAFF")
    opened = min((m["opened_on"] or "9999") for m in members)
    opened = None if opened == "9999" else opened
    resolved = max((m["resolved_on"] for m in members if m["resolved_on"]), default=None)
    return {
        "id": lead["id"], "references": [m["id"] for m in sorted(members, key=lambda m: (m["created_at"], m["id"]))],
        "category": lead["category"], "category_label": CATEGORIES.get(lead["category"], {}).get("label", lead["category"]),
        "department_id": lead["department_id"], "department_name": dept,
        "status": lead["status"], "status_text": STATUS_TEXT[lead["status"]],
        "priority": lead["priority"], "priority_text": PRIORITY_TEXT[lead["priority"]], "priority_reason": lead["priority_reason"],
        "report_count": len(members), "open_report_count": len(open_n),
        "road_id": lead["road_id"], "road_name": roads.get(lead["road_id"]), "version": lead["version"],
        "committed_days": lead["committed_days"], "due_on": lead["due_on"],
        "days_left": (due - today).days if (due and lead["status"] == "IN_PROGRESS") else None,
        "overdue": bool(due and lead["status"] == "IN_PROGRESS" and due < today),
        "escalation_level": level,
        "escalation_text": ("With the coordinator" if level >= 2 else ("With the head of the %s" % dept if level == 1 else None)),
        "assigned_user_id": lead["assigned_user_id"], "assigned_name": people.get(lead["assigned_user_id"]),
        "opened_on": opened, "resolved_on": resolved,
        "days_open": _days_between(opened, svc.d2s(today)) if lead["status"] in OPEN else None,
        "resolution_days": _days_between(opened, resolved),
        "public_note": lead["public_note"], "created_at": min(m["created_at"] for m in members), "updated_at": lead["updated_at"],
        "reports": [{"id": m["id"], "created_at": m["created_at"], "description": m["description"],
                     "location_text": m["location_text"], "lat": m["lat"], "lng": m["lng"],
                     "contact_name": m["contact_name"], "contact_detail": m["contact_detail"], "status": m["status"]}
                    for m in sorted(members, key=lambda m: (m["created_at"], m["id"]))],
        "timeline": events, "allowed_actions": actions, "next_statuses": next_statuses(user, lead),
    }


def _matches(item: dict, q: str) -> bool:
    hay = " ".join([" ".join(item["references"]), item["category_label"], item["road_name"] or "", item["department_name"] or "",
                    item["public_note"] or "", item["assigned_name"] or ""]
                   + [" ".join(filter(None, [r["description"], r["location_text"], r["contact_name"]])) for r in item["reports"]]).lower()
    return all(word in hay for word in q.lower().split())


def list_for_staff(conn, user: dict, status: Optional[str] = None, priority: Optional[str] = None, scope: str = "all",
                   q: Optional[str] = None, category: Optional[str] = None, assigned: Optional[str] = None,
                   opened_from: Optional[str] = None, opened_to: Optional[str] = None,
                   limit: Optional[int] = None, offset: int = 0) -> dict:
    """Problems this person may see. ``scope``: open (something still to do), closed (history), or all."""
    if user["role"] not in ("DEPARTMENT", "ADMIN"):
        raise forbidden("Complaints are handled by the responsible municipal department and the coordinator.")
    names = svc.org_names(conn)
    people = _user_names(conn)
    roads = {r["id"]: r["name"] for r in many(conn, "SELECT id, name FROM roads")}
    groups: Dict[str, List[dict]] = {}
    for c in many(conn, "SELECT * FROM complaints ORDER BY created_at, id"):
        if can_see(user, c):
            groups.setdefault(c["group_id"], []).append(c)
    items = [_staff_item(conn, user, ms, names, roads, people, with_timeline=(limit is None)) for ms in groups.values()]
    if scope == "open":
        items = [i for i in items if i["status"] in OPEN]
    elif scope == "closed":
        items = [i for i in items if i["status"] not in OPEN]
    if status:
        items = [i for i in items if i["status"] == status]
    if priority:
        items = [i for i in items if i["priority"] == priority]
    if category:
        items = [i for i in items if i["category"] == category]
    if assigned:
        items = [i for i in items if (i["assigned_user_id"] is None if assigned == "none" else i["assigned_user_id"] == assigned)]
    if opened_from:
        items = [i for i in items if (i["opened_on"] or "") >= opened_from]
    if opened_to:
        items = [i for i in items if (i["opened_on"] or "9999") <= opened_to]
    if q and q.strip():
        items = [i for i in items if _matches(i, q)]
    if scope == "closed":
        items.sort(key=lambda i: i["updated_at"], reverse=True)
    else:
        items.sort(key=lambda i: (-PRIORITIES.index(i["priority"]), -i["escalation_level"], i["due_on"] or "9999", i["created_at"]))
    total = len(items)
    if limit is not None:
        items = items[offset:offset + limit]
        for it in items:                                        # the list view is light; the detail has the timeline
            it["timeline"] = many(conn, "SELECT id, at, kind, message, actor_label, actor_name FROM complaint_events WHERE complaint_id = ? ORDER BY id", (it["id"],))
    return {"items": items, "total": total}


# --------------------------------------------------------------- staff actions
def authorize_complaint(user: dict, complaint_id: str, *, assign: bool = False) -> Callable:
    def run(conn):
        auth.require_role(user, "ADMIN") if assign else auth.require_role(user, "DEPARTMENT", "ADMIN")
        c = one(conn, "SELECT * FROM complaints WHERE id = ?", (complaint_id,))
        if not c or not can_see(user, c):
            raise not_found("Complaint")                       # other departments cannot even tell it exists
        if not assign and not can_act(user, c):
            raise forbidden("This complaint has been escalated. Only the head of the department or the coordinator can act on it now.")
        return {"complaint": c}
    return run


def _apply_to_group(conn, group_id: str, **fields) -> List[dict]:
    members = _members(conn, group_id)
    for m in members:
        _set(conn, m["id"], **fields)
    return members


def triage(conn, user: dict, ctx: dict, body) -> dict:
    c = ctx["complaint"]
    svc.check_version(c["version"], body.expected_version, "complaint")
    if c["status"] not in OPEN:
        raise invalid_state("This complaint is already %s." % STATUS_TEXT[c["status"]].lower())
    if body.status not in next_statuses(user, c):
        raise invalid_state("A complaint that is %s cannot move to %s." % (STATUS_TEXT[c["status"]].lower(), STATUS_TEXT[body.status].lower()))
    failures = []
    if body.status == "IN_PROGRESS":
        if not body.resolve_in_days:
            failures.append(svc.field_error("resolve_in_days", "Say in how many days it will be resolved (1 to %d)." % MAX_PROMISE_DAYS))
        elif body.resolve_in_days > MAX_PROMISE_DAYS:
            failures.append(svc.field_error("resolve_in_days", "The most you can promise is %d days." % MAX_PROMISE_DAYS))
    if body.status in ("RESOLVED", "REJECTED") and not body.note:
        failures.append(svc.field_error("note", "Add a short message for the people who reported it."))
    if failures:
        raise invalid("Check the highlighted fields.", failures)

    # The timeline names the office that acted, never a person. The coordinator is not the department.
    if user["role"] == "ADMIN":
        actor, speaker = "Coordinator", "The coordinator"
    else:
        actor, speaker = _label(conn, c["department_id"]), "The %s" % _dept_name(conn, c["department_id"])
    today = svc.today(conn)
    fields: dict = {"status": body.status}
    if body.note:
        fields["public_note"] = body.note
    lead_now = sorted(_members(conn, c["group_id"]), key=lambda m: (m["created_at"], m["id"]))[0]
    if user["role"] == "DEPARTMENT" and not lead_now["assigned_user_id"]:
        fields["assigned_user_id"] = user["id"]                    # whoever first works on it is the one working on it
    if body.status == "RESOLVED":
        fields["resolved_on"] = svc.d2s(today)
    if body.status == "IN_PROGRESS":
        due = today + timedelta(days=body.resolve_in_days)
        fields.update(committed_days=body.resolve_in_days, due_on=svc.d2s(due))
    members = _apply_to_group(conn, c["group_id"], **fields)
    for m in members:
        fresh = one(conn, "SELECT * FROM complaints WHERE id = ?", (m["id"],))
        if body.status == "ACKNOWLEDGED":
            msg = "%s acknowledged your report." % speaker
        elif body.status == "IN_PROGRESS":
            msg = _promise_text(conn, fresh, speaker)
        elif body.status == "RESOLVED":
            msg = "%s marked this as resolved. Please check it and confirm it is fixed, or tell us it is not." % speaker
        else:
            msg = "Closed without action by %s." % speaker.lower()
        if body.note:
            msg += " Message: %s" % body.note
        add_event(conn, m["id"], body.status, msg, actor, user)
    recompute_priority(conn, c["group_id"])
    svc.audit(conn, user, "COMPLAINT_" + body.status, body.note, road_id=c["road_id"], org_id=c["department_id"],
              details={"reference": c["id"], "group": c["group_id"], "reports": len(members), "days": body.resolve_in_days})
    fresh = one(conn, "SELECT version FROM complaints WHERE id = ?", (c["id"],))
    return {"id": c["id"], "version": fresh["version"], "case_id": None, "status": body.status,
            "message": "Updated %d report%s. Status: %s." % (len(members), "" if len(members) == 1 else "s", STATUS_TEXT[body.status])}


def assign(conn, user: dict, ctx: dict, body) -> dict:
    c = ctx["complaint"]
    svc.check_version(c["version"], body.expected_version, "complaint")
    if c["status"] not in OPEN:
        raise invalid_state("Only open complaints can be sent to a department.")
    org = one(conn, "SELECT id, name FROM orgs WHERE id = ? AND kind = 'DEPARTMENT'", (body.department_id,))
    if not org:
        raise invalid("Choose a department.", [svc.field_error("department_id", "Unknown department.")])
    members = _apply_to_group(conn, c["group_id"], department_id=org["id"])
    for m in members:
        add_event(conn, m["id"], "ROUTED", "Sent to the %s." % org["name"], "Coordinator", user)
    svc.audit(conn, user, "COMPLAINT_ASSIGNED", None, road_id=c["road_id"], org_id=org["id"], details={"reference": c["id"], "to": org["id"]})
    fresh = one(conn, "SELECT version FROM complaints WHERE id = ?", (c["id"],))
    return {"id": c["id"], "version": fresh["version"], "case_id": None, "status": c["status"],
            "message": "Sent to the %s." % org["name"]}


# ------------------------------------------------------- staff assignment
def can_assign_staff(user: dict, c: dict, target_user_id: Optional[str]) -> bool:
    """Admin: anyone in the complaint's department. Head: anyone in their own department. Staff: only themselves."""
    if user["role"] == "ADMIN":
        return bool(c["department_id"])
    if user["role"] != "DEPARTMENT" or c["department_id"] != user["org_id"]:
        return False
    if user.get("is_head"):
        return True
    return can_act(user, c) and (target_user_id is None or target_user_id == user["id"])


def authorize_assign_staff(user: dict, complaint_id: str, target_user_id: Optional[str]) -> Callable:
    def run(conn):
        auth.require_role(user, "DEPARTMENT", "ADMIN")
        c = one(conn, "SELECT * FROM complaints WHERE id = ?", (complaint_id,))
        if not c or not can_see(user, c):
            raise not_found("Complaint")
        if not can_assign_staff(user, c, target_user_id) or (target_user_id is None and not (user["role"] == "ADMIN" or user.get("is_head"))):
            raise forbidden("Only the head of department or the coordinator can give a complaint to someone else. Staff can take one for themselves.")
        return {"complaint": c}
    return run


def assign_staff(conn, user: dict, ctx: dict, body) -> dict:
    c = ctx["complaint"]
    svc.check_version(c["version"], body.expected_version, "complaint")
    if c["status"] not in OPEN:
        raise invalid_state("Only open complaints can be given to a staff member.")
    target = None
    if body.user_id:
        target = one(conn, "SELECT id, name, org_id, role FROM users WHERE id = ?", (body.user_id,))
        if not target or target["role"] != "DEPARTMENT" or target["org_id"] != c["department_id"]:
            raise invalid("Choose someone from the %s." % _dept_name(conn, c["department_id"]),
                          [svc.field_error("user_id", "That person is not in the department handling this complaint.")])
    members = _apply_to_group(conn, c["group_id"], assigned_user_id=target["id"] if target else None)
    for m in members:
        add_event(conn, m["id"], "STAFF_ASSIGNED",
                  "A member of the %s team is now looking after your report." % _dept_name(conn, c["department_id"]) if target
                  else "Your report is waiting to be taken by a member of the %s team." % _dept_name(conn, c["department_id"]),
                  _label(conn, c["department_id"]), user)
    svc.audit(conn, user, "COMPLAINT_STAFF_ASSIGNED" if target else "COMPLAINT_STAFF_UNASSIGNED", None, road_id=c["road_id"], org_id=c["department_id"],
              details={"reference": c["id"], "to": target["id"] if target else None, "to_name": target["name"] if target else None})
    fresh = one(conn, "SELECT version FROM complaints WHERE id = ?", (c["id"],))
    return {"id": c["id"], "version": fresh["version"], "case_id": None, "status": c["status"],
            "message": ("Now assigned to %s." % target["name"]) if target else "No longer assigned to anyone."}


# --------------------------------------------- a resident adds a guest report to their account
def claim(conn, resident: dict, reference: str, code: str) -> Optional[dict]:
    """Attach a report made as a guest to this account (needs the tracking code). None if the pair is wrong or already someone else's."""
    c = one(conn, "SELECT * FROM complaints WHERE id = ?", (reference.strip().upper(),))
    if not c or not _owns(c, code, None) or (c["resident_id"] and c["resident_id"] != resident["id"]):
        return None
    if not c["resident_id"]:
        conn.execute("UPDATE complaints SET resident_id = ? WHERE id = ?", (resident["id"], c["id"]))
    return one(conn, "SELECT * FROM complaints WHERE id = ?", (c["id"],))


# --------------------------------------------------------------- escalation
def escalation_due(conn) -> bool:
    return bool(one(conn, "SELECT 1 AS x FROM complaints WHERE status = 'IN_PROGRESS' AND due_on IS NOT NULL AND due_on < ? "
                          "AND escalation_level < 2", (svc.d2s(svc.today(conn)),)))


def escalate_overdue(conn) -> List[str]:
    """A missed promise goes to the head of department (HIGH). A missed promise by the head, or two days of
    silence from the head, goes to the coordinator (URGENT). Residents are told each time."""
    today = svc.today(conn)
    escalated: List[str] = []
    seen = set()
    for c in many(conn, "SELECT * FROM complaints WHERE status = 'IN_PROGRESS' AND due_on IS NOT NULL AND due_on < ? "
                        "AND escalation_level < 2 ORDER BY created_at, id", (svc.d2s(today),)):
        if c["group_id"] in seen:
            continue
        level = c["escalation_level"]
        if level == 0:
            go = True
        else:   # with the head already: a new promise that was missed, or two days without any action
            new_promise = c["due_on"] != c["escalated_due_on"]
            silent = (today - svc.s2d(c["escalated_on"])).days > HEAD_GRACE_DAYS
            go = new_promise or silent
        if not go:
            continue
        seen.add(c["group_id"])
        new_level = level + 1
        dept = _dept_name(conn, c["department_id"])
        members = _apply_to_group(conn, c["group_id"], escalation_level=new_level, escalated_on=svc.d2s(today), escalated_due_on=c["due_on"])
        recompute_priority(conn, c["group_id"])
        if new_level == 1:
            msg = ("The promised date (%s) was missed. Your report has been escalated to the head of the %s and marked high priority."
                   % (human(svc.s2d(c["due_on"])), dept))
            who = "WorkSync"
        else:
            msg = ("It is still not resolved. Your report has been escalated to the coordinator and marked urgent.")
            who = "WorkSync"
        for m in members:
            add_event(conn, m["id"], "ESCALATED", msg, who)
        svc.audit(conn, None, "COMPLAINT_ESCALATED", None, road_id=c["road_id"], org_id=c["department_id"],
                  details={"reference": c["id"], "group": c["group_id"], "level": new_level, "due_on": c["due_on"]})
        escalated.append(c["id"])
    return escalated


# ------------------------------------------------------- resident responses
def _owns(c: dict, code: Optional[str], resident: Optional[dict]) -> bool:
    if resident and c["resident_id"] == resident["id"]:
        return True
    return bool(code) and svc.hmac_equal(hashlib.sha256(code.strip().upper().encode()).hexdigest(), c["tracking_hash"])


def resident_respond(conn, reference: str, code: Optional[str], resident: Optional[dict], action: str, note: Optional[str]) -> dict:
    """Returns {'result': 'ok'|'missing'|'state', ...}; the caller records throttling and raises."""
    c = one(conn, "SELECT * FROM complaints WHERE id = ?", (reference.strip().upper(),))
    if not c or not _owns(c, code, resident):
        return {"result": "missing"}
    if c["status"] != "RESOLVED":
        return {"result": "state", "message": "You can respond after the department marks the problem resolved."}
    if action == "CONFIRM_FIXED":
        _set(conn, c["id"], status="CONFIRMED_FIXED")
        add_event(conn, c["id"], "CONFIRMED_FIXED", "You confirmed the problem is fixed. Thank you for helping keep the roads safe.", "You")
        svc.audit(conn, {"id": None, "name": "Member of the public"}, "COMPLAINT_CONFIRMED_FIXED", None, road_id=c["road_id"], org_id=c["department_id"], details={"reference": c["id"]})
        return {"result": "ok", "message": "Thank you. The report is closed as fixed.", "status": "CONFIRMED_FIXED"}
    dept = _dept_name(conn, c["department_id"])
    for m in many(conn, "SELECT * FROM complaints WHERE group_id = ? AND status = 'RESOLVED'", (c["group_id"],)):
        _set(conn, m["id"], status="REOPENED", committed_days=None, due_on=None, resolved_on=None, **({"public_note": note} if note and m["id"] == c["id"] else {}))
        who = "You" if m["id"] == c["id"] else "WorkSync"
        add_event(conn, m["id"], "REOPENED",
                  ("You said it is not fixed" if m["id"] == c["id"] else "Someone reported it is not fixed")
                  + ". It has been reopened with high priority and sent back to the %s.%s" % (dept, (" Your note: %s" % note) if note and m["id"] == c["id"] else ""), who)
    recompute_priority(conn, c["group_id"])
    svc.audit(conn, {"id": None, "name": "Member of the public"}, "COMPLAINT_REOPENED", note, road_id=c["road_id"], org_id=c["department_id"], details={"reference": c["id"]})
    return {"result": "ok", "message": "Thank you. It has been reopened with higher priority.", "status": "REOPENED"}


# ------------------------------------------------------- resident-facing views
def _timeline(conn, cid: str) -> List[dict]:
    return many(conn, "SELECT id, at, kind, message, actor_label FROM complaint_events WHERE complaint_id = ? ORDER BY id", (cid,))


def track_view(conn, c: dict) -> dict:
    """What the person who complained may see: no description, no contact details, no staff names."""
    names = svc.org_names(conn)
    road = one(conn, "SELECT name FROM roads WHERE id = ?", (c["road_id"],)) if c["road_id"] else None
    events = _timeline(conn, c["id"])
    siblings = [m for m in _members(conn, c["group_id"])]
    level = c["escalation_level"]
    dept = names.get(c["department_id"]) if c["department_id"] else None
    return {
        "reference": c["id"], "category_label": CATEGORIES.get(c["category"], {}).get("label", c["category"]),
        "department_name": dept, "status": c["status"], "status_text": STATUS_TEXT[c["status"]],
        "priority": c["priority"], "priority_text": PRIORITY_TEXT[c["priority"]],
        "priority_reason": c["priority_reason"], "road_name": road["name"] if road else None,
        "submitted_on": c["created_at"][:10], "last_update": c["updated_at"], "public_note": c["public_note"],
        "committed_days": c["committed_days"], "promised_by": c["due_on"],
        "escalation_text": ("With the coordinator" if level >= 2 else ("With the head of the %s" % dept if level == 1 else None)),
        "report_count": max(len(siblings), 1), "can_respond": c["status"] == "RESOLVED",
        "timeline": events, "last_event_id": events[-1]["id"] if events else 0,
    }


def public_feed(conn) -> dict:
    """Problems reported near people: category, status and an approximate place. Never descriptions, contact
    details, references or tracking codes."""
    names = svc.org_names(conn)
    roads = {r["id"]: r for r in many(conn, "SELECT id, name, lat, lng FROM roads")}
    groups: Dict[str, List[dict]] = {}
    for c in many(conn, "SELECT * FROM complaints WHERE status <> 'REJECTED' ORDER BY created_at, id"):
        groups.setdefault(c["group_id"], []).append(c)
    items = []
    for gid, ms in groups.items():
        open_ms = [m for m in ms if m["status"] in OPEN]
        lead = sorted(ms, key=lambda m: (LEAD_ORDER[m["status"]], m["created_at"], m["id"]))[0]
        fixed = not open_ms and all(m["status"] in ("RESOLVED", "CONFIRMED_FIXED") for m in ms)
        lat, lng = lead["lat"], lead["lng"]
        road = roads.get(lead["road_id"]) if lead["road_id"] else None
        if lat is None and road and road["lat"] is not None:
            lat, lng = round(road["lat"], 3), round(road["lng"], 3)
        due = svc.s2d(lead["due_on"])
        items.append({
            "id": hashlib.sha256(("pub:" + gid).encode()).hexdigest()[:12], "category": lead["category"],
            "category_label": CATEGORIES.get(lead["category"], {}).get("label", lead["category"]),
            "department_name": names.get(lead["department_id"]) if lead["department_id"] else None,
            "status": lead["status"], "status_text": STATUS_TEXT[lead["status"]], "fixed": fixed,
            "priority": lead["priority"], "priority_text": PRIORITY_TEXT[lead["priority"]],
            "report_count": len(ms), "since": min(m["created_at"] for m in ms)[:10], "last_update": lead["updated_at"],
            "promised_by": lead["due_on"] if lead["status"] == "IN_PROGRESS" else None,
            "escalated": lead["escalation_level"] > 0 and not fixed,
            "road_name": road["name"] if road else None, "lat": lat, "lng": lng,
        })
    items.sort(key=lambda i: (i["fixed"], -PRIORITIES.index(i["priority"]), i["last_update"]), reverse=False)
    return {"items": items[:200]}


def mine(conn, resident: dict) -> dict:
    rows = many(conn, "SELECT * FROM complaints WHERE resident_id = ? ORDER BY created_at DESC, id DESC", (resident["id"],))
    return {"items": [track_view(conn, c) for c in rows]}
