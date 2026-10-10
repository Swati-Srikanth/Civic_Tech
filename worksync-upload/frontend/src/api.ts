// The one HTTP client. Screens never call fetch directly and never recompute
// scheduling, permissions or start eligibility: they display what the server says.
import type {
  ActivityRow, AuditEvent, Bootstrap, CaseDetail, CaseSummary, ComplaintInput, ComplaintReceipt, ComplaintTrackView, ContractorDecision,
  DeclarationMode, DemoUser, DepartmentDecision, Failure, Gate, InspectionKind, InspectionResult, LoginResult,
  MutationResult, Overview, Project, ProjectHistory, ProjectInput, PublicComplaint, PublicRoad, Resident, RoadSummary, StaffComplaint,
  TeamMember, TeamMemberDetail,
} from "./types";

// In development the backend is a separate server on :8000. In a production build the website is served by the backend
// itself, so the API is on the same address (empty base) unless VITE_API_BASE_URL says otherwise.
const BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? (import.meta.env.PROD ? "" : "http://localhost:8000")).replace(/\/+$/, "");
const ORIGIN = typeof window !== "undefined" ? window.location.origin : "http://localhost";
const PREFIX = "/api/v1";

export class ApiRequestError extends Error {
  status: number;
  code: string;
  failures: Failure[];
  network: boolean;
  constructor(status: number, code: string, message: string, failures: Failure[] = [], network = false) {
    super(message);
    this.status = status;
    this.code = code;
    this.failures = failures;
    this.network = network;
  }
  get isStale(): boolean {
    return this.code === "STALE_PLAN" || this.code === "STALE_VERSION";
  }
  /** Message to show beside one form field, if the server named it. */
  fieldMessage(field: string): string | undefined {
    return this.failures.find((f) => f.field === field)?.message;
  }
  /** Every message for one field, joined, for fields that can fail for several reasons (such as a password). */
  fieldMessages(field: string): string | undefined {
    const all = this.failures.filter((f) => f.field === field).map((f) => f.message);
    return all.length ? all.join(" ") : undefined;
  }
}

let authToken: string | null = null;
let residentToken: string | null = null;
let onUnauthorized: (() => void) | null = null;
let onResidentExpired: (() => void) | null = null;

/** Session token for staff calls (null for the public). The server decides what it may do. */
export function setAuthToken(token: string | null): void {
  authToken = token;
}

/** Optional Google sign-in for residents. A resident token never works on staff endpoints (and vice versa). */
export function setResidentToken(token: string | null): void {
  residentToken = token;
}

export function setResidentExpiredHandler(fn: (() => void) | null): void {
  onResidentExpired = fn;
}

/** Called when a signed-in request is refused as unauthenticated (session expired or ended). */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

// --- idempotency -----------------------------------------------------------
// Same action + same payload after a network failure -> same key (safe retry).
// New or changed action -> new key. Keys are forgotten once the server has answered definitively.
const pendingKeys = new Map<string, string>();

function newKey(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return "k-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

function signature(method: string, path: string, body: unknown, user: string | null): string {
  return [user ?? "", method, path, JSON.stringify(body ?? null)].join("|");
}

export function _pendingKeyCount(): number {
  return pendingKeys.size;
}

export interface ComplaintQuery {
  status?: string; priority?: string; scope?: "open" | "closed" | "all"; q?: string; category?: string; assigned?: string;
  opened_from?: string; opened_to?: string; limit?: number; offset?: number;
}

function stringify(o: object): Record<string, string | undefined> {
  const out: Record<string, string | undefined> = {};
  for (const [k, v] of Object.entries(o as Record<string, unknown>)) out[k] = v === undefined || v === null || v === "" ? undefined : String(v);
  return out;
}

// --- core request ----------------------------------------------------------
interface Options {
  body?: unknown;
  query?: Record<string, string | undefined | null>;
  /** Public endpoints are called without any credentials. */
  anonymous?: boolean;
  /** Public endpoints that also recognise a signed-in resident (reporting, tracking, responding). */
  resident?: boolean;
  /** Sign-in, sign-out and look-ups are not replayable business actions, so they carry no Idempotency-Key. */
  noKey?: boolean;
}

async function request<T>(method: "GET" | "POST" | "PATCH", path: string, opts: Options = {}): Promise<T> {
  const url = new URL(BASE + PREFIX + path, ORIGIN);
  for (const [k, v] of Object.entries(opts.query ?? {})) if (v) url.searchParams.set(k, v);
  const headers: Record<string, string> = { Accept: "application/json" };
  const user = opts.anonymous ? null : opts.resident ? residentToken : authToken;
  if (user) headers["Authorization"] = `Bearer ${user}`;
  let sig = "";
  const keyed = method !== "GET" && !opts.noKey;
  if (method !== "GET") headers["Content-Type"] = "application/json";
  if (keyed) {
    sig = signature(method, path, opts.body, user ? user.slice(0, 8) : null);
    let key = pendingKeys.get(sig);
    if (!key) {
      key = newKey();
      pendingKeys.set(sig, key);
    }
    headers["Idempotency-Key"] = key;
  }
  let res: Response;
  try {
    res = await fetch(url.toString(), {
      method,
      headers,
      body: method === "GET" ? undefined : JSON.stringify(opts.body ?? {}),
    });
  } catch {
    // Network failure: keep the key so an identical retry is idempotent.
    throw new ApiRequestError(0, "NETWORK_ERROR", "Cannot reach the WorkSync server. Check that the backend is running, then try again.", [], true);
  }
  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    payload = null;
  }
  if (!res.ok) {
    if (keyed && res.status !== 503) pendingKeys.delete(sig);
    if (res.status === 401 && user) (opts.resident ? onResidentExpired : onUnauthorized)?.();
    const err = (payload as { error?: { code?: string; message?: string; failures?: Failure[] } } | null)?.error;
    throw new ApiRequestError(
      res.status,
      err?.code ?? "HTTP_ERROR",
      err?.message ?? "The server could not complete this request.",
      err?.failures ?? [],
    );
  }
  if (keyed) pendingKeys.delete(sig);
  return payload as T;
}

