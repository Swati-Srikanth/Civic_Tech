// Types mirror WORKSYNC_API_CONTRACT.md. Display-only extras are marked optional.

export type Role = "DEPARTMENT" | "CONTRACTOR" | "INSPECTOR" | "ADMIN";
export type ProjectKind = "UTILITY" | "RESURFACING";
export type ExecutionStatus = "PLANNED" | "IN_PROGRESS" | "DONE" | "CANCELLED";
export type CaseStatus = "DRAFT" | "CONTRACTOR_REVIEW" | "DEPARTMENT_REVIEW" | "APPROVED" | "BLOCKED" | "COMPLETED";
export type ContractorDecision = "ACCEPT" | "COUNTERPROPOSE" | "REJECT";
export type DepartmentDecision = "APPROVE" | "REJECT";
export type InspectionKind = "UTILITY_RELEASE" | "FINAL_SURFACE";
export type InspectionResult = "PASS" | "FAIL";
export type DeclarationMode = "ALL_WORK_REGISTERED" | "NO_PLANNED_WORK";
export type AssessmentOutcome = "PLAN_FOUND" | "NO_SEQUENTIAL_PLAN" | "UNASSESSABLE";
export type InspectionStatus = "PENDING" | "PASS" | "FAIL";
export type DateLabelKind = "PROPOSED" | "CONFIRMED";

export type ActionId =
  | "CREATE_PROJECT" | "EDIT_PROJECT" | "CANCEL_PROJECT" | "GENERATE_PLAN" | "RESPOND" | "APPROVE_PLAN"
  | "REVIEW_CASE" | "START_PROJECT" | "FINISH_PROJECT" | "INSPECT_PROJECT" | "DECLARE_WORKS" | "REPORT_INCIDENT"
  | "VIEW_COMPLAINTS" | "TRIAGE_COMPLAINT" | "ASSIGN_COMPLAINT" | "ASSIGN_STAFF" | "CREATE_SCENARIO";

export interface DemoUser {
  id: string;
  name: string;
  role: Role;
  org_id: string;
  org_name?: string;
  project_kind?: ProjectKind | null;
  is_head?: boolean;
}

export interface LoginResult {
  token: string;
  token_type: "Bearer";
  expires_at: string;
  user: DemoUser;
}

export type ComplaintCategory =
  | "WATER" | "ELECTRICAL" | "TELECOM" | "ROAD_DAMAGE" | "SAFETY_HAZARD" | "WORK_WITHOUT_NOTICE" | "DELAY" | "NOISE_DUST" | "OTHER";
export type ComplaintStatus = "NEW" | "ACKNOWLEDGED" | "IN_PROGRESS" | "RESOLVED" | "CONFIRMED_FIXED" | "REOPENED" | "REJECTED";
export type Priority = "NORMAL" | "HIGH" | "URGENT";

export interface ComplaintInput {
  category: ComplaintCategory;
  description: string;
  road_id?: string;
  location_text?: string;
  lat?: number;
  lng?: number;
  contact_name?: string;
  contact_detail?: string;
}

export interface ComplaintReceipt {
  id: string;
  tracking_code: string;
  status: ComplaintStatus;
  department_name: string | null;
  other_reports: number;
  priority: Priority;
  message: string;
  recorded_at: string;
}

export interface TimelineEvent {
  id: number;
  at: string;
  kind: string;
  message: string;
  actor_label: string;
  /** Staff only: the person who acted. Residents never receive this. */
  actor_name?: string | null;
}

/** What the person who complained sees: a detailed status, never the description or contact details. */
export interface ComplaintTrackView {
  reference: string;
  category_label: string;
  department_name: string | null;
  status: ComplaintStatus;
  status_text: string;
  priority: Priority;
  priority_text: string;
  priority_reason: string | null;
  road_name: string | null;
  submitted_on: string;
  last_update: string;
  public_note: string | null;
  committed_days: number | null;
  promised_by: string | null;
  escalation_text: string | null;
  report_count: number;
  can_respond: boolean;
  timeline: TimelineEvent[];
  last_event_id: number;
}

export interface PublicComplaint {
  id: string;
  category: ComplaintCategory;
  category_label: string;
  department_name: string | null;
  status: ComplaintStatus;
  status_text: string;
  fixed: boolean;
  priority: Priority;
  priority_text: string;
  report_count: number;
  since: string;
  last_update: string;
  promised_by: string | null;
  escalated: boolean;
  road_name: string | null;
  lat: number | null;
  lng: number | null;
}

