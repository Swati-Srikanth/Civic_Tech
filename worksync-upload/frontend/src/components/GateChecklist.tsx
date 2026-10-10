import type { ApiRequestError } from "../api";
import type { Blocker, Gate, Project } from "../types";
import { Notice } from "./Notice";

// Display grouping only: which checklist line a server blocker is shown under.
// Eligibility itself always comes from gate.eligible.
const GROUPS: { id: string; label: string; codes: string[]; kinds: ("UTILITY" | "RESURFACING")[] }[] = [
  { id: "plan", label: "Approved plan", kinds: ["UTILITY", "RESURFACING"],
    codes: ["PLAN_NOT_APPROVED", "CONSENT_INCOMPLETE", "PLAN_OUTDATED", "NEW_RELEVANT_PROJECT", "CASE_ON_HOLD", "PLAN_MISSING", "NOT_IN_PLAN"] },
  { id: "utilities", label: "Utility work complete", kinds: ["UTILITY", "RESURFACING"],
    codes: ["UTILITY_NOT_COMPLETE", "UTILITY_DECLARATIONS_MISSING", "PRIOR_UTILITY_NOT_DONE", "SEPARATION_TOO_SHORT"] },
  { id: "inspection", label: "Release inspection", kinds: ["RESURFACING"],
    codes: ["INSPECTION_MISSING", "INSPECTION_FAILED", "INSPECTION_TOO_EARLY"] },
  { id: "declarations", label: "Utility declarations", kinds: ["RESURFACING"],
    codes: ["COVERAGE_MISSING", "COVERAGE_STALE", "COVERAGE_EXPIRED", "COVERAGE_SHORT", "COVERAGE_CONTRADICTED"] },
  { id: "date", label: "Date readiness", kinds: ["UTILITY", "RESURFACING"],
    codes: ["NO_APPROVED_DATE", "DATE_NOT_APPROVED_START", "APPROVED_START_PASSED", "SURFACE_SEPARATION", "INSPECTION_SAME_DAY", "PROTECTED_SURFACE"] },
];

export function GateChecklist({ gate, loading, error, project, orgNames }: {
  gate: Gate | null; loading: boolean; error: ApiRequestError | null; project: Project; orgNames: Record<string, string>;
}) {
  if (loading && !gate) return <p className="loading">Checking start conditions…</p>;
  if (error) return <Notice kind="bad" title="Could not load the start checks"><p>{error.message}</p></Notice>;
  if (!gate) return null;
  const rows = GROUPS.filter((g) => g.kinds.includes(project.kind));
  const known = new Set(rows.flatMap((r) => r.codes));
  const other = gate.blockers.filter((b) => !known.has(b.code));
  const byGroup = (codes: string[]): Blocker[] => gate.blockers.filter((b) => codes.includes(b.code));
  // Without agreed dates, "earlier utility work" cannot be checked yet: say so instead of showing a tick.
  const noDates = gate.blockers.some((b) => b.code === "NO_APPROVED_DATE");
  return (
    <div className="stack-sm">
      <h4 style={{ margin: 0 }}>Start checks</h4>
      <ul className="checklist">
        {rows.map((r) => {
          const bl = byGroup(r.codes);
          const unchecked = project.kind === "UTILITY" && r.id === "utilities" && bl.length === 0 && noDates;
          const ok = bl.length === 0 && !unchecked;
          const label = project.kind === "UTILITY" && r.id === "utilities" ? "Earlier utility work complete" : r.label;
          return (
            <li key={r.id}>
              <span className={`checklist__mark ${ok ? "checklist__ok" : unchecked ? "checklist__next" : "checklist__bad"}`} aria-hidden="true">{ok ? "✓" : unchecked ? "–" : "✕"}</span>
              <div>
                <div className="checklist__label">{label}: {ok ? "met" : unchecked ? "not checked until there is an agreed plan" : "not met"}</div>
                {bl.length ? (
                  <ul className="checklist__why">
                    {bl.map((b, i) => (
                      <li key={i}>
                        {b.message}
                        {b.responsible_org_id ? <span className="checklist__next"> Responsible: {orgNames[b.responsible_org_id] ?? b.responsible_org_id}.</span> : null}
                        {b.next_action ? <span className="checklist__next"> Next: {b.next_action}</span> : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </li>
          );
        })}
        {other.length ? (
          <li>
            <span className="checklist__mark checklist__bad" aria-hidden="true">✕</span>
            <div>
              <div className="checklist__label">Other</div>
              <ul className="checklist__why">{other.map((b, i) => <li key={i}>{b.message}</li>)}</ul>
            </div>
          </li>
        ) : null}
      </ul>
      {gate.eligible ? (
        <Notice kind="ok" title="No blockers found right now">
          <p>This is a check, not an authorisation. Starting re-checks everything on the server.</p>
        </Notice>
      ) : null}
    </div>
  );
}
