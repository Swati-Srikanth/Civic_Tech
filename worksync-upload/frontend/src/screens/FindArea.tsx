import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Field } from "../components/Field";
import { MapMarker, MapView } from "../components/MapView";
import { Notice } from "../components/Notice";
import { PriorityBadge } from "../components/PriorityBadge";
import { StatusBadge } from "../components/StatusBadge";
import { fmtDate } from "../format";
import { awayText, formatKm, sortByDistance } from "../geo";
import { locationMemory } from "../locationMemory";
import { useResource } from "../hooks";
import { useApp } from "../state";
import { useLocation } from "../useLocation";
import type { PublicComplaint, RoadSummary } from "../types";
import { reportPrefill } from "./ReportProblem";

const NEAR_KM = 10;

/** Public home: what is happening where you are. No account needed. */
export function FindArea() {
  const { tick, openRoad, go } = useApp();
  const loc = useLocation(true);
  const roads = useResource(() => api.publicRoads(), [tick]);
  const feed = useResource(() => api.publicComplaints(), [tick]);
  const [query, setQuery] = useState("");
  const [browseAll, setBrowseAll] = useState(false);
  const place = loc.place ?? locationMemory.place;
  if (loc.place) locationMemory.place = loc.place;

  const nearRoads = useMemo(() => (place && roads.data ? sortByDistance(roads.data, place) : []), [place, roads.data]);
  const nearProblems = useMemo(
    () => (place && feed.data ? sortByDistance(feed.data.filter((p) => p.lat !== null && p.lng !== null) as (PublicComplaint & { lat: number; lng: number })[], place) : []),
    [place, feed.data],
  );
  const roadsShown = nearRoads.filter((r) => r.distanceKm <= NEAR_KM);
  const problemsShown = nearProblems.filter((p) => p.distanceKm <= NEAR_KM);

  const markers: MapMarker[] = useMemo(() => {
    const out: MapMarker[] = [];
    for (const r of roadsShown.filter((x) => x.work_count > 0)) {
      out.push({ id: "r-" + r.id, lat: r.lat, lng: r.lng, kind: "work", label: `${r.name}: ${r.work_count} road work${r.work_count === 1 ? "" : "s"}` });
    }
    for (const p of problemsShown) {
      out.push({ id: "p-" + p.id, lat: p.lat, lng: p.lng, kind: p.fixed ? "fixed" : p.priority === "URGENT" ? "urgent" : "complaint",
        label: `${p.category_label}: ${p.status_text}${p.report_count > 1 ? ` (${p.report_count} reports)` : ""}` });
    }
    return out;
  }, [roadsShown, problemsShown]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!loc.busy && query.trim().length >= 3) void loc.search(query);
  };

  const seeingThisToo = (p: PublicComplaint) => {
    reportPrefill.category = p.category;
    if (p.lat !== null && p.lng !== null) { reportPrefill.lat = p.lat; reportPrefill.lng = p.lng; }
    go("report");
  };

  return (
    <div className="stack">
      <div className="page-head">
        <h1>What's happening near me?</h1>
        <p className="muted">Road works and problems reported around where you are. You do not need an account.</p>
      </div>

      <section className="card" aria-label="Your location">
        {place ? (
          <div className="row row--between">
            <p><strong>Showing results near:</strong> {place.label}{place.accuracy ? ` (accurate to about ${Math.round(place.accuracy)} m)` : ""}</p>
          </div>
        ) : (
          <p><strong>Allow your location</strong> to see what is happening around you, or search for a place.</p>
        )}
        <div className="row">
          <button type="button" className="btn btn--primary" onClick={() => void loc.locate()} disabled={loc.busy}>
            {loc.busy ? "Finding you…" : place ? "Update my location" : "Use my current location"}
          </button>
        </div>
        <form className="row" onSubmit={submit} style={{ alignItems: "end" }}>
          <div style={{ flex: "1 1 240px" }}>
            <Field label="Or search for a place" help="A street, area, landmark or town.">
              {(p) => <input type="text" {...p} value={query} onChange={(e) => setQuery(e.target.value)} autoComplete="off" />}
            </Field>
          </div>
          <button type="submit" className="btn" disabled={loc.busy || query.trim().length < 3}>Search</button>
        </form>
        {loc.hits && loc.hits.length ? (
          <div className="stack-sm" role="group" aria-label="Choose the right place">
            {loc.hits.map((h, i) => <button key={i} type="button" className="btn" style={{ justifyContent: "flex-start", textAlign: "left" }} onClick={() => loc.setPlace(h)}>{h.label}</button>)}
          </div>
        ) : null}
        {loc.message ? <Notice kind="warn"><p>{loc.message}</p></Notice> : null}
        <p className="muted small">
          Privacy: your position stays in this browser. It is used here to sort and map what is nearby and is not sent to WorkSync.
          Typed place names go to OpenStreetMap's search, and the map picture loads from OpenStreetMap.
        </p>
      </section>

      {place ? (
        <section className="stack-sm" aria-label="Map">
          <MapView label="Map of your location with nearby road works and reported problems" user={place} markers={markers} height={340} />
        </section>
      ) : null}

      {(roads.error || feed.error) ? <Notice kind="bad" title="Could not load everything"><p>{(roads.error ?? feed.error)!.message}</p><div><button type="button" className="btn" onClick={() => { roads.reload(); feed.reload(); }}>Try again</button></div></Notice> : null}
      {(roads.loading && !roads.data) ? <p className="loading">Loading…</p> : null}

      {place && roads.data && feed.data ? (
        <div className="grid-2">
          <section className="stack" aria-label="Road works near you">
            <h2>Road works near you</h2>
            {roadsShown.length === 0 ? (
              <EmptyState title="No road works registered nearby">
                {nearRoads.length ? `Nothing is registered within ${NEAR_KM} km. The nearest is ${nearRoads[0].name}, ${formatKm(nearRoads[0].distanceKm)} away.` : "No roads are registered yet."}
              </EmptyState>
            ) : roadsShown.map((r) => <RoadCard key={r.id} road={r} distanceKm={r.distanceKm} onOpen={() => openRoad(r.id)} />)}
          </section>

          <section className="stack" aria-label="Public grievances near you">
            <div className="card" style={{ borderColor: "#e0b25b" }}>
              <h2>Public grievances near you</h2>
              <p className="muted small">Problems people have reported within {NEAR_KM} km. Locations are approximate and no personal details are shown.</p>
              {problemsShown.length === 0 ? (
                <p>No problems have been reported near you. {feed.data.length ? "" : "Nothing has been reported yet."}</p>
              ) : (
                <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {problemsShown.map((p) => (
                    <li key={p.id} className="card" style={{ background: "#fffaf0" }}>
                      <div className="card__head">
                        <strong>{p.category_label}</strong>
                        <div className="row">
                          <StatusBadge tone={p.fixed ? "ok" : p.escalated ? "bad" : "info"}>{p.fixed ? "Marked fixed" : p.status_text}</StatusBadge>
                          {!p.fixed ? <PriorityBadge priority={p.priority} text={p.priority_text} /> : null}
                        </div>
                      </div>
                      <p className="muted small">
                        {awayText(p.distanceKm).replace(/^./, (c) => c.toUpperCase())}{p.road_name ? ` · ${p.road_name}` : ""} · {p.report_count} report{p.report_count === 1 ? "" : "s"} since {fmtDate(p.since)}
                        {p.department_name ? ` · with the ${p.department_name}` : ""}
                      </p>
                      {p.promised_by && !p.fixed ? <p><strong>Promised by {fmtDate(p.promised_by)}</strong></p> : null}
                      {p.escalated && !p.fixed ? <p className="muted small">The promised date was missed, so it was escalated.</p> : null}
                      {!p.fixed ? <div><button type="button" className="btn" onClick={() => seeingThisToo(p)}>I'm seeing this too</button></div> : null}
                    </li>
                  ))}
                </ul>
              )}
              <div><button type="button" className="btn btn--primary" onClick={() => go("report")}>Report a problem</button></div>
            </div>
          </section>
        </div>
      ) : null}

      <section className="stack-sm">
        <button type="button" className="btn btn--link" aria-expanded={browseAll} onClick={() => setBrowseAll(!browseAll)} style={{ alignSelf: "flex-start" }}>
          {browseAll ? "Hide all roads" : "Or browse all registered roads"}
        </button>
        {browseAll ? (
          (roads.data ?? []).length ? <div className="grid-2">{roads.data!.map((r) => <RoadCard key={r.id} road={r} onOpen={() => openRoad(r.id)} />)}</div>
            : <EmptyState title="No roads are registered yet">Departments register road works at a location; they appear here once they do.</EmptyState>
        ) : null}
      </section>
    </div>
  );
}

function RoadCard({ road, distanceKm, onOpen }: { road: RoadSummary; distanceKm?: number; onOpen: () => void }) {
  return (
    <article className="card">
      <div className="card__head">
        <div>
          <h3>{road.name}</h3>
          <div className="muted small">{road.area_label ?? ""}</div>
        </div>
        {distanceKm !== undefined ? <StatusBadge tone="info">{awayText(distanceKm).replace(/^./, (c) => c.toUpperCase())}</StatusBadge> : null}
      </div>
      {road.work_count === 0 ? (
        <p className="muted">No road work is registered here.</p>
      ) : (
        <>
          <p>
            <strong>{road.work_count}</strong> work{road.work_count === 1 ? "" : "s"} registered
            {road.in_progress_count ? <>, <strong>{road.in_progress_count}</strong> in progress</> : null}.
          </p>
          <ul style={{ margin: 0, paddingLeft: 20 }}>{road.works.map((w) => <li key={w.id}>{w.title}</li>)}</ul>
        </>
      )}
      {road.notices[0] ? <p className="muted small">{road.notices[0]}</p> : null}
      <div><button type="button" className="btn btn--primary" onClick={onOpen}>See what's happening</button></div>
    </article>
  );
}
