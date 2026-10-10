"""Residents' own accounts (e-mail + password, stored only as a salted hash) alongside Google and guests."""
import sqlite3
import time

import pytest

import complaints
import google

PW = "river-stone-77"


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(complaints, "COMPLAINT_LIMIT", 10000)


def register(api, email="ana@example.com", password=PW, name="Ana Resident"):
    return api.c.post("/api/v1/auth/register", json={"name": name, "email": email, "password": password})


def login(api, email="ana@example.com", password=PW):
    return api.c.post("/api/v1/auth/resident/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": "Bearer " + token}


def file_report(api, token=None, text="The street light outside the clinic has been flickering for days."):
    h = {"Idempotency-Key": "r-%d-%d" % (api.n, time.time_ns())}
    api.n += 1
    if token:
        h.update(bearer(token))
    r = api.c.post("/api/v1/complaints", json={"category": "ELECTRICAL", "description": text, "lat": 13.2, "lng": 80.3}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- creating
def test_a_resident_can_create_an_account_and_is_signed_in(api):
    r = register(api)
    assert r.status_code == 201
    out = r.json()
    assert out["resident"]["email"] == "ana@example.com" and out["resident"]["provider"] == "local" and len(out["token"]) > 30
    assert "password" not in r.text and "hash" not in r.text.lower()
    me = api.c.get("/api/v1/auth/resident/me", headers=bearer(out["token"]))
    assert me.status_code == 200 and me.json()["name"] == "Ana Resident"


def test_the_password_is_stored_only_as_a_salted_hash(api, db_path):
    register(api, "a@example.com"); register(api, "b@example.com")                   # the same password twice
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT email, password_hash FROM residents WHERE password_hash IS NOT NULL ORDER BY email").fetchall()
    conn.close()
    assert len(rows) == 2
    for _, stored in rows:
        assert stored.startswith("pbkdf2_sha256$") and PW not in stored
    assert rows[0][1] != rows[1][1]                                                    # different salts


def test_weak_passwords_bad_e_mails_and_duplicates_are_refused_with_field_messages(api):
    cases = {"short1": "password", "password123": "password", "12345678": "password", "abcdefgh": "password", "ana": "password"}
    for pw, field in cases.items():
        r = register(api, password=pw)
        assert r.status_code == 422, pw
        assert any(f["field"] == field for f in r.json()["error"]["failures"]), pw
    assert any(f["field"] == "password" for f in register(api, "ana@example.com", "ana").json()["error"]["failures"])         # e-mail name as password
    bad = register(api, email="not-an-email")
    assert bad.status_code == 422 and any(f["field"] == "email" for f in bad.json()["error"]["failures"])
    assert register(api).status_code == 201
    dup = register(api, email="ANA@Example.com")                                       # e-mail is not case-sensitive
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "EMAIL_TAKEN"


def test_account_creation_is_throttled_per_client(api):
    codes = [register(api, email="u%d@example.com" % i).status_code for i in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429


# --------------------------------------------------------------- signing in
def test_sign_in_with_the_right_password_only_and_say_nothing_about_which_part_was_wrong(api):
    register(api)
    assert login(api).status_code == 200
    assert login(api, "ANA@example.com").status_code == 200
    wrong = login(api, password="river-stone-78")
    unknown = login(api, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_repeated_failures_lock_that_e_mail_for_a_while(api):
    register(api)
    for _ in range(5):
        assert login(api, password="wrong-wrong-1").status_code == 401
    assert login(api).status_code == 429                                              # even the right password
    register(api, "other@example.com")
    assert login(api, "other@example.com").status_code == 200                         # others are unaffected


def test_a_resident_session_never_opens_a_staff_door_and_staff_are_not_residents(api):
    token = register(api).json()["token"]
    for path in ("/projects", "/cases", "/complaints", "/overview", "/team", "/activity", "/auth/me", "/export/complaints.csv"):
        assert api.c.get("/api/v1" + path, headers=bearer(token)).status_code == 401, path
    assert api.c.get("/api/v1/me/complaints", headers=bearer(api.token("u-admin"))).status_code == 401
    assert api.c.post("/api/v1/auth/resident/logout", headers=bearer(token)).status_code == 200
    assert api.c.get("/api/v1/auth/resident/me", headers=bearer(token)).status_code == 401


# --------------------------------------------------------------- their reports
def test_reports_filed_while_signed_in_belong_to_the_account_and_survive_signing_in_again(api):
    first = register(api).json()["token"]
    mine = file_report(api, first)
    guest = file_report(api)
    assert [i["reference"] for i in api.c.get("/api/v1/me/complaints", headers=bearer(first)).json()["items"]] == [mine["id"]]
    api.c.post("/api/v1/auth/resident/logout", headers=bearer(first))
    again = login(api).json()["token"]
    assert [i["reference"] for i in api.c.get("/api/v1/me/complaints", headers=bearer(again)).json()["items"]] == [mine["id"]]
    assert guest["id"] != mine["id"]


def test_a_guest_report_can_be_added_to_an_account_with_its_tracking_code(api):
    guest = file_report(api)
    token = register(api).json()["token"]
    h = bearer(token)
    assert api.c.get("/api/v1/me/complaints", headers=h).json()["items"] == []
    assert api.c.post("/api/v1/me/complaints/claim", json={"reference": guest["id"], "code": "0000000000"}, headers=h).status_code == 404
    assert api.c.post("/api/v1/me/complaints/claim", json={"reference": "CMP-2026-9999", "code": guest["tracking_code"]}, headers=h).status_code == 404
    ok = api.c.post("/api/v1/me/complaints/claim", json={"reference": guest["id"], "code": guest["tracking_code"]}, headers=h)
    assert ok.status_code == 200 and ok.json()["reference"] == guest["id"]
    assert [i["reference"] for i in api.c.get("/api/v1/me/complaints", headers=h).json()["items"]] == [guest["id"]]
    # claiming twice is harmless; someone else's account cannot take it afterwards
    assert api.c.post("/api/v1/me/complaints/claim", json={"reference": guest["id"], "code": guest["tracking_code"]}, headers=h).status_code == 200
    other = register(api, "bob@example.com").json()["token"]
    assert api.c.post("/api/v1/me/complaints/claim", json={"reference": guest["id"], "code": guest["tracking_code"]}, headers=bearer(other)).status_code == 404
    assert api.c.post("/api/v1/me/complaints/claim", json={"reference": guest["id"], "code": guest["tracking_code"]}).status_code == 401


def test_guessing_codes_while_claiming_is_throttled(api):
    guest = file_report(api)
    h = bearer(register(api).json()["token"])
    codes = [api.c.post("/api/v1/me/complaints/claim", json={"reference": guest["id"], "code": "%010X" % i}, headers=h).status_code for i in range(16)]
    assert codes[-1] == 429


# ------------------------------------------------------------------ password
def test_changing_the_password_checks_the_old_one_and_signs_other_devices_out(api):
    phone = register(api).json()["token"]
    laptop = login(api).json()["token"]
    h = bearer(laptop)
    assert api.c.post("/api/v1/auth/resident/password", json={"current_password": "wrong-one-1", "new_password": "new-river-stone-8"}, headers=h).status_code == 422
    weak = api.c.post("/api/v1/auth/resident/password", json={"current_password": PW, "new_password": "12345678"}, headers=h)
    assert weak.status_code == 422 and weak.json()["error"]["failures"][0]["field"] == "new_password"
    ok = api.c.post("/api/v1/auth/resident/password", json={"current_password": PW, "new_password": "new-river-stone-8"}, headers=h)
    assert ok.status_code == 200
    assert api.c.get("/api/v1/auth/resident/me", headers=bearer(phone)).status_code == 401           # the other device was signed out
    assert api.c.get("/api/v1/auth/resident/me", headers=bearer(ok.json()["token"])).status_code == 200
    assert login(api).status_code == 401 and login(api, password="new-river-stone-8").status_code == 200
    assert api.c.post("/api/v1/auth/resident/password", json={"current_password": PW, "new_password": "x"}).status_code == 401


# ------------------------------------------------- local and Google stay apart
def test_a_local_account_and_a_google_account_with_the_same_e_mail_are_never_merged(api, monkeypatch):
    monkeypatch.setenv("WORKSYNC_GOOGLE_CLIENT_ID", "client-1")
    info = {"aud": "client-1", "iss": "https://accounts.google.com", "sub": "g-9", "email": "ana@example.com", "email_verified": "true",
            "name": "Ana G", "exp": str(int(time.time()) + 600)}
    monkeypatch.setattr(google, "fetch_tokeninfo", lambda c: info)
    local = register(api).json()
    g = api.c.post("/api/v1/auth/google", json={"credential": "x" * 40}).json()
    assert g["resident"]["id"] != local["resident"]["id"] and g["resident"]["provider"] == "google"
    mine = file_report(api, local["token"])
    assert api.c.get("/api/v1/me/complaints", headers=bearer(g["token"])).json()["items"] == []     # the Google account cannot see it
    # a Google account has no password to change
    r = api.c.post("/api/v1/auth/resident/password", json={"current_password": PW, "new_password": "new-river-stone-8"}, headers=bearer(g["token"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_PASSWORD"
    # signing in with a password goes only to the local account, never to the Google one
    assert login(api, password="anything-at-all-1").status_code == 401
    assert login(api).json()["resident"]["id"] == local["resident"]["id"]
