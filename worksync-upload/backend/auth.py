"""Staff sign-in: username + password, hashed at rest, opaque expiring session tokens.

The public (residents) never sign in. Every internal endpoint requires a valid
``Authorization: Bearer <token>`` obtained from ``POST /auth/login``. Seeded users
have dummy credentials listed in ``DEMO_CREDENTIALS.md``; this is a demonstration
mechanism, not a production identity system.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from db import one
from errors import ApiError, forbidden, unauthenticated

ROLES = ("DEPARTMENT", "CONTRACTOR", "INSPECTOR", "ADMIN")
SESSION_HOURS = 8

LOGIN_MAX_FAILURES = 5          # per username+client within the window
LOGIN_WINDOW_SECONDS = 300
TRACK_MAX_FAILURES = 15         # failed complaint look-ups per client within the window
TRACK_WINDOW_SECONDS = 600


def _rounds() -> int:
    return int(os.environ.get("WORKSYNC_PBKDF2_ROUNDS", "200000"))


# ---------------------------------------------------------------- passwords
def hash_password(password: str, rounds: Optional[int] = None) -> str:
    rounds = rounds or _rounds()
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "pbkdf2_sha256$%d$%s$%s" % (rounds, salt.hex(), digest.hex())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# Verifying against this when the username does not exist keeps timing similar either way.
_DUMMY_HASH = hash_password("not-a-real-password", rounds=_rounds())


# ----------------------------------------------------------------- throttle
def throttle_blocked(conn: sqlite3.Connection, kind: str, key: str, limit: int, window: int) -> bool:
    row = one(conn, "SELECT COUNT(*) AS n FROM throttle WHERE kind = ? AND key = ? AND at_epoch > ?",
              (kind, key, time.time() - window))
    return bool(row and row["n"] >= limit)


def throttle_record(conn: sqlite3.Connection, kind: str, key: str) -> None:
    conn.execute("INSERT INTO throttle(kind, key, at_epoch) VALUES (?,?,?)", (kind, key, time.time()))
    conn.execute("DELETE FROM throttle WHERE at_epoch < ?", (time.time() - 86400,))


def throttle_clear(conn: sqlite3.Connection, kind: str, key: str) -> None:
    conn.execute("DELETE FROM throttle WHERE kind = ? AND key = ?", (kind, key))


def client_key(host: Optional[str]) -> str:
    """Stable, non-reversible handle for a client address (we never store raw addresses)."""
    return hashlib.sha256(("worksync-client:" + (host or "unknown")).encode()).hexdigest()[:24]


# ----------------------------------------------------------------- sessions
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def public_user(user: dict) -> dict:
    out = {k: user.get(k) for k in ("id", "name", "role", "org_id", "org_name", "project_kind")}
    out["is_head"] = bool(user.get("is_head"))
    return out


def user_by_id(conn: sqlite3.Connection, user_id: str) -> Optional[dict]:
    return one(conn, "SELECT u.id, u.name, u.role, u.org_id, u.is_head, o.name AS org_name, o.project_kind "
                     "FROM users u JOIN orgs o ON o.id = u.org_id WHERE u.id = ?", (user_id,))


# --------------------------------------------------------- resident sessions
# Residents (Google sign-in, optional) live in their own tables, so a resident token can never be
# mistaken for a staff session and vice versa.
RESIDENT_SESSION_DAYS = 7


def create_resident_session(conn: sqlite3.Connection, resident_id: str) -> tuple:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=RESIDENT_SESSION_DAYS)
    conn.execute("INSERT INTO resident_sessions(token_hash, resident_id, created_at, expires_at) VALUES (?,?,?,?)",
                 (_hash_token(token), resident_id, _iso(now), _iso(expires)))
    conn.execute("DELETE FROM resident_sessions WHERE expires_at < ?", (_iso(now),))
    return token, _iso(expires)


def _resident_public(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"],
            "provider": "google" if row.get("google_sub") else "local"}


def resident_for_token(conn: sqlite3.Connection, token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    row = one(conn, "SELECT resident_id, expires_at FROM resident_sessions WHERE token_hash = ?", (_hash_token(token),))
    if not row or row["expires_at"] <= _iso(datetime.now(timezone.utc)):
        return None
    return _resident_public(one(conn, "SELECT id, name, email, google_sub FROM residents WHERE id = ?", (row["resident_id"],)))


def revoke_resident_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM resident_sessions WHERE token_hash = ?", (_hash_token(token),))


def upsert_resident(conn: sqlite3.Connection, google_sub: str, email: Optional[str], name: Optional[str]) -> dict:
    row = one(conn, "SELECT id FROM residents WHERE google_sub = ?", (google_sub,))
    if row:
        conn.execute("UPDATE residents SET email = ?, name = ? WHERE id = ?", (email, name, row["id"]))
        rid = row["id"]
    else:
        rid = "r-" + secrets.token_hex(6)
        conn.execute("INSERT INTO residents(id, google_sub, email, name, created_at) VALUES (?,?,?,?,?)",
                     (rid, google_sub, email, name, _iso(datetime.now(timezone.utc))))
    return _resident_public(one(conn, "SELECT id, name, email, google_sub FROM residents WHERE id = ?", (rid,)))


def create_session(conn: sqlite3.Connection, user_id: str) -> tuple:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=SESSION_HOURS)
    conn.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                 (_hash_token(token), user_id, _iso(now), _iso(expires)))
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))
    return token, _iso(expires)


def revoke_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))


def user_for_token(conn: sqlite3.Connection, token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    row = one(conn, "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (_hash_token(token),))
    if not row or row["expires_at"] <= _iso(datetime.now(timezone.utc)):
        return None
    return user_by_id(conn, row["user_id"])


def check_credentials(conn: sqlite3.Connection, username: str, password: str) -> Optional[dict]:
    """Return the user row id if the credentials are right, else None. Always does one hash check."""
    row = one(conn, "SELECT id, password_hash FROM users WHERE username = ?", (username.strip().lower(),))
    ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
    return {"id": row["id"]} if (row and ok) else None


# ------------------------------------------------- local resident accounts
# E-mail + password accounts for residents who do not want to use Google. The password is stored only as a salted
# PBKDF2 hash, so it can never be read back (not even by the people running the server). The e-mail is NOT verified
# (nothing is sent), so it is only a username: there is no "forgot password" e-mail, and a local account is never merged
# with a Google account that happens to use the same address.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
COMMON_PASSWORDS = {"password", "password1", "password123", "12345678", "123456789", "1234567890", "qwerty123", "qwertyuiop",
                    "iloveyou", "11111111", "abcd1234", "admin123", "welcome1", "letmein123"}
REGISTER_MAX_PER_HOUR = 10
RESIDENT_LOGIN_MAX_FAILURES = 5
RESIDENT_LOGIN_WINDOW_SECONDS = 300


def normalise_email(email: str) -> str:
    return email.strip().lower()


def password_problems(password: str, email: str = "", name: str = "") -> list:
    out = []
    if len(password) < 8:
        out.append("Use at least 8 characters.")
    if len(password) > 128:
        out.append("Use at most 128 characters.")
    if password.lower() in COMMON_PASSWORDS:
        out.append("That password is too common. Choose something less guessable.")
    if email and password.lower() == email.lower().split("@")[0]:
        out.append("The password must not be the same as your e-mail name.")
    if name and len(name) >= 4 and password.lower() == name.lower():
        out.append("The password must not be your name.")
    if password.isdigit() or password.isalpha():
        out.append("Mix letters with numbers or symbols.")
    return out


def register_resident(conn: sqlite3.Connection, name: str, email: str, password: str) -> dict:
    email = normalise_email(email)
    failures = []
    if not EMAIL_RE.match(email) or len(email) > 120:
        failures.append({"field": "email", "message": "Enter a valid e-mail address."})
    for m in password_problems(password, email, name):
        failures.append({"field": "password", "message": m})
    if failures:
        raise ApiError(422, "VALIDATION_ERROR", "Check the highlighted fields.", failures)
    if one(conn, "SELECT 1 AS x FROM residents WHERE lower(email) = ? AND password_hash IS NOT NULL", (email,)):
        raise ApiError(409, "EMAIL_TAKEN", "An account with this e-mail already exists. Try signing in instead.",
                       [{"field": "email", "message": "This e-mail already has an account."}])
    rid = "r-" + secrets.token_hex(6)
    conn.execute("INSERT INTO residents(id, google_sub, email, name, password_hash, created_at) VALUES (?,?,?,?,?,?)",
                 (rid, None, email, name.strip(), hash_password(password), _iso(datetime.now(timezone.utc))))
    return _resident_public(one(conn, "SELECT id, name, email, google_sub FROM residents WHERE id = ?", (rid,)))


def check_resident_login(conn: sqlite3.Connection, email: str, password: str) -> Optional[dict]:
    """The resident if e-mail + password are right, else None. Always does exactly one hash check (same timing)."""
    row = one(conn, "SELECT id, name, email, google_sub, password_hash FROM residents "
                    "WHERE lower(email) = ? AND password_hash IS NOT NULL", (normalise_email(email),))
    ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
    return _resident_public(row) if (row and ok) else None


def change_resident_password(conn: sqlite3.Connection, resident_id: str, current: str, new: str) -> None:
    row = one(conn, "SELECT email, name, password_hash FROM residents WHERE id = ?", (resident_id,))
    if not row or not row["password_hash"]:
        raise ApiError(409, "NO_PASSWORD", "This account signs in with Google, so it has no password to change.")
    if not verify_password(current, row["password_hash"]):
        raise ApiError(422, "VALIDATION_ERROR", "Check the highlighted fields.",
                       [{"field": "current_password", "message": "That is not your current password."}])
    problems = password_problems(new, row["email"] or "", row["name"] or "")
    if problems:
        raise ApiError(422, "VALIDATION_ERROR", "Check the highlighted fields.", [{"field": "new_password", "message": m} for m in problems])
    conn.execute("UPDATE residents SET password_hash = ? WHERE id = ?", (hash_password(new), resident_id))
    conn.execute("DELETE FROM resident_sessions WHERE resident_id = ?", (resident_id,))       # other devices must sign in again


def require_role(user: dict, *roles: str) -> None:
    if user["role"] not in roles:
        raise forbidden("Your role (%s) cannot perform this action." % user["role"].title())


def too_many_attempts() -> ApiError:
    return ApiError(429, "TOO_MANY_ATTEMPTS", "Too many failed attempts. Please wait a few minutes and try again.")


__all__ = [
    "ROLES", "hash_password", "verify_password", "client_key", "create_session", "revoke_session", "user_for_token",
    "check_credentials", "require_role", "public_user", "user_by_id", "throttle_blocked", "throttle_record",
    "throttle_clear", "too_many_attempts", "create_resident_session", "resident_for_token", "revoke_resident_session",
    "upsert_resident", "register_resident", "check_resident_login", "change_resident_password", "normalise_email",
    "REGISTER_MAX_PER_HOUR", "RESIDENT_LOGIN_MAX_FAILURES", "RESIDENT_LOGIN_WINDOW_SECONDS", "unauthenticated", "LOGIN_MAX_FAILURES", "LOGIN_WINDOW_SECONDS",
    "TRACK_MAX_FAILURES", "TRACK_WINDOW_SECONDS", "SESSION_HOURS",
]
