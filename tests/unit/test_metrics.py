"""Unit tests for the Prometheus request metrics, read from the default registry (no DB: lifespan is not run)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from src.routers.api import Services, create_app
from src.utils.metrics import MetricsMiddleware
from tests.conftest import FakeEmbedder, ScriptedLLM


def _value(name: str, **labels: str) -> float:
    """Current sample value; 0 before the first increment."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _client() -> TestClient:
    return TestClient(create_app(Services(embedder=FakeEmbedder(), llm=ScriptedLLM(), triad=None)))


def test_requests_are_counted_by_route_template_and_status(monkeypatch):
    monkeypatch.setenv("TENANT_TOKENS", "tok-a:tenant-a")
    client = _client()
    health = {"method": "GET", "route": "/health", "status": "200"}
    before = _value("rag_api_requests_total", **health)
    assert client.get("/health").status_code == 200 and client.get("/health").status_code == 200
    assert _value("rag_api_requests_total", **health) - before == 2

    unmatched = {"method": "GET", "route": "unmatched", "status": "404"}
    before = _value("rag_api_requests_total", **unmatched)
    assert client.get("/no/such/path").status_code == 404
    assert _value("rag_api_requests_total", **unmatched) - before == 1

    refused = {"method": "POST", "route": "/v1/retrieve", "status": "401"}
    before = _value("rag_api_requests_total", **refused)
    assert client.post("/v1/retrieve", json={"question": "q"}).status_code == 401
    assert _value("rag_api_requests_total", **refused) - before == 1
    assert _value("rag_api_request_seconds_count", method="POST", route="/v1/retrieve") >= 1


def test_no_metric_is_labelled_by_tenant():
    """Metrics never split by tenant: the only labels are method, route and status."""
    families = [f for f in REGISTRY.collect() if f.name.startswith("rag_api_")]
    assert {f.name for f in families} == {"rag_api_requests", "rag_api_request_seconds"}
    labels = {k for f in families for s in f.samples for k in s.labels}
    assert labels <= {"method", "route", "status", "le"}


def test_an_unhandled_error_is_counted_as_500():
    """An exception no handler maps never sends a response through the middleware; still a 500."""
    app = FastAPI()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    app.add_middleware(MetricsMiddleware)
    labels = {"method": "GET", "route": "/boom", "status": "500"}
    before = _value("rag_api_requests_total", **labels)
    assert TestClient(app, raise_server_exceptions=False).get("/boom").status_code == 500
    assert _value("rag_api_requests_total", **labels) - before == 1
