import { useState } from "react";
import { api } from "../api";
import { ActionPanel } from "../components/ActionPanel";
import { EmptyState } from "../components/EmptyState";
import { Field } from "../components/Field";
import { GateChecklist } from "../components/GateChecklist";
import { ErrorNotice, Notice } from "../components/Notice";
import { ProjectCard, staffCard } from "../components/ProjectCard";
import { InspectionBadge, StatusBadge } from "../components/StatusBadge";
import { addDays, DECLARATION_TEXT, fmtDate, fmtDateTime } from "../format";
import { useAction, useResource } from "../hooks";
import { useApp } from "../state";
import type { CaseDetail, DeclarationMode, Project } from "../types";

/** Screen D: starting, finishing, inspections, declarations, admin history and the simulated clock. */
export function WorkChecks() {
  const { user, roadId, tick, refresh } = useApp();
  const projects = useResource(() => api.listProjects(roadId), [roadId, user?.id, tick], !!user && !!roadId);
  const cases = useResource(() => api.listCases(roadId), [roadId, user?.id, tick], !!user && !!roadId);
  const activeId = (cases.data ?? []).find((c) => c.status !== "COMPLETED")?.id ?? (cases.data ?? [])[0]?.id ?? null;
  const detail = useResource(() => api.getCase(activeId!), [activeId, user?.id, tick], !!activeId);

  if (!user) return <Notice kind="info">Please sign in to continue.</Notice>;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Work and checks</h1>
        <p className="muted">Starting needs every check to pass at that moment. The server decides; this screen shows what it says.</p>
      </div>

      {user.role === "ADMIN" ? <ClockCard /> : null}
      {projects.error ? <ErrorNotice error={projects.error} onRefresh={projects.reload} /> : null}
      {projects.loading && !projects.data ? <p className="loading">Loading…</p> : null}
      {projects.data && projects.data.length === 0 ? (
        <EmptyState title="No projects for you on this road">Pick another road, or ask a department to register work.</EmptyState>
      ) : null}

      {detail.data && detail.data.status !== "COMPLETED" ? <DeclarationsPanel c={detail.data} onChanged={() => { detail.reload(); refresh(); }} /> : null}

      <div className="stack">
        {projects.data?.map((p) => <WorkProject key={p.id} project={p} onChanged={() => { projects.reload(); detail.reload(); refresh(); }} />)}
      </div>

      {user.role === "ADMIN" ? <BlockedCases /> : null}
    </div>
  );
}

function useOrgNames(): Record<string, string> {
  const { boot } = useApp();
  const names: Record<string, string> = { inspectorate: "Independent Inspectorate", admin: "WorkSync Administration" };
  boot?.contractors.forEach((c) => (names[c.id] = c.name));
  boot?.departments.forEach((d) => (names[d.id] = d.name));
  return names;
}

