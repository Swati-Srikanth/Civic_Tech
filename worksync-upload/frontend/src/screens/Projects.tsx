import { useState, type FormEvent } from "react";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { Field } from "../components/Field";
import { LocationPicker } from "../components/LocationPicker";
import { ProjectHistoryPanel } from "../components/ProjectHistoryPanel";
import { ErrorNotice, Notice } from "../components/Notice";
import { SampleResults, SampleScenario } from "../components/SampleScenario";
import { ProjectCard, staffCard } from "../components/ProjectCard";
import { fmtDate } from "../format";
import { useAction, useResource } from "../hooks";
import { useApp } from "../state";
import type { Project, ProjectInput, ProjectKind, SampleComplaint, TeamMember } from "../types";

const NEW_PLACE = "__new__";

interface FormValues {
  title: string; purpose: string; road_id: string; kind: ProjectKind | ""; assigned_contractor_id: string;
  earliest_start: string; deadline: string; duration_days: string;
}

/** Screen B: department staff register and edit their own projects. */
export function Projects() {
  const { user, boot, roadId, tick, refresh, go } = useApp();
  const [mode, setMode] = useState<{ type: "list" } | { type: "new" } | { type: "edit"; project: Project }>({ type: "list" });
  const [saved, setSaved] = useState<{ message: string; caseId: string | null } | null>(null);
  const [sample, setSample] = useState<SampleComplaint[] | null>(null);
  const [state, setState] = useState("active");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [historyOpen, setHistoryOpen] = useState<string | null>(null);
  const overseer = user?.role === "ADMIN" || !!user?.is_head;
  const { data, error, loading, reload } = useResource(() => api.listProjects(undefined, { state: state === "all" ? undefined : state, q }), [user?.id, tick, state, q], !!user);
  const team = useResource(() => api.team(), [user?.id, tick], !!user && overseer);
  const people = team.data?.items ?? [];
  const canCreate = boot?.allowed_actions.includes("CREATE_PROJECT") ?? false;

  if (!user) return <Notice kind="info">Please sign in to continue.</Notice>;

  return (
    <div className="stack">
      <div className="row row--between">
        <div className="page-head">
          <h1>Projects</h1>
          <p className="muted">
            {user.role === "DEPARTMENT" ? `Projects owned by ${user.org_name ?? "your department"}.` :
              user.role === "CONTRACTOR" ? "Projects assigned to your organisation." : "All registered projects."}
          </p>
        </div>
        {canCreate && mode.type === "list" ? (
          <button type="button" className="btn btn--primary" onClick={() => { setSaved(null); setMode({ type: "new" }); }}>Add project</button>
        ) : null}
      </div>

      {boot?.allowed_actions.includes("CREATE_SCENARIO") && boot.roads.length === 0 && !sample ? <SampleScenario onCreated={setSample} /> : null}
      {sample ? <SampleResults items={sample} onDismiss={() => setSample(null)} /> : null}

      {saved ? (
        <Notice kind="ok" title="Saved">
          <p>{saved.message}</p>
          {saved.caseId ? <div><button type="button" className="btn" onClick={() => go("coordinate", { caseId: saved.caseId! })}>Open coordination case</button></div> : null}
        </Notice>
      ) : null}

      {mode.type !== "list" ? (
        <ProjectForm
          key={mode.type === "edit" ? mode.project.id : "new"}
          project={mode.type === "edit" ? mode.project : null}
          defaultRoad={roadId}
          onCancel={() => setMode({ type: "list" })}
          onSaved={(message, caseId) => { setSaved({ message, caseId }); setMode({ type: "list" }); refresh(); }}
        />
      ) : null}

      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); setQ(search); }} aria-label="Find projects">
        <Field label="Search" className="span-2">{(f) => <input type="text" {...f} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Title, purpose, street, certificate…" />}</Field>
        <Field label="Show">
          {(f) => (
            <select {...f} value={state} onChange={(e) => setState(e.target.value)}>
              <option value="active">Current (planned and in progress)</option>
              <option value="done">Completed</option>
              <option value="cancelled">Cancelled</option>
              <option value="all">Everything</option>
            </select>
          )}
        </Field>
        <div className="row" style={{ alignItems: "end" }}><button type="submit" className="btn">Search</button></div>
      </form>
      {error ? <ErrorNotice error={error} onRefresh={reload} /> : null}
      {loading && !data ? <p className="loading">Loading projects…</p> : null}
      {data && data.length === 0 ? (
        <EmptyState title={state === "active" && !q ? "No projects yet" : "No projects match"}>
          {canCreate ? "Use “Add project” to register planned road work at a place on the map." : "Nothing is assigned to you."}
        </EmptyState>
      ) : null}
      <div className="grid-2">
        {data?.map((p) => (
          <ProjectCard key={p.id} data={{ ...staffCard(p), extra: [
            { label: "Road", value: p.road_name ?? p.road_id },
            { label: "Window", value: `${fmtDate(p.earliest_start)} to ${fmtDate(p.deadline)}` },
            { label: "Duration", value: `${p.duration_days} day${p.duration_days === 1 ? "" : "s"}` },
            { label: "Led by", value: p.lead_name ?? "nobody yet" },
            ...(p.cancel_reason ? [{ label: "Why cancelled", value: p.cancel_reason }] : []),
          ] }}>
            <LeadControl project={p} people={people} onDone={() => { reload(); refresh(); }} />
            <div><button type="button" className="btn btn--link" aria-expanded={historyOpen === p.id} onClick={() => setHistoryOpen(historyOpen === p.id ? null : p.id)}>{historyOpen === p.id ? "Hide history" : "Show history"}</button></div>
            {historyOpen === p.id ? <ProjectHistoryPanel projectId={p.id} /> : null}
            <div className="row">
              {p.case_id ? <button type="button" className="btn" onClick={() => go("coordinate", { caseId: p.case_id! })}>Open coordination case</button> : null}
              {p.allowed_actions.includes("EDIT_PROJECT") ? (
                <button type="button" className="btn" onClick={() => { setSaved(null); setMode({ type: "edit", project: p }); window.scrollTo?.({ top: 0 }); }}>Edit</button>
              ) : null}
              {p.allowed_actions.includes("CANCEL_PROJECT") ? <CancelControl project={p} onDone={(m) => { setSaved({ message: m, caseId: null }); refresh(); }} /> : null}
            </div>
          </ProjectCard>
        ))}
      </div>
    </div>
  );
}

