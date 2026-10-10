from datetime import date

import scheduler as s
from scheduler import Job

D = date


def job(i, kind, es, dl, dur):
    return Job(i, kind, es, dl, dur, i)


def test_market_plan_matches_expected_dates():
    jobs = [job("water-1", "UTILITY", D(2026, 11, 8), D(2026, 11, 20), 5),
            job("telecom-1", "UTILITY", D(2026, 11, 13), D(2026, 11, 22), 4),
            job("surface-1", "RESURFACING", D(2026, 11, 10), D(2026, 11, 24), 4)]
    r = s.assess(jobs, D(2026, 11, 8))
    assert r["outcome"] == s.PLAN_FOUND
    got = [(i["project_id"], i["start"], i["end"]) for i in r["schedule"]]
    assert got == [("water-1", D(2026, 11, 8), D(2026, 11, 12)),
                   ("telecom-1", D(2026, 11, 14), D(2026, 11, 17)),
                   ("surface-1", D(2026, 11, 21), D(2026, 11, 24))]


def test_temple_has_no_sequential_plan_and_explains():
    jobs = [job("power-1", "UTILITY", D(2026, 11, 30), D(2026, 12, 31), 5),
            job("surface-2", "RESURFACING", D(2026, 11, 12), D(2026, 11, 20), 3)]
    r = s.assess(jobs, D(2026, 11, 8))
    assert r["outcome"] == s.NO_SEQUENTIAL_PLAN
    assert r["violations"][0]["project_id"] == "surface-2"
    assert "global" not in " ".join(r["messages"]).lower()


def test_inclusive_end_and_buffers():
    assert s.end_date(D(2026, 11, 8), 1) == D(2026, 11, 8)
    assert s.end_date(D(2026, 11, 8), 5) == D(2026, 11, 12)


def test_best_ordering_chosen_for_earliest_completion_with_stable_ties():
    a = job("a", "UTILITY", D(2026, 11, 8), D(2026, 12, 30), 3)
    b = job("b", "UTILITY", D(2026, 11, 8), D(2026, 12, 30), 3)
    r = s.assess([b, a], D(2026, 11, 8))
    assert [i["project_id"] for i in r["schedule"]] == ["a", "b"]
    # the ordering that satisfies the tighter deadline wins even if ids sort the other way
    a = job("a", "UTILITY", D(2026, 11, 8), D(2026, 12, 30), 3)
    b = job("b", "UTILITY", D(2026, 11, 8), D(2026, 11, 10), 3)
    r = s.assess([a, b], D(2026, 11, 8))
    assert [i["project_id"] for i in r["schedule"]] == ["b", "a"]


def test_utilities_only_minimises_last_finish():
    jobs = [job("u1", "UTILITY", D(2026, 11, 8), D(2026, 12, 31), 2), job("u2", "UTILITY", D(2026, 11, 20), D(2026, 12, 31), 2)]
    r = s.assess(jobs, D(2026, 11, 8))
    assert r["outcome"] == s.PLAN_FOUND
    assert r["schedule"][-1]["end"] == D(2026, 11, 21)


def test_surface_without_utilities_uses_its_earliest_start():
    r = s.assess([job("s", "RESURFACING", D(2026, 11, 10), D(2026, 11, 20), 3)], D(2026, 11, 8))
    assert r["schedule"][0]["start"] == D(2026, 11, 10)


def test_unknown_dates_make_assessment_unassessable():
    r = s.assess([Job("x", "UTILITY", None, D(2026, 12, 1), 3, "X")], D(2026, 11, 8))
    assert r["outcome"] == s.UNASSESSABLE
    assert r["violations"][0]["fields"] == ["earliest_start"]


def test_more_than_three_utilities_is_blocked_not_truncated():
    jobs = [job("u%d" % i, "UTILITY", D(2026, 11, 8), D(2027, 3, 1), 2) for i in range(4)]
    r = s.assess(jobs, D(2026, 11, 8))
    assert r["outcome"] == s.UNASSESSABLE
    assert "No project was left out" in " ".join(r["messages"])


def test_work_beyond_review_horizon_is_visible_but_excluded():
    jobs = [job("s", "RESURFACING", D(2026, 11, 10), D(2026, 11, 20), 3),
            job("far", "UTILITY", D(2027, 9, 1), D(2027, 12, 1), 3)]
    r = s.assess(jobs, D(2026, 11, 8))
    assert r["outcome"] == s.PLAN_FOUND
    assert [e["project_id"] for e in r["excluded"]] == ["far"]
    assert [i["project_id"] for i in r["schedule"]] == ["s"]


def test_started_work_is_included_regardless_of_age():
    jobs = [job("s", "RESURFACING", D(2026, 11, 10), D(2026, 11, 20), 3),
            job("far", "UTILITY", D(2027, 9, 1), D(2027, 12, 1), 3)]
    r = s.assess(jobs, D(2026, 11, 8), started_ids=["far"])
    assert not r["excluded"]


def test_recent_surfacing_protects_the_road():
    jobs = [job("u", "UTILITY", D(2026, 11, 8), D(2026, 12, 30), 3)]
    r = s.assess(jobs, D(2026, 11, 8), protected_until=D(2027, 3, 1))
    assert r["outcome"] == s.NO_SEQUENTIAL_PLAN
    assert r["violations"][0]["code"] == "PROTECTED_SURFACE"


def test_plan_never_starts_before_today():
    r = s.assess([job("u", "UTILITY", D(2026, 11, 1), D(2026, 12, 30), 3)], D(2026, 11, 8))
    assert r["schedule"][0]["start"] == D(2026, 11, 8)