export interface StaffComplaint {
  id: string;
  references: string[];
  category: ComplaintCategory;
  category_label: string;
  department_id: string | null;
  department_name: string | null;
  status: ComplaintStatus;
  status_text: string;
  priority: Priority;
  priority_text: string;
  priority_reason: string | null;
  report_count: number;
  open_report_count: number;
  road_id: string | null;
  road_name: string | null;
  version: number;
  committed_days: number | null;
  due_on: string | null;
  days_left: number | null;
  overdue: boolean;
  escalation_level: number;
  escalation_text: string | null;
  assigned_user_id: string | null;
  assigned_name: string | null;
  opened_on: string | null;
  resolved_on: string | null;
  days_open: number | null;
  resolution_days: number | null;
  public_note: string | null;
  created_at: string;
  updated_at: string;
  reports: {
    id: string; created_at: string; description: string; location_text: string | null; lat: number | null; lng: number | null;
    contact_name: string | null; contact_detail: string | null; status: ComplaintStatus;
  }[];
  timeline: TimelineEvent[];
  allowed_actions: ActionId[];
  next_statuses: ("ACKNOWLEDGED" | "IN_PROGRESS" | "RESOLVED" | "REJECTED")[];
}

export interface Resident {
  id: string;
  name: string | null;
  email: string | null;
  provider: "local" | "google";
}

export interface CategoryInfo {
  id: ComplaintCategory;
  label: string;
  examples: string[];
  department_id: string | null;
  department_name: string | null;
}

export interface RoadSummary {
  id: string;
  name: string;
  lat: number;
  lng: number;
  area_label: string | null;
  work_count: number;
  in_progress_count: number;
  notices: string[];
  works: { id: string; title: string; kind: ProjectKind; execution_status: ExecutionStatus; case_status: CaseStatus | null }[];
}

export interface Bootstrap {
  contractors: { id: string; name: string }[];
  departments: { id: string; name: string }[];
  roads: { id: string; name: string; lat: number | null; lng: number | null; version: number }[];
  clock: { date: string; version: number; label?: string };
  policy: Record<string, string | number>;
  complaint_categories: CategoryInfo[];
  google_client_id: string | null;
  current_user: DemoUser | null;
  allowed_actions: ActionId[];
}

export interface PublicCard {
  id: string;
  title: string;
  purpose: string;
  kind: ProjectKind;
  owner_org_name: string;
  contractor_name: string;
  execution_status: ExecutionStatus;
  case_status: CaseStatus | null;
  proposed_start: string | null;
  proposed_end: string | null;
  confirmed_start: string | null;
  confirmed_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  verified_on: string | null;
  public_reason: string | null;
}

export interface PublicRoad {
  road: { id: string; name: string };
  as_of: { date: string; label: string };
  case: { id: string; status: CaseStatus; public_reason: string | null } | null;
  projects: PublicCard[];
  notices: string[];
  footer: string;
}

export interface Project {
  id: string;
  title: string;
  purpose: string;
  road_id: string;
  road_name?: string;
  kind: ProjectKind;
  assigned_contractor_id: string;
  assigned_contractor_name?: string;
  earliest_start: string;
  deadline: string;
  duration_days: number;
  version: number;
  material_version: number;
  owner_org_id: string;
  owner_org_name?: string;
  case_id: string | null;
  case_status?: CaseStatus | null;
  case_version?: number | null;
  plan_version?: number | null;
  execution_status: ExecutionStatus;
  actual_start: string | null;
  actual_end: string | null;
  inspection_status: InspectionStatus;
  verified_on?: string | null;
  pcc_number?: string | null;
  plan_start?: string | null;
  plan_end?: string | null;
  date_label?: DateLabelKind | null;
  lead_user_id?: string | null;
  lead_name?: string | null;
  created_by_name?: string | null;
  created_at?: string;
  cancel_reason?: string | null;
  allowed_actions: ActionId[];
}

export interface CaseSummary {
  id: string;
  road_id: string;
  road_name?: string;
  status: CaseStatus;
  version: number;
  plan_version: number;
  deadline_at: string | null;
  hold: boolean;
  hold_reason: string | null;
  project_count: number;
  allowed_actions: ActionId[];
}

export interface ScheduleItem {
  project_id: string;
  project_version: number;
  title: string;
  kind: ProjectKind;
  start: string;
  end: string;
  date_label: DateLabelKind;
  owner_org_id?: string;
  owner_org_name?: string;
  contractor_id?: string;
  contractor_name?: string;
  execution_status?: ExecutionStatus;
  actual_start?: string | null;
  actual_end?: string | null;
  inspection_status?: InspectionStatus;
}

export interface ContractorResponse {
  project_id: string;
  plan_version: number;
  decision: ContractorDecision;
  reason: string | null;
  earliest_start?: string | null;
  project_title?: string | null;
  contractor_name?: string | null;
  recorded_at?: string;
}

export interface DepartmentApproval {
  org_id: string;
  plan_version: number;
  decision: DepartmentDecision;
  reason: string | null;
  org_name?: string;
  recorded_at?: string;
}

