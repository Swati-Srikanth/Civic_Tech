import { useState, type FormEvent } from "react";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Field } from "../components/Field";
import { ErrorNotice } from "../components/Notice";
import { ProjectHistoryPanel } from "../components/ProjectHistoryPanel";
import { PriorityBadge } from "../components/PriorityBadge";
import { StatusBadge } from "../components/StatusBadge";
import { StaffTimeline } from "../components/Timeline";
import { fmtDate } from "../format";
import { useAction, useResource } from "../hooks";
import { useApp } from "../state";
import type { StaffComplaint } from "../types";

const PAGE = 12;

/** The archive: past complaints and projects, searchable, with who handled them and how long they took. */
export function History() {
  const { user } = useApp();
  const [tab, setTab] = useState<"complaints" | "projects">("complaints");
  if (!user) return null;
  return (
    <div className="stack">
      <div className="page-head">
        <h1>History</h1>
        <p className="muted">Everything that has been closed or finished, kept for reference. Search it, see who handled each one and how long it took, and export it.</p>
      </div>
      <div className="seg" role="group" aria-label="What to show">
        <label><input type="radio" name="hist-tab" checked={tab === "complaints"} onChange={() => setTab("complaints")} /> Past complaints</label>
        <label><input type="radio" name="hist-tab" checked={tab === "projects"} onChange={() => setTab("projects")} /> Past projects</label>
      </div>
      {tab === "complaints" ? <PastComplaints /> : <PastProjects />}
    </div>
  );
}

function Download({ kind }: { kind: "complaints" | "projects" }) {
  const act = useAction(async () => {
    const blob = await api.downloadCsv(kind);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${kind}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    return true;
  });
  return (
    <div className="stack-sm">
      <button type="button" className="btn" onClick={() => void act.run()} disabled={act.busy}>{act.busy ? "Preparing…" : `Download all ${kind} (CSV)`}</button>
      {act.error ? <ErrorNotice error={act.error} /> : null}
    </div>
  );
}

