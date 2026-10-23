"""Extraction level 2-3: JSON-LD / OpenGraph / meta + text heuristics. No LLM."""
import json
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from ..schema import SupplierCard, Phone, Email, SourceRef
from ..validate import (
    extract_emails, extract_inn, extract_phones, extract_price_range,
    extract_min_order, extract_certs, canonical_url, normalize_phone,
)
from ..engines.base import Candidate
from datetime import datetime


class PageData:
    """Everything we can pull from one page without LLM."""

    def __init__(self):
        self.name: Optional[str] = None
        self.phones: List[str] = []
        self.emails: List[str] = []
        self.website: Optional[str] = None
        self.address: Optional[str] = None
        self.city: Optional[str] = None
        self.region: Optional[str] = None
        self.inn: Optional[str] = None
        self.min_order: Optional[str] = None
        self.price_range: Optional[str] = None
        self.delivery: Optional[str] = None
        self.certs: List[str] = []
        self.categories: List[str] = []

    def coverage(self) -> float:
        fields = [
            self.name, self.phones, self.emails, self.website, self.address,
            self.inn, self.min_order, self.price_range, self.delivery, self.certs,
        ]
        filled = sum(1 for f in fields if f)
        return filled / len(fields)

    def to_card(self, cand: Candidate, fallback_city: str, category: str) -> SupplierCard:
        sources = [SourceRef(url=cand.url, engine=cand.engine, fetched_at=datetime.utcnow())]
        website = self.website or f"https://{cand.domain}"
        name = self.name or (cand.title.split("|")[0].split("—")[0].strip() or cand.domain)
        # normalize + dedup phones: JSON-LD may hold raw "-812-467-88-66" forms
        norm_phones: List[Phone] = []
        seen_e164 = set()
        for p in self.phones[:6]:
            e164 = normalize_phone(p) or p
            if e164 in seen_e164:
                continue
            seen_e164.add(e164)
            norm_phones.append(Phone(raw=p, e164=e164))
        return SupplierCard(
            name=name[:150],
            inn=self.inn,
            identity_key=website,
            phones=norm_phones[:3],
            emails=[Email(address=e) for e in self.emails[:3]],
            website=website,
            address=self.address,
            city=self.city or fallback_city,
            region=self.region,
            min_order=self.min_order,
            price_range=self.price_range,
            delivery=self.delivery,
            certs=self.certs[:5],
            categories=list({c for c in ([category] + self.categories) if c})[:5],
            sources=sources,
            confidence=round(0.25 + 0.75 * self.coverage(), 3),
        )


# ---------- JSON-LD / OG / meta ----------

_ORG_TYPES = ("Organization", "LocalBusiness", "Store", "Corporation", "FoodEstablishment")


def _fmt_price(amount, currency: str) -> Optional[str]:
    try:
        v = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if v <= 0 or v > 10_000_000:  # sanity: retail/opt prices only
        return None
    s = f"{v:g} руб."
    return s


def _price_from_structured(soup) -> Optional[str]:
    """Price from a product page's machine-readable markup, not free text.

    Priority: JSON-LD Product.offers > microdata itemprop=price > og:price.
    Returns the first plausible price ('NNNN руб.') or None.
    """
    # 1) JSON-LD Product -> offers (offers may be a dict or a list)
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        products = []
        _walk_jsonld(data, products, wanted="Product")
        for prod in products:
            offers = prod.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if isinstance(offers, list):
                for off in offers:
                    if not isinstance(off, dict):
                        continue
                    p = off.get("price") or off.get("lowPrice")
                    if p is not None:
                        cur = str(off.get("priceCurrency") or "RUB")
                        if cur.upper() in ("RUB", "RUR", "₽"):
                            r = _fmt_price(p, cur)
                            if r:
                                return r
    # 2) microdata itemprop="price" (content attr or tag text)
    for el in soup.find_all(attrs={"itemprop": "price"}):
        p = el.get("content") or el.get_text(strip=True)
        r = _fmt_price(p, "RUB")
        if r:
            return r
    # 3) og:price / product:price:amount
    for prop in ("og:price:amount", "product:price:amount", "og:price"):
        og = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if og and og.get("content"):
            r = _fmt_price(og["content"], "RUB")
            if r:
                return r
    return None


