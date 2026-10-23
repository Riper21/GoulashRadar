"""Candidate ranking: filter junk, boost B2B directories and match signals."""
from urllib.parse import urlparse

from .base import Candidate
from ..geo import is_ru_domain

# domains that never contain supplier info
JUNK_DOMAINS = {
    "youtube.com", "vk.com", "facebook.com", "instagram.com", "t.me", "telegram.me",
    "yandex.ru", "ya.ru", "mail.ru", "ok.ru", "dzen.ru", "pikabu.ru", "reddit.com",
    "wikipedia.org", "ozon.ru", "wildberries.ru", "avito.ru", "youtube-nocookie.com",
    "linkedin.com", "x.com", "twitter.com", "pinterest.com", "tiktok.com",
}

# B2B directories with structured supplier pages — higher trust
B2B_DOMAINS = {
    "pulscen.ru": 3, "tiu.ru": 3, "supl.biz": 3, "opt-union.ru": 3, "foodbay.com": 3,
    "agroserver.ru": 3, "prodgid.ru": 2, "b2b-center.ru": 2, "supplier.ru": 2,
    "2gis.ru": 2, "orgpage.ru": 2, "firma.gov.ru": 2, "checko.ru": 2, "rusprofile.ru": 2,
    "list-org.com": 2, "yandex.ru": -3, "yell.ru": 2, "flamp.ru": 1,
}

# URL patterns typical for supplier/org pages
SUPPLIER_URL_HINTS = (
    "/company", "/catalog", "/supplier", "/org/", "/firm/", "/postavshhik",
    "/products", "/o-kompanii", "/about", "/kontakty", "/contacts",
)

STOP_WORDS = ("вакансии", "новости", "статьи", "блог", "форум", "отзыв")


def rank_candidates(cands: list, category: str, city: str, limit: int = 40, ru_only: bool = True) -> list:
    """Score and filter candidates, return top-N sorted by score.

    ru_only=True (default): keep only RF resources — .ru/.su/.рф TLDs plus
    known RU B2B platforms on foreign TLDs (see app/geo.py).
    """
    scored = []
    cat_words = [w for w in category.lower().split() if len(w) > 2]
    city_l = (city or "").lower()

    for c in cands:
        domain = c.domain
        if domain in JUNK_DOMAINS:
            continue
        if any(domain == j or domain.endswith("." + j) for j in JUNK_DOMAINS):
            continue
        if ru_only and not is_ru_domain(domain):
            continue

        score = 0.0
        # B2B directory bonus
        for d, bonus in B2B_DOMAINS.items():
            if domain == d or domain.endswith("." + d):
                score += bonus
                break

        # title relevance
        title_l = (c.title or "").lower()
        for w in cat_words:
            if w in title_l:
                score += 1.5
            if w in c.url.lower():
                score += 0.5
        if city_l and city_l in title_l:
            score += 0.75
        if "опт" in title_l or "оптов" in c.url.lower() or "supplier" in c.url.lower():
            score += 0.5
        if "поставщик" in title_l:
            score += 1.0

        # supplier-ish URL structure
        url_l = c.url.lower()
        if any(h in url_l for h in SUPPLIER_URL_HINTS):
            score += 0.5
        if any(s in url_l or s in title_l for s in STOP_WORDS):
            score -= 1.5

        # multiple engines found same domain — trust signal
        if score > 0:
            scored.append((score, c))

    # de-dup by domain+path, keep best score per exact URL
    seen = set()
    best = []
    for score, c in sorted(scored, key=lambda x: -x[0]):
        if c.url in seen:
            continue
        seen.add(c.url)
        best.append((score, c))
        if len(best) >= limit:
            break
    return [c for _, c in best]
