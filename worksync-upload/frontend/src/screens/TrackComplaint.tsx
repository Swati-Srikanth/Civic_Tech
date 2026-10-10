import { useState, type FormEvent } from "react";
import { api } from "../api";
import { ComplaintStatusCard } from "../components/ComplaintStatus";
import { Field } from "../components/Field";
import { ErrorNotice } from "../components/Notice";
import { useAction } from "../hooks";
import { markSeen, saveReport, savedReports } from "../myReports";
import { useApp } from "../state";
import type { ComplaintTrackView } from "../types";

/** In-memory hand-off from the receipt screen; never stored. */
export const trackPrefill = { reference: "", code: "" };

/** Public: check the detailed status of a complaint with its reference and private tracking code. */
export function TrackComplaint() {
  const { resident, refreshMyReports } = useApp();
  const [reference, setReference] = useState(() => { const v = trackPrefill.reference; trackPrefill.reference = ""; return v; });
  const [code, setCode] = useState(() => { const v = trackPrefill.code; trackPrefill.code = ""; return v; });
  const [view, setView] = useState<ComplaintTrackView | null>(null);
  const [saved, setSaved] = useState(false);
  const act = useAction(() => api.trackComplaint(reference.trim(), code.trim()), (v) => {
    setView(v);
    markSeen(v.reference, v.last_event_id);
    setSaved(savedReports().some((r) => r.reference === v.reference));
    void refreshMyReports();
  });
  const submit = (e: FormEvent) => { e.preventDefault(); void act.run(); };

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Track a complaint</h1>
        <p className="muted">Enter the reference and tracking code you were given when you sent your report, to see exactly where it stands.</p>
      </div>
      <form className="card stack" onSubmit={submit} noValidate>
        <div className="form-grid">
          <Field label="Reference" help="Looks like CMP-2026-0001." error={act.error?.fieldMessage("reference")}>
            {(p) => <input type="text" {...p} value={reference} onChange={(e) => setReference(e.target.value)} autoComplete="off" />}
          </Field>
          <Field label="Tracking code" help="Ten letters and numbers." error={act.error?.fieldMessage("code")}>
            {(p) => <input type="text" {...p} value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" />}
          </Field>
        </div>
        {act.error ? <ErrorNotice error={act.error} fieldsShownInline={act.error.failures.length > 0} /> : null}
        <div><button type="submit" className="btn btn--primary" disabled={act.busy || !reference.trim() || !code.trim()}>{act.busy ? "Checking…" : "Check status"}</button></div>
      </form>

      {view ? (
        <>
          <ComplaintStatusCard view={view} code={code.trim()} onChanged={(v) => { setView(v); markSeen(v.reference, v.last_event_id); void refreshMyReports(); }} />
          {!resident && !saved ? (
            <div><button type="button" className="btn" onClick={() => { saveReport(view.reference, code.trim().toUpperCase()); setSaved(true); void refreshMyReports(); }}>Remember this report on this device</button></div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
