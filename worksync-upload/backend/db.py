"""SQLite schema, connections and transactions.

Every mutation runs inside one ``BEGIN IMMEDIATE`` transaction so business
changes, audit rows and the idempotency record commit (or roll back) together.
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Iterator, Optional


def db_path() -> str:
    return os.environ.get("WORKSYNC_DB") or str(Path(__file__).with_name("worksync.db"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('DEPARTMENT','CONTRACTOR','INSPECTORATE','ADMIN')),
    project_kind TEXT CHECK (project_kind IN ('UTILITY','RESURFACING'))
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('DEPARTMENT','CONTRACTOR','INSPECTOR','ADMIN')),
    org_id TEXT NOT NULL REFERENCES orgs(id),
    is_head INTEGER NOT NULL DEFAULT 0
);

-- Residents who chose to sign in with Google. Guests have no row. They can never use staff endpoints.
CREATE TABLE IF NOT EXISTS residents (
    id TEXT PRIMARY KEY,
    google_sub TEXT UNIQUE,
    email TEXT,
    name TEXT,
    password_hash TEXT,
    created_at TEXT NOT NULL
);
-- A local account is an e-mail + password (the e-mail is NOT verified: nothing is ever sent). One account per e-mail.
CREATE UNIQUE INDEX IF NOT EXISTS residents_local_email ON residents(lower(email)) WHERE password_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS resident_sessions (
    token_hash TEXT PRIMARY KEY,
    resident_id TEXT NOT NULL REFERENCES residents(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- Failed sign-ins and failed complaint look-ups, for throttling. Kept outside request transactions.
CREATE TABLE IF NOT EXISTS throttle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    at_epoch REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS throttle_lookup ON throttle(kind, key, at_epoch);

CREATE TABLE IF NOT EXISTS complaints (
    id TEXT PRIMARY KEY,
    tracking_hash TEXT NOT NULL,
    category TEXT NOT NULL,
    department_id TEXT REFERENCES orgs(id),
    description TEXT NOT NULL,
    road_id TEXT REFERENCES roads(id),
    location_text TEXT,
    lat REAL,
    lng REAL,
    contact_name TEXT,
    contact_detail TEXT,
    resident_id TEXT REFERENCES residents(id),
    status TEXT NOT NULL DEFAULT 'NEW'
        CHECK (status IN ('NEW','ACKNOWLEDGED','IN_PROGRESS','RESOLVED','CONFIRMED_FIXED','REOPENED','REJECTED')),
    version INTEGER NOT NULL DEFAULT 1,
    group_id TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'NORMAL' CHECK (priority IN ('NORMAL','HIGH','URGENT')),
    priority_reason TEXT,
    public_note TEXT,
    committed_days INTEGER,
    due_on TEXT,
    escalation_level INTEGER NOT NULL DEFAULT 0,
    escalated_on TEXT,
    escalated_due_on TEXT,
    assigned_user_id TEXT REFERENCES users(id),
    opened_on TEXT,
    resolved_on TEXT,
    client_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS complaints_by_group ON complaints(group_id);
CREATE INDEX IF NOT EXISTS complaints_by_dept ON complaints(department_id, status);

-- Every status change becomes a timeline entry. These are the resident's notifications.
CREATE TABLE IF NOT EXISTS complaint_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL REFERENCES complaints(id),
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    actor_label TEXT NOT NULL,
    actor_user_id TEXT,
    actor_name TEXT
);
CREATE INDEX IF NOT EXISTS events_by_complaint ON complaint_events(complaint_id);

CREATE TABLE IF NOT EXISTS roads (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL,
    lng REAL,
    area_label TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    registry_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS road_expected_depts (
    road_id TEXT NOT NULL REFERENCES roads(id),
    org_id TEXT NOT NULL REFERENCES orgs(id),
    PRIMARY KEY (road_id, org_id)
);

CREATE TABLE IF NOT EXISTS demo_clock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    date TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    road_id TEXT NOT NULL REFERENCES roads(id),
    status TEXT NOT NULL CHECK (status IN
        ('DRAFT','CONTRACTOR_REVIEW','DEPARTMENT_REVIEW','APPROVED','BLOCKED','COMPLETED')),
    version INTEGER NOT NULL DEFAULT 1,
    plan_version INTEGER NOT NULL DEFAULT 0,
    review_deadline_at TEXT,
    hold_reason TEXT,
    public_reason TEXT,
    completed_on TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_case_per_road
    ON cases(road_id) WHERE status <> 'COMPLETED';

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    purpose TEXT NOT NULL,
    road_id TEXT NOT NULL REFERENCES roads(id),
    kind TEXT NOT NULL CHECK (kind IN ('UTILITY','RESURFACING')),
    owner_org_id TEXT NOT NULL REFERENCES orgs(id),
    assigned_contractor_id TEXT NOT NULL REFERENCES orgs(id),
    earliest_start TEXT NOT NULL,
    deadline TEXT NOT NULL,
    duration_days INTEGER NOT NULL CHECK (duration_days > 0),
    version INTEGER NOT NULL DEFAULT 1,
    material_version INTEGER NOT NULL DEFAULT 1,
    case_id TEXT REFERENCES cases(id),
    execution_status TEXT NOT NULL DEFAULT 'PLANNED'
        CHECK (execution_status IN ('PLANNED','IN_PROGRESS','DONE','CANCELLED')),
    actual_start TEXT,
    actual_end TEXT,
    testing_complete INTEGER NOT NULL DEFAULT 0,
    reinstatement_complete INTEGER NOT NULL DEFAULT 0,
    finished_by_user_id TEXT REFERENCES users(id),
    delay_reason TEXT,
    pcc_number TEXT,
    cancel_reason TEXT,
    verified_on TEXT,
    created_by TEXT REFERENCES users(id),
    lead_user_id TEXT REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS projects_by_road ON projects(road_id);
CREATE INDEX IF NOT EXISTS projects_by_case ON projects(case_id);

CREATE TABLE IF NOT EXISTS plans (
    case_id TEXT NOT NULL REFERENCES cases(id),
    plan_version INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('PLAN_FOUND','NO_SEQUENTIAL_PLAN','UNASSESSABLE')),
    messages_json TEXT NOT NULL,
    violations_json TEXT NOT NULL,
    schedule_json TEXT NOT NULL,
    excluded_json TEXT NOT NULL,
    horizon_end TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_id, plan_version)
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    plan_version INTEGER NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id),
    decision TEXT NOT NULL CHECK (decision IN ('ACCEPT','COUNTERPROPOSE','REJECT')),
    reason TEXT,
    earliest_start TEXT,
    user_id TEXT NOT NULL REFERENCES users(id),
    recorded_at TEXT NOT NULL,
    UNIQUE (case_id, plan_version, project_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    plan_version INTEGER NOT NULL,
    org_id TEXT NOT NULL REFERENCES orgs(id),
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
    reason TEXT,
    user_id TEXT NOT NULL REFERENCES users(id),
    recorded_at TEXT NOT NULL,
    UNIQUE (case_id, plan_version, org_id)
);

CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL CHECK (kind IN ('UTILITY_RELEASE','FINAL_SURFACE')),
    result TEXT NOT NULL CHECK (result IN ('PASS','FAIL')),
    notes TEXT NOT NULL,
    inspected_on TEXT NOT NULL,
    inspector_user_id TEXT NOT NULL REFERENCES users(id),
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    road_id TEXT NOT NULL REFERENCES roads(id),
    org_id TEXT NOT NULL REFERENCES orgs(id),
    mode TEXT NOT NULL CHECK (mode IN ('ALL_WORK_REGISTERED','NO_PLANNED_WORK')),
    covers_from TEXT NOT NULL,
    covers_through TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    registry_version INTEGER NOT NULL,
    known_project_ids_json TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id),
    case_id TEXT NOT NULL REFERENCES cases(id),
    kind TEXT NOT NULL CHECK (kind IN ('WORK_WITHOUT_CLEARANCE','SITE_ISSUE')),
    description TEXT NOT NULL,
    occurred_date TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','REVIEWED')),
    reporter_user_id TEXT NOT NULL REFERENCES users(id),
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    actor_user_id TEXT,
    actor_name TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    case_id TEXT,
    road_id TEXT,
    project_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    org_id TEXT
);
CREATE INDEX IF NOT EXISTS audit_by_case ON audit(case_id);
CREATE INDEX IF NOT EXISTS audit_by_org ON audit(org_id);
CREATE INDEX IF NOT EXISTS audit_by_actor ON audit(actor_user_id);

CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit rows are append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit rows are append-only'); END;

CREATE TRIGGER IF NOT EXISTS plans_no_update BEFORE UPDATE ON plans
BEGIN SELECT RAISE(ABORT, 'plans are immutable'); END;
CREATE TRIGGER IF NOT EXISTS plans_no_delete BEFORE DELETE ON plans
BEGIN SELECT RAISE(ABORT, 'plans are immutable'); END;

CREATE TABLE IF NOT EXISTS idempotency (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    action TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    # isolation_level=None -> autocommit; transactions are explicit below.
    conn = sqlite3.connect(path or db_path(), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


SCHEMA_VERSION = "5"


def init_db(path: Optional[str] = None) -> None:
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        # An older database cannot be upgraded in place: fail clearly, not obscurely.
        existing = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if existing:
            has_meta = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
            version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone() if has_meta else None
            if not version or version["value"] != SCHEMA_VERSION:
                raise RuntimeError("This database was created by an older WorkSync version. "
                                   "Run `python seed.py --reset` to recreate it.")
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
    finally:
        conn.close()


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Write transaction: takes the write lock up front (BEGIN IMMEDIATE)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@contextlib.contextmanager
def read_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Consistent snapshot for multi-query reads."""
    conn.execute("BEGIN")
    try:
        yield conn
    finally:
        conn.execute("COMMIT")


def one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Optional[dict]:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def many(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
