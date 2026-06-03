"""tests/test_api_idempotency.py — the API-05 money-safety gate (Phase 08 Plan 04).

Proves the partial-close idempotency + absolute-volume contract (D-09/D-10/D-11),
the regression test for the percent-of-current double-fire (the 75% trap):

  * test_volume_validation — close_volume outside (0, pos.volume) -> 422 (D-10).
  * test_replay — same request_id + same params replays the cached 200 AND the
    broker's close_position is invoked EXACTLY ONCE (D-11 — the core guarantee).
  * test_conflict — same request_id + DIFFERENT close_volume -> 409 (D-11).
  * test_partial_close_requires_csrf — POST without X-CSRF-Token -> 403 (D-16).

Backed by the `api_app` fixture (conftest), whose DryRunConnector seeds a
deterministic XAUUSD position: account "Vantage Demo-10k", ticket 100001,
volume 0.30. `clean_tables` truncates idempotency_keys between tests so each
request_id starts fresh. Skips cleanly when dev Postgres is absent (the api_app
fixture calls pytest.skip on init_db failure).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

KNOWN_PASSWORD = "correct-horse-battery-staple"
ACCOUNT = "Vantage Demo-10k"
TICKET = 100001
POS_VOLUME = 0.30  # the seeded DryRunConnector position volume

CLOSE_PARTIAL = f"/api/v2/positions/{ACCOUNT}/{TICKET}/close-partial"


def _login(client: TestClient) -> str:
    """Drive the real JSON login route and return the live telebot_csrf token.

    GET /auth/csrf to obtain the cookie + token, then POST /auth/login echoing
    it. On success the server seeds the session + refreshes telebot_csrf; the
    TestClient cookie jar carries both forward. Returns the post-login token so
    the caller can echo it as X-CSRF-Token on mutations.
    """
    r = client.get("/api/v2/auth/csrf")
    assert r.status_code == 200, r.text
    token = r.json()["csrf_token"]
    r = client.post(
        "/api/v2/auth/login",
        json={"password": KNOWN_PASSWORD, "csrf_token": token},
    )
    assert r.status_code == 200, r.text
    return client.cookies.get("telebot_csrf")


def _connector(api_app):
    """The live DryRunConnector backing the seeded position (for spying)."""
    import dashboard

    return dashboard.get_executor().tm.connectors[ACCOUNT]


# ─── Volume validation (D-10): out-of-range -> 422 ───────────────────────────


def test_volume_validation(api_app):
    """close_volume <= 0 or >= pos.volume -> 422 (out of range), broker untouched."""
    c = TestClient(api_app)
    token = _login(c)
    hdr = {"X-CSRF-Token": token}

    # 0 and negative are not in (0, pos.volume).
    r = c.post(CLOSE_PARTIAL, json={"close_volume": 0.0, "request_id": "vv-zero"}, headers=hdr)
    assert r.status_code == 422, r.text

    r = c.post(CLOSE_PARTIAL, json={"close_volume": -0.1, "request_id": "vv-neg"}, headers=hdr)
    assert r.status_code == 422, r.text

    # >= full volume is out of range (must leave something open for a *partial*).
    r = c.post(
        CLOSE_PARTIAL,
        json={"close_volume": POS_VOLUME, "request_id": "vv-full"},
        headers=hdr,
    )
    assert r.status_code == 422, r.text

    r = c.post(
        CLOSE_PARTIAL,
        json={"close_volume": POS_VOLUME + 0.1, "request_id": "vv-over"},
        headers=hdr,
    )
    assert r.status_code == 422, r.text


# ─── Replay (D-11): same request_id + params -> cached 200, broker ONCE ───────


def test_replay(api_app):
    """Same request_id + same params replays the cached 200 and the broker's
    close_position is invoked EXACTLY ONCE (the anti-double-fire guarantee)."""
    c = TestClient(api_app)
    token = _login(c)
    hdr = {"X-CSRF-Token": token}

    # Spy: count close_position invocations on the live connector.
    conn = _connector(api_app)
    calls: list[float] = []
    orig = conn.close_position

    async def _spy(ticket, volume=None):
        calls.append(volume)
        return await orig(ticket, volume=volume)

    conn.close_position = _spy
    try:
        body = {"close_volume": 0.10, "request_id": "replay-1"}
        r1 = c.post(CLOSE_PARTIAL, json=body, headers=hdr)
        assert r1.status_code == 200, r1.text
        first = r1.json()
        assert first["ok"] is True
        assert first["closed_volume"] == 0.10
        assert first["closed_volume_display"] == "0.10"

        # Replay: identical request_id + params -> cached 200, broker NOT re-hit.
        r2 = c.post(CLOSE_PARTIAL, json=body, headers=hdr)
        assert r2.status_code == 200, r2.text
        assert r2.json() == first  # exact cached payload

        assert len(calls) == 1, f"broker close_position called {len(calls)}x (expected 1)"
        assert calls[0] == 0.10  # absolute volume, not a percent
    finally:
        conn.close_position = orig


# ─── Replay after the position shrinks below the request volume (CR-01) ──────


def test_replay_after_shrink_below_request_volume(api_app):
    """A retry whose original close shrank the position below `close_volume`
    still replays the cached 200 — the idempotency gate runs BEFORE the live
    range check (CR-01 regression).

    Close 0.20 of the 0.30 position (request R): the position shrinks to 0.10.
    The 200 is "lost", so the client retries the identical {0.20, R}. The live
    volume is now 0.10, so a range check (0 < 0.20 < 0.10) would 422 — but the
    request_id is known, so the cached 200 MUST replay and the broker MUST NOT
    be called a second time.
    """
    c = TestClient(api_app)
    token = _login(c)
    hdr = {"X-CSRF-Token": token}

    conn = _connector(api_app)
    calls: list[float] = []
    orig = conn.close_position

    async def _spy(ticket, volume=None):
        calls.append(volume)
        return await orig(ticket, volume=volume)

    conn.close_position = _spy
    try:
        body = {"close_volume": 0.20, "request_id": "shrink-replay-1"}
        r1 = c.post(CLOSE_PARTIAL, json=body, headers=hdr)
        assert r1.status_code == 200, r1.text
        first = r1.json()
        assert first["ok"] is True
        assert first["closed_volume"] == 0.20

        # Retry: live volume is now 0.10 < 0.20, but the cached 200 must replay.
        r2 = c.post(CLOSE_PARTIAL, json=body, headers=hdr)
        assert r2.status_code == 200, r2.text  # NOT 422 — the gate runs first
        assert r2.json() == first

        assert len(calls) == 1, f"broker close_position called {len(calls)}x (expected 1)"
    finally:
        conn.close_position = orig


# ─── Conflict (D-11): same request_id + different params -> 409 ───────────────


def test_conflict(api_app):
    """Reusing a request_id with a DIFFERENT close_volume -> 409.

    The idempotency gate runs first: the first close (0.10) stores a real payload
    under request_id "conflict-1"; the second request reuses that id with a
    different close_volume (0.05), so idempotency.check matches the id but not the
    params and returns "conflict" -> 409 (D-11), without re-hitting the broker.
    """
    c = TestClient(api_app)
    token = _login(c)
    hdr = {"X-CSRF-Token": token}

    r1 = c.post(
        CLOSE_PARTIAL,
        json={"close_volume": 0.10, "request_id": "conflict-1"},
        headers=hdr,
    )
    assert r1.status_code == 200, r1.text

    # Same request_id, different (still in-range) volume -> conflict.
    r2 = c.post(
        CLOSE_PARTIAL,
        json={"close_volume": 0.05, "request_id": "conflict-1"},
        headers=hdr,
    )
    assert r2.status_code == 409, r2.text


# ─── CSRF gate (D-16): no X-CSRF-Token -> 403 ────────────────────────────────


def test_partial_close_requires_csrf(api_app):
    """A partial-close POST WITHOUT a valid X-CSRF-Token -> 403 (the D-16 gate).

    Authenticate first (so the 403 is unambiguously the CSRF guard), strip the
    telebot_csrf cookie, then POST with no X-CSRF-Token header."""
    c = TestClient(api_app)
    _login(c)
    c.cookies.delete("telebot_csrf")
    r = c.post(
        CLOSE_PARTIAL,
        json={"close_volume": 0.10, "request_id": "csrf-1"},
    )
    assert r.status_code == 403, r.text
    assert "<html" not in r.text.lower()
    assert "traceback" not in r.text.lower()
