"""Geo filter: RU-only sourcing by default, foreign as opt-in.

RU criteria:
  - TLD .ru / .su / .рф (punycode xn--p1ai), incl. second-level zones (.msk.ru etc.)
  - known RU B2B platforms hosted on foreign TLDs (supl.biz, foodbay.com, ...)
"""
from urllib.parse import urlparse

# top-level zones of Russia
RU_TLDS = {".ru", ".su", ".рф", "xn--p1ai"}

# RU B2B directories that live on foreign TLDs — still RF sourcing
RU_PLATFORM_DOMAINS = {
    "supl.biz",       # российский B2B-каталог поставщиков
    "foodbay.com",    # RU food B2B
    "seller-market.com",  # RU marketplace каталог (проверяется контентом)
    "b2b-shop.ru",
}

_RU_TLD_SUFFIXES = (".ru", ".su", ".xn--p1ai")


def is_ru_domain(domain: str) -> bool:
    """True if the domain points to an RF resource (TLD or known RU platform)."""
    d = (domain or "").lower().strip()
    if not d:
        return False
    if d.endswith(_RU_TLD_SUFFIXES):
        return True
    # punycode whole-label .рф: e.g. xn--80aswg.xn--p1ai
    if d.endswith(".xn--p1ai"):
        return True
    for p in RU_PLATFORM_DOMAINS:
        if d == p or d.endswith("." + p):
            return True
    return False


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""
