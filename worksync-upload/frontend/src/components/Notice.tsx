import type { ReactNode } from "react";
import { ApiRequestError } from "../api";
import type { Blocker } from "../types";

type Kind = "info" | "ok" | "warn" | "bad";

export function Notice({ kind, title, children }: { kind: Kind; title?: string; children?: ReactNode }) {
  return (
    <div className={`notice notice--${kind}`} role={kind === "bad" ? "alert" : "status"}>
      {title ? <div className="notice__title">{title}</div> : null}
      {children}
    </div>
  );
}

function isBlocker(f: unknown): f is Blocker {
  return typeof f === "object" && f !== null && "code" in f && "message" in f;
}

/** Shows the server's own message. Stale errors offer a refresh and never resubmit anything. */
export function ErrorNotice({ error, onRefresh, fieldsShownInline = false }: { error: ApiRequestError; onRefresh?: () => void; fieldsShownInline?: boolean }) {
  if (error.isStale) {
    return (
      <Notice kind="warn" title="This plan changed. Refresh to review the latest dates.">
        <p>{error.message}</p>
        {onRefresh ? (
          <div>
            <button type="button" className="btn" onClick={() => onRefresh()}>Refresh</button>
          </div>
        ) : null}
      </Notice>
    );
  }
  if (error.status === 403) {
    return (
      <Notice kind="bad" title="You don't have permission for this">
        <p>{error.message}</p>
      </Notice>
    );
  }
  const raw = error.failures as unknown[];
  const blockers = raw.filter(isBlocker);
  const fieldFailures = error.failures.filter((f) => f.field && !fieldsShownInline);
  return (
    <Notice kind={error.code === "GATE_BLOCKED" ? "warn" : "bad"} title={error.code === "GATE_BLOCKED" ? "Not cleared to start" : "That did not go through"}>
      <p>{error.message}</p>
      {blockers.length > 1 ? (
        <ul>
          {blockers.map((b, i) => (
            <li key={i}>
              {b.message}
              {b.next_action ? <span> — {b.next_action}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {fieldFailures.length ? (
        <ul>
          {fieldFailures.map((f, i) => (
            <li key={i}>{f.message}</li>
          ))}
        </ul>
      ) : null}
    </Notice>
  );
}
