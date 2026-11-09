# 0003 · Per-tenant rate limits and a document quota

**Status:** Accepted 2026-11-02.

## Context
Every tenant shares one API, one database and one model budget, and nothing stopped one tenant from
starving the others: a loop of `/v1/retrieve` calls spends the shared model quota, and unbounded ingests
fill the shared database.

## Decision
- **Rate limits per tenant, per minute:** `RATE_LIMIT_QUERY_PER_MIN` (default 60) for `/chat` and
  `/v1/retrieve`, `RATE_LIMIT_INGEST_PER_MIN` (default 10) for `/ingest`. Over the limit is 429 with
  `Retry-After` (seconds to the next window).
- **Counters in Postgres** (`tenant_usage`, migration 0004), so every replica enforces one limit. A call
  increments its tenant's row for the current one-minute window with one atomic upsert, in its own committed
  transaction, before any work. The refusal is raised only after that commit, so refused calls stay counted,
  and the work's rollback cannot undo the count. The row is protected by the same row-level security as the documents.
- **Document quota:** `TENANT_MAX_DOCUMENTS` (default 1000) distinct documents. It is checked inside the
  ingest transaction after the document key is resolved, so a new document past the quota is 429 (no
  `Retry-After`) and rolls back with nothing stored; re-ingesting a document the tenant already holds is
  always allowed.
- Refusals are audited with outcome `denied` and `detail.reason` `rate_limited` or `document_quota`.
- A limit below 1 fails startup.

## Consequences
- One extra short transaction per call. Fixed windows allow up to twice the limit across a window boundary.
- Two concurrent ingests can both pass the quota check, so a tenant can exceed it by the number of
  concurrent ingests.
- Limits are the same for every tenant; per-tenant overrides and token-bucket smoothing are not built.
- Consumers see a new status on `/v1/retrieve`; the chatbot treats an unexpected status as a final
  `rag_error`, so a limited tenant gets "try again later" rather than a retry storm.