function WorkProject({ project: p, onChanged }: { project: Project; onChanged: () => void }) {
  const { tick } = useApp();
  const names = useOrgNames();
  const [open, setOpen] = useState<"finish" | "inspect" | "incident" | null>(null);
  const gate = useResource(() => api.gate(p.id), [p.id, p.version, tick], p.execution_status === "PLANNED" && !!p.case_id);
  const can = (a: string) => p.allowed_actions.includes(a as never);
  const start = useAction(() => api.start(p.id, p.version, p.plan_version ?? 0), () => { gate.reload(); onChanged(); });
  const [flash, setFlash] = useState<string | null>(null);
  const done = (message?: string) => { setOpen(null); if (message) setFlash(message); onChanged(); };

  return (
    <ProjectCard data={{ ...staffCard(p), extra: [{ label: "Road", value: p.road_name ?? p.road_id }] }} heading="h2">
      <div className="row">
        <InspectionBadge status={p.inspection_status} />
        {p.execution_status === "DONE" && p.inspection_status === "PENDING" ? <StatusBadge tone="info">Finished — waiting for inspection</StatusBadge> : null}
      </div>
      {p.execution_status === "PLANNED" ? <GateChecklist gate={gate.data} loading={gate.loading} error={gate.error} project={p} orgNames={names} /> : null}

      {start.result?.pcc_number ? (
        <Notice kind="ok" title="Surfacing started">
          <p>{start.result.message}</p>
          <div><span className="pcc">Certificate {start.result.pcc_number}</span></div>
        </Notice>
      ) : start.result ? <Notice kind="ok"><p>{start.result.message}</p></Notice> : null}
      {start.error ? <ErrorNotice error={start.error} onRefresh={() => { gate.reload(); onChanged(); }} /> : null}
      {flash ? <Notice kind="ok"><p>{flash}</p></Notice> : null}

      <div className="row">
        {can("START_PROJECT") ? (
          <button type="button" className="btn btn--primary" disabled={start.busy} onClick={() => void start.run()}>
            {start.busy ? "Checking and starting…" : "Authorise and start now"}
          </button>
        ) : null}
        {can("FINISH_PROJECT") ? <button type="button" className="btn btn--primary" aria-expanded={open === "finish"} onClick={() => setOpen(open === "finish" ? null : "finish")}>Report finished</button> : null}
        {can("INSPECT_PROJECT") ? (
          <button type="button" className="btn btn--primary" aria-expanded={open === "inspect"} onClick={() => setOpen(open === "inspect" ? null : "inspect")}>
            {p.kind === "UTILITY" ? "Record release inspection" : "Record final inspection"}
          </button>
        ) : null}
        {can("REPORT_INCIDENT") ? <button type="button" className="btn" aria-expanded={open === "incident"} onClick={() => setOpen(open === "incident" ? null : "incident")}>Report a site issue</button> : null}
      </div>

      {open === "finish" ? <FinishForm p={p} onDone={done} /> : null}
      {open === "inspect" ? <InspectForm p={p} onDone={done} /> : null}
      {open === "incident" ? <IncidentForm p={p} onDone={done} /> : null}
    </ProjectCard>
  );
}

function FinishForm({ p, onDone }: { p: Project; onDone: (message?: string) => void }) {
  const [testing, setTesting] = useState(false);
  const [reinst, setReinst] = useState(false);
  const [delay, setDelay] = useState("");
  const act = useAction(() => api.finish(p.id, {
    expected_version: p.version, ...(p.kind === "UTILITY" ? { testing_complete: testing, reinstatement_complete: reinst } : {}),
    ...(delay.trim() ? { delay_reason: delay.trim() } : {}),
  }), (r) => onDone(r.message));
  return (
    <ActionPanel title="Report finished" description="Record that the physical work is finished. It still needs an inspection before it counts as verified." error={act.error} success={act.result?.message} fieldsShownInline>
      <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run(); }}>
        {p.kind === "UTILITY" ? (
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field__label">Required for utility work</legend>
            <label className="check"><input type="checkbox" checked={testing} onChange={(e) => setTesting(e.target.checked)} /> <span>Testing is complete</span></label>
            {act.error?.fieldMessage("testing_complete") ? <div className="field__error">{act.error.fieldMessage("testing_complete")}</div> : null}
            <label className="check"><input type="checkbox" checked={reinst} onChange={(e) => setReinst(e.target.checked)} /> <span>Reinstatement is complete</span></label>
            {act.error?.fieldMessage("reinstatement_complete") ? <div className="field__error">{act.error.fieldMessage("reinstatement_complete")}</div> : null}
          </fieldset>
        ) : null}
        <Field label="Reason for delay (only if finished after the planned end)" error={act.error?.fieldMessage("delay_reason")}>
          {(f) => <textarea {...f} value={delay} onChange={(e) => setDelay(e.target.value)} />}
        </Field>
        <div><button type="submit" className="btn btn--primary" disabled={act.busy}>{act.busy ? "Saving…" : "Report finished"}</button></div>
      </form>
    </ActionPanel>
  );
}

