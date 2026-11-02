"""Rung-2: per-tenant rate limits and the document quota against real Postgres (ADR 0003)."""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.agents.synthesis import SufficiencyVerdict
from src.db.connection import connect, run
from src.routers.api import Services, create_app
from src.utils.limits import RateLimited, take
from tests.conftest import FakeEmbedder, ScriptedLLM, make_docx, make_xlsx

pytestmark = pytest.mark.integration

if sys.platform == "win32":  # psycopg async needs a selector loop; TestClient's portal uses the policy default
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _take_n(tenant: str, n: int, limit: int, now: datetime) -> list[int | None]:
    """Take `n` calls in one window; each entry is None (allowed) or the Retry-After seconds."""

    async def go() -> list[int | None]:
        out: list[int | None] = []
        conn = await connect(tenant)
        try:
            for _ in range(n):
                try:
                    async with conn.transaction():
                        await take(conn, tenant, "query", limit, now)
                    out.append(None)
                except RateLimited as exc:
                    out.append(exc.retry_after_s)
        finally:
            await conn.close()
        return out

    return run(go())


def test_a_window_allows_its_limit_then_refuses_until_the_next_minute(tenant):
    start = datetime(2026, 11, 2, 10, 0, 15, tzinfo=UTC)
    assert _take_n(tenant, 4, 2, start) == [None, None, 45, 45]  # refused calls still count
    assert _take_n(tenant, 1, 2, start + timedelta(minutes=1)) == [None]  # a new window
    assert _take_n(f"{tenant}-other", 2, 2, start) == [None, None]  # tenants never share a counter


def test_retrieve_over_the_limit_is_429_with_retry_after_and_audited(monkeypatch, tenant):
    monkeypatch.setenv("TENANT_TOKENS", f"tok-a:{tenant}")
    monkeypatch.setenv("RATE_LIMIT_QUERY_PER_MIN", "1")
    a = {"Authorization": "Bearer tok-a"}
    lean = ScriptedLLM(SufficiencyVerdict=[SufficiencyVerdict(sufficient=True)])
    with TestClient(create_app(Services(embedder=FakeEmbedder(), llm=ScriptedLLM(), triad=None,
                                        retrieve_llm=lean))) as client:
        assert client.post("/v1/retrieve", json={"question": "q"}, headers=a).status_code == 200
        r = client.post("/v1/retrieve", json={"question": "q"}, headers=a)
        assert r.status_code == 429
        assert 1 <= int(r.headers["Retry-After"]) <= 60
        audit = client.get("/audit", params={"action": "retrieve"}, headers=a).json()["entries"]
        assert [e["outcome"] for e in audit[:2]] == ["denied", "ok"]
        assert audit[0]["detail"] == {"reason": "rate_limited"}


def test_a_new_document_past_the_quota_is_refused_and_rolled_back(monkeypatch, tenant):
    monkeypatch.setenv("TENANT_TOKENS", f"tok-a:{tenant}")
    monkeypatch.setenv("TENANT_MAX_DOCUMENTS", "1")
    a = {"Authorization": "Bearer tok-a"}
    with TestClient(create_app(Services(embedder=FakeEmbedder(), llm=ScriptedLLM(), triad=None))) as client:
        assert client.post("/ingest", files={"file": ("r.docx", make_docx())}, headers=a).status_code == 200
        second = make_xlsx({"Q1": [["Region", "Sales"], ["North", 100]]})
        refused = client.post("/ingest", files={"file": ("s.xlsx", second)}, headers=a)
        assert refused.status_code == 429 and "Retry-After" not in refused.headers
        # Updating a document the tenant already holds is not a new document.
        assert client.post("/ingest", files={"file": ("r.docx", make_docx())}, headers=a).status_code == 200
        audit = client.get("/audit", params={"action": "ingest"}, headers=a).json()["entries"]
        assert [(e["outcome"], e["doc_key"]) for e in audit] == [("ok", "r.docx"), ("denied", None), ("ok", "r.docx")]

    async def held() -> int:
        conn = await connect(tenant)
        try:
            row = await (await conn.execute("SELECT count(DISTINCT doc_key) FROM page_registry")).fetchone()
            return row[0]
        finally:
            await conn.close()

    assert run(held()) == 1  # the refused document left nothing behind