def _walk_jsonld(node, out: List[dict], wanted: str = "org"):
    """Collect nodes of the wanted kind: 'org' (org/business) or 'Product'."""
    if isinstance(node, list):
        for item in node:
            _walk_jsonld(item, out, wanted)
        return
    if isinstance(node, dict):
        t = node.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if wanted == "Product":
            if "Product" in [str(x) for x in types]:
                out.append(node)
        else:
            if any(any(ot in str(x) for x in types) for ot in _ORG_TYPES):
                out.append(node)
        if "@graph" in node:
            _walk_jsonld(node["@graph"], out, wanted)


def from_structured(html: str, base_url: str) -> PageData:
    pd = PageData()
    soup = BeautifulSoup(html, "lxml")

    # JSON-LD
    orgs: List[dict] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        _walk_jsonld(data, orgs)
    for org in orgs[:3]:
        if not pd.name:
            pd.name = org.get("name")
        if not pd.website:
            url = org.get("url")
            if isinstance(url, str) and url.startswith("http"):
                pd.website = canonical_url(url)
        if not pd.address:
            a = org.get("address")
            if isinstance(a, dict):
                pd.address = ", ".join(
                    str(v) for k, v in a.items()
                    if k in ("postalCode", "addressLocality", "streetAddress", "addressRegion") and v
                )
            elif isinstance(a, str):
                pd.address = a
        if not pd.city:
            a = org.get("address")
            if isinstance(a, dict) and a.get("addressLocality"):
                pd.city = str(a["addressLocality"])
        for tel in (org.get("telephone") if isinstance(org.get("telephone"), list) else [org.get("telephone")]):
            if isinstance(tel, str) and tel:
                pd.phones.append(tel)
        for em in (org.get("email") if isinstance(org.get("email"), list) else [org.get("email")]):
            if isinstance(em, str) and em:
                pd.emails.append(em)

    # OpenGraph
    if not pd.name:
        og = soup.find("meta", property="og:site_name")
        if og and og.get("content"):
            pd.name = og["content"].strip()
    if not pd.website:
        og = soup.find("meta", property="og:url")
        if og and og.get("content") and og["content"].startswith("http"):
            pd.website = canonical_url(og["content"])

    # product price: JSON-LD Product.offers, microdata itemprop, og:price
    if not pd.price_range:
        pd.price_range = _price_from_structured(soup)

    # meta description -> commercial fields
    desc = soup.find("meta", attrs={"name": "description"})
    desc_text = desc.get("content", "") if desc else ""
    title_text = soup.title.string if soup.title and soup.title.string else ""

    text_probe = f"{title_text} {desc_text}"
    if not pd.inn:
        pd.inn = extract_inn(text_probe)
    if not pd.min_order:
        pd.min_order = extract_min_order(text_probe)
    if not pd.price_range:
        pd.price_range = extract_price_range(text_probe)
    if not pd.certs:
        pd.certs = extract_certs(text_probe)
    pd.phones.extend(extract_phones(text_probe))
    pd.emails.extend(extract_emails(text_probe))

    return pd


# ---------- heuristics over visible text ----------

_SKIP_TAGS = ("script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form")

_DELIVERY_RE = re.compile(
    r"((?:бесплатн\w+|платн\w+|[а-яё]+)[ ,]*){0,3}доставк[ауы]\w*"
    r"(?:[^.!?;]{0,80})|самовывоз\w*[^.!?;]{0,40}"
    r"|(?:СДЭК|Деловы[еи][ ]линии|ПЭК|Pony Express|DPD|dims24|желдор\w+)"
    r"[^.!?;]{0,50}",
    re.IGNORECASE,
)
_CITY_HINT_RE = re.compile(
    r"(?:\bг\.|\bгород[а]?\b)\s*([А-ЯЁ][а-яё-]{2,}(?:-[А-ЯЁ][а-яё-]{2,})?)", re.UNICODE
)

