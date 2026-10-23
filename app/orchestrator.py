"""Job orchestrator: lifecycle, stages, deadline, engine cascade."""
import asyncio
import uuid
from datetime import datetime
from typing import List, Optional

from .config import CONFIG
from .engines.base import Candidate, EngineResult
from .engines.ddg import DDGEngine
from .engines.bing import BingEngine
from .engines.yandex import YandexEngine
from .engines.twogis import TwoGisEngine
from .engines.ranking import rank_candidates
from .extract.cascade import extract_candidate
from .merge import Merger, identity_key_for
from .names import clean_name, shop_name_from_domain
from .score import score_card, verdict
from .schema import SupplierCard, Phone, SourceRef
from .sse import bus
from .store import get_store

ENGINES = [DDGEngine(), YandexEngine(), TwoGisEngine(), BingEngine()]


def _new_job_id() -> str:
    return uuid.uuid4().hex[:12]


async def start_search(category: str, city: str, force_refresh: bool, ru_only: bool = True) -> Optional[str]:
    """Create a job and run pipeline in background. Returns job_id (or None if cache hit).

    Cache-first: if a recent identical search exists (within CACHE_HIT_TTL),
    return cached cards immediately — the demo stays instant on repeat queries.
    ru_only=True: only RF resources (see app/geo.py).
    """
    store = get_store()
    if not force_refresh:
        cached = recent_job_with_cards(category, city, ru_only)
        if cached is not None:
            return cached
    job_id = _new_job_id()
    store.create_job(job_id, category, city)
    asyncio.get_event_loop().create_task(_run_job(job_id, category, city, ru_only))
    return job_id


CACHE_HIT_TTL_S = 6 * 3600  # reuse a search done within last 6 hours


def recent_job_with_cards(category: str, city: str, ru_only: bool = True) -> Optional[str]:
    """Find a done job with the same category+city+ru_only; re-emit its cards as a new job id."""
    from datetime import timedelta

    store = get_store()
    job = store.find_recent_job(category, city, CACHE_HIT_TTL_S)
    while job is not None:
        # replay must respect the ru_only mode: job stats record it
        import json as _json

        try:
            job_stats = _json.loads(job.get("stats") or "{}")
        except ValueError:
            job_stats = {}
        if job_stats.get("ru_only", True) == ru_only:
            break
        job = store.find_recent_job_before(category, city, CACHE_HIT_TTL_S, job["created_at"])
    if not job:
        return None
    cards = store.job_suppliers(job["id"])
    if not cards:
        return None
    # replay: new job id over old cards (SSE-friendly)
    new_id = f"r{_new_job_id()}"
    store.create_job(new_id, category, city)
    for key in store.job_keys(job["id"]):
        store.link_job(new_id, key)
    store.finish_job(new_id, "done", {"cache_replay": True, "source_job": job["id"], "found": len(cards)})

    async def _replay() -> None:
        bus.publish(new_id, "stage", {"key": "search", "label": "Данные из кэша (свежесть < 6 ч)", "progress": 0.9})
        bus.publish(new_id, "stage", {"key": "score", "label": "Скорим и сортируем", "progress": 0.95})
        for i, card in enumerate(cards):
            s = score_card(card, category, city)
            card.confidence = round(s["total"] / 100, 2)
            bus.publish(new_id, "card", {"card": card.model_dump(mode="json"), "score": s, "verdict": verdict(s["total"]), "index": i})
        bus.finish(new_id)

    asyncio.get_event_loop().create_task(_replay())
    return new_id


async def _run_job(job_id: str, category: str, city: str, ru_only: bool = True) -> None:
    stats = {"engines": [], "pages": 0, "llm_calls": 0, "cost_usd": 0.0, "ru_only": ru_only}
    store = get_store()
    try:
        await asyncio.wait_for(_run_pipeline(job_id, category, city, stats, store, ru_only), timeout=CONFIG.job_deadline_s)
        store.finish_job(job_id, "done", stats)
        bus.finish(job_id)
    except asyncio.TimeoutError:
        store.finish_job(job_id, "done", {**stats, "partial": True})
        bus.publish(job_id, "error", {"message": "Достигнут лимит времени — показаны частичные результаты"})
        bus.finish(job_id)
    except Exception as e:  # noqa: BLE001 — pipeline must never crash silently
        store.finish_job(job_id, "error", {**stats, "error": str(e)})
        bus.publish(job_id, "error", {"message": str(e)})
        bus.finish(job_id)


