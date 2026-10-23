"""Warm cache: pre-fetch demo queries so the deployed demo is instant.

Usage: py -X utf8 scripts/warm_cache.py
Reads DEMO_QUERIES below, runs search pipeline, leaves serp+page cache filled.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DEMO_QUERIES = [
    ("мука", "Москва"),
    ("упаковка для кофе", "Санкт-Петербург"),
    ("сыры", "Казань"),
    ("кофе", "Москва"),
    (" специи и приправы", "Екатеринбург"),
]


async def main():
    from app.orchestrator import _run_job
    from app.store import get_store
    from app.sse import bus

    store = get_store()
    for i, (category, city) in enumerate(DEMO_QUERIES):
        category = category.strip()
        job_id = f"warm{i}"
        store.create_job(job_id, category, city)
        await _run_job(job_id, category, city)
        job = store.get_job(job_id)
        stats = job.get("stats") or "{}"
        print(f"[warm] {category} / {city}: status={job['status']} stats={stats[:120]}")

    print("cache warmed")


if __name__ == "__main__":
    asyncio.run(main())
