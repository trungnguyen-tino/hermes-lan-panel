from __future__ import annotations

import time

from hermes_panel.auth import (
    LoginRateLimiter,
    create_session,
    hash_password,
    verify_password,
    verify_session,
)

SECRET = "x" * 32


def test_password_roundtrip():
    hashed = hash_password("mật khẩu 123")
    assert verify_password("mật khẩu 123", hashed) is True
    assert verify_password("sai", hashed) is False


def test_verify_password_with_garbage_hash():
    assert verify_password("bất kỳ", "") is False
    assert verify_password("bất kỳ", "không-phải-bcrypt") is False


def test_session_roundtrip():
    token, expiry = create_session("admin", SECRET, ttl=60)
    assert expiry > time.time()
    assert verify_session(token, SECRET) == "admin"


def test_session_rejects_wrong_secret_and_tampering():
    token, _ = create_session("admin", SECRET, ttl=60)
    assert verify_session(token, "y" * 32) is None
    payload, sig = token.split(".", 1)
    assert verify_session(payload + "." + sig[:-2] + "aa", SECRET) is None
    assert verify_session("rác", SECRET) is None
    assert verify_session("", SECRET) is None


def test_session_expires():
    token, _ = create_session("admin", SECRET, ttl=-1)
    assert verify_session(token, SECRET) is None


def test_rate_limiter_blocks_after_max_attempts():
    limiter = LoginRateLimiter(max_attempts=3, window=900)
    for _ in range(3):
        assert limiter.blocked("1.2.3.4") is False
        limiter.record_failure("1.2.3.4")
    assert limiter.blocked("1.2.3.4") is True
    assert limiter.blocked("5.6.7.8") is False
    limiter.reset("1.2.3.4")
    assert limiter.blocked("1.2.3.4") is False


def test_rate_limiter_forgets_old_attempts():
    limiter = LoginRateLimiter(max_attempts=2, window=0)
    limiter.record_failure("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert limiter.blocked("1.2.3.4") is False  # cửa sổ 0s → quên ngay
