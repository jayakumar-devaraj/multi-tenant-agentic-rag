# 0005 · fastembed on one ONNX Runtime thread

**Status:** Accepted 2026-11-03.

## Context
fastembed's ONNX Runtime session starts one intra-op thread per host core, and idle ones spin. The chatbot's
worker lost most of its CPU to this inside a 2-CPU container (its report `latency-2026-10-29-embedder-threads.md`
and its PR #86). This service built `FastEmbedEmbeddings` with no thread count, so it had the same default.

Measured on 2026-11-03 in the API image built from `main` (`0708e7c`), `BAAI/bge-small-en-v1.5`, on a host whose
`os.cpu_count()` is 12. Each run: 5 warm-up calls, then 30 query calls (`embed_query`) or 10 batch calls
(`embed_documents`, 16 short chunks); wall time and process CPU (`getrusage`) per call, two runs per setting:

| Container | Threads | Query wall / CPU | 16-chunk batch wall / CPU |
|---|---|---|---|
| `--cpus 2` | default | 34–80 / 71–142 ms | 702–759 / 1354–1407 ms |
| `--cpus 2` | 1 | 10–11 / 10–11 ms | 160–169 / 160–170 ms |
| uncapped | default | 10–13 / 59–78 ms | 185–195 / 1116–1180 ms |
| uncapped | 1 | 8.5–9.1 / 8.5–9.1 ms | 153–158 / 157–164 ms |

## Decision
`_embeddings()` builds `FastEmbedEmbeddings(model_name=..., threads=1)`. It is not configurable: one thread was
faster in wall time in every case measured, capped or not, at a seventh of the CPU or less.

## Consequences
- An embedding no longer takes CPU from the event loop and the other requests on the same replica; ingestion
  of a 16-chunk page is about 4× faster in a 2-CPU container.
- A larger model or much larger batches might gain from more threads; that would need its own measurement.
- `tests/unit/test_observability_main.py::test_fastembed_runs_on_one_onnx_thread` fails if the argument is
  dropped. The OpenAI embedding path is unchanged.
