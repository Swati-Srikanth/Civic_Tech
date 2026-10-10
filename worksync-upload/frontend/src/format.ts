// Display-only helpers: wording and date formatting. No business rules here.
import type { CaseStatus, ExecutionStatus, InspectionStatus, Role } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 'YYYY-MM-DD' -> '8 Nov 2026' without timezone shifts. */
export function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  const [y, m, day] = d.split("-").map(Number);
  if (!y || !m || !day) return d;
  return `${day} ${MONTHS[m - 1]} ${y}`;
}

export function fmtRange(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return "—";
  if (!end || end === start) return fmtDate(start);
  const [y1, m1, d1] = start.split("-").map(Number);
  const [y2, m2, d2] = end.split("-").map(Number);
  if (y1 === y2 && m1 === m2) return `${d1}–${d2} ${MONTHS[m1 - 1]} ${y1}`;
  return `${fmtDate(start)} – ${fmtDate(end)}`;
}

/** UTC ISO timestamp -> Asia/Kolkata wall time. */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return (
    new Intl.DateTimeFormat("en-IN", {
      timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: true,
    }).format(dt) + " IST"
  );
}

export function addDays(d: string, n: number): string {
  const [y, m, day] = d.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, day + n));
  return dt.toISOString().slice(0, 10);
}

// Status wording from the frontend brief.
export const CASE_TEXT: Record<CaseStatus, string> = {
  DRAFT: "Plan being prepared",
  CONTRACTOR_REVIEW: "Waiting for contractors",
  DEPARTMENT_REVIEW: "Waiting for departments",
  APPROVED: "Plan agreed — start checks still required",
  BLOCKED: "Needs review",
  COMPLETED: "Finished and checked",
};

export const EXEC_TEXT: Record<ExecutionStatus, string> = {
  PLANNED: "Planned",
  IN_PROGRESS: "Work in progress",
  DONE: "Work finished",
  CANCELLED: "Cancelled",
};

export const INSPECTION_TEXT: Record<InspectionStatus, string> = {
  PENDING: "Inspection pending",
  PASS: "Inspection passed",
  FAIL: "Inspection failed",
};

export const ROLE_TEXT: Record<Role, string> = {
  DEPARTMENT: "Department",
  CONTRACTOR: "Contractor",
  INSPECTOR: "Inspector",
  ADMIN: "Admin",
};

export const KIND_TEXT = { UTILITY: "Utility work", RESURFACING: "Final resurfacing" } as const;

export const DECLARATION_TEXT: Record<string, string> = {
  CURRENT: "Confirmed",
  COVERAGE_MISSING: "Not yet confirmed",
  COVERAGE_STALE: "Out of date",
  COVERAGE_EXPIRED: "Expired",
  COVERAGE_SHORT: "Does not cover enough time",
  COVERAGE_CONTRADICTED: "Contradicts registered work",
};

/** One status line for a project, by what the resident most needs to know. */
export function projectStatusText(exec: ExecutionStatus, caseStatus: CaseStatus | null, verifiedOn: string | null | undefined): string {
  if (exec === "CANCELLED") return "Cancelled";
  if (exec === "DONE") return verifiedOn ? "Finished and checked" : "Finished — waiting for inspection";
  if (exec === "IN_PROGRESS") return "Work in progress";
  return caseStatus ? CASE_TEXT[caseStatus] : "Not yet planned";
}

export function actionLabel(action: string): string {
  return action
    .toLowerCase()
    .split("_")
    .map((w, i) => (i === 0 ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
