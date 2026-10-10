import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class Api:
    """Tiny helper around TestClient that sends identity + idempotency headers."""

    def __init__(self, client):
        self.c = client
        self.n = 0
        self.tokens = {}

    def token(self, user):
        """Sign in for real (username + password check) and cache the session token. 'u-nobody' gets a bad token."""
        if user not in self.tokens:
            import seed
            if user not in seed.CREDENTIALS:
                return "not-a-real-token"
            username, password = seed.CREDENTIALS[user]
            r = self.c.post("/api/v1/auth/login", json={"username": username, "password": password})
            assert r.status_code == 200, r.text
            self.tokens[user] = r.json()["token"]
        return self.tokens[user]

    def headers(self, user=None, key=None, write=False):
        h = {}
        if user:
            h["Authorization"] = "Bearer " + self.token(user)
        if write:
            self.n += 1
            h["Idempotency-Key"] = key or "key-%d" % self.n
        return h

    def req(self, method, path, user=None, json=None, key=None, params=None):
        headers = self.headers(user, key, write=method in ("POST", "PATCH"))
        return self.c.request(method, "/api/v1" + path, json=json, headers=headers, params=params)

    def get(self, path, user=None, **kw):
        return self.req("GET", path, user, **kw)

    def post(self, path, user, json, key=None):
        return self.req("POST", path, user, json, key)

    def patch(self, path, user, json, key=None):
        return self.req("PATCH", path, user, json, key)

    # ---- convenience over the real endpoints
    def case(self, case_id="case-market", user="u-admin"):
        r = self.get("/cases/" + case_id, user)
        assert r.status_code == 200, r.text
        return r.json()

    def project(self, pid, user="u-admin"):
        road = {"water-1": "road-market", "telecom-1": "road-market", "surface-1": "road-market"}.get(pid)
        items = self.get("/projects", user, params={"road_id": road} if road else None).json()["items"]
        return next(p for p in items if p["id"] == pid)

    def respond(self, user, project_id, decision="ACCEPT", case_id="case-market", **extra):
        c = self.case(case_id)
        body = {"expected_version": c["version"], "plan_version": c["plan_version"], "project_id": project_id,
                "decision": decision}
        body.update(extra)
        return self.post("/cases/%s/responses" % case_id, user, body)

    def approve(self, user, decision="APPROVE", case_id="case-market", **extra):
        c = self.case(case_id)
        body = {"expected_version": c["version"], "plan_version": c["plan_version"], "decision": decision}
        body.update(extra)
        return self.post("/cases/%s/approvals" % case_id, user, body)

    def advance(self, days):
        clk = self.get("/bootstrap").json()["clock"]
        r = self.post("/demo/clock/advance", "u-admin", {"expected_version": clk["version"], "days": days})
        assert r.status_code == 200, r.text
        return r.json()

    def start(self, user, pid):
        p = self.project(pid)
        return self.post("/projects/%s/start" % pid, user, {"expected_version": p["version"], "plan_version": p["plan_version"]})

    def finish(self, user, pid, **extra):
        p = self.project(pid)
        body = {"expected_version": p["version"], "testing_complete": True, "reinstatement_complete": True}
        body.update(extra)
        return self.post("/projects/%s/finish" % pid, user, body)

    def inspect(self, user, pid, kind="UTILITY_RELEASE", result="PASS", notes="Checked on site"):
        p = self.project(pid)
        return self.post("/projects/%s/inspections" % pid, user,
                         {"expected_version": p["version"], "kind": kind, "result": result, "notes": notes})

    def declare(self, user, road_id="road-market", mode="NO_PLANNED_WORK", valid_until="2027-02-28", through="2027-06-30"):
        road = next(r for r in self.get("/bootstrap").json()["roads"] if r["id"] == road_id)
        return self.post("/roads/%s/declarations" % road_id, user,
                         {"expected_version": road["version"], "mode": mode, "covers_from": "2026-11-01",
                          "covers_through": through, "valid_until": valid_until})

    def approve_market(self):
        for pid, user in (("water-1", "u-aqua"), ("telecom-1", "u-link"), ("surface-1", "u-pave")):
            r = self.respond(user, pid)
            assert r.status_code == 200, r.text
        for user in ("u-water", "u-telecom", "u-roads"):
            r = self.approve(user)
            assert r.status_code == 200, r.text
        assert self.case()["status"] == "APPROVED"


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("WORKSYNC_DB", path)
    monkeypatch.setenv("WORKSYNC_PBKDF2_ROUNDS", "1000")      # fast hashing for tests only
    import seed
    seed.seed_database(path, reset=True, scenario=seed.TEST_CENTRE)
    return path


@pytest.fixture()
def api(db_path):
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        yield Api(client)
