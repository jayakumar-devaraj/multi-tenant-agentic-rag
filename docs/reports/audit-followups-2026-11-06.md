# Audit follow-ups: RAG service

Source: independent audit of this repo at `5e5429b` (score 78/100), run on 2026-11-03. Line numbers
below were re-checked against `origin/main` at `a7045f8` on 2026-11-06. The chatbot repository has
its own list (`docs/reports/audit-followups-2026-11-06.md` there).

Each item is tagged **observed** (reproduced or executed) or **inferred** (read from code, not run).
An inferred item must be reproduced before it is fixed. If it does not reproduce, close the item and
say so instead of changing code.

## How to use this file

Start a session in this repository and give it this prompt:

> Read `docs/reports/audit-followups-2026-11-06.md` and `CLAUDE.md`. Work the items in section 1 in
> order, then section 2. One branch and one PR per item. For each item: state the check that proves
> it done, make the smallest change, run it, commit, push, open the PR, and wait for CI. Do not
> merge until I say so. Stop and ask on anything marked "needs a decision".

Rules that bind every item (from `CLAUDE.md`):
- Follow the repo's own `CLAUDE.md` for git and documentation rules. Merge commits only, no history
  rewriting.
- Rung 2 verification needs the real Postgres with pgvector from `docker-compose.yml`. Only the
  database is needed, not the chatbot's stack. The Docker VM is limited to 8 GB and a second full
  stack has hung it before: check what is running first.
- Never state a result you did not run. Paste the command and its output line in the PR.

---

## 1. Code and test fixes (these move the score)

### 1.1 A refused call's rate-limit count is rolled back
- **Status:** inferred. Reproduce first with an integration test against real Postgres.
- **Where:** `src/utils/limits.py` line 86 raises `RateLimited` inside the transaction opened at
  `src/routers/api.py` lines 193-195 (`_rate_limit`). The transaction rolls back on the exception,
  which would undo the increment and the stale-window `DELETE`.
- **Effect if confirmed:** the tenant is still refused, but the claim "rejected calls count too"
  (docstring in `limits.py`, `docs/adr/0003-tenant-rate-limits-and-quota.md` line 16) is false.
- **Fix:** have `take` return the count and let `_rate_limit` raise after the transaction has
  committed. Correct the ADR and docstring to match what the code does.
- **Done when:** an integration test calls the endpoint limit + 3 times in one window and the stored
  count equals limit + 3; the 429 still carries `Retry-After`; the `denied` audit row is still written.
- **Rubric effect:** 2a +1, 1a +1.

### 1.2 Document quota can be exceeded by concurrent ingests
- **Status:** inferred. Reproduce first.
- **Where:** `src/routers/api.py` lines 241-245 count documents before and after `ingest_file` with no
  lock. At READ COMMITTED, parallel ingests can each see room and all commit.
- **Fix:** take `pg_advisory_xact_lock(hashtext(tenant_id))` for the check and the ingest, or
  enforce the cap in the database.
- **Done when:** an integration test runs N parallel ingests at the cap and the final count never
  exceeds `TENANT_MAX_DOCUMENTS`.

### 1.3 The documented test command errors without a database
- **Status:** observed. On a clean checkout `uv run pytest` gave 110 passed and 39 errors, all
  `RuntimeError: DATABASE_URL is not set`. Coverage was 83% without the database; the committed
  report (93%) includes it.
- **Fix:** skip integration tests with a clear message when `DATABASE_URL` is unset, or make the
  README say plainly that they need it. Also reconcile `docs/summary.md`, which says 42 tests need
  Postgres, with the 39 errors seen (cause not checked).
- **Rubric effect:** 3a +1.

### 1.4 No linter
- **Status:** observed. No `ruff` in `pyproject.toml` or `.github/workflows/ci.yml`.
- **Fix:** add `ruff check` and `ruff format --check` to CI and the README. Apply the formatting in a
  separate commit from any behavior change.

### 1.5 No retrieval-quality or load evidence
- **Status:** observed. `docs/reports/` holds only `rls-benchmark-2026-10-28.md`.
- **Fix:** a pre-registered retrieval eval (labeled questions, recall at k, groundedness) and a
  latency report, with the targets written before the run. Report failures as failures.

### 1.6 Never exercised against real services
- **Status:** from `docs/summary.md`. Langfuse, the OpenAI fallback and signed tokens against a real
  identity provider have only been tested with doubles or generated keys.
- **Fix:** run each once, and commit a report with the commands and the output.

---

## 2. Documentation and hygiene

### 2.1 Orchestration log
`docs/AI_ORCHESTRATION.md` has no rows I could find for #44, #45 and #46. Add them (run
`python3 scripts/check_docs.py` to see what the checker requires). Fill the session column only when
a creating call can be found; otherwise write `unrecorded`. Never infer one. Row 23 still names the
old rubric file `coding_challenge_eval_prompt_v2.md`: leave it as history and add a one-line rename note.

### 2.2 Limits to decide on
- The audit table has no partitioning or retention job (`docs/summary.md`, remaining work 3).
- The one-minute fixed window allows about double the limit across a window boundary: document it
  or move to a sliding window.

### 2.3 Provenance (partly cannot be recovered)
Only 3 of 126 commits carry a `Co-Authored-By` trailer, and 3 log rows are `unrecorded`. Past commits
cannot be given markers. Keep adding trailers or a session manifest from now on.

### 2.4 Local clone (for the owner, not a code change)
- The local clone may still be on `feat/rag-api-image`, whose remote branch is gone: switch to
  `main` and pull.
- Old worktrees (see `git worktree list`) may be removable. Ask before removing any; use
  `git worktree remove` without `--force`.

---

## 3. Expected effect

Items 1.1 to 1.4 are worth about +3 to +4 rubric points (78 to about 81-82). Items 1.5 and 1.6 are
product evidence and are worth little on the rubric. The remaining points depend on provenance that
cannot be added to past commits.
