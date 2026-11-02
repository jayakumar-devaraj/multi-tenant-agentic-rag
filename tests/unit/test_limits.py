"""Limit settings: defaults, overrides, and values that must fail startup."""

import pytest

from src.utils.limits import Limits


def test_defaults_and_overrides(monkeypatch):
    for name in ("RATE_LIMIT_QUERY_PER_MIN", "RATE_LIMIT_INGEST_PER_MIN", "TENANT_MAX_DOCUMENTS"):
        monkeypatch.delenv(name, raising=False)
    assert Limits.from_env() == Limits(query_per_min=60, ingest_per_min=10, max_documents=1000)
    monkeypatch.setenv("RATE_LIMIT_QUERY_PER_MIN", "5")
    assert Limits.from_env().per_min("query") == 5
    assert Limits.from_env().per_min("ingest") == 10


@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_a_limit_that_would_block_everything_or_is_not_a_number_fails(monkeypatch, value):
    monkeypatch.setenv("TENANT_MAX_DOCUMENTS", value)
    with pytest.raises(ValueError):
        Limits.from_env()
