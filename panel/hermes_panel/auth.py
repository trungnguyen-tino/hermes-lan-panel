"""Password hashing + HMAC-signed session cookies.

The panel has exactly one admin account; its bcrypt hash lives in
HERMES_PANEL_PASSWORD_HASH (written by install.sh). Sessions are stateless
HMAC tokens so a panel restart does not log the user out.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time

import bcrypt

_BCRYPT_ROUNDS = 12
SESSION_COOKIE = "hermes_panel_session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _b64(data: str) -> str:
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def _unb64(data: str) -> str:
    padding = (4 - len(data) % 4) % 4
    return base64.urlsafe_b64decode(data + "=" * padding).decode()


def create_session(username: str, secret: str, ttl: int) -> tuple[str, int]:
    """Return (token, expiry_epoch)."""
    expiry = int(time.time()) + ttl
    payload = _b64(f"{username}|{expiry}")
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{_b64(sig)}", expiry


def verify_session(token: str, secret: str) -> str | None:
    """Return the username when the token is valid and unexpired, else None."""
    if not token or not secret:
        return None
    try:
        payload, sig_b64 = token.split(".", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig_b64, _b64(expected)):
            return None
        username, expiry_str = _unb64(payload).rsplit("|", 1)
        if int(time.time()) > int(expiry_str):
            return None
        return username
    except (ValueError, TypeError, binascii.Error):
        return None


class LoginRateLimiter:
    """In-process limiter: N failed logins per IP per window → locked out."""

    def __init__(self, max_attempts: int = 10, window: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window = window
        self._hits: dict[str, list[float]] = {}

    def _recent(self, ip: str, now: float) -> list[float]:
        hits = [t for t in self._hits.get(ip, []) if now - t < self.window]
        self._hits[ip] = hits
        return hits

    def blocked(self, ip: str) -> bool:
        return len(self._recent(ip, time.time())) >= self.max_attempts

    def record_failure(self, ip: str) -> None:
        now = time.time()
        self._recent(ip, now).append(now)

    def reset(self, ip: str) -> None:
        self._hits.pop(ip, None)
