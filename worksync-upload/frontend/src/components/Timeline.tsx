import { fmtDateTime } from "../format";
import type { TimelineEvent } from "../types";

/** Every status change in plain words, oldest first. Entries newer than `seenUpTo` are marked as new. */
export function Timeline({ events, seenUpTo }: { events: TimelineEvent[]; seenUpTo?: number }) {
  if (!events.length) return <p className="muted">No updates yet.</p>;
  return (
    <ol className="timeline" aria-label="Status history">
      {events.map((e) => (
        <li key={e.id}>
          <div className="timeline__head">
            <strong>{e.actor_label}</strong>
            <span className="muted small"> · {fmtDateTime(e.at)}</span>
            {seenUpTo !== undefined && e.id > seenUpTo ? <span className="badge badge--info" style={{ marginLeft: 8 }}>New</span> : null}
          </div>
          <div>{e.message}</div>
        </li>
      ))}
    </ol>
  );
}

/** The same history for staff: it also names the person who acted (residents never get these names). */
export function StaffTimeline({ events }: { events: TimelineEvent[] }) {
  if (!events.length) return <p className="muted">No updates yet.</p>;
  return (
    <ol className="timeline" aria-label="Status history">
      {events.map((e) => (
        <li key={e.id}>
          <div>
            <strong>{e.actor_name ?? e.actor_label}</strong>
            {e.actor_name ? <span className="muted small"> ({e.actor_label})</span> : null}
            <span className="muted small"> · {fmtDateTime(e.at)}</span>
          </div>
          <div>{e.message}</div>
        </li>
      ))}
    </ol>
  );
}
