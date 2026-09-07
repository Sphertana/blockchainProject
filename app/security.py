"""Small web-security primitives for the server-rendered application."""

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    """In-process sliding-window limiter, sufficient for this single API instance."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def enforce(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - window_seconds:
                attempts.popleft()
            if len(attempts) >= limit:
                retry_after = max(1, int(window_seconds - (now - attempts[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests",
                    headers={"Retry-After": str(retry_after)},
                )
            attempts.append(now)


rate_limiter = RateLimiter()


def validate_runtime() -> None:
    if os.environ.get("ENVIRONMENT", "development") != "production":
        return
    for name in ("SESSION_SECRET", "WALLET_SECRET"):
        value = os.environ.get(name, "")
        if len(value) < 32 or value.startswith("dev-"):
            raise RuntimeError(f"{name} must be a random value of at least 32 characters")
    if os.environ["SESSION_SECRET"] == os.environ["WALLET_SECRET"]:
        raise RuntimeError("SESSION_SECRET and WALLET_SECRET must be independent")
    grade_key = os.environ.get("GRADE_ENCRYPTION_KEY", "")
    try:
        valid_grade_key = len(bytes.fromhex(grade_key)) == 32
    except ValueError:
        valid_grade_key = False
    if not valid_grade_key or len(set(grade_key)) < 8:
        raise RuntimeError("GRADE_ENCRYPTION_KEY must be a random 32-byte hex key")
    if os.environ.get("COOKIE_SECURE", "").lower() != "true":
        raise RuntimeError("COOKIE_SECURE=true is required in production")
    if not os.environ.get("PUBLIC_HOST"):
        raise RuntimeError("PUBLIC_HOST is required in production")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def require_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf_token", "")
    submitted_digest = hashlib.sha256(submitted.encode()).digest()
    expected_digest = hashlib.sha256(expected.encode()).digest()
    if not expected or not hmac.compare_digest(submitted_digest, expected_digest):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def client_key(request: Request, scope: str) -> str:
    host = request.client.host if request.client else "unknown"
    if os.environ.get("TRUST_PROXY", "false").lower() == "true":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            host = forwarded.split(",", 1)[0].strip()
    return f"{scope}:{host}"