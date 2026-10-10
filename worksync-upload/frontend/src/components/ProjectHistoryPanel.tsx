import { api } from "../api";
import { fmtDate, fmtDateTime } from "../format";
import { useResource } from "../hooks";
import { ErrorNotice } from "./Notice";

const KIND_LABEL: Record<string, string> = { ACTIVITY: "Activity", INSPECTION: "Inspection", INCIDENT: "Report", CONSENT: "Agreement" };
const pretty = (a: string) => { const t = a.toLowerCase().replace(/_/g, " "); return t[0].toUpperCase() + t.slice(1); };

/** Everything that happened to one project, oldest first: registration, agreement, start, finish, inspections, reports. */
export function ProjectHistoryPanel({ projectId }: { projectId: string }) {
  const { data, error, loading, reload } = useResource(() => api.projectHistory(projectId), [projectId]);
  if (loading && !data) return <p className="loading">Loading history…</p>;
  if (error) return <ErrorNotice error={error} onRefresh={reload} />;
  if (!data) return null;
  const p = data.project;
  return (
    <div className="stack-sm">
      <dl className="card__facts">
        <div><dt>Registered by</dt><dd>{p.created_by ?? "—"}</dd></div>
        <div><dt>Led by</dt><dd>{p.lead ?? "nobody yet"}</dd></div>
        {p.actual_start ? <div><dt>Work</dt><dd>{fmtDate(p.actual_start)}{p.actual_end ? ` to ${fmtDate(p.actual_end)}` : " (in progress)"}</dd></div> : null}
        {p.verified_on ? <div><dt>Verified</dt><dd>{fmtDate(p.verified_on)}{p.pcc_number ? ` · certificate ${p.pcc_number}` : ""}</dd></div> : null}
        {p.cancel_reason ? <div><dt>Cancelled</dt><dd>{p.cancel_reason}</dd></div> : null}
      </dl>
      <ol className="timeline" aria-label="Project history">
        {data.events.map((e, i) => (
          <li key={i}>
            <div><strong>{KIND_LABEL[e.kind] ?? e.kind}</strong> · {e.kind === "ACTIVITY" ? pretty(e.what) : e.what}</div>
            <div className="muted small">{e.who ?? "—"} · {fmtDateTime(e.at)}</div>
            {e.note ? <div className="small">“{e.note}”</div> : null}
          </li>
        ))}
        {data.events.length === 0 ? <li>No history recorded.</li> : null}
      </ol>
    </div>
  );
}
