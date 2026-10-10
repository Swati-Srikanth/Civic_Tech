import { useState } from "react";
import { api } from "../api";
import { ActionPanel } from "../components/ActionPanel";
import { EmptyState } from "../components/EmptyState";
import { Field } from "../components/Field";
import { ErrorNotice, Notice } from "../components/Notice";
import { ScheduleList } from "../components/ScheduleList";
import { CaseBadge, StatusBadge } from "../components/StatusBadge";
import { Stepper } from "../components/Stepper";
import { fmtDate, fmtDateTime } from "../format";
import { useAction, useResource } from "../hooks";
import { useApp } from "../state";
import type { CaseDetail } from "../types";

/** Screen C: contractor, department and admin actions on one coordination case. */
export function Coordinate() {
  const { user, roadId, tick, focusCaseId, refresh } = useApp();
  const [picked, setPicked] = useState<string | null>(null);
  const cases = useResource(() => api.listCases(roadId), [roadId, user?.id, tick], !!user && !!roadId);
  const list = cases.data ?? [];
  const caseId =
    (picked && list.some((c) => c.id === picked) ? picked : null) ??
    (focusCaseId && list.some((c) => c.id === focusCaseId) ? focusCaseId : null) ??
    list.find((c) => c.status !== "COMPLETED")?.id ?? list[0]?.id ?? null;
  const detail = useResource(() => api.getCase(caseId!), [caseId, user?.id, tick], !!caseId);

  if (!user) return <Notice kind="info">Please sign in to continue.</Notice>;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Coordinate work</h1>
        <p className="muted">One coordination case per road. Contractors respond first, then each department approves the exact plan.</p>
      </div>
      {cases.error ? <ErrorNotice error={cases.error} onRefresh={cases.reload} /> : null}
      {cases.loading && !cases.data ? <p className="loading">Loading…</p> : null}
      {cases.data && list.length === 0 ? (
        <EmptyState title="No coordination case you can see on this road">
          Either no work is registered here, or your organisation is not part of it.
        </EmptyState>
      ) : null}
      {list.length > 1 ? (
        <Field label="Coordination case">
          {(p) => (
            <select {...p} value={caseId ?? ""} onChange={(e) => setPicked(e.target.value)}>
              {list.map((c) => <option key={c.id} value={c.id}>{c.id} ({c.status.toLowerCase().replace("_", " ")})</option>)}
            </select>
          )}
        </Field>
      ) : null}
      {detail.error && !detail.data ? <ErrorNotice error={detail.error} onRefresh={detail.reload} /> : null}
      {detail.loading && !detail.data ? <p className="loading">Loading case…</p> : null}
      {detail.data ? <CaseView key={detail.data.id} c={detail.data} reload={() => { detail.reload(); refresh(); }} /> : null}
    </div>
  );
}

