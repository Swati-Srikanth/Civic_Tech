"""Request and response models (field names follow WORKSYNC_API_CONTRACT.md exactly)."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

try:  # Python 3.8+
    from typing import Literal
except ImportError:  # pragma: no cover
    from typing_extensions import Literal

Role = Literal["DEPARTMENT", "CONTRACTOR", "INSPECTOR", "ADMIN"]
ProjectKind = Literal["UTILITY", "RESURFACING"]
ExecutionStatus = Literal["PLANNED", "IN_PROGRESS", "DONE", "CANCELLED"]
CaseStatus = Literal["DRAFT", "CONTRACTOR_REVIEW", "DEPARTMENT_REVIEW", "APPROVED", "BLOCKED", "COMPLETED"]
ContractorDecision = Literal["ACCEPT", "COUNTERPROPOSE", "REJECT"]
DepartmentDecision = Literal["APPROVE", "REJECT"]
InspectionKind = Literal["UTILITY_RELEASE", "FINAL_SURFACE"]
InspectionResult = Literal["PASS", "FAIL"]
DeclarationMode = Literal["ALL_WORK_REGISTERED", "NO_PLANNED_WORK"]
AssessmentOutcome = Literal["PLAN_FOUND", "NO_SEQUENTIAL_PLAN", "UNASSESSABLE"]


class Req(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    # Responses may carry extra display-only fields; documented names never change.
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------- requests
class ProjectCreate(Req):
    title: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=400)
    road_id: str
    kind: ProjectKind
    assigned_contractor_id: str
    earliest_start: date
    deadline: date
    duration_days: int = Field(ge=1, le=365)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "title": "Gas pipe renewal", "purpose": "Replace ageing gas pipe before resurfacing",
        "road_id": "road-station", "kind": "UTILITY", "assigned_contractor_id": "con-grid",
        "earliest_start": "2026-11-09", "deadline": "2026-11-30", "duration_days": 4}]})


class ProjectPatch(Req):
    expected_version: int
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    purpose: Optional[str] = Field(default=None, min_length=1, max_length=400)
    assigned_contractor_id: Optional[str] = None
    earliest_start: Optional[date] = None
    deadline: Optional[date] = None
    duration_days: Optional[int] = Field(default=None, ge=1, le=365)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "expected_version": 1, "duration_days": 6}]})


class CancelRequest(Req):
    expected_version: int
    reason: str = Field(min_length=1, max_length=400)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "expected_version": 1, "reason": "Scope no longer needed"}]})


class PlanRequest(Req):
    expected_version: int

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"expected_version": 1}]})


class ContractorResponseRequest(Req):
    expected_version: int
    plan_version: int
    project_id: str
    decision: ContractorDecision
    reason: Optional[str] = Field(default=None, max_length=400)
    earliest_start: Optional[date] = None

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [
        {"expected_version": 4, "plan_version": 1, "project_id": "water-1", "decision": "ACCEPT"},
        {"expected_version": 4, "plan_version": 1, "project_id": "water-1", "decision": "COUNTERPROPOSE",
         "earliest_start": "2026-11-10"},
        {"expected_version": 4, "plan_version": 1, "project_id": "water-1", "decision": "REJECT",
         "reason": "Crew unavailable"}]})


class ApprovalRequest(Req):
    expected_version: int
    plan_version: int
    decision: DepartmentDecision
    reason: Optional[str] = Field(default=None, max_length=400)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [
        {"expected_version": 7, "plan_version": 1, "decision": "APPROVE"}]})


class ReviewRequest(Req):
    expected_version: int
    action: Literal["REQUEST_REVISION", "KEEP_BLOCKED"]
    reason: str = Field(min_length=1, max_length=400)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [
        {"expected_version": 5, "action": "REQUEST_REVISION", "reason": "Ask departments to resubmit dates"}]})


class StartRequest(Req):
    expected_version: int
    plan_version: int

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"expected_version": 7, "plan_version": 1}]})


class FinishRequest(Req):
    expected_version: int
    delay_reason: Optional[str] = Field(default=None, max_length=400)
    testing_complete: Optional[bool] = None
    reinstatement_complete: Optional[bool] = None

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [
        {"expected_version": 3, "testing_complete": True, "reinstatement_complete": True}]})


class InspectionRequest(Req):
    expected_version: int
    kind: InspectionKind
    result: InspectionResult
    notes: str = Field(min_length=1, max_length=400)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [
        {"expected_version": 4, "kind": "UTILITY_RELEASE", "result": "PASS", "notes": "Trench reinstated and tested"}]})


class DeclarationRequest(Req):
    expected_version: int
    mode: DeclarationMode
    covers_from: date
    covers_through: date
    valid_until: date

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "expected_version": 1, "mode": "NO_PLANNED_WORK", "covers_from": "2026-11-01",
        "covers_through": "2027-06-30", "valid_until": "2027-02-28"}]})


class IncidentRequest(Req):
    expected_version: int
    kind: Literal["WORK_WITHOUT_CLEARANCE", "SITE_ISSUE"]
    description: str = Field(min_length=1, max_length=600)
    occurred_date: Optional[date] = None

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "expected_version": 4, "kind": "SITE_ISSUE", "description": "Water leaking at the trench edge"}]})


class ClockAdvanceRequest(Req):
    expected_version: int
    days: int = Field(ge=1, le=366)

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"expected_version": 1, "days": 4}]})


ComplaintCategory = Literal["WATER", "ELECTRICAL", "TELECOM", "ROAD_DAMAGE", "SAFETY_HAZARD", "WORK_WITHOUT_NOTICE",
                            "DELAY", "NOISE_DUST", "OTHER"]
ComplaintStatus = Literal["NEW", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CONFIRMED_FIXED", "REOPENED", "REJECTED"]


class LoginRequest(Req):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"username": "your.username", "password": "your-password"}]})


class ComplaintCreate(Req):
    category: ComplaintCategory
    description: str = Field(min_length=10, max_length=1000)
    road_id: Optional[str] = None
    location_text: Optional[str] = Field(default=None, max_length=200)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    contact_name: Optional[str] = Field(default=None, max_length=80)
    contact_detail: Optional[str] = Field(default=None, max_length=120)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "category": "ELECTRICAL", "description": "Street light has been out for a week and the cable is hanging.",
        "road_id": None, "lat": 13.0878, "lng": 80.2785, "location_text": "Outside the bus stop",
        "contact_name": "A. Resident", "contact_detail": "resident@example.com"}]})


class ComplaintTrackRequest(Req):
    reference: str = Field(min_length=3, max_length=40)
    code: str = Field(min_length=4, max_length=40)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "reference": "CMP-2026-0001", "code": "A1B2C3D4E5"}]})


class ComplaintStatusRequest(Req):
    expected_version: int
    status: Literal["ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "REJECTED"]
    note: Optional[str] = Field(default=None, max_length=400)
    resolve_in_days: Optional[int] = Field(default=None, ge=1, le=366, description="Required with IN_PROGRESS: the promise, in days")

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [
        {"expected_version": 1, "status": "IN_PROGRESS", "resolve_in_days": 5, "note": "A crew is booked."},
        {"expected_version": 2, "status": "RESOLVED", "note": "The cable was replaced."}]})


class ComplaintAssignRequest(Req):
    expected_version: int
    department_id: str

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"expected_version": 1, "department_id": "power"}]})


class ResidentResponseRequest(Req):
    reference: str = Field(min_length=3, max_length=40)
    action: Literal["CONFIRM_FIXED", "REOPEN"]
    code: Optional[str] = Field(default=None, max_length=40)
    note: Optional[str] = Field(default=None, max_length=400)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [
        {"reference": "CMP-2026-0001", "action": "CONFIRM_FIXED", "code": "A1B2C3D4E5"}, {"reference": "CMP-2026-0001", "action": "REOPEN", "code": "A1B2C3D4E5", "note": "Still leaking."}]})


class GoogleLoginRequest(Req):
    credential: str = Field(min_length=20, max_length=4000, description="Google ID token from Google Identity Services")

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RoadCreate(Req):
    name: str = Field(min_length=2, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    area_label: Optional[str] = Field(default=None, max_length=80)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "name": "Market Road", "lat": 13.0878, "lng": 80.2785}]})


class ScenarioRequest(Req):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"lat": 13.0617, "lng": 80.2693}]})


# --------------------------------------------------------------- responses
class MutationResult(Out):
    id: str
    version: int
    case_id: Optional[str] = None
    message: str
    recorded_at: str

    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [{
        "id": "water-1", "version": 2, "case_id": "case-market",
        "message": "Saved.", "recorded_at": "2026-11-08T02:31:00Z"}]})


class ErrorBody(BaseModel):
    code: str
    message: str
    failures: List[Dict[str, Any]] = []


class ErrorEnvelope(BaseModel):
    error: ErrorBody

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "error": {"code": "STALE_PLAN", "message": "This plan changed. Refresh it before responding.", "failures": []}}]})


class Blocker(BaseModel):
    code: str
    message: str
    responsible_org_id: Optional[str] = None
    next_action: Optional[str] = None


class GateOut(BaseModel):
    project_id: str
    version: int
    plan_version: int
    eligible: bool
    not_an_authorisation: bool = True
    blockers: List[Blocker]

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "project_id": "surface-1", "version": 7, "plan_version": 1, "eligible": False, "not_an_authorisation": True,
        "blockers": [{"code": "COVERAGE_MISSING",
                      "message": "Power Department has not confirmed its planned work.",
                      "responsible_org_id": "power", "next_action": "Request its declaration."}]}]})


class Items(BaseModel):
    items: List[Dict[str, Any]]


class AssignStaffRequest(Req):
    expected_version: int
    user_id: Optional[str] = Field(default=None, description="The staff member, or null to remove the assignment")

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"expected_version": 2, "user_id": "u-water"}]})


class RegisterRequest(Req):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "name": "A. Resident", "email": "resident@example.com", "password": "a-long-passphrase-9"}]})


class ResidentLoginRequest(Req):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChangePasswordRequest(Req):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid")


class ClaimRequest(Req):
    reference: str = Field(min_length=3, max_length=40)
    code: str = Field(min_length=4, max_length=40)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