export interface DeclarationRow {
  org_id: string;
  org_name?: string;
  status: string;
  message: string | null;
  mode: DeclarationMode | null;
  covers_through: string | null;
  valid_until: string | null;
}

export interface CaseDetail {
  id: string;
  road_id: string;
  road_name: string;
  version: number;
  status: CaseStatus;
  plan_version: number;
  deadline_at: string | null;
  assessment: {
    outcome: AssessmentOutcome | null;
    messages: string[];
    violations?: { code: string; project_id: string | null; message: string }[];
    plan_version?: number;
  };
  schedule: ScheduleItem[];
  responses: ContractorResponse[];
  approvals: DepartmentApproval[];
  pending_responses: { project_id: string; title: string; contractor_id: string; contractor_name?: string }[];
  pending_approvals: { org_id: string; org_name?: string }[];
  required_departments: string[];
  coverage_required: string[];
  declarations: DeclarationRow[];
  hold: boolean;
  hold_reason: string | null;
  public_reason: string | null;
  excluded: { project_id: string; reason: string }[];
  horizon_end: string | null;
  projects: Project[];
  completed_on: string | null;
  allowed_actions: ActionId[];
}

export interface Blocker {
  code: string;
  message: string;
  responsible_org_id: string | null;
  next_action: string | null;
}

export interface Gate {
  project_id: string;
  version: number;
  plan_version: number;
  eligible: boolean;
  not_an_authorisation: boolean;
  blockers: Blocker[];
}

export interface AuditEvent {
  id: number;
  recorded_at: string;
  actor_name: string;
  action: string;
  reason: string | null;
}

export interface MutationResult {
  id: string;
  version: number;
  case_id?: string | null;
  message: string;
  recorded_at: string;
  pcc_number?: string | null;
  plan_version?: number;
  status?: CaseStatus;
  invalidated_case?: { id: string; version: number; status: CaseStatus } | null;
  case_created?: boolean;
  [extra: string]: unknown;
}

export interface SampleComplaint {
  reference: string;
  code: string;
  case: string;
}

export interface Failure {
  field?: string;
  message: string;
}

export interface ProjectInput {
  title: string;
  purpose: string;
  road_id: string;
  kind: ProjectKind;
  assigned_contractor_id: string;
  earliest_start: string;
  deadline: string;
  duration_days: number;
}

export interface ActivityRow {
  id: number;
  recorded_at: string;
  actor_user_id: string | null;
  actor_name: string;
  action: string;
  reason: string | null;
  case_id: string | null;
  project_id: string | null;
  reference: string | null;
  detail: string | null;
}

export interface Overview {
  scope: { department_id: string | null; department_name: string; is_overseer: boolean };
  complaints: {
    open: number; urgent: number; high: number; overdue: number; escalated: number; unassigned: number; unrouted: number;
    awaiting_confirmation: number; reopened: number; closed: number; total: number; avg_resolution_days: number | null;
    by_category: { category: string; label: string; open: number; closed: number }[];
  };
  projects: {
    total: number; planned: number; in_progress: number; done: number; cancelled: number;
    awaiting_agreement: number; agreed: number; blocked: number; on_hold: number;
  };
  needs_attention: { kind: "complaint" | "project"; id: string; title: string; department_name: string | null; priority: Priority; reason: string; assigned_name: string | null }[];
  my_work: { open_complaints: number; overdue: number; active_projects: number };
  recent_activity: ActivityRow[];
}

export interface TeamMember {
  id: string;
  name: string;
  is_head: boolean;
  department_id: string;
  department_name: string;
  open_complaints: number;
  overdue: number;
  escalated: number;
  awaiting_confirmation: number;
  resolved_total: number;
  avg_resolution_days: number | null;
  active_projects: number;
  completed_projects: number;
  actions: number;
  last_active: string | null;
}

export interface TeamMemberDetail {
  member: TeamMember;
  open_complaints: { id: string; category_label: string; priority: Priority; priority_text: string; status_text: string; due_on: string | null;
    overdue: boolean; escalation_text: string | null; report_count: number; days_open: number | null }[];
  closed_complaints: { id: string; category_label: string; status_text: string; resolved_on: string | null; resolution_days: number | null }[];
  projects: { id: string; title: string; road_name: string | null; execution_status: ExecutionStatus; case_id: string | null; verified_on: string | null }[];
  recent_actions: ActivityRow[];
}

export interface ProjectHistory {
  project: {
    id: string; title: string; execution_status: ExecutionStatus; created_by: string | null; lead: string | null; created_at: string;
    actual_start: string | null; actual_end: string | null; verified_on: string | null; pcc_number: string | null; cancel_reason: string | null;
  };
  events: { at: string; kind: string; who: string | null; what: string; note: string | null }[];
}
