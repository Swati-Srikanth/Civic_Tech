import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { Field } from "../components/Field";
import { LocationPicker } from "../components/LocationPicker";
import { ErrorNotice, Notice } from "../components/Notice";
import { PriorityBadge } from "../components/PriorityBadge";
import { distanceKm, formatKm } from "../geo";
import { locationMemory } from "../locationMemory";
import { useAction } from "../hooks";
import { markSeen, saveReport } from "../myReports";
import { useApp } from "../state";
import type { ComplaintCategory, ComplaintReceipt } from "../types";
import { trackPrefill } from "./TrackComplaint";

/** In-memory hand-off from other pages (a road page, or "I'm seeing this too"); never stored. */
export const reportPrefill: { roadId: string; category?: string; lat?: number; lng?: number } = { roadId: "" };

/** Public: report a problem. No account and no verification. */
export function ReportProblem() {
  const { boot, go, resident, refreshMyReports } = useApp();
  const first = useMemo(() => {
    const p = { ...reportPrefill };
    reportPrefill.roadId = ""; reportPrefill.category = undefined; reportPrefill.lat = undefined; reportPrefill.lng = undefined;
    return p;
  }, []);
  const [category, setCategory] = useState<ComplaintCategory | "">((first.category as ComplaintCategory | undefined) ?? "");
  const [pin, setPin] = useState<{ lat: number; lng: number } | null>(
    first.lat !== undefined && first.lng !== undefined ? { lat: first.lat, lng: first.lng }
      : locationMemory.place ? { lat: locationMemory.place.lat, lng: locationMemory.place.lng } : null);
  const [roadId, setRoadId] = useState(first.roadId);
  const [where, setWhere] = useState("");
  const [description, setDescription] = useState("");
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [remember, setRemember] = useState(true);
  const [local, setLocal] = useState<Record<string, string>>({});
  const [receipt, setReceipt] = useState<ComplaintReceipt | null>(null);

  const cat = boot?.complaint_categories.find((c) => c.id === category);
  const nearbyRoads = useMemo(
    () => (pin ? (boot?.roads ?? []).filter((r) => r.lat !== null && r.lng !== null && distanceKm(pin, { lat: r.lat!, lng: r.lng! }) <= 0.5) : []),
    [pin, boot],
  );

  const act = useAction(
    () => api.submitComplaint({
      category: category as ComplaintCategory, description: description.trim(),
      ...(roadId ? { road_id: roadId } : {}), ...(where.trim() ? { location_text: where.trim() } : {}),
      ...(pin ? { lat: pin.lat, lng: pin.lng } : {}), ...(name.trim() ? { contact_name: name.trim() } : {}),
      ...(contact.trim() ? { contact_detail: contact.trim() } : {}),
    }),
    (r) => {
      if (remember && !resident) saveReport(r.id, r.tracking_code);
      setReceipt(r);
      // What the person has just been told on the receipt is not "new": mark the first entries as seen.
      api.trackComplaint(r.id, r.tracking_code).then((v) => markSeen(v.reference, v.last_event_id)).catch(() => undefined).finally(() => void refreshMyReports());
    },
  );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const missing: Record<string, string> = {};
    if (!category) missing.category = "Choose what kind of problem it is.";
    if (description.trim().length < 10) missing.description = "Please describe it in at least 10 characters.";
    setLocal(missing);
    if (Object.keys(missing).length) return;
    void act.run();
  };
  const err = (f: string) => local[f] ?? act.error?.fieldMessage(f);

  if (receipt) {
    return (
      <div className="stack">
        <Notice kind="ok" title="Your report was received">
          <p>{receipt.department_name ? `It was sent to the ${receipt.department_name}.` : "It was sent to the coordinator, who will pass it to the right department."}</p>
          {receipt.other_reports > 0 ? <p>{receipt.other_reports} other {receipt.other_reports === 1 ? "person has" : "people have"} reported the same problem nearby, so yours was grouped with theirs and its priority was raised.</p> : null}
        </Notice>
        <section className="card" aria-label="Your reference">
          <div className="row"><strong>Reference:</strong> <span className="pcc">{receipt.id}</span> <PriorityBadge priority={receipt.priority} /></div>
          <div className="row"><strong>Tracking code:</strong> <span className="pcc">{receipt.tracking_code}</span></div>
          {resident ? <Notice kind="info"><p>This report is saved to your Google account under "My reports".</p></Notice>
            : remember ? <Notice kind="info"><p>It was also remembered in this browser under "My reports", with updates shown there.</p></Notice>
            : <Notice kind="warn"><p>Write these down now. The tracking code is shown only once and is the only way to check progress.</p></Notice>}
          <div className="row">
            <button type="button" className="btn btn--primary" onClick={() => { trackPrefill.reference = receipt.id; trackPrefill.code = receipt.tracking_code; go("track"); }}>See its status</button>
            <button type="button" className="btn" onClick={() => go("find")}>Back to what's near me</button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <form className="stack" onSubmit={submit} noValidate aria-label="Report a problem">
      <div className="page-head">
        <h1>Report a problem</h1>
        <p className="muted">Tell the right department about a fault or hazard. You do not need an account.</p>
      </div>
      <div className="card stack">
        <Field label="What kind of problem?" error={err("category")} help={cat ? (cat.department_name ? `This goes to the ${cat.department_name}.` : "This goes to the coordinator, who will pass it to the right department.") : undefined}>
          {(p) => (
            <select {...p} value={category} onChange={(e) => setCategory(e.target.value as ComplaintCategory)}>
              <option value="">Choose one</option>
              {boot?.complaint_categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          )}
        </Field>
        {cat && !description.trim() ? (
          <div className="stack-sm" aria-label="Examples">
            <span className="muted small">For example (tap one to use it as a starting point):</span>
            {cat.examples.map((ex) => (
              <button key={ex} type="button" className="btn" style={{ justifyContent: "flex-start", textAlign: "left", fontWeight: 400 }} onClick={() => setDescription(ex)}>{ex}</button>
            ))}
          </div>
        ) : null}
        <div className="stack-sm">
          <strong>Where is it?</strong>
          <LocationPicker value={pin} onChange={(lat, lng) => setPin({ lat, lng })} auto={!pin} mapLabel="Map: click to place a pin where the problem is" />
        </div>
        <div className="form-grid">
          {nearbyRoads.length ? (
            <Field label="Which street? (optional)" error={err("road_id")} help="Registered streets within 500 m of your pin.">
              {(p) => (
                <select {...p} value={roadId} onChange={(e) => setRoadId(e.target.value)}>
                  <option value="">Not sure</option>
                  {nearbyRoads.map((r) => <option key={r.id} value={r.id}>{r.name} ({formatKm(distanceKm(pin!, { lat: r.lat!, lng: r.lng! }))})</option>)}
                </select>
              )}
            </Field>
          ) : null}
          <Field label="Landmark or address (optional)" help="For example, outside the bus stop." error={err("location_text")}>
            {(p) => <input type="text" {...p} value={where} onChange={(e) => setWhere(e.target.value)} maxLength={200} />}
          </Field>
          <Field label="What is the problem?" help={`${description.trim().length}/1000. Say what you saw and when.`} className="span-2" error={err("description")}>
            {(p) => <textarea {...p} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} />}
          </Field>
        </div>
        <p className="muted small">Your pin is rounded to about 100 m and sent with the report so it can be routed and matched with similar reports.</p>
      </div>
      <div className="card stack">
        <h2>Contact details (optional)</h2>
        <p className="muted small">Only municipal staff can see these, and only so they can follow up. They are never shown publicly.</p>
        <div className="form-grid">
          <Field label="Your name">{(p) => <input type="text" {...p} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoComplete="name" />}</Field>
          <Field label="Phone or email">{(p) => <input type="text" {...p} value={contact} onChange={(e) => setContact(e.target.value)} maxLength={120} />}</Field>
        </div>
        {!resident ? (
          <label className="check"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> <span>Remember this report on this device so I can see its updates under "My reports"</span></label>
        ) : <p className="muted small">Signed in with Google: this report will be saved to your account.</p>}
      </div>
      {act.error ? <ErrorNotice error={act.error} fieldsShownInline={act.error.failures.every((f) => !!f.field)} /> : null}
      <div className="row">
        <button type="submit" className="btn btn--primary" disabled={act.busy}>{act.busy ? "Sending…" : "Send report"}</button>
        <button type="button" className="btn" onClick={() => go("find")}>Cancel</button>
      </div>
    </form>
  );
}
