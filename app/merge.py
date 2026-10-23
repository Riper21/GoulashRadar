"""Identity resolution and card merging: INN -> phone -> normalized domain.

Conflicting field values are not hidden: freshest/high-coverage source wins,
conflicts are recorded in card.sources metadata for the UI.
"""
import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from .schema import SupplierCard, Phone, Email, SourceRef
from .validate import canonical_url

_DOMAIN_STOP = re.compile(r"^(www|opt|m|moskva|msk|spb|catalog|katalog|shop|ru|magazin|new|demo)\b", re.IGNORECASE)


def norm_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    host = host.replace("www.", "")
    # city subdomains on B2B directories belong to the same supplier base:
    # moskva.tradedir.ru -> tradedir.ru
    parts = host.split(".")
    if len(parts) > 2 and parts[0] in _CITY_SUBDOMAINS:
        parts = parts[1:]
    return ".".join(parts)


_CITY_SUBDOMAINS = {
    "moskva", "msk", "spb", "sankt-peterburg", "novosibirsk", "ekaterinburg", "kazan",
    "nnovgorod", "chelyabinsk", "samara", "rostov", "krasnodar", "voronezh", "perm",
    "volgograd", "ufa", "krasnoyarsk", "saratov", "tyumen", "tula", "omsk", "barnaul",
    "irkutsk", "kemerovo", "ryazan", "astrahan", "penza", "vladivostok", "yaroslavl",
}


def company_token(name: str) -> str:
    """Normalized 'company name' token: drop legal forms, punctuation, lowercase."""
    s = (name or "").lower()
    s = re.sub(r"(ооо|ао|зао|ип|оао|пао|оо|нпо|нии|фгуп|гуп)\b", " ", s)
    s = re.sub(r"[«»\"'`()\-–—.,!?/\\]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # drop short generic words
    words = [w for w in s.split() if len(w) > 2 and w not in ("опт", "том", "интернет", "магазин", "сайт")]
    return " ".join(words)


def identity_key_for(card: SupplierCard, fallback_domain: str) -> str:
    if card.inn:
        return f"inn:{card.inn}"
    if card.phones:
        return f"tel:{card.phones[0].e164 or card.phones[0].raw}"
    dom = norm_domain(card.website or fallback_domain)
    tok = company_token(card.name)
    if dom:
        return f"dom:{dom}"
    return f"name:{tok}"


def merge_cards(base: SupplierCard, extra: SupplierCard, seen_urls: set) -> Tuple[SupplierCard, List[str]]:
    """Merge extra into base. Returns merged card and list of conflict notes."""
    conflicts: List[str] = []
    merged = base.model_copy(deep=True)

    def take_single(field: str) -> None:
        bv = getattr(base, field)
        ev = getattr(extra, field)
        if ev and not bv:
            setattr(merged, field, ev)
        elif ev and bv and str(ev).strip() != str(bv).strip():
            conflicts.append(f"{field}: «{bv}» / «{ev}»")

    take_single("inn")
    take_single("website")
    take_single("address")
    take_single("city")
    take_single("region")
    take_single("min_order")
    take_single("price_range")
    take_single("delivery")

    # lists: union, keep order base-first
    seen_p = {p.e164 or p.raw for p in merged.phones}
    for p in extra.phones:
        k = p.e164 or p.raw
        if k not in seen_p:
            merged.phones.append(p)
            seen_p.add(k)
    seen_e = {e.address for e in merged.emails}
    for e in extra.emails:
        if e.address not in seen_e:
            merged.emails.append(e)

    seen_c = {c.lower() for c in merged.certs}
    for c in extra.certs:
        if c.lower() not in seen_c:
            merged.certs.append(c)
    seen_cat = {c.lower() for c in merged.categories}
    for c in extra.categories:
        if c.lower() not in seen_cat:
            merged.categories.append(c)

    # name: prefer longer (usually more complete)
    if len(extra.name) > len(merged.name) + 3:
        merged.name = extra.name

    # sources: union by url
    for src in extra.sources:
        if src.url not in seen_urls:
            merged.sources.append(src)
            seen_urls.add(src.url)

    merged.extracted_at = datetime.utcnow()
    return merged, conflicts


class Merger:
    """Accumulates cards for one job, resolves identity, emits merged cards."""

    def __init__(self):
        self._by_key: dict = {}
        self._by_domain: dict = {}
        self._by_phone: dict = {}
        self._by_inn: dict = {}
        self._conflicts: List[str] = []

    def add(self, card: SupplierCard) -> Optional[SupplierCard]:
        """Add card. Returns merged card if this is a NEW identity, else None (absorbed)."""
        key = identity_key_for(card, card.website or "")
        dom = norm_domain(card.website or "")
        inn = card.inn
        phone = (card.phones[0].e164 if card.phones else None)

        # find existing identity: INN match is strongest
        existing = None
        if inn and inn in self._by_inn:
            existing = self._by_inn[inn]
        elif phone and phone in self._by_phone:
            existing = self._by_phone[phone]
        elif dom and dom in self._by_domain:
            existing = self._by_domain[dom]

        if existing is not None:
            seen_urls = {s.url for s in existing.sources}
            merged, conf = merge_cards(existing, card, seen_urls)
            self._conflicts.extend(conf)
            self._reindex(merged)
            return None  # absorbed into existing; UI update handled by re-emission

        # new identity
        self._by_key[key] = card
        if inn:
            self._by_inn[inn] = card
        if phone:
            self._by_phone[phone] = card
        if dom:
            self._by_domain[dom] = card
        return card

    def _reindex(self, merged: SupplierCard) -> None:
        key = identity_key_for(merged, merged.website or "")
        self._by_key[key] = merged
        dom = norm_domain(merged.website or "")
        if dom:
            self._by_domain[dom] = merged
        if merged.inn:
            self._by_inn[merged.inn] = merged
        if merged.phones:
            self._by_phone[merged.phones[0].e164 or merged.phones[0].raw] = merged

    def all_cards(self) -> List[SupplierCard]:
        return list(self._by_key.values())

    def conflicts(self) -> List[str]:
        return self._conflicts
