import type { CaseDetail } from "../types";
import { KIND_TEXT } from "../format";
import { DateLabel } from "./DateLabel";
import { ExecBadge, InspectionBadge } from "./StatusBadge";

/** Table on desktop, stacked cards on mobile (switched in CSS). Dates come straight from the plan. */
export function ScheduleList({ schedule }: { schedule: CaseDetail["schedule"] }) {
  return (
    <div>
      <table className="schedule-table">
        <caption className="sr-only">Proposed or confirmed schedule</caption>
        <thead>
          <tr><th scope="col">Work</th><th scope="col">Department</th><th scope="col">Contractor</th><th scope="col">Dates</th><th scope="col">Progress</th></tr>
        </thead>
        <tbody>
          {schedule.map((s) => (
            <tr key={s.project_id}>
              <th scope="row"><div>{s.title}</div><div className="muted small">{KIND_TEXT[s.kind]}</div></th>
              <td>{s.owner_org_name ?? "—"}</td>
              <td>{s.contractor_name ?? "—"}</td>
              <td><DateLabel kind={s.date_label} start={s.start} end={s.end} /></td>
              <td>
                <div className="stack-sm">
                  {s.execution_status ? <ExecBadge status={s.execution_status} /> : null}
                  {s.execution_status === "DONE" && s.inspection_status ? <InspectionBadge status={s.inspection_status} /> : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="schedule-cards">
        {schedule.map((s) => (
          <li key={s.project_id} className="card">
            <strong>{s.title}</strong>
            <span className="muted small">{KIND_TEXT[s.kind]} · {s.owner_org_name ?? "—"} · {s.contractor_name ?? "—"}</span>
            <DateLabel kind={s.date_label} start={s.start} end={s.end} />
            <div className="row">
              {s.execution_status ? <ExecBadge status={s.execution_status} /> : null}
              {s.execution_status === "DONE" && s.inspection_status ? <InspectionBadge status={s.inspection_status} /> : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