# nav-menu words that _CITY_HINT_RE mistakes for city names after "город"-like contexts
_NOT_A_CITY = {
    "женская", "женск", "мужская", "мужск", "оптовикам", "оптовая", "розница",
    "прайс", "контакты", "каталог", "доставка", "официальный", "сайте",
    "статьи", "новости", "отзывы", "акции", "скидки", "производства",
    "куплю", "продам", "применение", "услуги", "вакансии", "режим",
    # countries / regions, not cities
    "россии", "россия", "москве", "москвы", "питер", "спб",
    # nutrition-table words (matched after "NN г")
    "жиры", "белки", "углеводы", "калорийность",
    "миндаль", "грецкий", "фисташка", "смесь", "макадамия", "уведомить",
}


def _clean_city(candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return None
    c = candidate.strip()
    if c.lower() in _NOT_A_CITY:
        return None
    # city names are 3+ chars, start uppercase; reject hyphen-only/numeric junk
    if len(c) < 3 or not re.search(r"[А-ЯЁа-яё]", c):
        return None
    return c


def from_heuristics(html: str, pd: PageData, limit: int = 6000) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_SKIP_TAGS):
        tag.decompose()
    text = soup.get_text(" ", strip=True)[: limit * 2]

    if not pd.inn:
        pd.inn = extract_inn(text)
    for p in extract_phones(text):
        if p not in pd.phones:
            pd.phones.append(p)
    for e in extract_emails(text):
        if e not in pd.emails:
            pd.emails.append(e)
    if not pd.min_order:
        pd.min_order = extract_min_order(text)
    if not pd.price_range:
        pd.price_range = extract_price_range(text)
    if not pd.certs:
        pd.certs = extract_certs(text)
    if not pd.delivery:
        m = _DELIVERY_RE.search(text)
        if m:
            snippet = m.group(0).strip()
            # normalize whitespace: CSV cells must be single-line
            snippet = re.sub(r"\s+", " ", snippet)
            if 10 <= len(snippet) <= 120:
                pd.delivery = snippet
    if not pd.city:
        m = _CITY_HINT_RE.search(text)
        if m:
            pd.city = _clean_city(m.group(1))
    return pd


def extract_page(html: str, base_url: str) -> PageData:
    """Levels 2+3 combined: structured then heuristics fill the gaps."""
    pd = from_structured(html, base_url)
    pd = from_heuristics(html, pd)
    pd.phones = pd.phones[:3]
    pd.emails = pd.emails[:3]
    return pd


def page_text_for_llm(html: str, limit: int = 12000, smart: bool = True) -> str:
    """Clean visible text (markdown-ish) for the LLM level. Script/nav stripped.

    smart=True: compress to contact/offer-rich windows instead of a plain head cut.
    Long flat text makes slow LLM endpoints unusable (50+ s); 3–4K chars of the
    right slices keep the extraction both fast and complete.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_SKIP_TAGS):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    if not smart or len(text) <= limit:
        return text[:limit]

    # score 200-char windows by contact/commercial density, take best, keep order
    keys = (
        "тел", "фон", "phone", "@", "инн", "огрн", "адрес", "ул.", "д.",
        "заказ", "опт", "парти", "цена", "руб", "доставк", "минимал",
        "сертификат", "хассп", "iso", "деклар",
    )
    win = 200
    step = 150
    windows = []
    for start in range(0, len(text) - win + 1, step):
        chunk = text[start : start + win].lower()
        score = sum(chunk.count(k) for k in keys)
        windows.append((score, start))
    windows.sort(key=lambda x: -x[0])

    # head of the page often holds the name+contacts — always include
    chosen = {0}
    covered = 0
    for score, start in windows:
        if covered >= limit:
            break
        if any(abs(start - s) < win for s in chosen):
            continue  # overlapping window
        chosen.add(start)
        covered += win
    merged = sorted(chosen)
    parts = []
    prev_end = None
    for s in merged:
        seg = text[s : s + win]
        if prev_end is not None and s <= prev_end + step:
            parts[-1] = parts[-1][:-1] + " " + seg  # contiguous: join seamlessly
        else:
            parts.append(seg)
        prev_end = s + win
    return " … ".join(parts)[:limit]
