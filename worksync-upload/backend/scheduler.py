"""Pure date calculation for the sequential WorkSync demo policy.

No database access. All buffers and the 180-day windows are explicitly
*demo policy*, not statutory rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import permutations
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

UTILITY_GAP_DAYS = 2      # prior utility finish + 2 days before the next utility starts
SURFACE_GAP_DAYS = 4      # last utility finish + 4 days before surfacing starts
HORIZON_DAYS = 180        # review horizon after expected surface completion
PROTECTED_DAYS = 180      # no-cut restriction after a new surface
MAX_UTILITIES = 3
MAX_RESURFACING = 1

PLAN_FOUND = "PLAN_FOUND"
NO_SEQUENTIAL_PLAN = "NO_SEQUENTIAL_PLAN"
UNASSESSABLE = "UNASSESSABLE"


@dataclass(frozen=True)
class Job:
    id: str
    kind: str  # UTILITY | RESURFACING
    earliest_start: Optional[date]
    deadline: Optional[date]
    duration: Optional[int]
    title: str = ""


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def human(d: Optional[date]) -> str:
    """'8 Nov 2026': used in every message shown to people."""
    if d is None:
        return "an unknown date"
    return "%d %s %d" % (d.day, _MONTHS[d.month - 1], d.year)


def end_date(start: date, duration: int) -> date:
    """Inclusive end: end = start + duration - 1."""
    return start + timedelta(days=duration - 1)


def missing_fields(job: Job) -> List[str]:
    out = []
    if job.earliest_start is None:
        out.append("earliest_start")
    if job.deadline is None:
        out.append("deadline")
    if job.duration is None or job.duration < 1:
        out.append("duration_days")
    return out


def _label(job: Job) -> str:
    return job.title or job.id


def split_relevant(jobs: Sequence[Job], started_ids: Iterable[str] = ()) -> Tuple[List[Job], List[dict], Optional[date]]:
    """Relevance window: work due within 180 days after the expected surface
    completion (anchored on the resurfacing deadline), plus outstanding started
    work regardless of age. Everything else stays visible with a reason."""
    started = set(started_ids)
    surfaces = [j for j in jobs if j.kind == "RESURFACING"]
    if not surfaces:
        return list(jobs), [], None
    horizon_end = max(j.deadline for j in surfaces) + timedelta(days=HORIZON_DAYS)
    included, excluded = [], []
    for j in jobs:
        if j.kind == "RESURFACING" or j.id in started or j.earliest_start <= horizon_end:
            included.append(j)
        else:
            excluded.append({
                "project_id": j.id,
                "reason": "Earliest start %s is more than %d days after the surface is due, so it is "
                          "shown but not part of this plan." % (human(j.earliest_start), HORIZON_DAYS),
            })
    return included, excluded, horizon_end


def _run_order(order: Sequence[Job], surface: Optional[Job], not_before: date):
    """Earliest-start schedule for one utility ordering. Returns (items, violations, lateness)."""
    items, violations, lateness = [], [], 0
    prev_finish: Optional[date] = None
    for job in order:
        start = max(job.earliest_start, not_before)
        if prev_finish is not None:
            start = max(start, prev_finish + timedelta(days=UTILITY_GAP_DAYS))
        end = end_date(start, job.duration)
        items.append({"project_id": job.id, "start": start, "end": end})
        if end > job.deadline:
            late = (end - job.deadline).days
            lateness += late
            violations.append({
                "code": "DEADLINE_EXCEEDED", "project_id": job.id,
                "message": "%s would finish on %s, %d day(s) after its deadline of %s."
                           % (_label(job), human(end), late, human(job.deadline)),
            })
        prev_finish = end
    if surface is not None:
        start = max(surface.earliest_start, not_before)
        if prev_finish is not None:
            start = max(start, prev_finish + timedelta(days=SURFACE_GAP_DAYS))
        end = end_date(start, surface.duration)
        items.append({"project_id": surface.id, "start": start, "end": end})
        if end > surface.deadline:
            late = (end - surface.deadline).days
            lateness += late
            why = ""
            if prev_finish is not None:
                why = " (it cannot start until %d days after the last utility finish on %s)" % (
                    SURFACE_GAP_DAYS, human(prev_finish))
            violations.append({
                "code": "DEADLINE_EXCEEDED", "project_id": surface.id,
                "message": "%s would finish on %s, %d day(s) after its deadline of %s%s."
                           % (_label(surface), human(end), late, human(surface.deadline), why),
            })
    return items, violations, lateness


def assess(
    jobs: Sequence[Job],
    not_before: date,
    protected_until: Optional[date] = None,
    started_ids: Iterable[str] = (),
) -> Dict:
    """Assess one road's active scope.

    Returns {outcome, messages, violations, schedule, included_ids, excluded, horizon_end}.
    Never claims global impossibility: NO_SEQUENTIAL_PLAN only means that no
    sequential plan under this demo policy meets the stated constraints.
    """
    base = {"messages": [], "violations": [], "schedule": [], "included_ids": [],
            "excluded": [], "horizon_end": None}

    # Unknown relevant dates block assessment.
    problems = []
    for j in jobs:
        miss = missing_fields(j)
        if miss:
            problems.append({"code": "MISSING_FIELDS", "project_id": j.id,
                             "message": "%s is missing: %s." % (_label(j), ", ".join(miss)),
                             "fields": miss})
    if problems:
        return dict(base, outcome=UNASSESSABLE, violations=problems,
                    messages=["Planning cannot be assessed until the missing dates are provided."]
                             + [p["message"] for p in problems])
    if not jobs:
        return dict(base, outcome=UNASSESSABLE, messages=["There is no registered work to plan."])

    included, excluded, horizon_end = split_relevant(jobs, started_ids)
    base.update(excluded=excluded, horizon_end=horizon_end, included_ids=sorted(j.id for j in included))

    utilities = sorted((j for j in included if j.kind == "UTILITY"), key=lambda j: j.id)
    surfaces = sorted((j for j in included if j.kind == "RESURFACING"), key=lambda j: j.id)

    unsupported = []
    if len(utilities) > MAX_UTILITIES:
        unsupported.append("This demo plans at most %d utility projects together; %d are relevant on this road."
                           % (MAX_UTILITIES, len(utilities)))
    if len(surfaces) > MAX_RESURFACING:
        unsupported.append("This demo plans at most %d resurfacing project per road; %d are registered."
                           % (MAX_RESURFACING, len(surfaces)))
    if unsupported:
        return dict(base, outcome=UNASSESSABLE,
                    violations=[{"code": "UNSUPPORTED_SCOPE", "project_id": None, "message": m} for m in unsupported],
                    messages=unsupported + ["No project was left out to fit the limit; the case stays blocked."])

    surface = surfaces[0] if surfaces else None
    best = None            # (final_completion, order_ids, items)
    closest = None         # (lateness, items, violations)
    for order in permutations(utilities):
        items, violations, lateness = _run_order(order, surface, not_before)
        if not violations:
            final = items[-1]["end"]
            key = (final, tuple(i["project_id"] for i in items))
            if best is None or key < best[0]:
                best = (key, items)
        elif closest is None or lateness < closest[0]:
            closest = (lateness, items, violations)

    if best is None:
        _, _, violations = closest
        return dict(base, outcome=NO_SEQUENTIAL_PLAN, violations=violations,
                    messages=["No sequential plan under the demo policy meets every stated deadline."]
                             + [v["message"] for v in violations])

    items = best[1]
    if protected_until is not None:
        hits = [i for i in items
                if i["project_id"] in {u.id for u in utilities} and i["start"] <= protected_until]
        if hits:
            msgs = ["New surfacing finished recently; excavation is restricted until %s (demo policy, no waivers)."
                    % human(protected_until)]
            return dict(base, outcome=NO_SEQUENTIAL_PLAN,
                        violations=[{"code": "PROTECTED_SURFACE", "project_id": h["project_id"],
                                     "message": "Work planned from %s falls inside the protected period." % human(h["start"])}
                                    for h in hits],
                        messages=msgs)

    return dict(base, outcome=PLAN_FOUND, schedule=items,
                messages=[] if not excluded else ["%d project(s) are outside the review horizon." % len(excluded)])