async def _run_pipeline(job_id: str, category: str, city: str, stats: dict, store, ru_only: bool = True) -> None:
        # ---- stage 1: engines ----
        await _stage(job_id, "search", "Опрашиваем поисковые движки", 0.05)
        candidates: List[Candidate] = []
        engine_names = []
        for engine in ENGINES:
            try:
                result = await asyncio.wait_for(engine.search(category, city), timeout=25.0)
            except asyncio.TimeoutError:
                result = EngineResult([], error="timeout")
            stats["engines"].append({
                "name": engine.name,
                "cached": result.cached,
                "found": len(result.candidates),
                "error": result.error,
            })
            if result.error is None or result.candidates:
                engine_names.append(engine.name)
            candidates.extend(result.candidates)
            if len(candidates) >= 15:
                break  # enough candidates from first healthy engines

        await _stage(job_id, "candidates", "Отбираем сайты-кандидаты" + (" (только РФ)" if ru_only else ""), 0.2)
        top = rank_candidates(candidates, category, city, limit=CONFIG.max_candidates, ru_only=ru_only)

        # ---- stage 2: fetch & extract ----
        # 2a: parallel fetch + levels 1-3 (adapters, structured, heuristics), no LLM yet
        await _stage(job_id, "fetch", "Обходим сайты поставщиков", 0.35)
        total = min(len(top), CONFIG.max_pages_per_job)
        merger = Merger()
        fetched = 0

        # pending low-coverage pages -> LLM stage 2b
        low_cov: List = []  # (card, html, base_pd)

        async def process(i: int, cand: Candidate) -> None:
            nonlocal fetched
            result = await extract_candidate(cand, None)  # stats=None -> LLM level skipped
            fetched += 1
            if result:
                pd, html = result
                if pd.coverage() < 0.5 and CONFIG.llm.enabled and CONFIG.llm.api_key:
                    low_cov.append((cand, pd, html))
                else:
                    _emit_card(job_id, cand, pd, city, category, merger, store, stats)
            bus.publish(job_id, "progress", {"fetched": fetched, "total": total, "found": merger_count(merger)})

        await asyncio.gather(*(process(i, c) for i, c in enumerate(top[:total])))

        # 2b: LLM level for low-coverage pages — parallel calls, one wall-clock cap
        if low_cov:
            await _stage(job_id, "fetch", "Достаиваем детали через LLM", 0.6)
            from .extract.cascade import llm_combine as _llm_combine
            from .extract.llm import llm_extract

            llm_cap = min(CONFIG.llm.timeout_s, CONFIG.job_deadline_s / 2)

            async def llm_task(cand, pd, html):
                try:
                    llm_pd = await asyncio.wait_for(llm_extract(html, stats), timeout=llm_cap)
                except Exception:
                    llm_pd = None
                return cand, _llm_combine(pd, llm_pd)

            enriched = await asyncio.wait_for(
                asyncio.gather(*(llm_task(c, p, h) for c, p, h in low_cov)), timeout=llm_cap + 10
            )
            for cand, pd in enriched:
                _emit_card(job_id, cand, pd, city, category, merger, store, stats)

        # ---- stage 3: score ----
        await _stage(job_id, "score", "Скорим и сортируем", 0.95)
        stats["pages"] = total
        stats["found"] = merger_count(merger)
        stats["conflicts"] = merger.conflicts()[:20]


def _emit_card(job_id: str, cand: Candidate, pd, city: str, category: str, merger, store, stats) -> None:
    """Card from PageData -> merge -> store + SSE events."""
    card = pd.to_card(cand, city, category)
    card.identity_key = identity_key_for(card, card.website or "")
    card.name = clean_name(card.name, cand.domain)
    s = score_card(card, category, city)
    card.confidence = round(s["total"] / 100, 2)
    new_card = merger.add(card)
    if new_card is not None:
        store.upsert_supplier(new_card)
        store.link_job(job_id, new_card.identity_key)
        bus.publish(job_id, "card", {"card": new_card.model_dump(mode="json"), "score": s, "verdict": verdict(s["total"]), "index": merger_count(merger)})
    else:
        merged_card = _find_updated(merger, card.identity_key)
        if merged_card is not None:
            s2 = score_card(merged_card, category, city)
            merged_card.confidence = round(s2["total"] / 100, 2)
            store.upsert_supplier(merged_card)
            bus.publish(job_id, "card_update", {"card": merged_card.model_dump(mode="json"), "score": s2, "verdict": verdict(s2["total"])})


async def _stage(job_id: str, key: str, label: str, progress: float) -> None:
    bus.publish(job_id, "stage", {"key": key, "label": label, "progress": progress, "ts": datetime.utcnow().isoformat()})


def merger_count(merger: Merger) -> int:
    return len(merger.all_cards())


def _find_updated(merger: Merger, identity_key: str):
    for card in merger.all_cards():
        if identity_key_for(card, card.website or "") == identity_key or card.identity_key == identity_key:
            return card
    return None
