import { fmtDateTime } from "../format";
import type { ActivityRow } from "../types";

const pretty = (a: string) => { const t = a.toLowerCase().replace(/_/g, " "); return t[0].toUpperCase() + t.slice(1); };

/** A plain list of who did what and when. Staff names appear here; residents never see this. */
export function ActivityFeed({ items, empty = "Nothing has happened yet." }: { items: ActivityRow[]; empty?: string }) {
  if (!items.length) return <p className="muted">{empty}</p>;
  return (
    <ul className="history" aria-label="Activity">
      {items.map((a) => (
        <li key={a.id}>
          <strong>{pretty(a.action)}</strong>{a.reference ? <> · <code>{a.reference}</code></> : null}{a.detail ? <> · {a.detail}</> : null}
          <div className="muted small">{a.actor_name} · {fmtDateTime(a.recorded_at)}</div>
          {a.reason ? <div className="small">“{a.reason}”</div> : null}
        </li>
      ))}
    </ul>
  );
}
