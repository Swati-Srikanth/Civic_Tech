import { useState } from "react";
import { api } from "../api";
import { useAction } from "../hooks";
import { useApp } from "../state";
import type { SampleComplaint } from "../types";
import { ActionPanel } from "./ActionPanel";
import { LocationPicker } from "./LocationPicker";

/**
 * Administrator only. A fresh install has no streets or works. This builds a few clearly-invented sample works
 * around a place you choose (your own location, a searched place, or a map click) so the app can be tried.
 */
export function SampleScenario({ onCreated }: { onCreated: (complaints: SampleComplaint[]) => void }) {
  const { refresh } = useApp();
  const [pin, setPin] = useState<{ lat: number; lng: number } | null>(null);
  const act = useAction(() => api.createScenario(pin!.lat, pin!.lng), (r) => {
    onCreated((r.complaints as SampleComplaint[] | undefined) ?? []);
    refresh();
  });
  return (
    <ActionPanel
      title="Try it with sample works"
      description="There are no streets or road works yet. This creates three invented sample works, an empty street, and example complaints in every situation (new, duplicates, acknowledged, on track, overdue, escalated, resolved, reopened, fixed, closed, and ones waiting for the coordinator) around the place you choose, so you can try everything. It is demo data, can be created once, and a reset removes it."
      error={act.error} success={act.result?.message} fieldsShownInline
    >
      <LocationPicker value={pin} onChange={(lat, lng) => setPin({ lat, lng })} mapLabel="Map: choose where the sample works go" auto height={260} />
      <div><button type="button" className="btn btn--primary" disabled={!pin || act.busy} onClick={() => void act.run()}>{act.busy ? "Creating…" : "Create sample works and complaints here"}</button></div>
    </ActionPanel>
  );
}

/** Shown after the sample is created: what each example complaint is for, and the codes to try them as a resident. */
export function SampleResults({ items, onDismiss }: { items: SampleComplaint[]; onDismiss: () => void }) {
  return (
    <section className="card" aria-label="Sample complaints created">
      <h3>Sample created: example complaints for every situation</h3>
      <p className="muted small">
        These are invented. Use a reference and tracking code under <strong>Track a complaint</strong> (public page) to see it as the resident does,
        or open <strong>Complaints</strong> as the right department (or the coordinator) to act on it. The codes are shown only now.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table className="schedule-table" style={{ display: "table" }}>
          <thead><tr><th scope="col">Situation</th><th scope="col">Reference</th><th scope="col">Tracking code</th></tr></thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.reference}><td>{s.case}</td><td><code>{s.reference}</code></td><td><code>{s.code}</code></td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div><button type="button" className="btn" onClick={onDismiss}>Hide this list</button></div>
    </section>
  );
}
