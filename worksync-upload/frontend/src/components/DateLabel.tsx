import { fmtDate, fmtRange } from "../format";

export type DateKind = "PROPOSED" | "CONFIRMED" | "ACTUAL" | "VERIFIED";

const TAG: Record<DateKind, { tag: string; icon: string; note: string }> = {
  PROPOSED: { tag: "Proposed", icon: "◌", note: "not a promise" },
  CONFIRMED: { tag: "Confirmed", icon: "◉", note: "agreed by contractors and departments" },
  ACTUAL: { tag: "Actual", icon: "▶", note: "reported by the contractor" },
  VERIFIED: { tag: "Verified", icon: "✔", note: "checked by an inspector" },
};

/** Proposed, confirmed, actual and verified dates look and read differently on purpose. */
export function DateLabel({ kind, start, end, day }: { kind: DateKind; start?: string | null; end?: string | null; day?: string | null }) {
  const t = TAG[kind];
  const value = day !== undefined ? fmtDate(day) : fmtRange(start, end);
  return (
    <span className={`date-label date-label--${kind.toLowerCase()}`}>
      <span className="date-label__tag">
        <span aria-hidden="true">{t.icon} </span>
        {t.tag}
      </span>
      <strong>{value}</strong>
      <span className="date-label__note">({t.note})</span>
    </span>
  );
}
