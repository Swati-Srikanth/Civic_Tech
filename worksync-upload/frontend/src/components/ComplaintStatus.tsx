import { useState } from "react";
import { api } from "../api";
import { fmtDate, fmtDateTime } from "../format";
import { useAction } from "../hooks";
import type { ComplaintStatus, ComplaintTrackView, Priority } from "../types";
import { Field } from "./Field";
import { ErrorNotice, Notice } from "./Notice";
import { PriorityBadge } from "./PriorityBadge";
import { StatusBadge, type Tone } from "./StatusBadge";
import { Timeline } from "./Timeline";

const TONE: Record<ComplaintStatus, Tone> = {
  NEW: "info", ACKNOWLEDGED: "info", IN_PROGRESS: "info", RESOLVED: "warn", CONFIRMED_FIXED: "ok", REOPENED: "bad", REJECTED: "neutral",
};

/** The detailed status of one complaint, as the person who made it should see it. */
export function ComplaintStatusCard({ view, code, seenUpTo, onChanged, headingLevel = 2 }: {
  view: ComplaintTrackView;
  /** The tracking code, for guests. Signed-in residents act without it. */
  code?: string;
  seenUpTo?: number;
  onChanged?: (v: ComplaintTrackView) => void;
  headingLevel?: 2 | 3;
}) {
  const H = headingLevel === 2 ? "h2" : "h3";
  return (
    <section className="card" aria-label={`Complaint ${view.reference}`}>
      <div className="card__head">
        <div>
          <H>{view.reference}</H>
          <div className="muted small">{view.category_label}{view.road_name ? ` · ${view.road_name}` : ""}</div>
        </div>
        <div className="row">
          <StatusBadge tone={TONE[view.status]}>{view.status_text}</StatusBadge>
          {view.status !== "CONFIRMED_FIXED" && view.status !== "REJECTED" ? <PriorityBadge priority={view.priority as Priority} text={view.priority_text} /> : null}
        </div>
      </div>
      <dl className="card__facts">
        <div><dt>Handled by</dt><dd>{view.department_name ?? "The coordinator (will pass it to a department)"}</dd></div>
        <div><dt>Received</dt><dd>{fmtDate(view.submitted_on)}; last update {fmtDateTime(view.last_update)}</dd></div>
        {view.promised_by ? <div><dt>Promised by</dt><dd><strong>{fmtDate(view.promised_by)}</strong>{view.committed_days ? ` (within ${view.committed_days} day${view.committed_days === 1 ? "" : "s"})` : ""}</dd></div> : null}
        {view.report_count > 1 ? <div><dt>Same problem</dt><dd>{view.report_count} people reported it, which raises its priority</dd></div> : null}
        {view.priority_reason && view.status !== "CONFIRMED_FIXED" && view.status !== "REJECTED" ? <div><dt>Priority</dt><dd>{view.priority_reason}</dd></div> : null}
      </dl>
      {view.escalation_text ? <Notice kind="warn" title="Escalated"><p>{view.escalation_text}, because the promised date was missed.</p></Notice> : null}
      {view.public_note ? <Notice kind="info" title="Latest message from the authorities"><p>{view.public_note}</p></Notice> : null}
      <h3 style={{ fontSize: "1rem" }}>What has happened so far</h3>
      <Timeline events={view.timeline} seenUpTo={seenUpTo} />
      {view.can_respond ? <ResidentResponse reference={view.reference} code={code} onChanged={onChanged} /> : null}
    </section>
  );
}

function ResidentResponse({ reference, code, onChanged }: { reference: string; code?: string; onChanged?: (v: ComplaintTrackView) => void }) {
  const [reopening, setReopening] = useState(false);
  const [note, setNote] = useState("");
  const act = useAction(
    (action: "CONFIRM_FIXED" | "REOPEN") => api.respondToComplaint(reference, code, action, action === "REOPEN" ? note.trim() || undefined : undefined),
    (r) => { setReopening(false); onChanged?.(r.complaint); },
  );
  return (
    <div className="notice notice--warn" role="group" aria-label="Is it fixed?">
      <div className="notice__title">The department says this is resolved. Is it fixed?</div>
      <div className="row">
        <button type="button" className="btn btn--primary" disabled={act.busy} onClick={() => void act.run("CONFIRM_FIXED")}>Yes, it is fixed</button>
        <button type="button" className="btn btn--danger" aria-expanded={reopening} onClick={() => setReopening(!reopening)}>No, it is not fixed</button>
      </div>
      {reopening ? (
        <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run("REOPEN"); }}>
          <Field label="What is still wrong? (optional)" error={act.error?.fieldMessage("note")}>
            {(p) => <textarea {...p} value={note} onChange={(e) => setNote(e.target.value)} maxLength={400} />}
          </Field>
          <div><button type="submit" className="btn btn--danger" disabled={act.busy}>Reopen this report</button></div>
        </form>
      ) : null}
      {act.error ? <ErrorNotice error={act.error} fieldsShownInline /> : null}
    </div>
  );
}