function CancelControl({ project, onDone }: { project: Project; onDone: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const act = useAction((r: string) => api.cancelProject(project.id, project.version, r), (r) => onDone(r.message));
  if (!open) return <button type="button" className="btn btn--danger" onClick={() => setOpen(true)}>Cancel project</button>;
  return (
    <form className="stack-sm" style={{ width: "100%" }} onSubmit={(e) => { e.preventDefault(); void act.run(reason); }}>
      <Field label="Reason for cancelling" error={act.error?.fieldMessage("reason")} help="Only work that has not started can be cancelled.">
        {(p) => <textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}
      </Field>
      {act.error ? <ErrorNotice error={act.error} fieldsShownInline /> : null}
      <div className="row">
        <button type="submit" className="btn btn--danger" disabled={act.busy || !reason.trim()}>{act.busy ? "Cancelling…" : "Confirm cancellation"}</button>
        <button type="button" className="btn" onClick={() => setOpen(false)}>Keep project</button>
      </div>
    </form>
  );
}

function ProjectForm({ project, defaultRoad, onCancel, onSaved }: {
  project: Project | null; defaultRoad: string; onCancel: () => void; onSaved: (message: string, caseId: string | null) => void;
}) {
  const { boot, user } = useApp();
  const [v, setV] = useState<FormValues>(() => project ? {
    title: project.title, purpose: project.purpose, road_id: project.road_id, kind: project.kind,
    assigned_contractor_id: project.assigned_contractor_id, earliest_start: project.earliest_start, deadline: project.deadline,
    duration_days: String(project.duration_days),
  } : {
    title: "", purpose: "", road_id: defaultRoad, kind: user?.project_kind ?? "", assigned_contractor_id: "",
    earliest_start: "", deadline: "", duration_days: "",
  });
  const [local, setLocal] = useState<Record<string, string>>({});
  const [placeName, setPlaceName] = useState("");
  const [pin, setPin] = useState<{ lat: number; lng: number } | null>(null);
  const set = <K extends keyof FormValues>(k: K, val: FormValues[K]) => setV((x) => ({ ...x, [k]: val }));

  const action = useAction(async () => {
    if (!project) {
      let roadId = v.road_id;
      if (roadId === NEW_PLACE) {
        // Streets are registered where the work is: find-or-create, so the same street is never duplicated.
        const road = await api.createRoad(placeName.trim(), pin!.lat, pin!.lng);
        roadId = road.id;
      }
      const input: ProjectInput = { ...v, road_id: roadId, kind: v.kind as ProjectKind, duration_days: Number(v.duration_days) };
      return api.createProject(input);
    }
    const changes: Partial<ProjectInput> = {};
    if (v.title !== project.title) changes.title = v.title;
    if (v.purpose !== project.purpose) changes.purpose = v.purpose;
    if (v.assigned_contractor_id !== project.assigned_contractor_id) changes.assigned_contractor_id = v.assigned_contractor_id;
    if (v.earliest_start !== project.earliest_start) changes.earliest_start = v.earliest_start;
    if (v.deadline !== project.deadline) changes.deadline = v.deadline;
    if (Number(v.duration_days) !== project.duration_days) changes.duration_days = Number(v.duration_days);
    return api.patchProject(project.id, project.version, changes);
  }, (r) => onSaved(r.message, (r.case_id as string | null | undefined) ?? project?.case_id ?? null));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const missing: Record<string, string> = {};
    (["title", "purpose", "road_id", "kind", "assigned_contractor_id", "earliest_start", "deadline", "duration_days"] as const).forEach((k) => {
      if (!String(v[k]).trim()) missing[k] = "This is required.";
    });
    if (!project && v.road_id === NEW_PLACE) {
      if (placeName.trim().length < 2) missing.place_name = "Give the street or place a name.";
      if (!pin) missing.pin = "Choose the place on the map.";
    }
    setLocal(missing);
    if (Object.keys(missing).length) return;
    void action.run();
  };
  const err = (field: string): string | undefined => local[field] ?? action.error?.fieldMessage(field);
  const needsFreshConsent = !!project && !!project.case_status && project.case_status !== "DRAFT";

  return (
    <form className="card stack" onSubmit={submit} noValidate aria-label={project ? "Edit project" : "Add project"}>
      <h2>{project ? "Edit project" : "Add project"}</h2>
      {needsFreshConsent ? <Notice kind="warn"><p>Changing this plan will require fresh responses and approvals.</p></Notice> : null}
      <div className="form-grid">
        <Field label="Title" error={err("title")} className="span-2">{(p) => <input type="text" {...p} value={v.title} onChange={(e) => set("title", e.target.value)} />}</Field>
        <Field label="Purpose" help="Why this work is needed." error={err("purpose")} className="span-2">{(p) => <textarea {...p} value={v.purpose} onChange={(e) => set("purpose", e.target.value)} />}</Field>
        <Field label="Where is the work?" error={err("road_id")} help={project ? "The place cannot be changed after registering." : undefined}>
          {(p) => (
            <select {...p} value={v.road_id} disabled={!!project} onChange={(e) => set("road_id", e.target.value)}>
              <option value="">Choose a place</option>
              {boot?.roads.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              {!project ? <option value={NEW_PLACE}>A new place on the map…</option> : null}
            </select>
          )}
        </Field>
        <Field label="Type of work" error={err("kind")} help={user?.project_kind ? "Your department registers this type." : undefined}>
          {(p) => (
            <select {...p} value={v.kind} disabled={!!project || !!user?.project_kind} onChange={(e) => set("kind", e.target.value as ProjectKind)}>
              <option value="">Choose a type</option>
              <option value="UTILITY">Utility work</option>
              <option value="RESURFACING">Final resurfacing</option>
            </select>
          )}
        </Field>
        <Field label="Assigned contractor" error={err("assigned_contractor_id")}>
          {(p) => (
            <select {...p} value={v.assigned_contractor_id} onChange={(e) => set("assigned_contractor_id", e.target.value)}>
              <option value="">Choose a contractor</option>
              {boot?.contractors.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
        </Field>
        <Field label="Owner department" help="Filled from the selected demo user.">
          {(p) => <input type="text" {...p} value={user?.org_name ?? ""} readOnly />}
        </Field>
        <Field label="Earliest start" help="The first day work could begin." error={err("earliest_start")}>
          {(p) => <input type="date" {...p} value={v.earliest_start} onChange={(e) => set("earliest_start", e.target.value)} />}
        </Field>
        <Field label="Finish deadline" help="Work must be finished by this day." error={err("deadline")}>
          {(p) => <input type="date" {...p} value={v.deadline} onChange={(e) => set("deadline", e.target.value)} />}
        </Field>
        <Field label="Duration (days)" help="Include testing and reinstatement for utility work." error={err("duration_days")}>
          {(p) => <input type="number" min={1} {...p} value={v.duration_days} onChange={(e) => set("duration_days", e.target.value)} />}
        </Field>
      </div>
      {!project && v.road_id === NEW_PLACE ? (
        <div className="stack-sm card">
          <h3>Register the place</h3>
          <Field label="Street or place name" error={err("place_name")} help="If a street with this name is already registered within 150 m, it is reused.">
            {(p) => <input type="text" {...p} value={placeName} onChange={(e) => setPlaceName(e.target.value)} maxLength={80} />}
          </Field>
          <LocationPicker value={pin} onChange={(lat, lng) => setPin({ lat, lng })} auto mapLabel="Map: click to place the pin where the work will happen" />
          {err("pin") ? <div className="field__error">{err("pin")}</div> : null}
        </div>
      ) : null}
      {action.error ? <ErrorNotice error={action.error} fieldsShownInline={action.error.failures.every((f) => !!f.field)} /> : null}
      <div className="row">
        <button type="submit" className="btn btn--primary" disabled={action.busy}>{action.busy ? "Saving…" : project ? "Save changes" : "Register project"}</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}



/** Who leads a project. A head (or the coordinator) can give it to anyone in the department; staff can take it themselves. */
function LeadControl({ project: p, people, onDone }: { project: Project; people: TeamMember[]; onDone: () => void }) {
  const { user } = useApp();
  const [who, setWho] = useState("");
  const [flash, setFlash] = useState<string | null>(null);
  const act = useAction((target: string | null) => api.assignProjectStaff(p.id, p.version, target), (r) => { setFlash(r.message); setWho(""); onDone(); });
  if (!user || p.execution_status === "DONE" || p.execution_status === "CANCELLED") return null;
  const overseer = user.role === "ADMIN" || !!user.is_head;
  const mine = user.role === "DEPARTMENT" && p.owner_org_id === user.org_id;
  if (!mine && user.role !== "ADMIN") return null;
  const candidates = people.filter((m) => m.department_id === p.owner_org_id);
  return (
    <div className="stack-sm">
      <div className="row" style={{ alignItems: "end" }}>
        {mine && p.lead_user_id !== user.id ? <button type="button" className="btn" disabled={act.busy} onClick={() => void act.run(user.id)}>Lead this project myself</button> : null}
        {overseer && candidates.length ? (
          <>
            <Field label="Who leads it">
              {(f) => (
                <select {...f} value={who} onChange={(e) => setWho(e.target.value)}>
                  <option value="">Choose someone</option>
                  {candidates.map((m) => <option key={m.id} value={m.id}>{m.name}{m.is_head ? " (head)" : ""} · {m.active_projects} project{m.active_projects === 1 ? "" : "s"}</option>)}
                </select>
              )}
            </Field>
            <button type="button" className="btn" disabled={act.busy || !who} onClick={() => void act.run(who)}>Assign</button>
          </>
        ) : null}
      </div>
      {flash ? <Notice kind="ok"><p>{flash}</p></Notice> : null}
      {act.error ? <ErrorNotice error={act.error} onRefresh={onDone} /> : null}
    </div>
  );
}
