import type { CaseStatus } from "../types";

type StepState = "done" | "current" | "todo" | "blocked";

// Pure display mapping of the server's status onto three labelled steps.
function states(status: CaseStatus): { steps: [StepState, StepState, StepState]; notes: [string, string, string] } {
  switch (status) {
    case "CONTRACTOR_REVIEW": return { steps: ["current", "todo", "todo"], notes: ["In progress", "Not started", "Not started"] };
    case "DEPARTMENT_REVIEW": return { steps: ["done", "current", "todo"], notes: ["Done", "In progress", "Not started"] };
    case "APPROVED": return { steps: ["done", "done", "current"], notes: ["Done", "Done", "Plan agreed; start checks still required"] };
    case "COMPLETED": return { steps: ["done", "done", "done"], notes: ["Done", "Done", "Finished and checked"] };
    case "BLOCKED": return { steps: ["blocked", "blocked", "blocked"], notes: ["Needs review", "Paused", "Paused"] };
    default: return { steps: ["todo", "todo", "todo"], notes: ["Not started", "Not started", "Not started"] };
  }
}

const ICON = { done: "✓", current: "→", todo: "○", blocked: "⚠" } as const;

export function Stepper({ status }: { status: CaseStatus }) {
  const { steps, notes } = states(status);
  const names = ["Contractors", "Departments", "Ready for work"];
  return (
    <ol className="stepper" aria-label="Progress">
      {names.map((n, i) => (
        <li key={n} data-state={steps[i]} aria-current={steps[i] === "current" ? "step" : undefined}>
          <span className="stepper__name"><span aria-hidden="true">{ICON[steps[i]]} </span>{n}</span>
          <span className="stepper__state">{notes[i]}</span>
        </li>
      ))}
    </ol>
  );
}
