"""E2E cassette tests: parse saved SERP/pages, no network. Golden-set style.

Covers: DDG SERP parsing -> candidates; page extraction -> PageData fields.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIX = Path(__file__).parent / "fixtures" / "pages"

from app.engines.ddg import DDGEngine
from app.engines.ranking import rank_candidates
from app.extract.structured import extract_page


def test_ddg_cassette_parse():
    engine = DDGEngine()
    html = (FIX / "ddg_debug.html").read_text(encoding="utf-8")
    cands = engine._parse(html)
    assert len(cands) >= 5, f"expected >=5 candidates, got {len(cands)}"
    urls = [c.url for c in cands]
    assert all(u.startswith("http") for u in urls)
    # no ddg-internal links
    assert all("duckduckgo.com" not in u for u in urls)
    # mukomoloff is a real supplier site in this SERP
    assert any(
        "mukomoloff" in c.url or "muka" in c.url or "опт" in c.title.lower()
        for c in cands
    ), "SERP should contain supplier-ish results"


def test_ranking_filters_junk():
    engine = DDGEngine()
    html = (FIX / "ddg_debug.html").read_text(encoding="utf-8")
    cands = engine._parse(html)
    ranked = rank_candidates(cands, "мука", "Москва")
    assert len(ranked) > 0
    # junk domains must be filtered
    junk = ("youtube.com", "vk.com", "ozon.ru", "wikipedia.org")
    assert all(not any(c.domain == j or c.domain.endswith("." + j) for j in junk) for c in ranked)


def test_page_extraction_smoke():
    """Extract from a supplier page saved locally (uses ddg_debug as generic HTML)."""
    html = (FIX / "ddg_debug.html").read_text(encoding="utf-8")
    pd = extract_page(html, "https://html.duckduckgo.com/")
    # page must give something (title name or contacts) without crashing
    assert pd is not None


def run_pipeline_cassette():
    """Mini-golden: DDG cassette -> candidates -> ranked top exists."""
    engine = DDGEngine()
    html = (FIX / "ddg_debug.html").read_text(encoding="utf-8")
    cands = engine._parse(html)
    ranked = rank_candidates(cands, "мука", "Москва", limit=10)
    return cands, ranked


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
