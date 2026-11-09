"""Pre-registered retrieval eval: recall@k and /v1/retrieve latency (docs/reports/retrieval-eval-2026-11-06.md).

Usage: `DATABASE_URL=... PYTHONPATH=. uv run python tests/load/retrieval_eval.py 2>/dev/null`
Needs Postgres with pgvector and the local fastembed model. Prints a Markdown report. The sufficiency model call
is a test double, so no provider credentials are needed and groundedness is not measured here.
"""

import asyncio
import io
import json
import logging
import os
import statistics
import time
import uuid
from collections import defaultdict
from pathlib import Path

import docx
import httpx
import openpyxl
import pymupdf

from src.agents.synthesis import SufficiencyVerdict
from src.db.connection import database_url, run, tenant_transaction
from src.main import _embeddings, _LangchainEmbedder
from src.retrieval.hybrid import retrieve
from src.routers.api import Services, create_app
from src.utils.auth import Session
from tests.migration_support import upgrade_head

DATA = Path(__file__).parent / "retrieval_eval_data"
ROUNDS, CONCURRENCY = 10, 10
TOKEN = "eval-token"


class AlwaysSufficient:
    """TEST DOUBLE: stands in for the sufficiency model call, answering at once (see the pre-registration)."""

    def with_structured_output(self, schema: type) -> "AlwaysSufficient":
        return self

    async def ainvoke(self, messages: object, config: object = None) -> SufficiencyVerdict:
        return SufficiencyVerdict(sufficient=True)


def build_file(doc: dict) -> bytes:
    """The document's file in its own format, so ingestion runs its real worker."""
    if doc["format"] == "txt":
        return doc["text"].encode()
    buf = io.BytesIO()
    if doc["format"] == "docx":
        d = docx.Document()
        d.add_heading(doc["heading"], level=1)
        for paragraph in doc["paragraphs"]:
            d.add_paragraph(paragraph)
        d.save(buf)
    elif doc["format"] == "xlsx":
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for tab, rows in doc["tabs"].items():
            ws = wb.create_sheet(tab)
            for row in rows:
                ws.append(row)
        wb.save(buf)
    else:
        pdf = pymupdf.open()
        for p in doc["pages"]:
            page = pdf.new_page()
            page.insert_text((72, 72), p["title"], fontsize=14)
            page.insert_textbox(pymupdf.Rect(72, 96, 523, 700), p["body"], fontsize=11)
        return pdf.tobytes()
    return buf.getvalue()


def percentile(values: list[float], pct: int) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[pct - 1]


async def main() -> None:
    corpus = json.loads((DATA / "corpus.json").read_text(encoding="utf-8"))["documents"]
    questions = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    tenant = f"eval-{uuid.uuid4().hex[:8]}"
    os.environ.update(
        TENANT_TOKENS=f"{TOKEN}:{tenant}",
        ALLOW_STATIC_TOKENS="true",
        FASTEMBED_MODEL="BAAI/bge-small-en-v1.5",
        RATE_LIMIT_QUERY_PER_MIN="1000000",
        RATE_LIMIT_INGEST_PER_MIN="1000",
    )
    upgrade_head(database_url())
    embedder = _LangchainEmbedder(_embeddings())
    app = create_app(Services(embedder=embedder, llm=AlwaysSufficient(), triad=None))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    session = Session(tenant_id=tenant, subject="eval")

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eval", timeout=120) as client,
    ):
        sections = 0
        for doc in corpus:
            r = await client.post("/ingest", files={"file": (doc["name"], build_file(doc))}, headers=headers)
            r.raise_for_status()
            sections += len(r.json()["units"])

        ranked = {}
        for q in questions:
            async with tenant_transaction(app.state.pool, tenant) as conn:
                found = await retrieve(conn, embedder, session, q["question"], top_k=5)
            ranked[q["id"]] = [(s.doc_key, s.page_key) for s in found]

        async def timed(question: str) -> float:
            start = time.perf_counter()
            r = await client.post("/v1/retrieve", json={"question": question}, headers=headers)
            r.raise_for_status()
            return time.perf_counter() - start

        for q in questions:  # warm-up, discarded
            await timed(q["question"])
        requests = [q["question"] for _ in range(ROUNDS) for q in questions]
        sequential = [await timed(text) for text in requests]

        limit = asyncio.Semaphore(CONCURRENCY)

        async def bounded(text: str) -> float:
            async with limit:
                return await timed(text)

        concurrent = await asyncio.gather(*(bounded(text) for text in requests))

    def recall(q: dict, k: int) -> float:
        wanted = {tuple(r) for r in q["relevant"]}
        return len(wanted & set(ranked[q["id"]][:k])) / len(wanted)

    print(f"Ingested {len(corpus)} documents, {sections} sections; {len(questions)} questions.\n")
    print(f"- **recall@5:** {statistics.mean(recall(q, 5) for q in questions):.3f}")
    print(f"- **recall@4:** {statistics.mean(recall(q, 4) for q in questions):.3f}\n")
    by_category = defaultdict(list)
    for q in questions:
        by_category[q["category"]].append(q)
    print("| category | questions | recall@5 | recall@4 |\n|---|---|---|---|")
    for name, group in by_category.items():
        r5, r4 = (statistics.mean(recall(q, k) for q in group) for k in (5, 4))
        print(f"| {name} | {len(group)} | {r5:.3f} | {r4:.3f} |")
    print("\nQuestions below 1.0 at k=5 or k=4:\n")
    print(
        "| id | category | recall@5 | recall@4 | question | labeled | returned, best first |\n|---|---|---|---|---|---|---|"
    )
    for q in questions:
        if recall(q, 4) < 1:
            labeled = ", ".join(f"{d} {p}" for d, p in q["relevant"])
            returned = ", ".join(f"{d} {p}" for d, p in ranked[q["id"]])
            row = (
                q["id"],
                q["category"],
                f"{recall(q, 5):.2f}",
                f"{recall(q, 4):.2f}",
                q["question"],
                labeled,
                returned,
            )
            print("| " + " | ".join(row) + " |")
    print(f"\n| /v1/retrieve, {len(requests)} requests | p50 ms | p95 ms | max ms |\n|---|---|---|---|")
    for name, values in (("sequential", sequential), (f"{CONCURRENCY} at a time", list(concurrent))):
        ms = [v * 1000 for v in values]
        print(f"| {name} | {percentile(ms, 50):.0f} | {percentile(ms, 95):.0f} | {max(ms):.0f} |")


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    run(main())
