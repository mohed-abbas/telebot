"""api/idempotency.py — partial-close dedupe over PostgreSQL (Phase 08 Plan 01).

D-01..D-04, Pitfall 1: the idempotency_keys DDL lives HERE, never in db.py
(db.py._create_tables owns all bot-core tables and stays byte-for-byte untouched).
`db._pool` is used strictly as a READ-ONLY accessor — db.py is never edited.

Design (template: failed_login_attempts lifecycle, db.py:204-214 / 979-1005):
  * request_id is the sole PK (D-02). account/ticket/close_volume are stored to
    detect a replay-vs-conflict on the SAME request_id (D-11).
  * result JSONB caches the original mutation payload so a replay returns the
    exact original 200 without re-hitting the broker (D-10/D-11).
  * Insert-first (`INSERT ... ON CONFLICT (request_id) DO NOTHING`) closes the
    check-then-act race (OQ1): one atomic statement decides new vs existing.
  * age_out deletes rows older than ttl_hours via make_interval (D-03), mirroring
    db.get_failed_login_count's interval idiom.

D-11 state mapping (returned by `check`):
  "new"      -> no prior row; caller executes the mutation then calls `store`.
  "replay"   -> prior row with SAME account+ticket+close_volume; cached result returned.
  "conflict" -> prior row with DIFFERENT params for this request_id; caller 409s.
"""

from __future__ import annotations

import json

import db

# Float comparison tolerance for close_volume (lot step is 2dp; 1e-9 is safe).
_VOL_EPS = 1e-9


async def ensure_table() -> None:
    """Create idempotency_keys + its created_at index (additive, idempotent DDL).

    Called once from the dashboard lifespan (NOT from db.init_db — that is bot core).
    """
    async with db._pool.acquire() as conn:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS idempotency_keys (
                request_id   TEXT PRIMARY KEY,
                account      TEXT NOT NULL,
                ticket       BIGINT NOT NULL,
                close_volume DOUBLE PRECISION NOT NULL,
                result       JSONB NOT NULL,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )"""
        )
        await conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_idempotency_created
                ON idempotency_keys(created_at)"""
        )


async def check(
    request_id: str, account: str, ticket: int, close_volume: float
) -> tuple[str, dict | None]:
    """Classify a (request_id, params) pair as new / replay / conflict (D-11).

    Insert-first to close the check-then-act race: attempt to claim the
    request_id with an empty-result placeholder via ON CONFLICT DO NOTHING.
      * row created  -> "new"     (caller runs the mutation, then `store`s the result)
      * row existed  -> compare params:
            same account+ticket+close_volume  -> "replay" (cached result, may be {})
            different                          -> "conflict"
    """
    async with db._pool.acquire() as conn:
        # Atomic claim: returns a row only when WE inserted it (no prior key).
        inserted = await conn.fetchrow(
            """INSERT INTO idempotency_keys (request_id, account, ticket, close_volume, result)
                VALUES ($1, $2, $3, $4, '{}'::jsonb)
                ON CONFLICT (request_id) DO NOTHING
                RETURNING request_id""",
            request_id, account, ticket, close_volume,
        )
        if inserted is not None:
            return "new", None

        # request_id already present — fetch its params + cached result.
        row = await conn.fetchrow(
            """SELECT account, ticket, close_volume, result
                FROM idempotency_keys WHERE request_id = $1""",
            request_id,
        )
        if row is None:
            # Extremely rare: aged-out between the two statements. Treat as new.
            return "new", None

        same = (
            row["account"] == account
            and row["ticket"] == ticket
            and abs(row["close_volume"] - close_volume) < _VOL_EPS
        )
        if not same:
            return "conflict", None

        cached = row["result"]
        if isinstance(cached, str):  # asyncpg may hand back JSONB as text
            cached = json.loads(cached) if cached else {}
        return "replay", (cached or {})


async def store(
    request_id: str, account: str, ticket: int, close_volume: float, result: dict
) -> None:
    """Persist the mutation result for a request_id (D-10).

    Upserts so it works whether `check` pre-claimed the row (the common path) or
    the caller stores without a prior check. ON CONFLICT updates the cached
    result + params for the existing key.
    """
    payload = json.dumps(result)
    async with db._pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO idempotency_keys
                    (request_id, account, ticket, close_volume, result)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                ON CONFLICT (request_id) DO UPDATE
                    SET account = EXCLUDED.account,
                        ticket = EXCLUDED.ticket,
                        close_volume = EXCLUDED.close_volume,
                        result = EXCLUDED.result""",
            request_id, account, ticket, close_volume, payload,
        )


async def age_out(ttl_hours: int = 24) -> None:
    """Delete idempotency rows older than ttl_hours (D-03, ~24h age-out)."""
    async with db._pool.acquire() as conn:
        await conn.execute(
            """DELETE FROM idempotency_keys
                WHERE created_at < NOW() - make_interval(hours => $1)""",
            ttl_hours,
        )