// --- endpoints (paths and field names follow the shared contract) ----------
export const api = {
  bootstrap: (anonymous = false) => request<Bootstrap>("GET", "/bootstrap", { anonymous }),
  publicRoad: (roadId: string) => request<PublicRoad>("GET", `/roads/${roadId}/public`, { anonymous: true }),
  publicRoads: () => request<{ items: RoadSummary[] }>("GET", "/roads", { anonymous: true }).then((r) => r.items),

  // staff sign-in (never used by the public)
  login: (username: string, password: string) =>
    request<LoginResult>("POST", "/auth/login", { body: { username, password }, anonymous: true, noKey: true }),
  logout: () => request<{ message: string }>("POST", "/auth/logout", { body: {}, noKey: true }),
  me: () => request<DemoUser>("GET", "/auth/me"),

  // complaints: reporting, tracking and the public feed need no account (a signed-in resident is recognised)
  submitComplaint: (input: ComplaintInput) =>
    request<ComplaintReceipt>("POST", "/complaints", { body: input, resident: true }),
  trackComplaint: (reference: string, code: string) =>
    request<ComplaintTrackView>("POST", "/complaints/track", { body: { reference, code }, resident: true, noKey: true }),
  respondToComplaint: (reference: string, code: string | undefined, action: "CONFIRM_FIXED" | "REOPEN", note?: string) =>
    request<{ message: string; status: string; complaint: ComplaintTrackView }>("POST", "/complaints/respond", {
      body: { reference, action, ...(code ? { code } : {}), ...(note ? { note } : {}) }, resident: true, noKey: true,
    }),
  publicComplaints: () => request<{ items: PublicComplaint[] }>("GET", "/complaints/public", { anonymous: true }).then((r) => r.items),

  // optional Google sign-in for residents
  googleLogin: (credential: string) =>
    request<{ token: string; expires_at: string; resident: Resident }>("POST", "/auth/google", { body: { credential }, anonymous: true, noKey: true }),
  residentMe: () => request<Resident>("GET", "/auth/resident/me", { resident: true }),
  residentLogout: () => request<{ message: string }>("POST", "/auth/resident/logout", { body: {}, resident: true, noKey: true }),
  myComplaints: () => request<{ items: ComplaintTrackView[] }>("GET", "/me/complaints", { resident: true }).then((r) => r.items),

  // staff: the complaints inbox for their own department (the coordinator sees all)
  listComplaints: (params: ComplaintQuery = {}) =>
    request<{ items: StaffComplaint[]; total: number }>("GET", "/complaints", { query: stringify(params) }),
  assignComplaintStaff: (id: string, expected_version: number, user_id: string | null) =>
    request<MutationResult>("POST", `/complaints/${id}/assign-staff`, { body: { expected_version, user_id } }),
  assignProjectStaff: (id: string, expected_version: number, user_id: string | null) =>
    request<MutationResult>("POST", `/projects/${id}/assign-staff`, { body: { expected_version, user_id } }),

  // the staff window
  overview: (department_id?: string) => request<Overview>("GET", "/overview", { query: { department_id } }),
  team: (department_id?: string) =>
    request<{ items: TeamMember[]; unassigned_complaints: number; unassigned_projects: number }>("GET", "/team", { query: { department_id } }),
  teamMember: (id: string) => request<TeamMemberDetail>("GET", `/team/${id}`),
  activity: (params: { limit?: number; offset?: number; user_id?: string; department_id?: string } = {}) =>
    request<{ items: ActivityRow[]; everyone: boolean }>("GET", "/activity", { query: stringify(params) }),
  projectHistory: (id: string) => request<ProjectHistory>("GET", `/projects/${id}/history`),
  downloadCsv: async (kind: "complaints" | "projects"): Promise<Blob> => {
    const res = await fetch(`${BASE}${PREFIX}/export/${kind}.csv`, { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} });
    if (!res.ok) throw new ApiRequestError(res.status, "EXPORT_FAILED", "The file could not be created. Please try again.");
    return res.blob();
  },

  // resident accounts (e-mail + password), as well as Google
  register: (name: string, email: string, password: string) =>
    request<{ token: string; expires_at: string; resident: Resident }>("POST", "/auth/register", { body: { name, email, password }, anonymous: true, noKey: true }),
  residentLogin: (email: string, password: string) =>
    request<{ token: string; expires_at: string; resident: Resident }>("POST", "/auth/resident/login", { body: { email, password }, anonymous: true, noKey: true }),
  changePassword: (current_password: string, new_password: string) =>
    request<{ message: string; token: string }>("POST", "/auth/resident/password", { body: { current_password, new_password }, resident: true, noKey: true }),
  claimComplaint: (reference: string, code: string) =>
    request<ComplaintTrackView>("POST", "/me/complaints/claim", { body: { reference, code }, resident: true, noKey: true }),
  setComplaintStatus: (id: string, expected_version: number, status: "ACKNOWLEDGED" | "IN_PROGRESS" | "RESOLVED" | "REJECTED",
    extra: { note?: string; resolve_in_days?: number } = {}) =>
    request<MutationResult>("POST", `/complaints/${id}/status`, { body: { expected_version, status, ...extra } }),
  assignComplaint: (id: string, expected_version: number, department_id: string) =>
    request<MutationResult>("POST", `/complaints/${id}/assign`, { body: { expected_version, department_id } }),

  // places
  createRoad: (name: string, lat: number, lng: number) =>
    request<MutationResult & { name: string; created: boolean }>("POST", "/roads", { body: { name, lat, lng } }),
  createScenario: (lat: number, lng: number) => request<MutationResult>("POST", "/demo/scenario", { body: { lat, lng } }),

  listProjects: (roadId?: string, filter: { state?: string; q?: string } = {}) =>
    request<{ items: Project[] }>("GET", "/projects", { query: { road_id: roadId, ...stringify(filter) } }).then((r) => r.items),
  createProject: (input: ProjectInput) => request<MutationResult>("POST", "/projects", { body: input }),
  patchProject: (id: string, expected_version: number, changes: Partial<ProjectInput>) =>
    request<MutationResult>("PATCH", `/projects/${id}`, { body: { expected_version, ...changes } }),
  cancelProject: (id: string, expected_version: number, reason: string) =>
    request<MutationResult>("POST", `/projects/${id}/cancel`, { body: { expected_version, reason } }),

  listCases: (roadId?: string) =>
    request<{ items: CaseSummary[] }>("GET", "/cases", { query: { road_id: roadId } }).then((r) => r.items),
  getCase: (id: string) => request<CaseDetail>("GET", `/cases/${id}`),
  generatePlan: (id: string, expected_version: number) =>
    request<MutationResult>("POST", `/cases/${id}/plans`, { body: { expected_version } }),
  respond: (
    caseId: string,
    b: { expected_version: number; plan_version: number; project_id: string; decision: ContractorDecision; reason?: string; earliest_start?: string },
  ) => request<MutationResult>("POST", `/cases/${caseId}/responses`, { body: b }),
  approve: (
    caseId: string,
    b: { expected_version: number; plan_version: number; decision: DepartmentDecision; reason?: string },
  ) => request<MutationResult>("POST", `/cases/${caseId}/approvals`, { body: b }),
  review: (caseId: string, b: { expected_version: number; action: "REQUEST_REVISION" | "KEEP_BLOCKED"; reason: string }) =>
    request<MutationResult>("POST", `/cases/${caseId}/review`, { body: b }),
  audit: (caseId: string) => request<{ items: AuditEvent[] }>("GET", `/cases/${caseId}/audit`).then((r) => r.items),

  gate: (projectId: string) => request<Gate>("GET", `/projects/${projectId}/gate`),
  start: (projectId: string, expected_version: number, plan_version: number) =>
    request<MutationResult>("POST", `/projects/${projectId}/start`, { body: { expected_version, plan_version } }),
  finish: (
    projectId: string,
    b: { expected_version: number; delay_reason?: string; testing_complete?: boolean; reinstatement_complete?: boolean },
  ) => request<MutationResult>("POST", `/projects/${projectId}/finish`, { body: b }),
  inspect: (
    projectId: string,
    b: { expected_version: number; kind: InspectionKind; result: InspectionResult; notes: string },
  ) => request<MutationResult>("POST", `/projects/${projectId}/inspections`, { body: b }),
  incident: (
    projectId: string,
    b: { expected_version: number; kind: "WORK_WITHOUT_CLEARANCE" | "SITE_ISSUE"; description: string; occurred_date?: string },
  ) => request<MutationResult>("POST", `/projects/${projectId}/incidents`, { body: b }),
  declare: (
    roadId: string,
    b: { expected_version: number; mode: DeclarationMode; covers_from: string; covers_through: string; valid_until: string },
  ) => request<MutationResult>("POST", `/roads/${roadId}/declarations`, { body: b }),
  advanceClock: (expected_version: number, days: number) =>
    request<MutationResult>("POST", "/demo/clock/advance", { body: { expected_version, days } }),
};