function PastComplaints() {
  const { user, boot, tick } = useApp();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [applied, setApplied] = useState({ q: "", category: "", status: "", from: "", to: "" });
  const [page, setPage] = useState(0);
  const { data, error, loading, reload } = useResource(
    () => api.listComplaints({ scope: "closed", q: applied.q, category: applied.category, status: applied.status, opened_from: applied.from, opened_to: applied.to, limit: PAGE, offset: page * PAGE }),
    [applied, page, user?.id, tick], !!user);
  const submit = (e: FormEvent) => { e.preventDefault(); setPage(0); setApplied({ q, category, status, from, to }); };
  const total = data?.total ?? 0;

  return (
    <div className="stack">
      <form className="card stack-sm" onSubmit={submit} aria-label="Search past complaints">
        <div className="form-grid">
          <Field label="Search" help="Words from the description, street, reference, handler…" className="span-2">{(f) => <input type="text" {...f} value={q} onChange={(e) => setQ(e.target.value)} />}</Field>
          <Field label="Category">
            {(f) => (
              <select {...f} value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">All</option>
                {boot?.complaint_categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            )}
          </Field>
          <Field label="How it ended">
            {(f) => (
              <select {...f} value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">Any</option>
                <option value="CONFIRMED_FIXED">Confirmed fixed</option>
                <option value="RESOLVED">Marked resolved</option>
                <option value="REJECTED">Closed without action</option>
              </select>
            )}
          </Field>
          <Field label="Opened from">{(f) => <input type="date" {...f} value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
          <Field label="Opened until">{(f) => <input type="date" {...f} value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
        </div>
        <div className="row">
          <button type="submit" className="btn btn--primary">Search</button>
          <button type="button" className="btn" onClick={() => { setQ(""); setCategory(""); setStatus(""); setFrom(""); setTo(""); setPage(0); setApplied({ q: "", category: "", status: "", from: "", to: "" }); }}>Clear</button>
        </div>
      </form>
      <Download kind="complaints" />
      {error ? <ErrorNotice error={error} onRefresh={reload} /> : null}
      {loading && !data ? <p className="loading">Loading…</p> : null}
      {data && data.items.length === 0 ? <EmptyState title="No past complaints match">Try fewer words or a wider date range.</EmptyState> : null}
      {data ? <p className="muted small" aria-live="polite">{total} result{total === 1 ? "" : "s"}{total > PAGE ? `, showing ${page * PAGE + 1} to ${Math.min(total, (page + 1) * PAGE)}` : ""}</p> : null}
      {data?.items.map((c) => <PastComplaintRow key={c.id} c={c} />)}
      {total > PAGE ? (
        <div className="row">
          <button type="button" className="btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
          <button type="button" className="btn" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      ) : null}
    </div>
  );
}

function PastComplaintRow({ c }: { c: StaffComplaint }) {
  return (
    <details className="card">
      <summary style={{ cursor: "pointer", minHeight: 44, padding: "6px 0" }}>
        <strong>{c.category_label}</strong> · <code>{c.references[0]}</code>{c.report_count > 1 ? ` (+${c.report_count - 1} more report${c.report_count === 2 ? "" : "s"})` : ""}
        <span className="muted small"> · {c.department_name ?? "coordinator"} · {c.status_text}{c.resolution_days !== null ? ` · ${c.resolution_days} day${c.resolution_days === 1 ? "" : "s"} to resolve` : ""}</span>
      </summary>
      <div className="stack-sm">
        <div className="row"><StatusBadge tone={c.status === "REJECTED" ? "neutral" : "ok"}>{c.status_text}</StatusBadge><PriorityBadge priority={c.priority} text={c.priority_text} /></div>
        <dl className="card__facts">
          <div><dt>Handled by</dt><dd>{c.assigned_name ?? "nobody was assigned"}</dd></div>
          <div><dt>Opened</dt><dd>{fmtDate(c.opened_on)}{c.resolved_on ? `; resolved ${fmtDate(c.resolved_on)}` : ""}</dd></div>
          <div><dt>Street</dt><dd>{c.road_name ?? "not given"}</dd></div>
          {c.public_note ? <div><dt>Final message</dt><dd>{c.public_note}</dd></div> : null}
        </dl>
        <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {c.reports.map((r) => <li key={r.id}><span className="muted small">{r.id}</span> {r.description}</li>)}
        </ul>
        <h3 style={{ fontSize: "1rem" }}>Status history</h3>
        <StaffTimeline events={c.timeline} />
      </div>
    </details>
  );
}

function PastProjects() {
  const { user, tick } = useApp();
  const [q, setQ] = useState("");
  const [state, setState] = useState("past");
  const [applied, setApplied] = useState({ q: "", state: "past" });
  const [open, setOpen] = useState<string | null>(null);
  const { data, error, loading, reload } = useResource(() => api.listProjects(undefined, applied), [applied, user?.id, tick], !!user);
  const submit = (e: FormEvent) => { e.preventDefault(); setApplied({ q, state }); };

  return (
    <div className="stack">
      <form className="card stack-sm" onSubmit={submit} aria-label="Search past projects">
        <div className="form-grid">
          <Field label="Search" help="Title, purpose, street, certificate…" className="span-2">{(f) => <input type="text" {...f} value={q} onChange={(e) => setQ(e.target.value)} />}</Field>
          <Field label="Which">
            {(f) => (
              <select {...f} value={state} onChange={(e) => setState(e.target.value)}>
                <option value="past">Completed and cancelled</option>
                <option value="done">Completed</option>
                <option value="cancelled">Cancelled</option>
              </select>
            )}
          </Field>
        </div>
        <div><button type="submit" className="btn btn--primary">Search</button></div>
      </form>
      <Download kind="projects" />
      {error ? <ErrorNotice error={error} onRefresh={reload} /> : null}
      {loading && !data ? <p className="loading">Loading…</p> : null}
      {data && data.length === 0 ? <EmptyState title="No past projects match" /> : null}
      {data?.map((p) => (
        <article key={p.id} className="card">
          <div className="card__head">
            <div><h2 style={{ fontSize: "1.1rem" }}>{p.title}</h2><div className="muted small">{p.road_name} · {p.owner_org_name} · {p.assigned_contractor_name}</div></div>
            <StatusBadge tone={p.execution_status === "DONE" ? "ok" : "neutral"}>{p.execution_status === "DONE" ? "Completed" : "Cancelled"}</StatusBadge>
          </div>
          <dl className="card__facts">
            <div><dt>Led by</dt><dd>{p.lead_name ?? "—"}</dd></div>
            {p.actual_start ? <div><dt>Work</dt><dd>{fmtDate(p.actual_start)} to {fmtDate(p.actual_end)}</dd></div> : null}
            {p.verified_on ? <div><dt>Verified</dt><dd>{fmtDate(p.verified_on)}{p.pcc_number ? ` · certificate ${p.pcc_number}` : ""}</dd></div> : null}
            {p.cancel_reason ? <div><dt>Why cancelled</dt><dd>{p.cancel_reason}</dd></div> : null}
          </dl>
          <div><button type="button" className="btn" aria-expanded={open === p.id} onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? "Hide history" : "Show its full history"}</button></div>
          {open === p.id ? <ProjectHistoryPanel projectId={p.id} /> : null}
        </article>
      ))}
    </div>
  );
}
