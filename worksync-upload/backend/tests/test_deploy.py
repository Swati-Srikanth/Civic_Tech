"""Hosting: one address for the website and the API, the staff password and sample data set at deploy time,
and the clock and throttling behaving safely behind a proxy."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
import seed
from db import connect, one
from errors import ApiError


@pytest.fixture
def site(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('hi')")
    (tmp_path / "index.html").write_text("<!doctype html><title>WorkSync</title>")
    (tmp_path / "secret.txt").write_text("not for the web")
    app = FastAPI()
    app.add_exception_handler(ApiError, main.api_error_handler)
    main.mount_website(app, tmp_path / "assets" / "..")     # a path with ".." must still resolve to the site folder
    return TestClient(app), tmp_path


def test_every_page_address_gets_the_app_and_files_are_served(site):
    c, _ = site
    assert "<title>WorkSync</title>" in c.get("/").text
    assert "<title>WorkSync</title>" in c.get("/report").text            # a refreshed page deep link
    assert c.get("/report").headers["cache-control"] == "no-cache"
    assert c.get("/assets/app.js").text == "console.log('hi')"


def test_unknown_api_addresses_are_api_errors_not_the_web_page(site):
    c, _ = site
    r = c.get("/api/v1/nothing-here")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert c.get("/api").status_code == 404


def test_the_website_cannot_be_used_to_read_other_files(site):
    c, tmp = site
    (tmp.parent / "outside.txt").write_text("private")
    for path in ("/../outside.txt", "/%2e%2e/outside.txt", "/..%2foutside.txt", "/assets/../../outside.txt"):
        r = c.get(path)
        assert "private" not in r.text, path


def test_security_headers_are_sent(api):
    r = api.c.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def _seed(tmp_path, monkeypatch, **env):
    path = str(tmp_path / "hosted.db")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("WORKSYNC_DB", path)
    main.prepare_database()
    return path


def test_staff_password_can_be_set_at_deploy_time(tmp_path, monkeypatch):
    path = _seed(tmp_path, monkeypatch, WORKSYNC_STAFF_PASSWORD="Judge#Pass2026")
    with TestClient(main.app) as c:
        ok = c.post("/api/v1/auth/login", json={"username": "water.head", "password": "Judge#Pass2026"})
        assert ok.status_code == 200
        old = c.post("/api/v1/auth/login", json={"username": "water.head", "password": "WaterHead@26"})
        assert old.status_code == 401                                   # the published demo password is gone


def test_a_weak_deploy_password_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSYNC_STAFF_PASSWORD", "password")
    monkeypatch.setenv("WORKSYNC_DB", str(tmp_path / "weak.db"))
    with pytest.raises(SystemExit):
        main.prepare_database()


def test_demo_scenario_is_loaded_on_the_first_start_only(tmp_path, monkeypatch):
    path = _seed(tmp_path, monkeypatch, WORKSYNC_DEMO_SCENARIO="13.0617,80.2693")
    conn = connect(path)
    try:
        roads = one(conn, "SELECT COUNT(*) AS n FROM roads")["n"]
        complaints = one(conn, "SELECT COUNT(*) AS n FROM complaints")["n"]
    finally:
        conn.close()
    assert roads >= 3 and complaints >= 10
    main.prepare_database()                                              # a restart must not add the samples again
    conn = connect(path)
    try:
        assert one(conn, "SELECT COUNT(*) AS n FROM complaints")["n"] == complaints
    finally:
        conn.close()


def test_without_the_setting_a_new_install_is_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKSYNC_DEMO_SCENARIO", raising=False)
    path = _seed(tmp_path, monkeypatch)
    conn = connect(path)
    try:
        assert one(conn, "SELECT COUNT(*) AS n FROM roads")["n"] == 0
    finally:
        conn.close()


def _admin_clock_request(api, headers=None):
    token = api.token("u-admin")
    clock = api.c.get("/api/v1/bootstrap").json()["clock"]
    h = {"Authorization": "Bearer " + token, "Idempotency-Key": "clk-%s" % (headers or {}).get("tag", "x")}
    h.update({k: v for k, v in (headers or {}).items() if k != "tag"})
    return api.c.post("/api/v1/demo/clock/advance", headers=h, json={"expected_version": clock["version"], "days": 1})


def test_the_clock_is_open_locally_but_closed_behind_a_proxy(api, monkeypatch):
    monkeypatch.delenv("WORKSYNC_BEHIND_PROXY", raising=False)
    assert _admin_clock_request(api, {"tag": "local"}).status_code == 200
    monkeypatch.setenv("WORKSYNC_BEHIND_PROXY", "1")
    r = _admin_clock_request(api, {"tag": "proxy", "X-Forwarded-For": "127.0.0.1"})   # a faked "local" caller
    assert r.status_code == 403
    monkeypatch.setenv("WORKSYNC_ALLOW_REMOTE_CLOCK", "1")
    assert _admin_clock_request(api, {"tag": "allowed"}).status_code == 200            # only if the owner opts in


def test_throttling_uses_the_address_the_proxy_added_not_one_the_caller_wrote(api, monkeypatch):
    from starlette.requests import Request
    monkeypatch.setenv("WORKSYNC_BEHIND_PROXY", "1")

    def host(xff):
        scope = {"type": "http", "headers": [(b"x-forwarded-for", xff.encode())] if xff else [], "client": ("10.0.0.9", 1)}
        return main.client_host(Request(scope))

    assert host("1.1.1.1, 203.0.113.7") == "203.0.113.7"       # the caller wrote 1.1.1.1; the proxy added 203.0.113.7
    assert host("") == "10.0.0.9"
    monkeypatch.delenv("WORKSYNC_BEHIND_PROXY")
    assert host("1.1.1.1") == "10.0.0.9"                       # not behind a proxy: the header is ignored
