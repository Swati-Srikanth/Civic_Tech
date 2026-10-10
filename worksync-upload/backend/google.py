"""Optional Google sign-in for residents.

Residents never have to sign in: guests can report and track complaints with a tracking code. Signing in with Google
only adds a convenience (a "My reports" list that follows the person across devices).

The browser obtains a Google ID token (Google Identity Services) and sends it here. We verify it with Google's own
``tokeninfo`` endpoint, then check the audience (our client id), issuer, expiry and that the e-mail is verified.
Setting ``WORKSYNC_GOOGLE_CLIENT_ID`` turns the feature on; without it the endpoint answers 503 and the UI hides the
button. The HTTP call is isolated in ``fetch_tokeninfo`` so tests can replace it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from errors import ApiError

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")


def client_id() -> Optional[str]:
    return (os.environ.get("WORKSYNC_GOOGLE_CLIENT_ID") or "").strip() or None


def fetch_tokeninfo(credential: str) -> dict:
    url = TOKENINFO_URL + "?" + urllib.parse.urlencode({"id_token": credential})
    try:
        with urllib.request.urlopen(url, timeout=8) as r:           # noqa: S310 (fixed https URL)
            return json.load(r)
    except urllib.error.HTTPError:
        raise ApiError(401, "INVALID_GOOGLE_TOKEN", "Google did not accept that sign-in. Please try again.")
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise ApiError(503, "GOOGLE_UNAVAILABLE", "Google sign-in could not be reached right now. You can continue as a guest.")


def verify_credential(credential: str) -> dict:
    """Return {sub, email, name} for a valid Google ID token issued to *our* client id, else raise ApiError."""
    cid = client_id()
    if not cid:
        raise ApiError(503, "GOOGLE_NOT_CONFIGURED", "Google sign-in is not set up on this server. You can continue as a guest.")
    info = fetch_tokeninfo(credential)
    bad = ApiError(401, "INVALID_GOOGLE_TOKEN", "Google did not accept that sign-in. Please try again.")
    if info.get("aud") != cid or info.get("iss") not in ISSUERS or not info.get("sub"):
        raise bad
    try:
        if int(info.get("exp", 0)) <= int(time.time()):
            raise bad
    except (TypeError, ValueError):
        raise bad
    if str(info.get("email_verified", "")).lower() != "true":
        raise ApiError(401, "EMAIL_NOT_VERIFIED", "Your Google e-mail address is not verified, so it cannot be used to sign in.")
    return {"sub": str(info["sub"]), "email": info.get("email"), "name": info.get("name") or info.get("email")}