function CaseView({ c, reload: refetch }: { c: CaseDetail; reload: () => void }) {
  const { user } = useApp();
  // The panel that sent an action disappears once the server stops offering it, so confirmations live here.
  const [flash, setFlash] = useState<string | null>(null);
  const reload = (message?: string) => { if (typeof message === "string" && message) setFlash(message); refetch(); };
  const has = (a: string) => c.allowed_actions.includes(a as never);
  const responseByProject = new Map(c.responses.map((r) => [r.project_id, r]));
  const approvalByOrg = new Map(c.approvals.map((a) => [a.org_id, a]));
  const showPlan = c.schedule.length > 0;
  const amContractorPending = c.pending_responses.filter((p) => p.contractor_id === user?.org_id);

  return (
    <div className="stack">
      <section className="card" aria-label="Case summary">
        <div className="card__head">
          <div>
            <h2>{c.road_name}</h2>
            <div className="muted small">Plan version {c.plan_version || "—"}</div>
          </div>
          <CaseBadge status={c.status} />
        </div>
        {c.deadline_at ? (
          <p>
            <strong>Response due:</strong> {fmtDateTime(c.deadline_at)} <span className="muted small">(simulated clock; silence is never approval)</span>
          </p>
        ) : null}
        <Stepper status={c.status} />
        {c.status === "APPROVED" ? (
          <Notice kind="info"><p>The plan is agreed, but that is not clearance to start. Each start is checked again under “Work and checks”.</p></Notice>
        ) : null}
        {c.hold ? (
          <Notice kind="warn" title="On hold"><p>{c.public_reason ?? "New starts are blocked while this is reviewed."}</p></Notice>
        ) : null}
        {c.status === "BLOCKED" && !c.hold && c.public_reason ? <Notice kind="warn" title="Needs review"><p>{c.public_reason}</p></Notice> : null}
        {c.status === "COMPLETED" ? <Notice kind="ok"><p>Finished and checked on {fmtDate(c.completed_on)}.</p></Notice> : null}
      </section>

      {flash ? <Notice kind="info" title="Result"><p>{flash}</p></Notice> : null}

      {c.assessment.outcome && c.assessment.outcome !== "PLAN_FOUND" ? (
        <Notice kind="warn" title={c.assessment.outcome === "NO_SEQUENTIAL_PLAN" ? "No sequential plan fits every deadline" : "This case cannot be planned yet"}>
          <ul>{c.assessment.messages.map((m, i) => <li key={i}>{m}</li>)}</ul>
          <p className="small">Under this demo's rules only. This does not mean the work is impossible; a department can change the dates.</p>
        </Notice>
      ) : null}

      {showPlan ? (
        <section className="stack-sm" aria-label="Schedule">
          <h2>Schedule</h2>
          <ScheduleList schedule={c.schedule} />
          {c.excluded.length ? (
            <Notice kind="info" title="Shown but not part of this plan">
              <ul>{c.excluded.map((e) => <li key={e.project_id}>{c.projects.find((p) => p.id === e.project_id)?.title ?? e.project_id}: {e.reason}</li>)}</ul>
            </Notice>
          ) : null}
        </section>
      ) : c.status === "DRAFT" ? (
        <EmptyState title="The plan is being prepared">
          {has("GENERATE_PLAN") ? "Generate a plan to ask contractors for their response." : "A department will generate the plan."}
        </EmptyState>
      ) : null}

      {showPlan ? (
        <div className="grid-2">
          <section className="card" aria-label="Contractor responses">
            <h3>Contractors</h3>
            <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {c.schedule.map((s) => {
                const r = responseByProject.get(s.project_id);
                return (
                  <li key={s.project_id} className="row row--between">
                    <span>{s.contractor_name ?? s.contractor_id}<span className="muted small"> · {s.title}</span></span>
                    {r ? (
                      <StatusBadge tone={r.decision === "ACCEPT" ? "ok" : r.decision === "REJECT" ? "bad" : "warn"}>
                        {r.decision === "ACCEPT" ? "Accepted" : r.decision === "REJECT" ? "Cannot do these dates" : "Suggested a later start"}
                      </StatusBadge>
                    ) : <StatusBadge tone="neutral">Waiting</StatusBadge>}
                  </li>
                );
              })}
            </ul>
          </section>
          <section className="card" aria-label="Department approvals">
            <h3>Departments</h3>
            <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {c.required_departments.map((org) => {
                const a = approvalByOrg.get(org);
                const name = c.schedule.find((s) => s.owner_org_id === org)?.owner_org_name ?? org;
                return (
                  <li key={org} className="row row--between">
                    <span>{name}</span>
                    {a ? <StatusBadge tone={a.decision === "APPROVE" ? "ok" : "bad"}>{a.decision === "APPROVE" ? "Approved" : "Rejected"}</StatusBadge>
                      : <StatusBadge tone="neutral">{c.status === "CONTRACTOR_REVIEW" ? "Not asked yet" : "Waiting"}</StatusBadge>}
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      ) : null}

      {has("GENERATE_PLAN") ? <GeneratePanel c={c} reload={reload} /> : null}
      {has("RESPOND") ? amContractorPending.map((p) => <ResponsePanel key={`${p.project_id}-${c.plan_version}`} c={c} projectId={p.project_id} title={p.title} reload={reload} />) : null}
      {has("APPROVE_PLAN") ? <ApprovalPanel c={c} reload={reload} /> : null}
      {has("REVIEW_CASE") ? <ReviewPanel c={c} reload={reload} /> : null}
    </div>
  );
}

function GeneratePanel({ c, reload }: { c: CaseDetail; reload: (message?: string) => void }) {
  const act = useAction(() => api.generatePlan(c.id, c.version), (r) => reload(r.message));
  return (
    <ActionPanel title="Generate the plan" description="The server finds the earliest sequential dates that meet every deadline, or explains why it cannot." error={act.error} success={act.result?.message} onRefresh={() => reload()}>
      <div><button type="button" className="btn btn--primary" disabled={act.busy} onClick={() => void act.run()}>{act.busy ? "Generating…" : "Generate plan"}</button></div>
    </ActionPanel>
  );
}

function ResponsePanel({ c, projectId, title, reload }: { c: CaseDetail; projectId: string; title: string; reload: (message?: string) => void }) {
  const [choice, setChoice] = useState<"COUNTERPROPOSE" | "REJECT" | null>(null);
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const item = c.schedule.find((s) => s.project_id === projectId);
  const base = { expected_version: c.version, plan_version: c.plan_version, project_id: projectId };
  const act = useAction(
    (b: { decision: "ACCEPT" | "COUNTERPROPOSE" | "REJECT"; earliest_start?: string; reason?: string }) => api.respond(c.id, { ...base, ...b }),
    (r) => { setChoice(null); reload(r.message); },
  );
  return (
    <ActionPanel
      title={`Your response: ${title}`}
      description={item ? `Proposed ${fmtDate(item.start)} to ${fmtDate(item.end)}. This answer applies to plan version ${c.plan_version} only.` : undefined}
      error={act.error} success={act.result?.message} onRefresh={() => reload()} fieldsShownInline
    >
      <div className="row">
        <button type="button" className="btn btn--primary" disabled={act.busy} onClick={() => void act.run({ decision: "ACCEPT" })}>Accept these dates</button>
        <button type="button" className="btn" aria-expanded={choice === "COUNTERPROPOSE"} onClick={() => setChoice(choice === "COUNTERPROPOSE" ? null : "COUNTERPROPOSE")}>Suggest a later start</button>
        <button type="button" className="btn btn--danger" aria-expanded={choice === "REJECT"} onClick={() => setChoice(choice === "REJECT" ? null : "REJECT")}>Cannot do these dates</button>
      </div>
      {choice === "COUNTERPROPOSE" ? (
        <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run({ decision: "COUNTERPROPOSE", earliest_start: date }); }}>
          <Field label="Your new earliest start" help="Must be later than the current earliest start. The server will re-plan." error={act.error?.fieldMessage("earliest_start")}>
            {(p) => <input type="date" {...p} value={date} onChange={(e) => setDate(e.target.value)} />}
          </Field>
          <div><button type="submit" className="btn btn--primary" disabled={act.busy || !date}>Send suggestion</button></div>
        </form>
      ) : null}
      {choice === "REJECT" ? (
        <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run({ decision: "REJECT", reason }); }}>
          <Field label="Reason" help="Required. Everyone in the case can read it." error={act.error?.fieldMessage("reason")}>
            {(p) => <textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <div><button type="submit" className="btn btn--danger" disabled={act.busy || !reason.trim()}>Send: cannot do these dates</button></div>
        </form>
      ) : null}
    </ActionPanel>
  );
}

function ApprovalPanel({ c, reload }: { c: CaseDetail; reload: (message?: string) => void }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const act = useAction(
    (b: { decision: "APPROVE" | "REJECT"; reason?: string }) => api.approve(c.id, { expected_version: c.version, plan_version: c.plan_version, ...b }),
    (r) => { setRejecting(false); reload(r.message); },
  );
  return (
    <ActionPanel title="Your department's decision" description={`Approving covers all of your department's work in plan version ${c.plan_version}.`} error={act.error} success={act.result?.message} onRefresh={() => reload()} fieldsShownInline>
      <div className="row">
        <button type="button" className="btn btn--primary" disabled={act.busy} onClick={() => void act.run({ decision: "APPROVE" })}>Approve plan</button>
        <button type="button" className="btn btn--danger" aria-expanded={rejecting} onClick={() => setRejecting(!rejecting)}>Reject with reason</button>
      </div>
      {rejecting ? (
        <form className="stack-sm" onSubmit={(e) => { e.preventDefault(); void act.run({ decision: "REJECT", reason }); }}>
          <Field label="Reason for rejecting" error={act.error?.fieldMessage("reason")}>
            {(p) => <textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
          <div><button type="submit" className="btn btn--danger" disabled={act.busy || !reason.trim()}>Reject plan</button></div>
        </form>
      ) : null}
    </ActionPanel>
  );
}

function ReviewPanel({ c, reload }: { c: CaseDetail; reload: (message?: string) => void }) {
  const [reason, setReason] = useState("");
  const act = useAction(
    (action: "REQUEST_REVISION" | "KEEP_BLOCKED") => api.review(c.id, { expected_version: c.version, action, reason }),
    (r) => { setReason(""); reload(r.message); },
  );
  return (
    <ActionPanel title="Administrator review" description="You can ask for a revision or keep the case blocked. You cannot approve for anyone or override a rejection." error={act.error} success={act.result?.message} onRefresh={() => reload()} fieldsShownInline>
      <Field label="Reason (required)" error={act.error?.fieldMessage("reason")}>
        {(p) => <textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} />}
      </Field>
      <div className="row">
        <button type="button" className="btn btn--primary" disabled={act.busy || !reason.trim()} onClick={() => void act.run("REQUEST_REVISION")}>Request revision</button>
        <button type="button" className="btn" disabled={act.busy || !reason.trim()} onClick={() => void act.run("KEEP_BLOCKED")}>Keep blocked</button>
      </div>
    </ActionPanel>
  );
}
