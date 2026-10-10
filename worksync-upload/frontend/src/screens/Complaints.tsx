import { useState } from "react";
import { api } from "../api";
import { ActionPanel } from "../components/ActionPanel";
import { EmptyState } from "../components/EmptyState";
import { Field } from "../components/Field";
import { ErrorNotice, Notice } from "../components/Notice";
import { PriorityBadge } from "../components/PriorityBadge";
import { StatusBadge, type Tone } from "../components/StatusBadge";
import { StaffTimeline } from "../components/Timeline";
import { addDays, fmtDate, fmtDateTime } from "../format";
import { useAction, useResource } from "../hooks";
import { useApp } from "../state";
import type { ComplaintStatus, StaffComplaint, TeamMember } from "../types";

const TONE: Record<ComplaintStatus, Tone> = {
  NEW: "warn", ACKNOWLEDGED: "info", IN_PROGRESS: "info", RESOLVED: "ok", CONFIRMED_FIXED: "ok", REOPENED: "bad", REJECTED: "neutral",
};
type Next = "ACKNOWLEDGED" | "IN_PROGRESS" | "RESOLVED" | "REJECTED";
const LABEL: Record<Next, string> = {
  ACKNOWLEDGED: "Acknowledge", IN_PROGRESS: "Promise a resolution time", RESOLVED: "Mark resolved", REJECTED: "Close without action",
};

/** Staff: the open complaints for your department, most urgent first. The coordinator sees every department. Past ones are in History. */
export function Complaints() {
  const { user, tick, refresh, go } = useApp();
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [assigned, setAssigned] = useState("");
  const [q, setQ] = useState("");
  const overseer = user?.role === "ADMIN" || !!user?.is_head;
  const { data, error, loading, reload } = useResource(
    () => api.listComplaints({ scope: "open", status, priority, assigned, q }),
    [status, priority, assigned, q, user?.id, tick], !!user,
  );
  const team = useResource(() => api.team(), [user?.id, tick], !!user && overseer);
  const scope = user?.role === "ADMIN" ? "Every department's complaints." : `Complaints for the ${user?.org_name ?? "your department"} only.`;
  const people = team.data?.items ?? [];

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Complaints from the public</h1>
        <p className="muted">
          {scope} Reports of the same problem are grouped, and more reports means higher priority. A promised date that is missed goes to the head of
          department with high priority. Contact details are visible to staff only. Finished ones are in <button type="button" className="btn btn--link" style={{ padding: 0, minHeight: 0 }} onClick={() => go("history")}>History</button>.
        </p>
      </div>
      <div className="form-grid">
        <Field label="Search" className="span-2">{(p) => <input type="text" {...p} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Words from the description, street, reference…" />}</Field>
        <Field label="Status">
          {(p) => (
            <select {...p} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All open</option>
              <option value="NEW">Received</option>
              <option value="ACKNOWLEDGED">Acknowledged</option>
              <option value="IN_PROGRESS">Work under way</option>
              <option value="REOPENED">Reopened</option>
            </select>
          )}
        </Field>
        <Field label="Priority">
          {(p) => (
            <select {...p} value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="">All</option>
              <option value="URGENT">Urgent</option>
              <option value="HIGH">High</option>
              <option value="NORMAL">Normal</option>
            </select>
          )}
        </Field>
        {overseer ? (
          <Field label="Handled by">
            {(p) => (
              <select {...p} value={assigned} onChange={(e) => setAssigned(e.target.value)}>
                <option value="">Anyone</option>
                <option value="none">Nobody yet</option>
                {people.map((m) => <option key={m.id} value={m.id}>{m.name}{user?.role === "ADMIN" ? ` (${m.department_name})` : ""}</option>)}
              </select>
            )}
          </Field>
        ) : null}
      </div>
      {error ? <ErrorNotice error={error} onRefresh={reload} /> : null}
      {loading && !data ? <p className="loading">Loading…</p> : null}
      {data && data.items.length === 0 ? <EmptyState title="Nothing open here">Nothing matches this filter right now.</EmptyState> : null}
      {data?.items.map((c) => <ProblemCard key={c.id} c={c} people={people} onChanged={() => { reload(); refresh(); }} />)}
    </div>
  );
}

