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

## Results

The pre-registration above is commit `f98c8ad`. Everything above this heading and the data files are
unchanged since then.

| Measure | Target | Result | Outcome |
|---|---|---|---|
| recall@5 | at least 0.80 | 0.900 | **Met, on this synthetic set only** |
| groundedness | at least 0.80 | not measured | **Not run:** no Groq key was available |
| `/v1/retrieve` p95, sequential | at most 2 s | 54, 60 and 56 ms over three runs | **Met, without the model call** |

Command, run three times against `pgvector/pgvector:pg16` from `main` at `9a7cc46` plus this script. It does
not include the open fixes in #48 to #51. The script was reformatted between runs 2 and 3, with no logic change.

```bash
DATABASE_URL=postgresql://rag@127.0.0.1:5434/rag PYTHONPATH=. uv run python tests/load/retrieval_eval.py
```

### Recall

Recall was identical in all three runs. Without the model, each question ran one retrieval pass, with no
re-query.

| Category | Questions | recall@5 | recall@4 |
|---|---|---|---|
| exact_id | 5 | 1.000 | 1.000 |
| paraphrase | 15 | 0.867 | 0.733 |
| table | 6 | 1.000 | 1.000 |
| cross_section | 4 | 0.750 | 0.750 |
| **all** | **30** | **0.900** | **0.833** |

recall@4 is the figure closer to what the service does, because `retrieve` defaults to `top_k=4`. It is
reported without a target.

Every question below 1.0:

| Question | Labeled section | recall@5 | recall@4 | Top returned |
|---|---|---|---|---|
| q11 A customer gave me an expensive present, what do I do? | handbook page 6 | 0.00 | 0.00 | sales Q2, customer onboarding |
| q15 How worn can the rubber get before a lorry needs new wheels fitted? | fleet page 2 | 0.00 | 0.00 | fleet page 3, fleet page 5 |
| q28 How long is CCTV footage kept, and who supplies CCTV monitoring? | security page 4, contracts tab | 0.50 | 0.50 | security page 4, warehouse |
| q30 How many litres can go on a fuel card per fill, and how much notice does the fuel card contract need? | fleet page 4, renewals tab | 0.50 | 0.50 | fleet page 4, fleet page 5 |
| q13 How long do we hang on to client data once a deal finishes? | security page 4 | 1.00 | 0.00 | security page 3, customer onboarding (labeled section fifth) |
| q20 How often must lift-truck operators requalify? | warehouse | 1.00 | 0.00 | fleet page 1, handbook page 1 (labeled section fifth) |

What these show, and what they do not:
- Identifier and table lookups were all found. The misses are in paraphrases and two-part questions.
- q13 and q20 are found only at rank 5, so the service's default of 4 would miss them on the first pass.
- q28 missed the contracts tab even though it contains the word "CCTV", and q30 missed the renewals tab. The
  cause was not investigated; nothing was changed in response.

### Latency

300 requests per case, through the app in process, with real embeddings and Postgres and a test double for
the model call.

| Case | Run 1 p50 / p95 / max ms | Run 2 p50 / p95 / max ms | Run 3 p50 / p95 / max ms |
|---|---|---|---|
| sequential | 36 / 54 / 95 | 35 / 60 / 79 | 35 / 56 / 92 |
| 10 at a time (no target) | 135 / 217 / 330 | 128 / 231 / 341 | 135 / 204 / 270 |

A caller's latency also includes the sufficiency model call, the network and any re-query passes, none of
which are measured here. Target 2 s was set for this narrower measure, and it was met by a wide margin on a
26-section corpus, which is too small to predict behavior at scale.

### Deviations

None to the data, labels, targets or retrieval parameters. Groundedness was registered in advance as not
run without a key.
