"""Geo filter tests: RU-only sourcing. No network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.geo import is_ru_domain
from app.engines.base import Candidate
from app.engines.ranking import rank_candidates


def test_ru_tlds():
    assert is_ru_domain("mukomoloff.ru")
    assert is_ru_domain("moskva.tradedir.ru")
    assert is_ru_domain("example.su")
    assert is_ru_domain("xn--80aswg.xn--p1ai")  # сайт.рф


def test_foreign_tlds_rejected():
    assert not is_ru_domain("alibaba.com")
    assert not is_ru_domain("made-in-china.com")
    assert not is_ru_domain("example.org")
    assert not is_ru_domain("eu-supplier.de")


def test_ru_platforms_on_foreign_tld():
    assert is_ru_domain("supl.biz")
    assert is_ru_domain("foodbay.com")
    assert is_ru_domain("shop.foodbay.com")


def test_ranking_ru_only_filters_foreign():
    cands = [
        Candidate(url="https://mukomoloff.ru/", title="Мука оптом Москва", engine="ddg", domain="mukomoloff.ru"),
        Candidate(url="https://www.alibaba.com/trade/muka", title="Мука оптом supplier", engine="ddg", domain="www.alibaba.com"),
        Candidate(url="https://supl.biz/ru/muka", title="Мука опт", engine="ddg", domain="supl.biz"),
    ]
    ranked = rank_candidates(cands, "мука", "Москва", ru_only=True)
    domains = {c.domain for c in ranked}
    assert "mukomoloff.ru" in domains
    assert "supl.biz" in domains
    assert "www.alibaba.com" not in domains


def test_ranking_foreign_allowed_when_optin():
    cands = [
        Candidate(url="https://mukomoloff.ru/", title="Мука оптом Москва", engine="ddg", domain="mukomoloff.ru"),
        Candidate(url="https://www.alibaba.com/trade/muka", title="Мука оптом supplier", engine="ddg", domain="www.alibaba.com"),
    ]
    ranked = rank_candidates(cands, "мука", "Москва", ru_only=False)
    domains = {c.domain for c in ranked}
    assert "www.alibaba.com" in domains


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