function InspectForm({ p, onDone }: { p: Project; onDone: (message?: string) => void }) {
  const [result, setResult] = useState<"PASS" | "FAIL">("PASS");
  const [notes, setNotes] = useState("");
  const kind = p.kind === "UTILITY" ? "UTILITY_RELEASE" : "FINAL_SURFACE";
  const act = useAction(() => api.inspect(p.id, { expected_version: p.version, kind, result, notes }), (r) => onDone(r.message));
  return (
    <ActionPanel title={p.kind === "UTILITY" ? "Release inspection" : "Final inspection"} description="You cannot verify evidence that you submitted yourself." error={act.error} success={act.result?.message} fieldsShownInline>
      <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run(); }}>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label">Result</legend>
          <div className="seg">
            <label><input type="radio" name={`res-${p.id}`} checked={result === "PASS"} onChange={() => setResult("PASS")} /> Pass</label>
            <label><input type="radio" name={`res-${p.id}`} checked={result === "FAIL"} onChange={() => setResult("FAIL")} /> Fail</label>
          </div>
        </fieldset>
        <Field label="Short notes" error={act.error?.fieldMessage("notes") ?? act.error?.fieldMessage("kind")}>
          {(f) => <textarea {...f} value={notes} onChange={(e) => setNotes(e.target.value)} />}
        </Field>
        <div><button type="submit" className="btn btn--primary" disabled={act.busy || !notes.trim()}>{act.busy ? "Saving…" : "Save inspection"}</button></div>
      </form>
    </ActionPanel>
  );
}

function IncidentForm({ p, onDone }: { p: Project; onDone: (message?: string) => void }) {
  const [kind, setKind] = useState<"SITE_ISSUE" | "WORK_WITHOUT_CLEARANCE">("SITE_ISSUE");
  const [description, setDescription] = useState("");
  const [when, setWhen] = useState("");
  const act = useAction(() => api.incident(p.id, { expected_version: p.version, kind, description, ...(when ? { occurred_date: when } : {}) }), (r) => onDone(r.message));
  return (
    <ActionPanel title="Report a site issue" description="This records a claim and places a review hold. It never gives anyone permission after the fact." error={act.error} success={act.result?.message} fieldsShownInline>
      <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run(); }}>
        <Field label="What happened?">
          {(f) => (
            <select {...f} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="SITE_ISSUE">A problem at the site</option>
              <option value="WORK_WITHOUT_CLEARANCE">Work happened without clearance</option>
            </select>
          )}
        </Field>
        <Field label="Describe it" error={act.error?.fieldMessage("description")}>
          {(f) => <textarea {...f} value={description} onChange={(e) => setDescription(e.target.value)} />}
        </Field>
        <Field label="Date it happened (optional)">{(f) => <input type="date" {...f} value={when} onChange={(e) => setWhen(e.target.value)} />}</Field>
        <div><button type="submit" className="btn btn--primary" disabled={act.busy || !description.trim()}>{act.busy ? "Saving…" : "Send report"}</button></div>
      </form>
    </ActionPanel>
  );
}

function DeclarationsPanel({ c, onChanged }: { c: CaseDetail; onChanged: () => void }) {
  const { boot, roadId } = useApp();
  const clock = boot?.clock.date ?? "";
  const through = c.horizon_end ?? (clock ? addDays(clock, 180) : "");
  const [mode, setMode] = useState<DeclarationMode>("ALL_WORK_REGISTERED");
  const [from, setFrom] = useState(clock);
  const [to, setTo] = useState(through);
  const [until, setUntil] = useState(through);
  const roadVersion = boot?.roads.find((r) => r.id === roadId)?.version ?? 0;
  const act = useAction(() => api.declare(roadId, { expected_version: roadVersion, mode, covers_from: from, covers_through: to, valid_until: until }), () => onChanged());
  const canDeclare = c.allowed_actions.includes("DECLARE_WORKS");
  return (
    <ActionPanel
      title="Utility declarations"
      description="Before final resurfacing, every expected utility department must confirm all its planned work through the review period. A registered project alone is not enough."
      error={act.error} success={act.result?.message} fieldsShownInline={!!act.error?.failures.every((f) => !!f.field)}
    >
      <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {c.declarations.map((d) => (
          <li key={d.org_id} className="row row--between">
            <span>{d.org_name ?? d.org_id}{d.covers_through ? <span className="muted small"> · covers to {fmtDate(d.covers_through)}</span> : null}</span>
            <StatusBadge tone={d.status === "CURRENT" ? "ok" : "warn"}>{DECLARATION_TEXT[d.status] ?? d.status}</StatusBadge>
          </li>
        ))}
      </ul>
      {canDeclare ? (
        <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run(); }}>
          <h4 style={{ margin: 0 }}>Confirm your department's work</h4>
          <div className="form-grid">
            <Field label="What are you declaring?" className="span-2" error={act.error?.fieldMessage("mode")}>
              {(f) => (
                <select {...f} value={mode} onChange={(e) => setMode(e.target.value as DeclarationMode)}>
                  <option value="ALL_WORK_REGISTERED">All my planned work on this road is registered</option>
                  <option value="NO_PLANNED_WORK">I have no planned work on this road</option>
                </select>
              )}
            </Field>
            <Field label="Covers from" help="Prefilled from today's demo date." error={act.error?.fieldMessage("covers_from")}>{(f) => <input type="date" {...f} value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
            <Field label="Covers through" help="Prefilled from the plan's review period." error={act.error?.fieldMessage("covers_through")}>{(f) => <input type="date" {...f} value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
            <Field label="Valid until" error={act.error?.fieldMessage("valid_until")}>{(f) => <input type="date" {...f} value={until} onChange={(e) => setUntil(e.target.value)} />}</Field>
          </div>
          <div><button type="submit" className="btn btn--primary" disabled={act.busy}>{act.busy ? "Saving…" : "Submit declaration"}</button></div>
        </form>
      ) : null}
    </ActionPanel>
  );
}

