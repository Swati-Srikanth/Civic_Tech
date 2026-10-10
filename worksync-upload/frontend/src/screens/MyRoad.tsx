import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Notice } from "../components/Notice";
import { ProjectCard, publicCard } from "../components/ProjectCard";
import { fmtDate } from "../format";
import { useResource } from "../hooks";
import { useApp } from "../state";
import { reportPrefill } from "./ReportProblem";

/** Public road detail: what work, why, who, when, and where it stands. No sign-in. */
export function MyRoad() {
  const { publicRoadId, tick, go } = useApp();
  const { data, error, loading, reload } = useResource(() => api.publicRoad(publicRoadId!), [publicRoadId, tick], !!publicRoadId);

  if (!publicRoadId) {
    return (
      <EmptyState title="Choose a road first">
        <button type="button" className="btn btn--primary" onClick={() => go("find")}>Find roads near me</button>
      </EmptyState>
    );
  }

  return (
    <div className="stack">
      <div><button type="button" className="btn btn--link" onClick={() => go("find")}>← Back to roads near me</button></div>
      <div className="page-head">
        <h1>{data?.road.name ?? "Road"}</h1>
        <p className="muted">
          Road work planned or happening here, why it is needed, who is doing it and where it stands.
          {data ? <> Dates are for the simulated demo date of <strong>{fmtDate(data.as_of.date)}</strong>.</> : null}
        </p>
      </div>

      {error ? (
        <Notice kind="bad" title="Could not load this road">
          <p>{error.message}</p>
          <div><button type="button" className="btn" onClick={reload}>Try again</button></div>
        </Notice>
      ) : null}
      {loading && !data ? <p className="loading">Loading…</p> : null}

      {data && data.notices.length ? (
        <Notice kind="info" title="What is happening now">
          <ul>{data.notices.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </Notice>
      ) : null}

      {data && data.projects.length === 0 ? (
        <EmptyState title="No road work is registered here">Nothing is planned or in progress on {data.road.name} right now.</EmptyState>
      ) : null}

      {data && data.projects.length ? (
        <div className="grid-2">{data.projects.map((p) => <ProjectCard key={p.id} data={publicCard(p)} />)}</div>
      ) : null}

      <div className="card">
        <h3>Something wrong on this road?</h3>
        <div>
          <button type="button" className="btn" onClick={() => { reportPrefill.roadId = publicRoadId; go("report"); }}>Report a problem here</button>
        </div>
      </div>

      <p className="footer-note">{data?.footer ?? "Checks known registered work; cannot physically prevent unregistered excavation."}</p>
    </div>
  );
}
