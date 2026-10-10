"""WorkSync backend: FastAPI routes, CORS, error envelope and startup checks.

Run:  uvicorn main:app --host 127.0.0.1 --port 8000
Docs: http://localhost:8000/docs   Schema: http://localhost:8000/openapi.json
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

import schemas as sc
import service as svc
import views
import auth
import complaints
import google
import staff
from db import connect, init_db, one, read_transaction, transaction
from errors import ApiError, not_found, unauthenticated

API_PREFIX = "/api/v1"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def cors_origins() -> List[str]:
    raw = os.environ.get("WORKSYNC_CORS_ORIGINS", "http://localhost:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


# ------------------------------------------------------------- startup
def prepare_database() -> None:
    init_db()
    conn = connect()
    try:
        empty = one(conn, "SELECT COUNT(*) AS n FROM users")["n"] == 0
    finally:
        conn.close()
    if empty and os.environ.get("WORKSYNC_AUTOSEED", "1") == "1":
        import seed
        # A public demo should not open empty: WORKSYNC_DEMO_SCENARIO="LAT,LNG" loads the invented sample works and
        # example complaints around that point on the first start.
        scenario = None
        raw = os.environ.get("WORKSYNC_DEMO_SCENARIO", "").strip()
        if raw:
            lat, lng = (float(x) for x in raw.split(","))
            scenario = (lat, lng)
        seed.seed_database(scenario=scenario, sample_complaints=True)


async def _periodic_review_check() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await asyncio.to_thread(svc.sweep_command_time)
        except Exception:  # keep the checker alive; the next command-time check will retry
            pass


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    prepare_database()
    task = asyncio.create_task(_periodic_review_check())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="WorkSync API",
    version="1.0.0",
    description=("Local demonstrator backend. The public (residents) needs no sign-in and sees only public endpoints. "
                 "Staff sign in with `POST /auth/login` (dummy credentials, see DEMO_CREDENTIALS.md) and send "
                 "`Authorization: Bearer <token>`; this is not production authentication. Dates use YYYY-MM-DD; the "
                 "clock and work dates are Asia/Kolkata. All buffers and the 180-day windows are demo policy."),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
    expose_headers=["Idempotent-Replay"],
)


# ------------------------------------------------------ error envelope
@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    headers = {"Retry-After": "1"} if exc.status == 503 else None
    return JSONResponse(exc.envelope(), status_code=exc.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    failures = []
    for e in exc.errors():
        loc = [str(x) for x in e.get("loc", []) if x not in ("body", "query", "path", "header")]
        failures.append({"field": ".".join(loc), "message": str(e.get("msg", "Invalid value")).replace("Value error, ", "")})
    return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "Check the highlighted fields.",
                                   "failures": failures}}, status_code=422)


@app.exception_handler(StarletteHTTPException)
async def http_handler(_: Request, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse({"error": {"code": code, "message": str(exc.detail), "failures": []}}, status_code=exc.status_code)


@app.exception_handler(sqlite3.OperationalError)
async def sqlite_handler(_: Request, exc: sqlite3.OperationalError):
    if "locked" in str(exc) or "busy" in str(exc):
        return JSONResponse({"error": {"code": "DATABASE_BUSY", "message": "The database is busy. Please retry the same request.",
                                       "failures": []}}, status_code=503, headers={"Retry-After": "1"})
    return JSONResponse({"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong on the server.", "failures": []}},
                        status_code=500)


@app.exception_handler(Exception)
async def unexpected_handler(_: Request, exc: Exception):
    return JSONResponse({"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong on the server.", "failures": []}},
                        status_code=500)


# ---------------------------------------------------------- dependencies
bearer = HTTPBearer(auto_error=False, description="Token from POST /auth/login")


def _token(creds: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    return creds.credentials if creds else None


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> dict:
    """Staff only. A missing, expired or unknown token is refused; there is no anonymous fallback."""
    conn = connect()
    try:
        user = auth.user_for_token(conn, _token(creds))
    finally:
        conn.close()
    if not user:
        raise unauthenticated("Please sign in to continue.")
    return user


def optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> Optional[dict]:
    conn = connect()
    try:
        return auth.user_for_token(conn, _token(creds))
    finally:
        conn.close()


def optional_resident(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> Optional[dict]:
    """A signed-in resident (Google), if any. Guests simply have none."""
    conn = connect()
    try:
        return auth.resident_for_token(conn, _token(creds))
    finally:
        conn.close()


def current_resident(resident: Optional[dict] = Depends(optional_resident)) -> dict:
    if not resident:
        raise unauthenticated("Sign in with Google to see your reports.")
    return resident


def client_host(request: Request) -> str:
    """Who is calling, for throttling. Behind a hosting proxy (WORKSYNC_BEHIND_PROXY=1) the connection comes from the
    proxy, so the address the proxy itself appended (the right-most X-Forwarded-For entry) is used. Entries further
    left can be written by the caller, so they are never trusted."""
    if os.environ.get("WORKSYNC_BEHIND_PROXY") == "1":
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else ""


def idempotency_key(idempotency_key: Optional[str] = Header(
        default=None, description="Unique per intended action; reuse it only to retry the same action.")) -> str:
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise ApiError(422, "IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key header (up to 200 characters) with this request.")
    return idempotency_key.strip()


def read(fn: Callable, *args) -> Any:
    conn = connect()
    try:
        with read_transaction(conn):
            return fn(conn, *args)
    finally:
        conn.close()


def respond(result) -> JSONResponse:
    code, body, replay = result
    return JSONResponse(body, status_code=code, headers={"Idempotent-Replay": "true"} if replay else None)


ERRORS = {c: {"model": sc.ErrorEnvelope} for c in (401, 403, 404, 409, 422, 503)}
MUTATION = {200: {"model": sc.MutationResult}, **ERRORS}

router = APIRouter(prefix=API_PREFIX)

CASE_EXAMPLE = {
    "id": "case-market", "road_id": "road-market", "road_name": "Market Road", "version": 4, "status": "CONTRACTOR_REVIEW",
    "plan_version": 1, "deadline_at": "2026-11-10T02:30:00Z",
    "assessment": {"outcome": "PLAN_FOUND", "messages": []},
    "schedule": [
        {"project_id": "water-1", "project_version": 1, "title": "Water main repair", "kind": "UTILITY",
         "start": "2026-11-08", "end": "2026-11-12", "date_label": "PROPOSED"},
        {"project_id": "telecom-1", "project_version": 1, "title": "Telecom duct work", "kind": "UTILITY",
         "start": "2026-11-14", "end": "2026-11-17", "date_label": "PROPOSED"},
        {"project_id": "surface-1", "project_version": 1, "title": "Final road surface", "kind": "RESURFACING",
         "start": "2026-11-21", "end": "2026-11-24", "date_label": "PROPOSED"}],
    "responses": [], "approvals": [], "required_departments": ["roads", "telecom", "water"],
    "coverage_required": ["power", "telecom", "water"], "hold": False, "public_reason": None,
    "allowed_actions": ["RESPOND"],
}


# ----------------------------------------------------------------- reads
@router.get("/bootstrap", tags=["public"], summary="Roads, clock and labelled demo policy (more detail once signed in)")
def get_bootstrap(user: Optional[dict] = Depends(optional_user)):
    return read(views.bootstrap, user)


@router.get("/roads", tags=["public"], summary="Public: every road with coordinates and a resident-safe summary")
def get_roads():
    return read(views.public_roads)


@router.get("/roads/{road_id}/public", tags=["public"], summary="Public road view (no identity needed)")
def get_public_road(road_id: str):
    return read(views.public_road, road_id)


@router.get("/projects", tags=["projects"], response_model=sc.Items, responses=ERRORS)
def get_projects(road_id: Optional[str] = Query(default=None), state: Optional[str] = Query(default=None, description="active | done | cancelled | past"),
                 q: Optional[str] = Query(default=None, max_length=100), user: dict = Depends(current_user)):
    return read(views.list_projects, user, road_id, state, q)


@router.get("/cases", tags=["cases"], response_model=sc.Items, responses=ERRORS)
def get_cases(road_id: Optional[str] = Query(default=None), user: dict = Depends(current_user)):
    return read(views.list_cases, user, road_id)


@router.get("/cases/{case_id}", tags=["cases"], responses={200: {"content": {"application/json": {"example": CASE_EXAMPLE}}}, **ERRORS},
            summary="Case detail (the example shows the contract's core fields; more display fields are included)")
def get_case_detail(case_id: str, user: dict = Depends(current_user)):
    return read(views.case_detail, user, case_id)


@router.get("/cases/{case_id}/audit", tags=["cases"], response_model=sc.Items, responses=ERRORS)
def get_case_audit(case_id: str, user: dict = Depends(current_user)):
    return read(views.audit_events, user, case_id)


@router.get("/projects/{project_id}/gate", tags=["execution"], response_model=sc.GateOut, responses=ERRORS,
            summary="Read-only start eligibility; never an authorisation")
def get_gate(project_id: str, user: dict = Depends(current_user)):
    def run(conn):
        p = views.get_project_detail(conn, user, project_id)
        return svc.compute_gate(conn, p)
    return read(run)


# ------------------------------------------------------------- mutations
@router.post("/projects", status_code=201, tags=["projects"], responses={201: {"model": sc.MutationResult}, **ERRORS})
def post_project(body: sc.ProjectCreate, user: dict = Depends(current_user), key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /projects", body.model_dump(mode="json"),
        svc.authorize_create_project(user, body),
        lambda conn, ctx: svc.create_project(conn, user, body), status=201))


@router.patch("/projects/{project_id}", tags=["projects"], responses=MUTATION)
def patch_project(project_id: str, body: sc.ProjectPatch, user: dict = Depends(current_user),
                  key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "PATCH /projects/%s" % project_id, body.model_dump(mode="json", exclude_unset=True),
        svc.authorize_owner_project(user, project_id),
        lambda conn, ctx: svc.patch_project(conn, user, ctx, body)))


@router.post("/projects/{project_id}/cancel", tags=["projects"], responses=MUTATION)
def post_cancel(project_id: str, body: sc.CancelRequest, user: dict = Depends(current_user),
                key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /projects/%s/cancel" % project_id, body.model_dump(mode="json"),
        svc.authorize_owner_project(user, project_id),
        lambda conn, ctx: svc.cancel_project(conn, user, ctx, body)))


@router.post("/cases/{case_id}/plans", tags=["cases"], responses=MUTATION,
             summary="Generate a supported sequential plan, or persist a blocked assessment")
def post_plan(case_id: str, body: sc.PlanRequest, user: dict = Depends(current_user), key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /cases/%s/plans" % case_id, body.model_dump(mode="json"),
        svc.authorize_generate_plan(user, case_id),
        lambda conn, ctx: svc.generate_plan(conn, user, ctx, body)))


@router.post("/cases/{case_id}/responses", tags=["cases"], responses=MUTATION)
def post_response(case_id: str, body: sc.ContractorResponseRequest, user: dict = Depends(current_user),
                  key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /cases/%s/responses" % case_id, body.model_dump(mode="json"),
        svc.authorize_respond(user, case_id, body.project_id),
        lambda conn, ctx: svc.respond(conn, user, ctx, body)))


@router.post("/cases/{case_id}/approvals", tags=["cases"], responses=MUTATION)
def post_approval(case_id: str, body: sc.ApprovalRequest, user: dict = Depends(current_user),
                  key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /cases/%s/approvals" % case_id, body.model_dump(mode="json"),
        svc.authorize_approve(user, case_id),
        lambda conn, ctx: svc.approve(conn, user, ctx, body)))


@router.post("/cases/{case_id}/review", tags=["cases"], responses=MUTATION,
             summary="Admin review: request revision or keep blocked. Never forces approval")
def post_review(case_id: str, body: sc.ReviewRequest, user: dict = Depends(current_user), key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /cases/%s/review" % case_id, body.model_dump(mode="json"),
        svc.authorize_admin_case(user, case_id),
        lambda conn, ctx: svc.review_case(conn, user, ctx, body)))


@router.post("/projects/{project_id}/start", tags=["execution"], responses=MUTATION,
             summary="Authorise and start now (re-checks the gate; issues a PCC for resurfacing)")
def post_start(project_id: str, body: sc.StartRequest, user: dict = Depends(current_user), key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /projects/%s/start" % project_id, body.model_dump(mode="json"),
        svc.authorize_assigned_contractor(user, project_id),
        lambda conn, ctx: svc.start_project(conn, user, ctx, body)))


@router.post("/projects/{project_id}/finish", tags=["execution"], responses=MUTATION)
def post_finish(project_id: str, body: sc.FinishRequest, user: dict = Depends(current_user), key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /projects/%s/finish" % project_id, body.model_dump(mode="json"),
        svc.authorize_assigned_contractor(user, project_id),
        lambda conn, ctx: svc.finish_project(conn, user, ctx, body)))


@router.post("/projects/{project_id}/inspections", tags=["execution"], responses=MUTATION)
def post_inspection(project_id: str, body: sc.InspectionRequest, user: dict = Depends(current_user),
                    key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /projects/%s/inspections" % project_id, body.model_dump(mode="json"),
        svc.authorize_inspector(user, project_id),
        lambda conn, ctx: svc.record_inspection(conn, user, ctx, body)))


@router.post("/projects/{project_id}/incidents", tags=["execution"], responses=MUTATION,
             summary="Record a claim and place a review hold; never grants retrospective permission")
def post_incident(project_id: str, body: sc.IncidentRequest, user: dict = Depends(current_user),
                  key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /projects/%s/incidents" % project_id, body.model_dump(mode="json"),
        svc.authorize_incident(user, project_id),
        lambda conn, ctx: svc.report_incident(conn, user, ctx, body)))


@router.post("/roads/{road_id}/declarations", tags=["execution"], responses=MUTATION)
def post_declaration(road_id: str, body: sc.DeclarationRequest, user: dict = Depends(current_user),
                     key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /roads/%s/declarations" % road_id, body.model_dump(mode="json"),
        svc.authorize_declare(user, road_id),
        lambda conn, ctx: svc.declare(conn, user, ctx, body)))


@router.post("/demo/clock/advance", tags=["demo"], responses=MUTATION,
             summary="Advance the simulated clock (forward-only, local demo only)")
def post_clock(request: Request, body: sc.ClockAdvanceRequest, user: dict = Depends(current_user),
               key: str = Depends(idempotency_key)):
    host = request.client.host if request.client else ""
    # Behind a proxy every request looks local to the app, so the clock is then open only if explicitly allowed.
    local_ok = (host in LOCAL_HOSTS and os.environ.get("WORKSYNC_BEHIND_PROXY") != "1") \
        or os.environ.get("WORKSYNC_ALLOW_REMOTE_CLOCK") == "1"
    return respond(svc.mutate(
        user, key, "POST /demo/clock/advance", body.model_dump(mode="json"),
        svc.authorize_clock(user, local_ok),
        lambda conn, ctx: svc.advance_clock(conn, user, ctx, body)))


# ------------------------------------------------------------------ auth
@router.post("/auth/login", tags=["auth"], summary="Staff sign-in (not for the public)", responses={401: {"model": sc.ErrorEnvelope}, 429: {"model": sc.ErrorEnvelope}})
def post_login(body: sc.LoginRequest, request: Request):
    key = auth.client_key(client_host(request)) + "|" + body.username.strip().lower()
    conn = connect()
    try:
        outcome = None
        with transaction(conn):
            if auth.throttle_blocked(conn, "login", key, auth.LOGIN_MAX_FAILURES, auth.LOGIN_WINDOW_SECONDS):
                outcome = "blocked"
            else:
                found = auth.check_credentials(conn, body.username, body.password)
                if not found:
                    auth.throttle_record(conn, "login", key)         # committed even though we refuse below
                    outcome = "bad"
                else:
                    auth.throttle_clear(conn, "login", key)
                    token, expires = auth.create_session(conn, found["id"])
                    user = auth.user_by_id(conn, found["id"])
                    svc.audit(conn, user, "SIGNED_IN")
                    outcome = "ok"
        if outcome == "blocked":
            raise auth.too_many_attempts()
        if outcome == "bad":
            raise ApiError(401, "INVALID_CREDENTIALS", "Incorrect username or password.")
        return {"token": token, "token_type": "Bearer", "expires_at": expires, "user": auth.public_user(user)}
    finally:
        conn.close()


@router.post("/auth/logout", tags=["auth"], responses=ERRORS)
def post_logout(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer), user: dict = Depends(current_user)):
    conn = connect()
    try:
        with transaction(conn):
            auth.revoke_session(conn, _token(creds) or "")
            svc.audit(conn, user, "SIGNED_OUT")
    finally:
        conn.close()
    return {"message": "Signed out."}


@router.get("/auth/me", tags=["auth"], responses=ERRORS)
def get_me(user: dict = Depends(current_user)):
    return auth.public_user(user)


# ------------------------------------------------------------ complaints
@router.get("/complaints/public", tags=["complaints"], summary="Public: problems reported near people (no personal details)")
def get_public_feed():
    return read(complaints.public_feed)


@router.post("/complaints", status_code=201, tags=["complaints"],
             responses={201: {"model": sc.MutationResult}, 422: {"model": sc.ErrorEnvelope}, 429: {"model": sc.ErrorEnvelope}},
             summary="Public: report a problem (no sign-in; Google sign-in is optional)")
def post_complaint(body: sc.ComplaintCreate, request: Request, key: str = Depends(idempotency_key),
                   resident: Optional[dict] = Depends(optional_resident)):
    ckey = auth.client_key(client_host(request))
    actor = {"id": ("resident:" + resident["id"]) if resident else "public:" + ckey, "name": "Member of the public"}
    return respond(svc.mutate(actor, key, "POST /complaints", body.model_dump(mode="json"),
                              lambda conn: {}, lambda conn, ctx: complaints.create(conn, body, ckey, resident), status=201))


def _owner_lookup(conn, reference: str, code: Optional[str], resident: Optional[dict]):
    c = one(conn, "SELECT * FROM complaints WHERE id = ?", (reference.strip().upper(),))
    return c if c and complaints._owns(c, code, resident) else None


@router.post("/complaints/track", tags=["complaints"], summary="Public: check a complaint with its reference and tracking code",
             responses={404: {"model": sc.ErrorEnvelope}, 429: {"model": sc.ErrorEnvelope}})
def post_track(body: sc.ComplaintTrackRequest, request: Request, resident: Optional[dict] = Depends(optional_resident)):
    ckey = auth.client_key(client_host(request))
    conn = connect()
    try:
        result = None
        with transaction(conn):
            if auth.throttle_blocked(conn, "track", ckey, auth.TRACK_MAX_FAILURES, auth.TRACK_WINDOW_SECONDS):
                result = "blocked"
            else:
                c = _owner_lookup(conn, body.reference, body.code, resident)
                if c:
                    result = complaints.track_view(conn, c)
                else:
                    auth.throttle_record(conn, "track", ckey)
                    result = "missing"
        if result == "blocked":
            raise auth.too_many_attempts()
        if result == "missing":
            raise not_found("A complaint with that reference and tracking code")
        return result
    finally:
        conn.close()


@router.post("/complaints/respond", tags=["complaints"], summary="The person who complained confirms it is fixed, or reopens it",
             responses={404: {"model": sc.ErrorEnvelope}, 409: {"model": sc.ErrorEnvelope}, 429: {"model": sc.ErrorEnvelope}})
def post_resident_response(body: sc.ResidentResponseRequest, request: Request, resident: Optional[dict] = Depends(optional_resident)):
    ckey = auth.client_key(client_host(request))
    conn = connect()
    try:
        out = None
        with transaction(conn):
            if auth.throttle_blocked(conn, "track", ckey, auth.TRACK_MAX_FAILURES, auth.TRACK_WINDOW_SECONDS):
                out = {"result": "blocked"}
            else:
                out = complaints.resident_respond(conn, body.reference, body.code, resident, body.action, body.note)
                if out["result"] == "missing":
                    auth.throttle_record(conn, "track", ckey)
        if out["result"] == "blocked":
            raise auth.too_many_attempts()
        if out["result"] == "missing":
            raise not_found("A complaint with that reference and tracking code")
        if out["result"] == "state":
            raise ApiError(409, "INVALID_STATE", out["message"])
        conn2 = connect()
        try:
            c = one(conn2, "SELECT * FROM complaints WHERE id = ?", (body.reference.strip().upper(),))
            return {"message": out["message"], "status": out["status"], "complaint": complaints.track_view(conn2, c)}
        finally:
            conn2.close()
    finally:
        conn.close()


@router.get("/me/complaints", tags=["complaints"], summary="Resident (Google): my reports with their timelines",
            responses={401: {"model": sc.ErrorEnvelope}})
def get_my_complaints(resident: dict = Depends(current_resident)):
    return read(complaints.mine, resident)


@router.get("/complaints", tags=["complaints"], responses=ERRORS,
           summary="Staff: the complaints inbox for your department (the coordinator sees all)")
def get_complaints(status: Optional[str] = Query(default=None), priority: Optional[str] = Query(default=None),
                   scope: str = Query(default="all", pattern="^(open|closed|all)$", description="open = still to do, closed = history"),
                   q: Optional[str] = Query(default=None, max_length=100), category: Optional[str] = Query(default=None),
                   assigned: Optional[str] = Query(default=None, description="a staff user id, or 'none'"),
                   opened_from: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                   opened_to: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                   limit: Optional[int] = Query(default=None, ge=1, le=200), offset: int = Query(default=0, ge=0),
                   user: dict = Depends(current_user)):
    return read(complaints.list_for_staff, user, status, priority, scope, q, category, assigned, opened_from, opened_to, limit, offset)


@router.post("/complaints/{complaint_id}/status", tags=["complaints"], responses=MUTATION,
             summary="Staff: acknowledge, promise a resolution time, resolve or close")
def post_complaint_status(complaint_id: str, body: sc.ComplaintStatusRequest, user: dict = Depends(current_user),
                          key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /complaints/%s/status" % complaint_id, body.model_dump(mode="json"),
        complaints.authorize_complaint(user, complaint_id),
        lambda conn, ctx: complaints.triage(conn, user, ctx, body)))


@router.post("/complaints/{complaint_id}/assign", tags=["complaints"], responses=MUTATION,
             summary="Coordinator: send a complaint to a department")
def post_complaint_assign(complaint_id: str, body: sc.ComplaintAssignRequest, user: dict = Depends(current_user),
                          key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /complaints/%s/assign" % complaint_id, body.model_dump(mode="json"),
        complaints.authorize_complaint(user, complaint_id, assign=True),
        lambda conn, ctx: complaints.assign(conn, user, ctx, body)))



@router.post("/complaints/{complaint_id}/assign-staff", tags=["complaints"], responses=MUTATION,
             summary="Head/coordinator: give a complaint to a staff member (staff may take one for themselves)")
def post_complaint_assign_staff(complaint_id: str, body: sc.AssignStaffRequest, user: dict = Depends(current_user),
                                key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /complaints/%s/assign-staff" % complaint_id, body.model_dump(mode="json"),
        complaints.authorize_assign_staff(user, complaint_id, body.user_id),
        lambda conn, ctx: complaints.assign_staff(conn, user, ctx, body)))


# ------------------------------------------------- the staff window: overview, team, history
@router.get("/overview", tags=["staff window"], responses=ERRORS, summary="Dashboard for your department (the coordinator: any or all)")
def get_overview(department_id: Optional[str] = Query(default=None), user: dict = Depends(current_user)):
    return read(staff.overview, user, department_id)


@router.get("/team", tags=["staff window"], responses=ERRORS, summary="Head/coordinator: every colleague and what they are working on")
def get_team(department_id: Optional[str] = Query(default=None), user: dict = Depends(current_user)):
    return read(staff.team, user, department_id)


@router.get("/team/{user_id}", tags=["staff window"], responses=ERRORS, summary="One person's complaints, projects and recent actions")
def get_team_member(user_id: str, user: dict = Depends(current_user)):
    return read(staff.team_member, user, user_id)


@router.get("/activity", tags=["staff window"], responses=ERRORS, summary="Activity trail (head/coordinator: everyone in scope; staff: their own)")
def get_activity(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), user_id: Optional[str] = Query(default=None),
                 department_id: Optional[str] = Query(default=None), user: dict = Depends(current_user)):
    return read(staff.activity, user, limit, offset, user_id, department_id)


@router.get("/projects/{project_id}/history", tags=["projects"], responses=ERRORS, summary="Everything that happened to one project")
def get_project_history(project_id: str, user: dict = Depends(current_user)):
    return read(staff.project_history, user, project_id, lambda conn, u, pid: views.get_project_detail(conn, u, pid))


@router.post("/projects/{project_id}/assign-staff", tags=["projects"], responses=MUTATION,
             summary="Head/coordinator: choose who leads a project (staff may take one for themselves)")
def post_project_assign_staff(project_id: str, body: sc.AssignStaffRequest, user: dict = Depends(current_user),
                              key: str = Depends(idempotency_key)):
    return respond(svc.mutate(
        user, key, "POST /projects/%s/assign-staff" % project_id, body.model_dump(mode="json"),
        staff.authorize_assign_project(user, project_id, body.user_id),
        lambda conn, ctx: staff.assign_project(conn, user, ctx, body)))


def _csv_response(name: str, text: str) -> Response:
    return Response(content=text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@router.get("/export/complaints.csv", tags=["staff window"], responses=ERRORS, summary="CSV of the complaints you may see")
def export_complaints(user: dict = Depends(current_user)):
    return _csv_response("complaints.csv", read(staff.complaints_csv, user))


@router.get("/export/projects.csv", tags=["staff window"], responses=ERRORS, summary="CSV of the projects you may see")
def export_projects(user: dict = Depends(current_user)):
    return _csv_response("projects.csv", read(lambda conn: staff.projects_csv(conn, user, views.visible_project_rows)))


# ------------------------------------------------------ roads and sample data
@router.post("/roads", status_code=201, tags=["projects"], responses={201: {"model": sc.MutationResult}, **ERRORS},
             summary="Staff: register a street at a place (an existing street of that name nearby is reused)")
def post_road(body: sc.RoadCreate, user: dict = Depends(current_user), key: str = Depends(idempotency_key)):
    return respond(svc.mutate(user, key, "POST /roads", body.model_dump(mode="json"), svc.authorize_create_road(user),
                              lambda conn, ctx: svc.register_road(conn, user, ctx, body), status=201))


@router.post("/demo/scenario", status_code=201, tags=["demo"], responses={201: {"model": sc.MutationResult}, **ERRORS},
             summary="Admin: create clearly-labelled sample works around a point (once)")
def post_scenario(body: sc.ScenarioRequest, user: dict = Depends(current_user), key: str = Depends(idempotency_key)):
    def authorize(conn):
        auth.require_role(user, "ADMIN")
        return {}

    def perform(conn, ctx):
        import seed
        out = seed.create_scenario(conn, body.lat, body.lng)
        svc.audit(conn, user, "SAMPLE_SCENARIO_CREATED", None, details={"lat": body.lat, "lng": body.lng})
        return {"id": "scenario", "version": 1, "case_id": None, "roads": out["roads"], "complaints": out["complaints"],
                "message": "Sample works and %d example complaints were created around that point. They are invented demo data." % len(out["complaints"])}
    return respond(svc.mutate(user, key, "POST /demo/scenario", body.model_dump(mode="json"), authorize, perform, status=201))


# ----------------------------------------------------- resident (Google, optional)
@router.post("/auth/google", tags=["auth"], summary="Optional: sign a resident in with a Google ID token",
             responses={401: {"model": sc.ErrorEnvelope}, 503: {"model": sc.ErrorEnvelope}})
def post_google(body: sc.GoogleLoginRequest):
    info = google.verify_credential(body.credential)
    conn = connect()
    try:
        with transaction(conn):
            resident = auth.upsert_resident(conn, info["sub"], info["email"], info["name"])
            token, expires = auth.create_resident_session(conn, resident["id"])
        return {"token": token, "token_type": "Bearer", "expires_at": expires, "resident": resident}
    finally:
        conn.close()



# ------------------------------------------------ resident accounts (e-mail + password, or Google)
@router.post("/auth/register", status_code=201, tags=["auth"], summary="Residents: create an account (e-mail + password; optional)",
             responses={201: {"description": "Account created and signed in"}, 409: {"model": sc.ErrorEnvelope}, 422: {"model": sc.ErrorEnvelope}, 429: {"model": sc.ErrorEnvelope}})
def post_register(body: sc.RegisterRequest, request: Request):
    ckey = auth.client_key(client_host(request))
    conn = connect()
    try:
        with transaction(conn):
            if auth.throttle_blocked(conn, "register", ckey, auth.REGISTER_MAX_PER_HOUR, 3600):
                raise auth.too_many_attempts()
            auth.throttle_record(conn, "register", ckey)
            resident = auth.register_resident(conn, body.name, body.email, body.password)
            token, expires = auth.create_resident_session(conn, resident["id"])
        return JSONResponse({"token": token, "token_type": "Bearer", "expires_at": expires, "resident": resident}, status_code=201)
    finally:
        conn.close()


@router.post("/auth/resident/login", tags=["auth"], summary="Residents: sign in with e-mail and password",
             responses={401: {"model": sc.ErrorEnvelope}, 429: {"model": sc.ErrorEnvelope}})
def post_resident_login(body: sc.ResidentLoginRequest, request: Request):
    key = auth.client_key(client_host(request)) + "|" + auth.normalise_email(body.email)
    conn = connect()
    try:
        outcome, token, expires, resident = None, None, None, None
        with transaction(conn):
            if auth.throttle_blocked(conn, "rlogin", key, auth.RESIDENT_LOGIN_MAX_FAILURES, auth.RESIDENT_LOGIN_WINDOW_SECONDS):
                outcome = "blocked"
            else:
                resident = auth.check_resident_login(conn, body.email, body.password)
                if not resident:
                    auth.throttle_record(conn, "rlogin", key)
                    outcome = "bad"
                else:
                    auth.throttle_clear(conn, "rlogin", key)
                    token, expires = auth.create_resident_session(conn, resident["id"])
                    outcome = "ok"
        if outcome == "blocked":
            raise auth.too_many_attempts()
        if outcome == "bad":
            raise ApiError(401, "INVALID_CREDENTIALS", "Incorrect e-mail or password.")
        return {"token": token, "token_type": "Bearer", "expires_at": expires, "resident": resident}
    finally:
        conn.close()


@router.post("/auth/resident/password", tags=["auth"], summary="Residents: change your password (signs out your other devices)",
             responses={401: {"model": sc.ErrorEnvelope}, 422: {"model": sc.ErrorEnvelope}})
def post_resident_password(body: sc.ChangePasswordRequest, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
                           resident: dict = Depends(current_resident)):
    conn = connect()
    try:
        with transaction(conn):
            auth.change_resident_password(conn, resident["id"], body.current_password, body.new_password)
            token, expires = auth.create_resident_session(conn, resident["id"])
        return {"message": "Password changed. Your other devices were signed out.", "token": token, "expires_at": expires}
    finally:
        conn.close()


@router.post("/me/complaints/claim", tags=["complaints"], summary="Residents: add a report made as a guest to your account",
             responses={404: {"model": sc.ErrorEnvelope}, 401: {"model": sc.ErrorEnvelope}})
def post_claim(body: sc.ClaimRequest, request: Request, resident: dict = Depends(current_resident)):
    ckey = auth.client_key(client_host(request))
    conn = connect()
    try:
        result = None
        with transaction(conn):
            if auth.throttle_blocked(conn, "track", ckey, auth.TRACK_MAX_FAILURES, auth.TRACK_WINDOW_SECONDS):
                result = "blocked"
            else:
                c = complaints.claim(conn, resident, body.reference, body.code)
                if c:
                    result = complaints.track_view(conn, c)
                else:
                    auth.throttle_record(conn, "track", ckey)
                    result = "missing"
        if result == "blocked":
            raise auth.too_many_attempts()
        if result == "missing":
            raise not_found("A complaint with that reference and tracking code")
        return result
    finally:
        conn.close()


@router.post("/auth/resident/logout", tags=["auth"])
def post_resident_logout(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer), resident: dict = Depends(current_resident)):
    conn = connect()
    try:
        with transaction(conn):
            auth.revoke_resident_session(conn, _token(creds) or "")
    finally:
        conn.close()
    return {"message": "Signed out."}


@router.get("/auth/resident/me", tags=["auth"], responses={401: {"model": sc.ErrorEnvelope}})
def get_resident_me(resident: dict = Depends(current_resident)):
    return resident


app.include_router(router)


@app.get("/health", tags=["public"], include_in_schema=False)
def health():
    return {"ok": True}


# ------------------------------------------------ the website itself (one address for the app and the API)
def frontend_dir() -> Optional[Path]:
    """The built website: WORKSYNC_STATIC_DIR, else backend/static, else ../frontend/dist (after `npm run build`)."""
    raw = os.environ.get("WORKSYNC_STATIC_DIR")
    here = Path(__file__).resolve().parent
    for p in ([Path(raw)] if raw else [here / "static", here.parent / "frontend" / "dist"]):
        if (p / "index.html").is_file():
            return p.resolve()
    return None


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


def mount_website(target_app: FastAPI, site: Path) -> None:
    """Serve the built website from `site`: its files, and index.html for every page address (the app routes itself)."""
    if (site / "assets").is_dir():
        target_app.mount("/assets", StaticFiles(directory=str(site / "assets")), name="assets")

    @target_app.get("/{path:path}", include_in_schema=False)
    def website(path: str):
        if path == "api" or path.startswith("api/"):
            raise not_found("That address")                     # an unknown API path is an API error, not the web page
        target = (site / path).resolve()
        if path and target.is_file() and site in target.parents:
            return FileResponse(str(target))
        return FileResponse(str(site / "index.html"), headers={"Cache-Control": "no-cache"})


_SITE = frontend_dir()
if _SITE is not None:
    mount_website(app, _SITE)
