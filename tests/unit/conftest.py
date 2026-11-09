"""Unit-test wiring: the per-tenant rate limiter needs Postgres, which unit tests replace with stubs.

Its behaviour is covered against real Postgres in tests/integration/test_tenant_limits.py.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_rate_limit_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    async def take(*args: object, **kwargs: object) -> int:
        return 0

    monkeypatch.setattr("src.routers.api.take", take)
