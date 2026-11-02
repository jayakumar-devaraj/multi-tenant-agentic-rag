"""Per-tenant rate limits and the document quota (ADR 0003).

Counters live in Postgres (`tenant_usage`, migration 0004), so every API replica enforces the same limit.
A window is one minute; each call increments its tenant's row atomically and the row's count decides.
Rejected calls count too, so hammering does not reset the window.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import psycopg

Action = Literal["query", "ingest"]
WINDOW = timedelta(minutes=1)
DEFAULTS = {"query": 60, "ingest": 10}
DEFAULT_MAX_DOCUMENTS = 1000


class RateLimited(Exception):
    """The tenant has used its calls for this window (a caller error → 429 with Retry-After)."""

    def __init__(self, action: Action, retry_after_s: int) -> None:
        super().__init__(f"{action} rate limit reached")
        self.retry_after_s = retry_after_s


class QuotaExceeded(Exception):
    """The tenant holds its maximum number of documents (a caller error → 429, no Retry-After)."""


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    value = int(raw) if raw.strip() else default
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


@dataclass(frozen=True)
class Limits:
    """Limits from the environment: RATE_LIMIT_QUERY_PER_MIN, RATE_LIMIT_INGEST_PER_MIN, TENANT_MAX_DOCUMENTS."""

    query_per_min: int
    ingest_per_min: int
    max_documents: int

    @classmethod
    def from_env(cls) -> "Limits":
        """Read and validate the limits; a value below 1 fails startup loudly."""
        return cls(
            query_per_min=_int_env("RATE_LIMIT_QUERY_PER_MIN", DEFAULTS["query"]),
            ingest_per_min=_int_env("RATE_LIMIT_INGEST_PER_MIN", DEFAULTS["ingest"]),
            max_documents=_int_env("TENANT_MAX_DOCUMENTS", DEFAULT_MAX_DOCUMENTS),
        )

    def per_min(self, action: Action) -> int:
        """The per-minute limit for `action`."""
        return self.query_per_min if action == "query" else self.ingest_per_min


async def take(
    conn: psycopg.AsyncConnection, tenant_id: str, action: Action, limit: int, now: datetime | None = None
) -> None:
    """Count one call in the tenant's current window; RateLimited once the window's count exceeds `limit`.

    `conn` is bound to `tenant_id` (row-level security); the caller commits.
    """
    now = now or datetime.now(UTC)
    window = now.replace(second=0, microsecond=0)
    row = await (
        await conn.execute(
            """
            INSERT INTO tenant_usage (tenant_id, action, window_start, count) VALUES (%s, %s, %s, 1)
            ON CONFLICT (tenant_id, action, window_start) DO UPDATE SET count = tenant_usage.count + 1
            RETURNING count
            """,
            (tenant_id, action, window),
        )
    ).fetchone()
    await conn.execute(
        "DELETE FROM tenant_usage WHERE tenant_id = %s AND action = %s AND window_start < %s",
        (tenant_id, action, window),
    )
    if row is not None and row[0] > limit:
        raise RateLimited(action, max(1, int((window + WINDOW - now).total_seconds())))


async def documents_held(conn: psycopg.AsyncConnection, tenant_id: str) -> int:
    """How many distinct documents the tenant holds (counted against TENANT_MAX_DOCUMENTS)."""
    row = await (
        await conn.execute("SELECT count(DISTINCT doc_key) FROM page_registry WHERE tenant_id = %s", (tenant_id,))
    ).fetchone()
    return int(row[0]) if row else 0
