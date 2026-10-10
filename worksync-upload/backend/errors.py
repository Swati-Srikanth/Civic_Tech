"""Structured API error carrying the contract's error envelope."""
from __future__ import annotations

from typing import List, Optional


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, failures: Optional[List[dict]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.failures = failures or []

    def envelope(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "failures": self.failures}}


def unauthenticated(msg: str = "Choose a demo user (X-Demo-User header) to continue.") -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", msg)


def forbidden(msg: str) -> ApiError:
    return ApiError(403, "FORBIDDEN", msg)


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", "%s was not found." % what)


def stale_version(what: str) -> ApiError:
    return ApiError(409, "STALE_VERSION", "This %s changed. Refresh it and review the latest details." % what)


def stale_plan() -> ApiError:
    return ApiError(409, "STALE_PLAN", "This plan changed. Refresh it before responding.")


def invalid_state(msg: str) -> ApiError:
    return ApiError(409, "INVALID_STATE", msg)


def invalid(msg: str, failures: Optional[List[dict]] = None, code: str = "VALIDATION_ERROR") -> ApiError:
    return ApiError(422, code, msg, failures)
