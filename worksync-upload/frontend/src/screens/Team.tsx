import { useState } from "react";
import { api } from "../api";
import { ActivityFeed } from "../components/ActivityFeed";
import { EmptyState } from "../components/EmptyState";
import { Field } from "../components/Field";
import { ErrorNotice, Notice } from "../components/Notice";
import { PriorityBadge } from "../components/PriorityBadge";
import { StatusBadge } from "../components/StatusBadge";
import { fmtDate, fmtDateTime } from "../format";
import { useResource } from "../hooks";
import { useApp } from "../state";
import type { TeamMember } from "../types";

/** For the head of department (and the coordinator): every colleague, what each is working on, and the activity trail. */
export function Team() {
  const { user, boot, tick } = useApp();
  const [dept, setDept] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [only, setOnly] = useState("");
  const team = useResource(() => api.team(dept || undefined), [dept, user?.id, tick], !!user);
  const trail = useResource(() => api.activity({ limit: 30, user_id: only || undefined, department_id: dept || undefined }), [only, dept, user?.id, tick], !!user);

  if (!user) return null;
  const items = team.data?.items ?? [];

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Team</h1>
        <p className="muted">Everyone in the department, what they are working on, and what they have done. Open a person to see their complaints, projects and actions.</p>
      </div>
      {user.role === "ADMIN" ? (
        <Field label="Department">
          {(f) => (
            <select {...f} value={dept} onChange={(e) => { setDept(e.target.value); setOnly(""); }} style={{ maxWidth: 280 }}>
              <option value="">All departments</option>
              {boot?.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          )}
        </Field>
      ) : null}
      {team.error ? <ErrorNotice error={team.error} onRefresh={team.reload} /> : null}
      {team.loading && !team.data ? <p className="loading">Loading…</p> : null}
      {team.data && (team.data.unassigned_complaints || team.data.unassigned_projects) ? (
        <Notice kind="warn" title="Work with nobody on it">
          <p>{team.data.unassigned_complaints} open complaint problem{team.data.unassigned_complaints === 1 ? "" : "s"} and {team.data.unassigned_projects} project{team.data.unassigned_projects === 1 ? "" : "s"} have nobody working on them. Give them to someone from the Complaints or Projects screens.</p>
        </Notice>
      ) : null}
      {team.data && items.length === 0 ? <EmptyState title="No staff to show" /> : null}
      <div className="grid-2">
        {items.map((m) => (
          <article key={m.id} className="card">
            <div className="card__head">
              <div>
                <h2 style={{ fontSize: "1.1rem" }}>{m.name}</h2>
                <div className="muted small">{m.department_name}</div>
              </div>
              <div className="row">{m.is_head ? <StatusBadge tone="info">Head of department</StatusBadge> : null}
                {m.overdue ? <StatusBadge tone="bad">{m.overdue} overdue</StatusBadge> : null}</div>
            </div>
            <MemberFacts m={m} />
            <div className="row">
              <button type="button" className="btn" aria-expanded={open === m.id} onClick={() => setOpen(open === m.id ? null : m.id)}>{open === m.id ? "Hide details" : "What they are working on"}</button>
              <button type="button" className="btn btn--link" onClick={() => setOnly(only === m.id ? "" : m.id)}>{only === m.id ? "Show everyone's activity" : "Only their activity"}</button>
            </div>
            {open === m.id ? <MemberDetail id={m.id} /> : null}
          </article>
        ))}
      </div>
      <section className="card" aria-label="Activity trail">
        <h2>Activity trail{only ? `: ${items.find((i) => i.id === only)?.name ?? ""}` : ""}</h2>
        {trail.error ? <ErrorNotice error={trail.error} onRefresh={trail.reload} /> : null}
        <ActivityFeed items={trail.data?.items ?? []} empty="No activity yet." />
      </section>
    </div>
  );
}

function MemberFacts({ m }: { m: TeamMember }) {
  return (
    <dl className="card__facts">
      <div><dt>Handling now</dt><dd>{m.open_complaints} complaint{m.open_complaints === 1 ? "" : "s"}{m.escalated ? `, ${m.escalated} escalated` : ""}; {m.active_projects} project{m.active_projects === 1 ? "" : "s"}</dd></div>
      <div><dt>Done so far</dt><dd>{m.resolved_total} complaint{m.resolved_total === 1 ? "" : "s"} resolved{m.avg_resolution_days !== null ? ` (about ${m.avg_resolution_days} days each)` : ""}; {m.completed_projects} project{m.completed_projects === 1 ? "" : "s"} completed</dd></div>
      <div><dt>Waiting on residents</dt><dd>{m.awaiting_confirmation}</dd></div>
      <div><dt>Activity</dt><dd>{m.actions} action{m.actions === 1 ? "" : "s"}{m.last_active ? `, last ${fmtDateTime(m.last_active)}` : ""}</dd></div>
    </dl>
  );
}

function MemberDetail({ id }: { id: string }) {
  const { data, error, loading, reload } = useResource(() => api.teamMember(id), [id]);
  if (loading && !data) return <p className="loading">Loading…</p>;
  if (error) return <ErrorNotice error={error} onRefresh={reload} />;
  if (!data) return null;
  return (
    <div className="stack-sm">
      <h3>Open complaints</h3>
      {data.open_complaints.length === 0 ? <p className="muted">None right now.</p> : (
        <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {data.open_complaints.map((c) => (
            <li key={c.id} className="card">
              <div className="row row--between"><strong>{c.category_label}</strong><PriorityBadge priority={c.priority} text={c.priority_text} /></div>
              <div className="muted small">{c.status_text} · {c.report_count} report{c.report_count === 1 ? "" : "s"}{c.days_open !== null ? ` · open ${c.days_open} day${c.days_open === 1 ? "" : "s"}` : ""}</div>
              {c.due_on ? <div className="small">Promised by {fmtDate(c.due_on)}{c.overdue ? " (overdue)" : ""}</div> : null}
              {c.escalation_text ? <div className="small"><strong>{c.escalation_text}</strong></div> : null}
            </li>
          ))}
        </ul>
      )}
      <h3>Projects</h3>
      {data.projects.length === 0 ? <p className="muted">None.</p> : (
        <ul style={{ margin: 0, paddingLeft: 20 }}>{data.projects.map((p) => <li key={p.id}>{p.title}{p.road_name ? ` (${p.road_name})` : ""}: {p.execution_status.toLowerCase().replace("_", " ")}{p.verified_on ? `, verified ${fmtDate(p.verified_on)}` : ""}</li>)}</ul>
      )}
      <h3>Recently closed</h3>
      {data.closed_complaints.length === 0 ? <p className="muted">None yet.</p> : (
        <ul style={{ margin: 0, paddingLeft: 20 }}>{data.closed_complaints.map((c) => <li key={c.id}>{c.category_label}: {c.status_text.toLowerCase()}{c.resolution_days !== null ? `, ${c.resolution_days} day${c.resolution_days === 1 ? "" : "s"}` : ""}</li>)}</ul>
      )}
      <h3>Recent actions</h3>
      <ActivityFeed items={data.recent_actions} empty="No actions yet." />
    </div>
  );
}
