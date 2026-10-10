import { useEffect, useState } from "react";
import { ComplaintStatusCard } from "../components/ComplaintStatus";
import { EmptyState } from "../components/EmptyState";
import { Notice } from "../components/Notice";
import { forgetAllReports, forgetReport, markSeen, savedReports, seenEvent, unreadCount } from "../myReports";
import { useApp } from "../state";
import type { ComplaintTrackView } from "../types";

/** The person's own reports with their current status and any updates they have not seen yet. */
export function MyReports() {
  const { myReports, resident, boot, refreshMyReports, go } = useApp();
  const [open, setOpen] = useState<string | null>(null);
  const [, bump] = useState(0);
  const codes = new Map(savedReports().map((r) => [r.reference, r.code]));

  useEffect(() => { void refreshMyReports(); }, [refreshMyReports]);

  const expand = (v: ComplaintTrackView) => {
    setOpen(open === v.reference ? null : v.reference);
  };

  // What is new is shown while the card is open, and counted as seen once it is closed again.
  const close = (v: ComplaintTrackView) => { markSeen(v.reference, v.last_event_id); bump((n) => n + 1); void refreshMyReports(); };

  return (
    <div className="stack">
      <div className="page-head">
        <h1>My reports</h1>
        <p className="muted">
          {resident ? `Reports saved to your account (${resident.email ?? resident.name ?? ""}), plus any remembered on this device.`
            : "Reports you chose to remember on this device. Updates appear here and are checked every 30 seconds while this page is open."}
        </p>
      </div>
      {!resident && boot?.google_client_id ? <Notice kind="info"><p>Sign in with Google (top right) to keep your reports across devices. It is optional.</p></Notice> : null}
      {myReports.length === 0 ? (
        <EmptyState title="No reports yet">
          Reports you send are remembered here when you allow it. You can also look one up with its tracking code.
          <div className="row" style={{ justifyContent: "center", marginTop: 8 }}>
            <button type="button" className="btn btn--primary" onClick={() => go("report")}>Report a problem</button>
            <button type="button" className="btn" onClick={() => go("track")}>Track a complaint</button>
          </div>
        </EmptyState>
      ) : null}
      {myReports.map((v) => {
        const unread = unreadCount(v.reference, v.timeline);
        const isOpen = open === v.reference;
        return (
          <div key={v.reference} className="stack-sm">
            <button type="button" className="card" style={{ textAlign: "left", cursor: "pointer", font: "inherit" }} aria-expanded={isOpen}
              onClick={() => { if (isOpen) close(v); expand(v); }}>
              <div className="card__head">
                <strong>{v.reference} · {v.category_label}</strong>
                <div className="row">
                  {unread ? <span className="badge badge--bad">{unread} new update{unread === 1 ? "" : "s"}</span> : null}
                  <span className="badge badge--info">{v.status_text}</span>
                </div>
              </div>
              <div className="muted small">{v.timeline.length ? v.timeline[v.timeline.length - 1].message : ""}</div>
            </button>
            {isOpen ? (
              <>
                <ComplaintStatusCard view={v} code={codes.get(v.reference)} seenUpTo={seenEvent(v.reference)} headingLevel={3}
                  onChanged={() => { void refreshMyReports(); }} />
                {codes.has(v.reference) ? (
                  <div><button type="button" className="btn btn--link" onClick={() => { forgetReport(v.reference); setOpen(null); void refreshMyReports(); }}>Forget this report on this device</button></div>
                ) : null}
              </>
            ) : null}
          </div>
        );
      })}
      {savedReports().length ? (
        <div><button type="button" className="btn btn--link" onClick={() => { forgetAllReports(); setOpen(null); void refreshMyReports(); }}>Forget everything remembered on this device</button></div>
      ) : null}
    </div>
  );
}