function ProblemCard({ c, people, onChanged }: { c: StaffComplaint; people: TeamMember[]; onChanged: () => void }) {
  const { user, boot } = useApp();
  const [status, setStatus] = useState<Next | "">("");
  const [days, setDays] = useState("");
  const [note, setNote] = useState("");
  const [dept, setDept] = useState("");
  const [flash, setFlash] = useState<string | null>(null);

  const update = useAction(
    () => api.setComplaintStatus(c.id, c.version, status as Next, { ...(note.trim() ? { note: note.trim() } : {}), ...(status === "IN_PROGRESS" ? { resolve_in_days: Number(days) } : {}) }),
    (r) => { setFlash(r.message); setStatus(""); setDays(""); setNote(""); onChanged(); },
  );
  const assign = useAction(
    () => api.assignComplaint(c.id, c.version, dept),
    (r) => { setFlash(r.message); setDept(""); onChanged(); },
  );
  const [who, setWho] = useState("");
  const staff = useAction(
    (target: string | null) => api.assignComplaintStaff(c.id, c.version, target),
    (r) => { setFlash(r.message); setWho(""); onChanged(); },
  );
  const can = (a: string) => c.allowed_actions.includes(a as never);
  const overseer = user?.role === "ADMIN" || !!user?.is_head;
  const candidates = people.filter((m) => m.department_id === c.department_id);
  const today = boot?.clock.date;
  const due = status === "IN_PROGRESS" && today && Number(days) > 0 ? addDays(today, Number(days)) : null;
  const isRecommit = status === "IN_PROGRESS" && c.status === "IN_PROGRESS";

  return (
    <article className="card" style={c.priority === "URGENT" ? { borderColor: "#b91c1c", borderWidth: 2 } : c.priority === "HIGH" ? { borderColor: "#e0b25b" } : undefined}>
      <div className="card__head">
        <div>
          <h2 style={{ fontSize: "1.1rem" }}>{c.category_label}</h2>
          <div className="muted small">
            {c.department_name ?? "Not yet assigned to a department"} · {c.road_name ?? "street not given"} · first reported {fmtDateTime(c.created_at)}
          </div>
        </div>
        <div className="row">
          {c.status !== "CONFIRMED_FIXED" && c.status !== "REJECTED" ? <PriorityBadge priority={c.priority} text={c.priority_text} /> : null}
          <StatusBadge tone={TONE[c.status]}>{c.status_text}</StatusBadge>
          {c.report_count > 1 ? <StatusBadge tone="warn">{c.report_count} reports of the same problem</StatusBadge> : null}
        </div>
      </div>
      <p className="small">
        <strong>Being handled by:</strong> {c.assigned_name ?? "nobody yet"}{c.days_open !== null ? ` · open ${c.days_open} day${c.days_open === 1 ? "" : "s"} on the calendar` : ""}
      </p>
      {c.priority_reason ? <p className="small"><strong>Why this priority:</strong> {c.priority_reason}.</p> : null}
      {c.escalation_text ? (
        <Notice kind={c.escalation_level >= 2 ? "bad" : "warn"} title={c.escalation_level >= 2 ? "Escalated to the coordinator" : "Escalated to the head of department"}>
          <p>{c.escalation_text}. The promised date was missed.{c.escalation_level === 1 && user && !user.is_head && user.role !== "ADMIN" ? " Only the head of department or the coordinator can act on it now." : ""}</p>
        </Notice>
      ) : null}
      {c.due_on && c.status === "IN_PROGRESS" ? (
        <p>
          <strong>Promised by {fmtDate(c.due_on)}</strong>{c.committed_days ? ` (within ${c.committed_days} day${c.committed_days === 1 ? "" : "s"})` : ""}.{" "}
          {c.overdue ? <strong style={{ color: "var(--bad-fg)" }}>Overdue.</strong> : c.days_left !== null ? `${c.days_left} day${c.days_left === 1 ? "" : "s"} left.` : ""}
        </p>
      ) : null}
      <details>
        <summary style={{ cursor: "pointer", minHeight: 44, padding: "10px 0" }}>{c.reports.length} report{c.reports.length === 1 ? "" : "s"} (with contact details)</summary>
        <ul className="stack-sm" style={{ listStyle: "none", padding: 0 }}>
          {c.reports.map((r) => (
            <li key={r.id} className="card">
              <div className="muted small">{r.id} · {fmtDateTime(r.created_at)}</div>
              <p>{r.description}</p>
              <p className="small muted">
                {r.location_text ? `${r.location_text} · ` : ""}{r.lat !== null && r.lng !== null ? `${r.lat}, ${r.lng} · ` : ""}
                Contact: {r.contact_name || r.contact_detail ? [r.contact_name, r.contact_detail].filter(Boolean).join(" · ") : "not given"}
              </p>
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary style={{ cursor: "pointer", minHeight: 44, padding: "10px 0" }}>Status history (what the residents were told)</summary>
        <StaffTimeline events={c.timeline} />
      </details>
      {flash ? <Notice kind="ok"><p>{flash}</p></Notice> : null}

      {can("ASSIGN_STAFF") ? (
        <ActionPanel title="Who is working on this?" description={overseer ? "Give it to someone in the team, or take it yourself." : "Take it so your colleagues know you are handling it."} error={staff.error} onRefresh={onChanged} fieldsShownInline>
          <div className="row" style={{ alignItems: "end" }}>
            {user && c.assigned_user_id !== user.id && user.role === "DEPARTMENT" ? (
              <button type="button" className="btn" disabled={staff.busy} onClick={() => void staff.run(user.id)}>Take this one myself</button>
            ) : null}
            {overseer ? (
              <>
                <Field label="Give it to">
                  {(p) => (
                    <select {...p} value={who} onChange={(e) => setWho(e.target.value)}>
                      <option value="">Choose someone</option>
                      {candidates.map((m) => <option key={m.id} value={m.id}>{m.name}{m.is_head ? " (head)" : ""} · {m.open_complaints} open</option>)}
                    </select>
                  )}
                </Field>
                <button type="button" className="btn" disabled={staff.busy || !who} onClick={() => void staff.run(who)}>Give it</button>
                {c.assigned_user_id ? <button type="button" className="btn btn--link" disabled={staff.busy} onClick={() => void staff.run(null)}>Remove</button> : null}
              </>
            ) : null}
          </div>
        </ActionPanel>
      ) : null}

      {c.next_statuses.length ? (
        <ActionPanel title="Update this problem" description={`This updates all ${c.open_report_count} open report${c.open_report_count === 1 ? "" : "s"}, and each person is notified.`} error={update.error} onRefresh={onChanged} fieldsShownInline>
          <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); if (status) void update.run(); }}>
            <Field label="What is the new status?">
              {(p) => (
                <select {...p} value={status} onChange={(e) => setStatus(e.target.value as Next)}>
                  <option value="">Choose</option>
                  {c.next_statuses.map((s, i) => <option key={`${s}-${i}`} value={s}>{s === "IN_PROGRESS" && c.status === "IN_PROGRESS" ? "Set a new promised date" : LABEL[s]}</option>)}
                </select>
              )}
            </Field>
            {status === "IN_PROGRESS" ? (
              <Field label="We will resolve this within (days)" help={due ? `That makes the promised date ${fmtDate(due)} (simulated calendar). If it is missed it goes to the ${isRecommit ? "coordinator" : "head of department"}.` : "Residents are told this date. If it is missed it escalates automatically."} error={update.error?.fieldMessage("resolve_in_days")}>
                {(p) => <input type="number" min={1} max={60} {...p} value={days} onChange={(e) => setDays(e.target.value)} />}
              </Field>
            ) : null}
            <Field label="Message to the people who reported it" help={status === "RESOLVED" || status === "REJECTED" ? "Required. They will see it." : "Optional. They will see it."} error={update.error?.fieldMessage("note")}>
              {(p) => <textarea {...p} value={note} onChange={(e) => setNote(e.target.value)} maxLength={400} />}
            </Field>
            <div><button type="submit" className="btn btn--primary" disabled={update.busy || !status}>{update.busy ? "Saving…" : "Save update"}</button></div>
          </form>
        </ActionPanel>
      ) : null}

      {can("ASSIGN_COMPLAINT") ? (
        <ActionPanel title="Send to a department" description="Only the coordinator can route a complaint. The reporters are told which department has it." error={assign.error} onRefresh={onChanged} fieldsShownInline>
          <form className="row" onSubmit={(e) => { e.preventDefault(); if (dept) void assign.run(); }} style={{ alignItems: "end" }}>
            <Field label="Department">
              {(p) => (
                <select {...p} value={dept} onChange={(e) => setDept(e.target.value)}>
                  <option value="">Choose</option>
                  {boot?.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              )}
            </Field>
            <button type="submit" className="btn" disabled={assign.busy || !dept}>{assign.busy ? "Sending…" : "Send"}</button>
          </form>
        </ActionPanel>
      ) : null}
    </article>
  );
}
