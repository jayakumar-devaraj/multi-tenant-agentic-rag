# 0004 · Prometheus request metrics

**Status:** Accepted 2026-11-03.

## Context
JSON logs and LangFuse traces explain one request; nothing measured the service over time. A caller such as
the chatbot saw this service's faults only indirectly, as its own 5xx or latency, and its Prometheus could not
scrape anything here. The assignment forbids cross-pollination of metrics between tenants.

## Decision
- The API exposes `rag_api_requests_total{method,route,status}` and `rag_api_request_seconds{method,route}`
  with `prometheus-client`, from a pure ASGI middleware added outermost in `create_app` (`src/utils/metrics.py`),
  the same shape as the chatbot gateway's metrics.
- `route` is the route template or `unmatched`, never the raw path. An exception no handler maps is counted as a
  500. Latency ends when the response headers are sent.
- No metric has a tenant label, and none counts per tenant: metrics stay aggregate. Per-tenant usage stays in
  `tenant_usage` and the audit trail, behind row-level security.
- The metrics are served by `prometheus_client.start_http_server` on `METRICS_PORT` (default 9100), bound to the
  API's `HOST`, from `src.main`. It is a port of its own, so `/metrics` is never reachable through the API port;
  compose does not publish it.

## Consequences
- Rejections (401, 403), limits (429) and provider or database outages (503) show as status series, without
  their reason or tenant; `auth_rejections` and the logs keep the detail.
- Metric names and labels become an interface for a scraper's rules; renaming one is a breaking change for them.
- The retrieval loop (attempts, sufficiency verdicts) and model calls are not measured, only whole requests.
- Histogram buckets reach 60 s because `/chat` and `/v1/retrieve` wait on model calls.
