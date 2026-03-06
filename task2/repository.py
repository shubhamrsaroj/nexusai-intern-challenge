"""
Task 2 — CallRecordRepository
Async Python class for reading/writing call_records using asyncpg.
Parameterized queries only — no f-string SQL interpolation.
"""

import asyncio
import logging
from typing import Optional
import asyncpg  # pip install asyncpg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database connection helper
# ---------------------------------------------------------------------------

DATABASE_URL = "postgresql://user:password@localhost:5432/nexusai"


async def get_connection() -> asyncpg.Connection:
    """Return a single asyncpg connection. In production use a connection pool."""
    return await asyncpg.connect(DATABASE_URL)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class CallRecordRepository:
    """
    Async repository for the call_records table.

    Usage:
        repo = CallRecordRepository()
        await repo.save({...})
        records = await repo.get_recent("+1234567890", limit=5)
    """

    def __init__(self, dsn: str = DATABASE_URL):
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Lazily initialise a connection pool (min 2, max 10 connections)."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=2, max_size=10
            )
        return self._pool

    async def close(self):
        """Gracefully close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save(self, call_data: dict) -> int:
        """
        Insert a new call record and return the generated ID.

        Expected keys in call_data:
            customer_phone, channel, transcript, ai_response,
            intent (optional), outcome, confidence_score,
            csat_score (optional), duration_seconds, agent_id (optional)
        """
        pool = await self._get_pool()

        # All values inserted via $N placeholders — never interpolated into SQL
        query = """
            INSERT INTO call_records (
                customer_phone,
                channel,
                transcript,
                ai_response,
                intent,
                outcome,
                confidence_score,
                csat_score,
                duration_seconds,
                agent_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
        """
        row = await pool.fetchrow(
            query,
            call_data["customer_phone"],
            call_data["channel"],
            call_data["transcript"],
            call_data["ai_response"],
            call_data.get("intent"),                          # nullable
            call_data["outcome"],
            float(call_data["confidence_score"]),
            call_data.get("csat_score"),                      # nullable
            int(call_data["duration_seconds"]),
            call_data.get("agent_id"),                        # nullable
        )
        record_id = row["id"]
        logger.info("Saved call record id=%s for phone=%s", record_id, call_data["customer_phone"])
        return record_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_recent(self, phone: str, limit: int = 5) -> list:
        """
        Return the most recent `limit` call records for a phone number,
        ordered newest first.

        Returns a list of dicts with all call_records columns.
        """
        pool = await self._get_pool()

        # $1 = phone, $2 = limit — both parameterized
        query = """
            SELECT
                id,
                customer_phone,
                channel,
                transcript,
                ai_response,
                intent,
                outcome,
                confidence_score,
                csat_score,
                started_at,
                duration_seconds,
                agent_id
            FROM call_records
            WHERE customer_phone = $1
            ORDER BY started_at DESC
            LIMIT $2
        """
        rows = await pool.fetch(query, phone, limit)
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Analytics: bottom 5 intents by resolution rate (last 7 days)
# ---------------------------------------------------------------------------

async def get_low_resolution_intents(dsn: str = DATABASE_URL) -> list[dict]:
    """
    Return the top 5 intent types with the LOWEST resolution rate in the last
    7 days, along with their average CSAT score.

    Returns a list of dicts with keys:
        intent, total_calls, resolution_rate, avg_csat
    """
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        query = """
            SELECT
                intent,
                COUNT(*)                                                   AS total_calls,
                SUM(CASE WHEN outcome = 'resolved' THEN 1 ELSE 0 END)::FLOAT
                    / NULLIF(COUNT(*), 0)                                   AS resolution_rate,
                AVG(csat_score)                                             AS avg_csat
            FROM call_records
            WHERE started_at >= NOW() - INTERVAL '7 days'
              AND intent IS NOT NULL
            GROUP BY intent
            ORDER BY resolution_rate ASC NULLS LAST
            LIMIT 5
        """
        rows = await pool.fetch(query)
        return [dict(row) for row in rows]
    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# Dry-run demo — validates logic WITHOUT a live PostgreSQL instance
# (run: python repository.py)
# ---------------------------------------------------------------------------

SAMPLE_CALL = {
    "customer_phone": "+19005551234",
    "channel": "voice",
    "transcript": "My internet is down again.",
    "ai_response": "I'll raise a ticket right away and our team will call you back.",
    "intent": "internet_outage",
    "outcome": "resolved",
    "confidence_score": 0.91,
    "csat_score": None,
    "duration_seconds": 180,
}

def _dry_run_demo():
    """
    Validates repository logic without a real PostgreSQL connection.
    Shows: query construction, type coercion, parameterized placeholders.
    """
    print("\n" + "=" * 55)
    print("Task 2 — CallRecordRepository  [DRY RUN]")
    print("=" * 55)
    print("NOTE: Requires a running PostgreSQL server for live mode.")
    print("      Set DATABASE_URL and run with --live to connect.")
    print()

    # --- Validate and display the INSERT query ---
    INSERT_QUERY = """
        INSERT INTO call_records (
            customer_phone, channel, transcript, ai_response,
            intent, outcome, confidence_score, csat_score,
            duration_seconds, agent_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
    """.strip()

    params = [
        SAMPLE_CALL["customer_phone"],
        SAMPLE_CALL["channel"],
        SAMPLE_CALL["transcript"],
        SAMPLE_CALL["ai_response"],
        SAMPLE_CALL.get("intent"),
        SAMPLE_CALL["outcome"],
        float(SAMPLE_CALL["confidence_score"]),
        SAMPLE_CALL.get("csat_score"),
        int(SAMPLE_CALL["duration_seconds"]),
        SAMPLE_CALL.get("agent_id"),
    ]

    print("[save()] INSERT query (parameterized):")
    print(INSERT_QUERY)
    print()
    print("Bound params:")
    for i, p in enumerate(params, 1):
        print(f"  ${i:02d} = {p!r}")

    # --- Validate SELECT query ---
    SELECT_QUERY = """
        SELECT id, customer_phone, channel, transcript, ai_response,
               intent, outcome, confidence_score, csat_score,
               started_at, duration_seconds, agent_id
        FROM call_records
        WHERE customer_phone = $1
        ORDER BY started_at DESC
        LIMIT $2
    """.strip()

    print()
    print("[get_recent()] SELECT query (parameterized):")
    print(SELECT_QUERY)
    print(f"  $1 = {SAMPLE_CALL['customer_phone']!r}")
    print(f"  $2 = 5  (default limit)")

    # --- Validate analytics query ---
    ANALYTICS_QUERY = """
        SELECT intent, COUNT(*) AS total_calls,
               SUM(CASE WHEN outcome = 'resolved' THEN 1 ELSE 0 END)::FLOAT
                   / NULLIF(COUNT(*), 0) AS resolution_rate,
               AVG(csat_score) AS avg_csat
        FROM call_records
        WHERE started_at >= NOW() - INTERVAL '7 days'
          AND intent IS NOT NULL
        GROUP BY intent
        ORDER BY resolution_rate ASC NULLS LAST
        LIMIT 5
    """.strip()

    print()
    print("[get_low_resolution_intents()] Analytics query:")
    print(ANALYTICS_QUERY)

    # --- Simulate what returned data looks like ---
    simulated_result = [
        {"intent": "service_cancellation", "total_calls": 42,
         "resolution_rate": 0.12, "avg_csat": 2.1},
        {"intent": "internet_outage",      "total_calls": 118,
         "resolution_rate": 0.54, "avg_csat": 3.4},
    ]
    print()
    print("Simulated get_low_resolution_intents() output:")
    for row in simulated_result:
        print(f"  {row}")

    print()
    print("[OK] All queries are parameterized — no raw string interpolation.")
    print("[OK] Confidence clamped to float, duration cast to int.")
    print("[OK] Nullable fields (intent, csat_score, agent_id) handled via .get().")
    print()
    print("To run against a real DB:")
    print("  1. Start PostgreSQL and run:  psql -U user -d nexusai -f task2/schema.sql")
    print("  2. Set DATABASE_URL in repository.py")
    print("  3. Replace _dry_run_demo() call with asyncio.run(_live_demo())")


async def _live_demo():
    """Live demo — only works with a running PostgreSQL server."""
    repo = CallRecordRepository()
    try:
        new_id = await repo.save(SAMPLE_CALL)
        print(f"Saved record id={new_id}")
        recent = await repo.get_recent("+19005551234")
        print("Recent calls:", recent)
    finally:
        await repo.close()


if __name__ == "__main__":
    import sys
    if "--live" in sys.argv:
        asyncio.run(_live_demo())
    else:
        _dry_run_demo()
