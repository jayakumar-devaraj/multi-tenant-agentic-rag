"""Rung-2: a rejected request leaves a row in auth_rejections, never the credential (real Postgres)."""

import asyncio
import hashlib
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

from src.db.connection import connect, run
from src.routers.api import Services, create_app
from tests.conftest import FakeEmbedder, ScriptedLLM

pytestmark = pytest.mark.integration

if sys.platform == "win32":  # psycopg async needs a selector loop; TestClient's portal uses the policy default
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _rows(request_ids: list[str]) -> list[tuple]:
    async def go() -> list[tuple]:
        conn = await connect()
        try:
            cur = await conn.execute(
                "SELECT status, reason, path, credential, fingerprint, tenant_id, request_id FROM auth_rejections "
                "WHERE request_id = ANY(%s) ORDER BY id", (request_ids,))
            return await cur.fetchall()
        finally:
            await conn.close()

    return run(go())


def test_missing_and_unknown_tokens_are_recorded_without_the_token(monkeypatch, tenant):
    monkeypatch.setenv("TENANT_TOKENS", f"tok-a:{tenant}")
    secret = f"not-a-real-token-{uuid.uuid4().hex}"
    ids = [f"rej-{uuid.uuid4().hex}" for _ in range(2)]
    with TestClient(create_app(Services(embedder=FakeEmbedder(), llm=ScriptedLLM(), triad=None))) as client:
        missing = client.post("/v1/retrieve", json={"question": "q"}, headers={"X-Request-ID": ids[0]})
        wrong = client.post("/v1/retrieve", json={"question": "q"},
                            headers={"X-Request-ID": ids[1], "Authorization": f"Bearer {secret}"})
    assert (missing.status_code, wrong.status_code) == (401, 401)
    rows = _rows(ids)
    assert [r[:4] for r in rows] == [
        (401, "missing", "/v1/retrieve", "none"),
        (401, "invalid or missing bearer token", "/v1/retrieve", "static"),
    ]
    assert rows[0][4] is None and rows[1][4] == hashlib.sha256(secret.encode()).hexdigest()[:16]
    assert all(r[5] is None for r in rows)  # no tenant is known for a 401
    assert secret not in repr(rows)
