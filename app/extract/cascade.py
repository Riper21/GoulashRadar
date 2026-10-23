"""Extract cascade: adapter -> structured+heuristics -> LLM (budgeted, evidence-verified)."""
from typing import Optional

from ..engines.base import Candidate
from ..fetch.http import fetch_page
from .adapters.b2b import adapter_for
from .structured import extract_page, PageData
from .llm import llm_extract


async def extract_candidate(cand: Candidate, job_stats: Optional[dict] = None, force: bool = False) -> Optional[tuple]:
    """Fetch page and extract PageData. Returns (PageData, html) or None if page unusable.

    job_stats=None skips the LLM level — orchestrator runs it as a separate
    parallel batch (see llm_batch in orchestrator) to control wall-clock time.
    Legacy mode (job_stats dict) still runs LLM inline with a wait cap.
    force=True re-downloads the page, bypassing the page cache.
    """
    html = await fetch_page(cand.url, force=force)
    if not html:
        return None

    adapter = adapter_for(cand.url)
    if adapter:
        try:
            pd = adapter.parse(html, cand.url)
            if pd.coverage() < 0.3:
                pd = extract_page(html, cand.url)
        except Exception:
            pd = extract_page(html, cand.url)
    else:
        pd = extract_page(html, cand.url)

    # inline LLM level (legacy path): only when caller passes stats and coverage is low
    if job_stats is not None and pd.coverage() < 0.5:
        try:
            import asyncio

            from ..config import CONFIG

            llm_wait = min(CONFIG.llm.timeout_s, CONFIG.job_deadline_s / 3)
            llm_pd = await asyncio.wait_for(llm_extract(html, job_stats), timeout=llm_wait)
        except asyncio.TimeoutError:
            job_stats["llm_timeouts"] = job_stats.get("llm_timeouts", 0) + 1
            llm_pd = None
        except Exception:
            llm_pd = None
        if llm_pd is not None:
            pd = _combine(pd, llm_pd)

    # a page must give at least a name or contact to become a card
    if not pd.name and not pd.phones and not pd.emails:
        return None
    return pd, html


def llm_combine(base: PageData, llm_pd: Optional[PageData]) -> PageData:
    """Combine heuristic result with LLM result; base wins on conflicts."""
    if llm_pd is None:
        return base
    return _combine(base, llm_pd)


def _combine(base: PageData, llm_pd: PageData) -> PageData:
    """LLM result fills the gaps in base; base wins on conflicts (deterministic first)."""
    out = PageData()
    for field in (
        "name", "website", "address", "city", "region",
        "inn", "min_order", "price_range", "delivery",
    ):
        setattr(out, field, getattr(base, field) or getattr(llm_pd, field))
    out.phones = (base.phones + [p for p in llm_pd.phones if p not in base.phones])[:3]
    out.emails = (base.emails + [e for e in llm_pd.emails if e not in base.emails])[:3]
    out.certs = (base.certs + [c for c in llm_pd.certs if c not in base.certs])[:5]
    out.categories = (base.categories + [c for c in llm_pd.categories if c not in base.categories])[:5]
    return out
