import { useState } from "react";
import { api } from "../api";
import { ActivityFeed } from "../components/ActivityFeed";
import { Field } from "../components/Field";
import { ErrorNotice, Notice } from "../components/Notice";
import { PriorityBadge } from "../components/PriorityBadge";
import { useResource } from "../hooks";
import { useApp } from "../state";

function Stat({ label, value, tone = "plain", hint }: { label: string; value: number | string; tone?: "plain" | "warn" | "bad" | "ok"; hint?: string }) {
  return (
    <div className={`stat stat--${tone}`}>
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
      {hint ? <div className="muted small">{hint}</div> : null}
    </div>
  );
}

/** The staff window's home: how the department is doing, what needs attention, and your own work. */
export function Overview() {
  const { user, boot, tick, go } = useApp();
  const [dept, setDept] = useState("");
  const { data, error, loading, reload } = useResource(() => api.overview(dept || undefined), [dept, user?.id, tick], !!user);
  if (!user) return null;
  const c = data?.complaints, p = data?.projects;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Overview{data ? `: ${data.scope.department_name}` : ""}</h1>
        <p className="muted">
          {data?.scope.is_overseer ? "You can see everything in this department, including each colleague's work (see Team)." : "The department's numbers, and your own work."}
        </p>
      </div>
      {user.role === "ADMIN" ? (
        <Field label="Department">
          {(f) => (
            <select {...f} value={dept} onChange={(e) => setDept(e.target.value)} style={{ maxWidth: 280 }}>
              <option value="">All departments</option>
              {boot?.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          )}
        </Field>
      ) : null}
      {error ? <ErrorNotice error={error} onRefresh={reload} /> : null}
      {loading && !data ? <p className="loading">Loading…</p> : null}

      {data && c && p ? (
        <>
          <section aria-label="Your own work" className="card">
            <h2>My work</h2>
            <div className="stats">
              <Stat label="Complaints I'm handling" value={data.my_work.open_complaints} />
              <Stat label="…of which overdue" value={data.my_work.overdue} tone={data.my_work.overdue ? "bad" : "plain"} />
              <Stat label="Projects I lead" value={data.my_work.active_projects} />
            </div>
          </section>

          <section aria-label="Complaints" className="stack-sm">
            <h2>Complaints</h2>
            <div className="stats">
              <Stat label="Open problems" value={c.open} />
              <Stat label="Urgent" value={c.urgent} tone={c.urgent ? "bad" : "plain"} />
              <Stat label="High priority" value={c.high} tone={c.high ? "warn" : "plain"} />
              <Stat label="Promise missed" value={c.overdue} tone={c.overdue ? "bad" : "plain"} />
              <Stat label="Escalated" value={c.escalated} tone={c.escalated ? "warn" : "plain"} />
              <Stat label="Nobody working on it" value={c.unassigned} tone={c.unassigned ? "warn" : "plain"} />
              {user.role === "ADMIN" ? <Stat label="Not sent to a department" value={c.unrouted} tone={c.unrouted ? "warn" : "plain"} /> : null}
              <Stat label="Waiting for the resident to confirm" value={c.awaiting_confirmation} />
              <Stat label="Reopened" value={c.reopened} tone={c.reopened ? "warn" : "plain"} />
              <Stat label="Closed so far" value={c.closed} tone="ok" />
              <Stat label="Average days to resolve" value={c.avg_resolution_days ?? "—"} hint="on the simulated calendar" />
            </div>
          </section>

          <section aria-label="Projects" className="stack-sm">
            <h2>Projects</h2>
            <div className="stats">
              <Stat label="In progress" value={p.in_progress} />
              <Stat label="Planned" value={p.planned} />
              <Stat label="Waiting for agreement" value={p.awaiting_agreement} />
              <Stat label="Plan agreed" value={p.agreed} tone="ok" />
              <Stat label="Plan needs review" value={p.blocked} tone={p.blocked ? "warn" : "plain"} />
              <Stat label="On hold" value={p.on_hold} tone={p.on_hold ? "warn" : "plain"} />
              <Stat label="Completed" value={p.done} tone="ok" />
              <Stat label="Cancelled" value={p.cancelled} />
            </div>
          </section>

          <section aria-label="Needs attention" className="stack-sm">
            <h2>Needs attention</h2>
            {data.needs_attention.length === 0 ? <Notice kind="ok"><p>Nothing needs attention right now.</p></Notice> : (
              <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {data.needs_attention.map((a) => (
                  <li key={a.kind + a.id} className="card">
                    <div className="card__head">
                      <div><strong>{a.title}</strong><div className="muted small">{a.kind === "complaint" ? "Complaint" : "Project"}{a.department_name ? ` · ${a.department_name}` : ""}{a.assigned_name ? ` · with ${a.assigned_name}` : ""}</div></div>
                      <PriorityBadge priority={a.priority} />
                    </div>
                    <p>{a.reason}.</p>
                    <div><button type="button" className="btn" onClick={() => go(a.kind === "complaint" ? "complaints" : "projects")}>{a.kind === "complaint" ? "Open complaints" : "Open projects"}</button></div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-label="By category" className="card">
            <h2>By category</h2>
            {c.by_category.length === 0 ? <p className="muted">No complaints yet.</p> : (
              <table className="schedule-table" style={{ display: "table" }}>
                <thead><tr><th scope="col">Category</th><th scope="col">Open</th><th scope="col">Closed</th></tr></thead>
                <tbody>{c.by_category.map((r) => <tr key={r.category}><th scope="row">{r.label}</th><td>{r.open}</td><td>{r.closed}</td></tr>)}</tbody>
              </table>
            )}
          </section>

          <section aria-label="Recent activity" className="card">
            <h2>Recent activity</h2>
            <ActivityFeed items={data.recent_activity} />
            {data.scope.is_overseer ? <div><button type="button" className="btn" onClick={() => go("team")}>See the whole team and the full trail</button></div> : null}
          </section>
        </>
      ) : null}
    </div>
  );
}
