import type { ReactNode } from "react";
import type { ExecutionStatus, Project, PublicCard } from "../types";
import { KIND_TEXT, projectStatusText } from "../format";
import { DateLabel, type DateKind } from "./DateLabel";
import { StatusBadge, type Tone } from "./StatusBadge";

export interface CardData {
  title: string;
  purpose: string;
  kind: "UTILITY" | "RESURFACING";
  department: string;
  contractor: string;
  statusText: string;
  tone: Tone;
  dates: { kind: DateKind; start?: string | null; end?: string | null; day?: string | null }[];
  reason?: string | null;
  pcc?: string | null;
  extra?: { label: string; value: string }[];
}

const toneFor = (exec: ExecutionStatus, text: string): Tone =>
  exec === "CANCELLED" ? "neutral" : exec === "DONE" ? (text.startsWith("Finished and checked") ? "ok" : "info") : exec === "IN_PROGRESS" ? "info" : "neutral";

export function publicCard(c: PublicCard): CardData {
  const statusText = projectStatusText(c.execution_status, c.case_status, c.verified_on);
  const dates: CardData["dates"] = [];
  if (c.proposed_start) dates.push({ kind: "PROPOSED", start: c.proposed_start, end: c.proposed_end });
  if (c.confirmed_start) dates.push({ kind: "CONFIRMED", start: c.confirmed_start, end: c.confirmed_end });
  if (c.actual_start) dates.push({ kind: "ACTUAL", start: c.actual_start, end: c.actual_end });
  if (c.verified_on) dates.push({ kind: "VERIFIED", day: c.verified_on });
  let tone = toneFor(c.execution_status, statusText);
  if (c.execution_status === "PLANNED") tone = c.case_status === "BLOCKED" ? "warn" : c.case_status === "APPROVED" ? "ok" : c.case_status ? "info" : "neutral";
  return {
    title: c.title, purpose: c.purpose, kind: c.kind, department: c.owner_org_name, contractor: c.contractor_name,
    statusText, tone, dates, reason: c.public_reason,
  };
}

export function staffCard(p: Project): CardData {
  const statusText = projectStatusText(p.execution_status, p.case_status ?? null, p.verified_on);
  const dates: CardData["dates"] = [];
  if (p.plan_start && p.date_label) dates.push({ kind: p.date_label, start: p.plan_start, end: p.plan_end });
  if (p.actual_start) dates.push({ kind: "ACTUAL", start: p.actual_start, end: p.actual_end });
  if (p.verified_on) dates.push({ kind: "VERIFIED", day: p.verified_on });
  let tone = toneFor(p.execution_status, statusText);
  if (p.execution_status === "PLANNED") tone = p.case_status === "BLOCKED" ? "warn" : p.case_status === "APPROVED" ? "ok" : p.case_status ? "info" : "neutral";
  return {
    title: p.title, purpose: p.purpose, kind: p.kind, department: p.owner_org_name ?? p.owner_org_id,
    contractor: p.assigned_contractor_name ?? p.assigned_contractor_id, statusText, tone, dates, pcc: p.pcc_number,
  };
}

/** Answers: what work, why, who, when, current status. */
export function ProjectCard({ data, children, heading = "h3" }: { data: CardData; children?: ReactNode; heading?: "h2" | "h3" }) {
  const H = heading;
  return (
    <article className="card">
      <div className="card__head">
        <div>
          <H>{data.title}</H>
          <div className="muted small">{KIND_TEXT[data.kind]}</div>
        </div>
        <StatusBadge tone={data.tone}>{data.statusText}</StatusBadge>
      </div>
      <dl className="card__facts">
        <div><dt>Why</dt><dd>{data.purpose}</dd></div>
        <div><dt>Department</dt><dd>{data.department}</dd></div>
        <div><dt>Contractor</dt><dd>{data.contractor}</dd></div>
        {data.extra?.map((e) => (
          <div key={e.label}><dt>{e.label}</dt><dd>{e.value}</dd></div>
        ))}
      </dl>
      <div className="dates">
        {data.dates.length ? (
          data.dates.map((d, i) => <DateLabel key={i} kind={d.kind} start={d.start} end={d.end} day={d.day} />)
        ) : (
          <span className="muted">No dates yet: the plan is not ready.</span>
        )}
      </div>
      {data.reason ? <p><strong>Note:</strong> {data.reason}</p> : null}
      {data.pcc ? <div><span className="pcc">Certificate {data.pcc}</span></div> : null}
      {children}
    </article>
  );
}
