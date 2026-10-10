import { useEffect, useRef, useState } from "react";
import { useLocation } from "../useLocation";
import { Field } from "./Field";
import { MapMarker, MapView } from "./MapView";
import { Notice } from "./Notice";

interface Props {
  value: { lat: number; lng: number } | null;
  onChange: (lat: number, lng: number) => void;
  mapLabel: string;
  /** Find the person's position automatically if the browser already allows it. */
  auto?: boolean;
  markers?: MapMarker[];
  height?: number;
}

/** Choose a place three ways: current location, a typed place, or a click on the map. */
export function LocationPicker({ value, onChange, mapLabel, auto = false, markers, height = 280 }: Props) {
  const loc = useLocation(auto);
  const [query, setQuery] = useState("");
  const change = useRef(onChange);
  change.current = onChange;

  useEffect(() => {
    if (loc.place) change.current(loc.place.lat, loc.place.lng);
  }, [loc.place]);

  // Not a <form>: this picker sits inside other forms (report, project, sample works), and a form inside a
  // form makes the browser submit the outer page (the report screen jumped back home). Enter is handled here.
  const runSearch = () => {
    if (query.trim().length >= 3 && !loc.busy) void loc.search(query);
  };

  return (
    <div className="stack-sm">
      <div className="row">
        <button type="button" className="btn" onClick={() => void loc.locate()} disabled={loc.busy}>{loc.busy ? "Working…" : "Use my current location"}</button>
      </div>
      <div className="row" role="search" style={{ alignItems: "end" }}>
        <div style={{ flex: "1 1 220px" }}>
          <Field label="Or search for a place" help="Typed text is sent to OpenStreetMap's search to find it.">
            {(p) => (
              <input type="text" {...p} value={query} onChange={(e) => setQuery(e.target.value)} autoComplete="off"
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); runSearch(); } }} />
            )}
          </Field>
        </div>
        <button type="button" className="btn" onClick={runSearch} disabled={loc.busy || query.trim().length < 3}>Search</button>
      </div>
      {loc.hits && loc.hits.length ? (
        <div className="stack-sm" role="group" aria-label="Choose the right place">
          {loc.hits.map((h, i) => (
            <button key={i} type="button" className="btn" style={{ justifyContent: "flex-start", textAlign: "left" }} onClick={() => loc.setPlace(h)}>{h.label}</button>
          ))}
        </div>
      ) : null}
      {loc.message ? <Notice kind="warn"><p>{loc.message}</p></Notice> : null}
      <MapView label={mapLabel} user={null} pick={value} markers={markers} onPick={(la, ln) => onChange(la, ln)} height={height} />
      <p className="muted small">{value ? `Chosen: ${value.lat.toFixed(4)}, ${value.lng.toFixed(4)}. Click the map to move the pin.` : "Click the map to place a pin, or use one of the options above."}</p>
    </div>
  );
}