function ClockCard() {
  const { boot, refresh } = useApp();
  const [days, setDays] = useState("1");
  const act = useAction(() => api.advanceClock(boot?.clock.version ?? 0, Number(days)), () => refresh());
  return (
    <ActionPanel
      title="Simulated time (demo only)"
      description="This moves a pretend calendar forward so you can see deadlines and dates. It does not grant approval and cannot go back."
      error={act.error} success={act.result?.message} fieldsShownInline
    >
      <form className="row" onSubmit={(e) => { e.preventDefault(); void act.run(); }} style={{ alignItems: "end" }}>
        <Field label="Days to move forward" error={act.error?.fieldMessage("days")}>{(f) => <input type="number" min={1} {...f} value={days} onChange={(e) => setDays(e.target.value)} />}</Field>
        <button type="submit" className="btn btn--primary" disabled={act.busy}>{act.busy ? "Moving…" : "Advance simulated time"}</button>
        <span className="muted">Now: <strong>{fmtDate(boot?.clock.date)}</strong></span>
      </form>
    </ActionPanel>
  );
}

function BlockedCases() {
  const { tick, setRoadId, go } = useApp();
  const { data, error, reload } = useResource(() => api.listCases(), [tick]);
  const blocked = (data ?? []).filter((c) => c.status === "BLOCKED" || c.hold);
  return (
    <section className="stack" aria-label="Blocked cases">
      <h2>Blocked cases</h2>
      {error ? <ErrorNotice error={error} onRefresh={reload} /> : null}
      {data && blocked.length === 0 ? <EmptyState title="Nothing is blocked right now" /> : null}
      {blocked.map((c) => (
        <div key={c.id} className="card card--hold">
          <div className="card__head">
            <div>
              <h3>{c.road_name ?? c.road_id}</h3>
              <div className="muted small">{c.id} · plan version {c.plan_version || "—"}</div>
            </div>
            <StatusBadge tone="warn">{c.hold ? `On hold: ${(c.hold_reason ?? "").toLowerCase().replace(/_/g, " ")}` : "Needs review"}</StatusBadge>
          </div>
          <div className="row">
            <button type="button" className="btn" onClick={() => { setRoadId(c.road_id); go("coordinate", { caseId: c.id }); }}>Review this case</button>
          </div>
          <History caseId={c.id} />
        </div>
      ))}
    </section>
  );
}

function History({ caseId }: { caseId: string }) {
  const [open, setOpen] = useState(false);
  const { tick } = useApp();
  const { data, error, loading } = useResource(() => api.audit(caseId), [caseId, tick], open);
  return (
    <details onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary style={{ cursor: "pointer", minHeight: 44, display: "flex", alignItems: "center" }}>Activity history</summary>
      {loading && !data ? <p className="loading">Loading…</p> : null}
      {error ? <ErrorNotice error={error} /> : null}
      <ul className="history">
        {data?.map((e) => (
          <li key={e.id}>
            <strong>{e.action.toLowerCase().replace(/_/g, " ")}</strong> · {e.actor_name} · <span className="muted small">{fmtDateTime(e.recorded_at)}</span>
            {e.reason ? <div className="small">“{e.reason}”</div> : null}
          </li>
        ))}
      </ul>
    </details>
  );
}
