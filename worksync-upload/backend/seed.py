"""Fictional demo data. Run:  python seed.py --reset

Everything that has rules (projects, plans, declarations) is created through the
same service functions the API uses, so the audit history is real.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from typing import Optional

import schemas as sc
import service as svc
from auth import hash_password
import complaints
import auth
from errors import ApiError
from db import connect, db_path, init_db, many, one, transaction

DEMO_START = "2026-11-08"

ORGS = [
    ("water", "Water Department", "DEPARTMENT", "UTILITY"),
    ("telecom", "Telecom Department", "DEPARTMENT", "UTILITY"),
    ("power", "Power Department", "DEPARTMENT", "UTILITY"),
    ("roads", "Roads Department", "DEPARTMENT", "RESURFACING"),
    ("con-aqua", "Aqua Pipeworks Ltd", "CONTRACTOR", None),
    ("con-link", "LinkDuct Infrastructure", "CONTRACTOR", None),
    ("con-grid", "GridLine Electrical", "CONTRACTOR", None),
    ("con-pave", "PaveWell Surfacing", "CONTRACTOR", None),
    ("inspectorate", "Independent Inspectorate", "INSPECTORATE", None),
    ("admin", "WorkSync Administration", "ADMIN", None),
]

# (id, display name, role, organisation, username, DUMMY password, is_head). These are fictional demo credentials
# for a local demonstrator only; they are also listed in DEMO_CREDENTIALS.md. Passwords are stored hashed.
USERS = [
    ("u-water", "Asha Nair", "DEPARTMENT", "water", "water.dept", "Water@Dept26", 0),
    ("u-telecom", "Karthik Rao", "DEPARTMENT", "telecom", "telecom.dept", "Telecom@Dept26", 0),
    ("u-power", "Meena Iyer", "DEPARTMENT", "power", "power.dept", "Power@Dept26", 0),
    ("u-roads", "Vikram Shah", "DEPARTMENT", "roads", "roads.dept", "Roads@Dept26", 0),
    ("u-water2", "Ravi Menon", "DEPARTMENT", "water", "water.staff", "WaterStaff@26", 0),
    ("u-telecom2", "Deepa Krishnan", "DEPARTMENT", "telecom", "telecom.staff", "TelecomStaff@26", 0),
    ("u-power2", "Arjun Reddy", "DEPARTMENT", "power", "power.staff", "PowerStaff@26", 0),
    ("u-roads2", "Sneha Kapoor", "DEPARTMENT", "roads", "roads.staff", "RoadsStaff@26", 0),
    ("u-water-head", "Rekha Pillai", "DEPARTMENT", "water", "water.head", "WaterHead@26", 1),
    ("u-telecom-head", "Sanjay Kulkarni", "DEPARTMENT", "telecom", "telecom.head", "TelecomHead@26", 1),
    ("u-power-head", "Lakshmi Menon", "DEPARTMENT", "power", "power.head", "PowerHead@26", 1),
    ("u-roads-head", "Imran Qureshi", "DEPARTMENT", "roads", "roads.head", "RoadsHead@26", 1),
    ("u-aqua", "Dev Patel", "CONTRACTOR", "con-aqua", "aqua.contractor", "Aqua@Contr26", 0),
    ("u-link", "Lata Menon", "CONTRACTOR", "con-link", "link.contractor", "Link@Contr26", 0),
    ("u-grid", "Suresh Babu", "CONTRACTOR", "con-grid", "grid.contractor", "Grid@Contr26", 0),
    ("u-pave", "Farah Khan", "CONTRACTOR", "con-pave", "pave.contractor", "Pave@Contr26", 0),
    ("u-inspector", "Nisha Verma", "INSPECTOR", "inspectorate", "inspector.nisha", "Inspect@Nisha26", 0),
    ("u-inspector2", "Arun Das", "INSPECTOR", "inspectorate", "inspector.arun", "Inspect@Arun26", 0),
    ("u-admin", "Priya Sharma", "ADMIN", "admin", "admin", "Admin@Work26", 0),
]
CREDENTIALS = {u[0]: (u[4], u[5]) for u in USERS}
TEST_CENTRE = (13.0617, 80.2693)   # tests build the sample scenario here

# The sample scenario (opt-in) places three invented works at these offsets (degrees) from a point you choose, so a
# tester can see them near their own location. Nothing is created unless the scenario is requested.
SCENARIO_ROADS = [
    ("road-market", "Market Road", 0.0261, 0.0092, "Sample works"),
    ("road-temple", "Temple Street", -0.0281, 0.0004, "Sample works"),
    ("road-station", "Station Road", 0.0115, -0.0084, "Sample works"),
]


def _project(conn, user_id: str, project_id: str, **kw) -> dict:
    user = one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
    body = sc.ProjectCreate(**kw)
    return svc.create_project(conn, user, body, project_id=project_id)


def _plan(conn, user_id: str, case_id: str) -> dict:
    user = one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
    case = svc.get_case(conn, case_id)
    return svc.generate_plan(conn, user, {"case": case}, sc.PlanRequest(expected_version=case["version"]))


def _declare(conn, user_id: str, road_id: str, mode: str = "ALL_WORK_REGISTERED") -> dict:
    user = one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
    road = svc.get_road(conn, road_id)
    body = sc.DeclarationRequest(expected_version=road["version"], mode=mode, covers_from=date(2026, 11, 1),
                                 covers_through=date(2027, 6, 30), valid_until=date(2027, 2, 28))
    return svc.declare(conn, user, {"road": road}, body)


def _staff(conn, user_id: str) -> dict:
    return auth.user_by_id(conn, user_id)


def _file(conn, category: str, text: str, lat: float, lng: float, n: int, **extra) -> dict:
    """File a sample complaint as if a different resident sent it (each sample has its own client key)."""
    body = sc.ComplaintCreate(category=category, description=text, lat=lat, lng=lng, **extra)
    out = complaints.create(conn, body, "sample-%d" % n, None)
    return out


def _move(conn, user_id: str, reference: str, status: str, **extra) -> None:
    c = one(conn, "SELECT * FROM complaints WHERE id = ?", (reference,))
    body = sc.ComplaintStatusRequest(expected_version=c["version"], status=status, **extra)
    complaints.triage(conn, _staff(conn, user_id), {"complaint": c}, body)


def create_sample_complaints(conn, lat: float, lng: float) -> list:
    """Invented example problems covering every situation a complaint can be in, so each screen can be tried.
    Returns a list of {reference, code, case} (the codes let you try tracking and the resident's confirm/reopen)."""
    out, n = [], [0]

    def new(category, text, dlat, dlng, case, **extra):
        n[0] += 1
        r = _file(conn, category, text, lat + dlat, lng + dlng, n[0], **extra)
        out.append({"reference": r["id"], "code": r["tracking_code"], "case": case})
        return r["id"]

    # 1. a single new report, normal priority
    new("WATER", "Water is leaking from a pipe outside the market and running onto the road.", 0.012, -0.006,
        "New and untouched: normal priority, waiting for Water to acknowledge")
    # 2. the same problem reported four times -> one URGENT problem
    for i, text in enumerate(["The street light is out and a cable is hanging low near the bus stop.",
                              "A live-looking cable is hanging at head height by the bus stop; the light above it is dead.",
                              "Electric cable hanging down at the bus stop, children walk under it to school.",
                              "Cable hanging low and the street light has not worked for a week at this stop."]):
        new("ELECTRICAL", text, 0.004, 0.003, "Duplicate reports: %d of 4 for one electrical problem (urgent once there are 4)" % (i + 1))
    # 3. acknowledged
    ref = new("TELECOM", "A telephone cable has fallen across the lane and vehicles keep catching it.", -0.008, 0.007,
              "Acknowledged by Telecom, no date promised yet")
    _move(conn, "u-telecom", ref, "ACKNOWLEDGED", note="We have logged this and will inspect it.")
    # 4. work under way with a promise that is still on track
    ref = new("ROAD_DAMAGE", "A large pothole at the junction; two-wheelers keep swerving around it.", 0.006, 0.011,
              "Promised in 5 days: on track")
    _move(conn, "u-roads", ref, "IN_PROGRESS", resolve_in_days=5, note="A patching crew is booked.")
    # 5. promise missed -> escalated to the head of department (the promise is back-dated so it is already overdue)
    ref = new("WATER", "Tap water has been brown and the pressure is very low since last week.", -0.004, -0.009,
              "Promise missed: escalated to the head of the Water Department, high priority")
    _move(conn, "u-water", ref, "IN_PROGRESS", resolve_in_days=3, note="The pipe is being flushed.")
    conn.execute("UPDATE complaints SET due_on = ? WHERE id = ?", (svc.d2s(svc.today(conn) - timedelta(days=2)), ref))
    complaints.escalate_overdue(conn)
    # 6. still unresolved after the head also failed -> the coordinator, urgent
    ref = new("ELECTRICAL", "The transformer near the school gate sparks every time it rains.", -0.011, 0.002,
              "Escalated twice: now with the coordinator, urgent")
    _move(conn, "u-power", ref, "IN_PROGRESS", resolve_in_days=2, note="An engineer will visit.")
    conn.execute("UPDATE complaints SET due_on = ? WHERE id = ?", (svc.d2s(svc.today(conn) - timedelta(days=6)), ref))
    complaints.escalate_overdue(conn)
    conn.execute("UPDATE complaints SET escalated_on = ? WHERE id = ?", (svc.d2s(svc.today(conn) - timedelta(days=4)), ref))
    complaints.escalate_overdue(conn)
    # 7. resolved, waiting for the resident to confirm
    ref = new("ROAD_DAMAGE", "The road sank after the pipe repair and now collects water.", 0.002, -0.012,
              "Marked resolved: use its tracking code to confirm it is fixed or reopen it")
    _move(conn, "u-roads", ref, "RESOLVED", note="The surface was relaid and compacted.")
    # 8. reopened by the resident -> back to the department with higher priority
    ref = new("TELECOM", "The cable duct cover is open and cables are lying exposed on the footpath.", -0.013, -0.004,
              "Reopened: the resident said it was not fixed")
    _move(conn, "u-telecom", ref, "RESOLVED", note="The cover was replaced.")
    code = next(o["code"] for o in out if o["reference"] == ref)
    complaints.resident_respond(conn, ref, code, None, "REOPEN", "The cover is still loose and the cables are showing again.")
    # 9. confirmed fixed by the resident
    ref = new("ELECTRICAL", "The street light outside the clinic has been flickering for days.", 0.009, -0.002,
              "Confirmed fixed by the resident (shows as fixed on the public map)")
    _move(conn, "u-power", ref, "RESOLVED", note="The lamp and driver were replaced.")
    complaints.resident_respond(conn, ref, next(o["code"] for o in out if o["reference"] == ref), None, "CONFIRM_FIXED", None)
    # 10. closed without action
    ref = new("WATER", "My neighbour's private tank overflows into the lane every morning.", -0.002, 0.013,
              "Closed without action (a private matter): shown to the resident with the reason")
    _move(conn, "u-water", ref, "REJECTED", note="This is a private property matter, not a municipal pipe.")
    # 11-14. categories that no single department owns: they wait for the coordinator
    new("SAFETY_HAZARD", "An open trench with no barrier or warning sign beside the footpath.", 0.001, -0.004,
        "Unrouted safety hazard: high priority, in the coordinator's queue to assign")
    new("WORK_WITHOUT_NOTICE", "A crew started digging at night with no notice board or permit displayed.", -0.006, 0.0,
        "Unrouted: work without notice, for the coordinator")
    new("DELAY", "The trench has been open for three weeks and nobody is working on it.", 0.0, 0.008,
        "Unrouted: work taking too long, for the coordinator")
    new("NOISE_DUST", "Drilling starts at 6 a.m. every day and dust is covering the shops.", 0.008, 0.004,
        "Unrouted: noise and dust, for the coordinator")
    new("OTHER", "Building material was left on the road after the work finished.", -0.009, -0.011,
        "Unrouted: something else, for the coordinator")
    return out


def _past(conn, days_ago: int) -> str:
    return svc.d2s(svc.today(conn) - timedelta(days=days_ago))


def _backdate(conn, reference: str, opened_days_ago: int, resolved_days_ago: Optional[int]) -> None:
    """Make an invented complaint look like it was handled earlier, so history and resolution times have variety."""
    ts = "2026-%02d-%02dT09:30:00Z" % ((svc.today(conn) - timedelta(days=opened_days_ago)).month, (svc.today(conn) - timedelta(days=opened_days_ago)).day)
    conn.execute("UPDATE complaints SET opened_on = ?, created_at = ?, resolved_on = ? WHERE id = ?",
                 (_past(conn, opened_days_ago), ts, _past(conn, resolved_days_ago) if resolved_days_ago is not None else None, reference))


def create_sample_history(conn, lat: float, lng: float) -> None:
    """Invented *past* records for the History screens: older works that finished (and one cancelled), and complaints that
    were handled weeks ago by different staff members, with different resolution times. Nothing here is live."""
    # --- older works on a street whose case is already complete
    road, _ = svc.create_road(conn, None, "Old Mill Road", lat + 0.0185, lng - 0.0205, "Sample history", road_id="road-old-mill")
    water, roads_u = "u-water2", "u-roads2"
    conn.execute("INSERT INTO cases(id, road_id, status, version, plan_version, completed_on, created_at) VALUES ('case-old-mill', ?, 'COMPLETED', 9, 1, ?, '2026-09-02T09:00:00Z')",
                 (road["id"], _past(conn, 24)))
    plan = [{"project_id": "oldmill-water", "start": _past(conn, 60), "end": _past(conn, 56), "project_version": 3, "material_version": 1},
            {"project_id": "oldmill-surface", "start": _past(conn, 50), "end": _past(conn, 47), "project_version": 3, "material_version": 1}]
    conn.execute("INSERT INTO plans(case_id, plan_version, outcome, messages_json, violations_json, schedule_json, excluded_json, horizon_end, created_by, created_at) "
                 "VALUES ('case-old-mill', 1, 'PLAN_FOUND', '[]', '[]', ?, '[]', ?, ?, '2026-09-02T09:05:00Z')", (json.dumps(plan), _past(conn, -150), roads_u))
    rows = [
        ("oldmill-water", "Sewer connection repair", "Repair a collapsed sewer connection under the carriageway", "UTILITY", "water", "con-aqua", _past(conn, 60), _past(conn, 56), 5,
         "DONE", _past(conn, 60), _past(conn, 56), _past(conn, 52), None, water),
        ("oldmill-surface", "Resurfacing after the sewer repair", "Relay the surface once the sewer work was released", "RESURFACING", "roads", "con-pave", _past(conn, 50), _past(conn, 47), 4,
         "DONE", _past(conn, 50), _past(conn, 47), _past(conn, 44), "PCC-2026-9001", roads_u),
        ("oldmill-telecom", "Duct extension (cancelled)", "Extend the duct to the new housing block", "UTILITY", "telecom", "con-link", _past(conn, 40), _past(conn, 30), 4,
         "CANCELLED", None, None, None, None, "u-telecom2"),
    ]
    for (pid, title, purpose, kind, owner, contractor, es, dl, dur, status, a_start, a_end, verified, pcc, lead) in rows:
        conn.execute(
            "INSERT INTO projects(id, title, purpose, road_id, kind, owner_org_id, assigned_contractor_id, earliest_start, deadline, duration_days, version, material_version,"
            " case_id, execution_status, actual_start, actual_end, testing_complete, reinstatement_complete, verified_on, pcc_number, cancel_reason, created_by, lead_user_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,3,1,'case-old-mill',?,?,?,?,?,?,?,?,?,?,'2026-09-02T08:50:00Z')",
            (pid, title, purpose, road["id"], kind, owner, contractor, es, dl, dur, status, a_start, a_end,
             1 if kind == "UTILITY" and status == "DONE" else 0, 1 if kind == "UTILITY" and status == "DONE" else 0, verified, pcc,
             "The new housing block was postponed by the developer." if status == "CANCELLED" else None, lead, lead))
    conn.execute("INSERT INTO inspections(project_id, kind, result, notes, inspected_on, inspector_user_id, recorded_at) VALUES "
                 "('oldmill-water','UTILITY_RELEASE','PASS','Trench reinstated and tested',?, 'u-inspector', '2026-09-30T10:00:00Z')", (_past(conn, 52),))
    conn.execute("INSERT INTO inspections(project_id, kind, result, notes, inspected_on, inspector_user_id, recorded_at) VALUES "
                 "('oldmill-surface','FINAL_SURFACE','PASS','Even surface, joints sealed',?, 'u-inspector2', '2026-10-05T10:00:00Z')", (_past(conn, 44),))
    for (when, actor_id, actor, action, pid, reason) in [
        ("2026-09-02T08:50:00Z", water, "Ravi Menon", "PROJECT_REGISTERED", "oldmill-water", None),
        ("2026-09-02T08:55:00Z", roads_u, "Sneha Kapoor", "PROJECT_REGISTERED", "oldmill-surface", None),
        ("2026-09-02T09:05:00Z", roads_u, "Sneha Kapoor", "PLAN_GENERATED", None, None),
        ("2026-09-04T11:00:00Z", None, "System", "PLAN_APPROVED", None, None),
        ("2026-09-09T08:10:00Z", "u-aqua", "Dev Patel", "WORK_STARTED", "oldmill-water", "Contractor reported start."),
        ("2026-09-13T17:20:00Z", "u-aqua", "Dev Patel", "WORK_FINISHED", "oldmill-water", None),
        ("2026-09-30T10:00:00Z", "u-inspector", "Nisha Verma", "INSPECTION_PASS", "oldmill-water", "Trench reinstated and tested"),
        ("2026-10-05T10:00:00Z", "u-inspector2", "Arun Das", "INSPECTION_PASS", "oldmill-surface", "Even surface, joints sealed"),
        ("2026-09-20T09:00:00Z", "u-telecom2", "Deepa Krishnan", "PROJECT_CANCELLED", "oldmill-telecom", "The new housing block was postponed by the developer."),
    ]:
        org = "water" if actor_id == water else "roads" if actor_id == roads_u else "telecom" if actor_id == "u-telecom2" else None
        conn.execute("INSERT INTO audit(recorded_at, actor_user_id, actor_name, action, reason, case_id, road_id, project_id, details_json, org_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (when, actor_id, actor, action, reason, "case-old-mill", road["id"], pid, json.dumps({"title": pid}), org or ("water" if pid == "oldmill-water" else "roads")))


def create_sample_complaints_history(conn, lat: float, lng: float, start_index: int) -> None:
    """Complaints that were handled earlier by different staff, with a spread of resolution times."""
    n = [start_index]

    def handled(category, text, dlat, dlng, dept_user, opened_ago, resolved_ago, final):
        n[0] += 1
        r = _file(conn, category, text, lat + dlat, lng + dlng, n[0])
        ref = r["id"]
        _move(conn, dept_user, ref, "ACKNOWLEDGED", note="Logged and assigned.")
        _move(conn, dept_user, ref, "RESOLVED", note="Fixed and checked on site.")
        if final == "CONFIRMED_FIXED":
            complaints.resident_respond(conn, ref, r["tracking_code"], None, "CONFIRM_FIXED", None)
        _backdate(conn, ref, opened_ago, resolved_ago)

    handled("WATER", "A hydrant was leaking at the corner and wasting water.", 0.0165, 0.004, "u-water2", 34, 31, "CONFIRMED_FIXED")
    handled("WATER", "Low water pressure on the whole lane for two days.", -0.0175, -0.0105, "u-water", 28, 20, "CONFIRMED_FIXED")
    handled("ELECTRICAL", "Two street lights out along the footpath by the park.", 0.0142, -0.0095, "u-power2", 41, 38, "CONFIRMED_FIXED")
    handled("ELECTRICAL", "A meter box door was hanging open with wires visible.", -0.0158, 0.0121, "u-power", 22, 21, "RESOLVED")
    handled("ROAD_DAMAGE", "A deep pothole damaged two vehicles last week.", 0.0172, 0.0118, "u-roads2", 19, 12, "CONFIRMED_FIXED")
    handled("TELECOM", "Broadband cable sagging across the road at truck height.", -0.0132, 0.0165, "u-telecom2", 45, 40, "CONFIRMED_FIXED")


def create_scenario(conn, lat: float, lng: float, sample_complaints: bool = True) -> dict:
    """Invented sample works around (lat, lng): Market Road has a sequential plan and a missing Power declaration,
    Temple Street has no valid sequential plan, Station Road is empty. Clearly labelled as sample data."""
    if one(conn, "SELECT 1 AS x FROM roads WHERE id = 'road-market'"):
        raise ApiError(409, "SCENARIO_EXISTS", "The sample scenario was already created. Run `python seed.py --reset` to start over.")
    for rid, name, dlat, dlng, label in SCENARIO_ROADS:
        svc.create_road(conn, None, name, lat + dlat, lng + dlng, label, road_id=rid)

    # Market Road: expected sequential plan Water 8-12, Telecom 14-17, surface 21-24 Nov.
    _project(conn, "u-water", "water-1", title="Water main repair",
             purpose="Replace a leaking water main under the carriageway", road_id="road-market", kind="UTILITY",
             assigned_contractor_id="con-aqua", earliest_start=date(2026, 11, 8), deadline=date(2026, 11, 20), duration_days=5)
    _project(conn, "u-telecom", "telecom-1", title="Telecom duct work",
             purpose="Lay new fibre ducts for the neighbourhood", road_id="road-market", kind="UTILITY",
             assigned_contractor_id="con-link", earliest_start=date(2026, 11, 13), deadline=date(2026, 11, 22), duration_days=4)
    _project(conn, "u-roads", "surface-1", title="Final road surface",
             purpose="Resurface the carriageway once utility work is released", road_id="road-market",
             kind="RESURFACING", assigned_contractor_id="con-pave", earliest_start=date(2026, 11, 10),
             deadline=date(2026, 11, 24), duration_days=4)
    # Water and Telecom confirm all their planned work; Power's declaration is deliberately missing.
    _declare(conn, "u-water", "road-market")
    _declare(conn, "u-telecom", "road-market")
    _plan(conn, "u-roads", "case-market")

    # Temple Street: Power finishes too late for the surface deadline -> no sequential plan.
    _project(conn, "u-power", "power-1", title="Power cable upgrade",
             purpose="Replace ageing low-voltage cable", road_id="road-temple", kind="UTILITY",
             assigned_contractor_id="con-grid", earliest_start=date(2026, 11, 30), deadline=date(2026, 12, 31), duration_days=5)
    _project(conn, "u-roads", "surface-2", title="Final road surface",
             purpose="Resurface the carriageway", road_id="road-temple", kind="RESURFACING",
             assigned_contractor_id="con-pave", earliest_start=date(2026, 11, 12), deadline=date(2026, 11, 20), duration_days=3)
    _plan(conn, "u-roads", "case-temple")
    out = create_sample_complaints(conn, lat, lng) if sample_complaints else []
    if sample_complaints:
        create_sample_history(conn, lat, lng)
        create_sample_complaints_history(conn, lat, lng, len(out) + 100)
        _assign_sample_staff(conn)
    return {"roads": [r[0] for r in SCENARIO_ROADS], "complaints": out}


def _assign_sample_staff(conn) -> None:
    """Spread the open sample complaints across the team so the head's view shows who is working on what."""
    plan = [("WATER", "u-water2"), ("ELECTRICAL", "u-power2"), ("TELECOM", "u-telecom"), ("ROAD_DAMAGE", "u-roads2")]
    for category, uid in plan:
        for c in many(conn, "SELECT id, group_id FROM complaints WHERE category = ? AND status IN ('NEW','ACKNOWLEDGED','IN_PROGRESS','REOPENED') "
                            "AND assigned_user_id IS NULL AND department_id = ?", (category, auth.user_by_id(conn, uid)["org_id"])):
            conn.execute("UPDATE complaints SET assigned_user_id = ? WHERE group_id = ? AND status IN ('NEW','ACKNOWLEDGED','IN_PROGRESS','REOPENED')", (uid, c["group_id"]))


def seed_database(path: Optional[str] = None, reset: bool = False, scenario: Optional[tuple] = None,
                  sample_complaints: bool = False) -> None:
    """Organisations, users and the demo clock only. There are no streets, works or complaints unless a
    scenario location is passed (or the administrator creates the sample scenario from the app)."""
    path = path or db_path()
    if reset:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
    init_db(path)
    # A hosted demo can set one password for every staff account without it being written in the repository.
    override = os.environ.get("WORKSYNC_STAFF_PASSWORD")
    if override is not None and auth.password_problems(override):
        raise SystemExit("WORKSYNC_STAFF_PASSWORD is too weak: " + " ".join(auth.password_problems(override)))
    conn = connect(path)
    try:
        with transaction(conn):
            conn.executemany("INSERT INTO orgs(id, name, kind, project_kind) VALUES (?,?,?,?)", ORGS)
            for uid, name, role, org, username, password, is_head in USERS:
                conn.execute("INSERT INTO users(id, username, password_hash, name, role, org_id, is_head) VALUES (?,?,?,?,?,?,?)",
                             (uid, username, hash_password(override or password), name, role, org, is_head))
            conn.execute("INSERT INTO demo_clock(id, date, version) VALUES (1, ?, 1)", (DEMO_START,))
            if scenario:
                create_scenario(conn, scenario[0], scenario[1], sample_complaints)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the WorkSync demo database")
    parser.add_argument("--reset", action="store_true", help="delete the existing database file first")
    parser.add_argument("--db", help="database path (default: WORKSYNC_DB or backend/worksync.db)")
    parser.add_argument("--scenario", nargs=2, type=float, metavar=("LAT", "LNG"),
                        help="also create the invented sample works and example complaints around this point")
    args = parser.parse_args()
    target = args.db or db_path()
    seed_database(target, reset=args.reset, scenario=tuple(args.scenario) if args.scenario else None, sample_complaints=True)
    print("Seeded %s (demo date %s)%s" % (target, DEMO_START, ", with sample works and example complaints" if args.scenario else ", no streets or works"))
    if args.scenario:
        print("Example complaints exist for every situation. Sign in as the coordinator to see and act on them. "
              "(Their tracking codes are shown by the app's sample button, not here.)")
