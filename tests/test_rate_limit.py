"""App-level login rate limit (AUTH-05, D-17) — independent of nginx.

Drives the real JSON login route (`/api/v2/auth/login`, the only login since
CUT-03) through per-IP httpx clients on the session loop, so the asyncpg pool
and the handlers share one event loop.
"""
from __future__ import annotations

import db
from tests.conftest import API_PASSWORD, make_api_client


async def _attempt(c, password: str):
    r = await c.get("/api/v2/auth/csrf")
    assert r.status_code == 200, r.text
    token = r.json()["csrf_token"]
    return await c.post(
        "/api/v2/auth/login", json={"password": password, "csrf_token": token},
    )


async def test_five_failures_triggers_lockout(api_app):
    async with make_api_client(api_app, client_ip="10.99.77.42") as c:
        for _ in range(5):
            assert (await _attempt(c, "wrong")).status_code == 401
        # 6th attempt hits the lockout (before the argon2 verify).
        r = await _attempt(c, "wrong")
        assert r.status_code == 429, r.text
        assert "rate_limited" in r.text


async def test_lockout_is_per_ip(api_app):
    async with make_api_client(api_app, client_ip="10.99.77.43") as locked:
        for _ in range(5):
            await _attempt(locked, "wrong")
        assert (await _attempt(locked, "wrong")).status_code == 429
    async with make_api_client(api_app, client_ip="10.99.77.44") as other:
        # A different client IP is not affected by the first one's lockout.
        assert (await _attempt(other, "wrong")).status_code == 401


async def test_success_clears_counter(api_app):
    ip = "10.99.88.1"
    async with make_api_client(api_app, client_ip=ip) as c:
        for _ in range(2):
            assert (await _attempt(c, "wrong")).status_code == 401
        assert await db.get_failed_login_count(ip, minutes=15) == 2

        r = await _attempt(c, API_PASSWORD)
        assert r.status_code == 200, r.text
        assert await db.get_failed_login_count(ip, minutes=15) == 0, (
            "Successful login must clear the IP's failure counter (D-17)"
        )
