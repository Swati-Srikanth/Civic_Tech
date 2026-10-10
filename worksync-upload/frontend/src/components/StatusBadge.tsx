import type { ReactNode } from "react";
import type { CaseStatus, ExecutionStatus, InspectionStatus } from "../types";
import { CASE_TEXT, EXEC_TEXT, INSPECTION_TEXT } from "../format";

export type Tone = "neutral" | "info" | "ok" | "warn" | "bad";

const ICON: Record<Tone, string> = { neutral: "●", info: "ℹ", ok: "✓", warn: "⚠", bad: "✕" };

/** Status is always text + icon, never colour alone. */
export function StatusBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`badge badge--${tone}`}>
      <span aria-hidden="true">{ICON[tone]}</span>
      <span>{children}</span>
    </span>
  );
}

export const caseTone = (s: CaseStatus): Tone =>
  ({ DRAFT: "neutral", CONTRACTOR_REVIEW: "info", DEPARTMENT_REVIEW: "info", APPROVED: "ok", BLOCKED: "warn", COMPLETED: "ok" } as const)[s];

export function CaseBadge({ status }: { status: CaseStatus }) {
  return <StatusBadge tone={caseTone(status)}>{CASE_TEXT[status]}</StatusBadge>;
}

const execTone = (s: ExecutionStatus): Tone =>
  ({ PLANNED: "neutral", IN_PROGRESS: "info", DONE: "ok", CANCELLED: "neutral" } as const)[s];

export function ExecBadge({ status }: { status: ExecutionStatus }) {
  return <StatusBadge tone={execTone(status)}>{EXEC_TEXT[status]}</StatusBadge>;
}

export function InspectionBadge({ status }: { status: InspectionStatus }) {
  const tone: Tone = status === "PASS" ? "ok" : status === "FAIL" ? "bad" : "neutral";
  return <StatusBadge tone={tone}>{INSPECTION_TEXT[status]}</StatusBadge>;
}
