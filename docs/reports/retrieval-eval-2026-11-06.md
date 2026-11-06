# Retrieval quality and latency: pre-registered eval, 2026-11-06

Follow-up 1.5. This section was committed and pushed before any eval code existed or any run took place,
and it does not change afterwards. Results are added below it. A miss is reported as a miss, and the
data, labels and retrieval parameters are not tuned in response to a result. Any later change to them is
listed under "Deviations".

## Pre-registration

**Data.** `tests/load/retrieval_eval_data/`: 8 synthetic documents for a fictional freight company (PDF,
XLSX, DOCX, TXT; 26 sections, a section being one PDF page, one spreadsheet tab, or one whole DOCX or TXT
file) and 30 hand-labeled questions. The results describe only this set. They are not a claim about real
documents.

Question categories: `exact_id` (5, quoting an identifier), `paraphrase` (15, avoiding the document's
wording), `table` (6, a lookup in a spreadsheet tab), `cross_section` (4, needing two sections).

| Measure | Target | Definition |
|---|---|---|
| recall@5 | at least 0.80 | Mean over the 30 questions of (labeled sections in the top 5) / (labeled sections). Calls `src.retrieval.hybrid.retrieve` with `top_k=5`. |
| groundedness | at least 0.80 | Mean Ragas Faithfulness over `/chat` answers to the 30 questions, with a real Groq model. |
| `/v1/retrieve` p95 | at most 2 s | p95 over 300 sequential requests (10 rounds of the 30 questions), after one discarded warm-up round of 30. |

**Latency conditions.** The real FastAPI app in process, through `httpx.ASGITransport`, so no network or
server process is measured. Real `BAAI/bge-small-en-v1.5` fastembed embeddings, real Postgres and the
audit write. The sufficiency model call is replaced by a test double that answers "sufficient" at once,
as agreed for this target ("without the model call"), so this is not the latency a caller sees with a
model.

**Reported without a target:** recall@4 (the service's default `top_k`, so what the graph actually
receives); recall by category; each missed question; p50 and p95 for the same 300 requests sent 10 at a
time.

**Known limits, stated in advance.**
- The author of the code wrote the questions and labels, so the set may be easier than real use.
- 26 sections says little about ranking at scale, and latency here says nothing about a large corpus.
- The database is a single local container (512 MB cap) connected as the superuser, which bypasses
  row-level security; the `WHERE tenant_id` predicates still apply. `docs/reports/rls-benchmark-2026-10-28.md`
  found no measurable overhead from the policies.
- The chatbot stack was running on the same machine.

**Groundedness.** It needs a real chat model, and no Groq key is available for this run. It is reported as
not run, not as a pass or a miss, unless a key is provided later.
