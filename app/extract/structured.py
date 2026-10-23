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

    def to_card(self, cand: Candidate, job_city: str, category: str) -> SupplierCard:
        # city: ONLY what the page explicitly states; never the query city as a guess
        _ = job_city
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
            city=self.city,
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
                pd.city = _clean_city(str(a["addressLocality"]))
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
    r"(?:\bг\.|\bгород[аыу]?\b|\bгород(?:а|у)?\s+поставки\b)[\s:]*"
    # multi-word ("Нижний Новгород") and hyphenated ("Ростов-на-Дону", "Усолье-сибирское")
    r"([А-ЯЁ][а-яё]+(?:[-\s][А-ЯЁа-яё]+)*)",
    re.UNICODE,
)

# Known Russian cities (objective whitelist): text heuristics may ONLY pick from it.
# Anything else is not marked as a city — better empty than wrong ("Упаковка", "Жиры").
_RU_CITIES = {
    "москва", "санкт-петербург", "новосибирск", "екатеринбург", "казань",
    "нижний новгород", "челябинск", "самара", "омск", "ростов-на-дону", "уфа",
    "красноярск", "воронеж", "пермь", "волгоград", "краснодар", "саратов",
    "тюмень", "тольятти", "барнаул", "ижевск", "ульяновск", "иркутск",
    "хабаровск", "ярославль", "владивосток", "махачкала", "томск", "оренбург",
    "кемерово", "новокузнецк", "рязань", "астрахань", "набережные челны",
    "пенза", "липецк", "киров", "чебоксары", "тула", "калуга", "курск", "сочи",
    "ставрополь", "улан-удэ", "тверь", "магнитогорск", "иваново", "брянск",
    "севастополь", "нижний тагил", "архангельск", "владимир", "симферополь",
    "смоленск", "сургут", "вологда", "владикавказ", "грозный", "мурманск",
    "якутск", "ростов", "подольск", "петрозаводск", "каменск-уральский",
    "сыктывкар", "нижневартовск", "орск", "сызрань", "новочеркасск", "нижнекамск",
    "братск", "балаково", "обнинск", "нефтеюганск", "великий новгород",
    "старый оскол", "псков", "мытищи", "люберцы", "балашиха", "химки",
    "красногорск", "одинцово", "королёв", "домодедово", "сергиев посад",
    "пушкино", "раменское", "долгопрудный", "нальчик", "кисловодск",
    "новомосковск", "первоуральск", "невинномысск", "камышин", "орехово-зуево",
    "керчь", "дербент", "волгодонск", "белгород", "выборг", "саров", "дубна",
    "реутов", "коломна", "клин", "серпухов", "электросталь", "копейск",
    "миасс", "озерск", "снежинск", "верхняя пышма", "таганрог", "шахты",
    "батайск", "новошахтинск", "азов", "абакан", "канск", "ачинск",
    "лесосибирск", "железногорск", "зеленогорск", "дивногорск", "березники",
    "соликамск", "краснотурьинск", "каменск-шахтинский", "алметьевск",
    "ангарск", "усолье-сибирское", "черемхово", "шелехов", "нижнеудинск",
    "тайшет", "зима", "тулун", "усть-илимск", "берёзовский", "сосновоборск",
    "красноярск", "сатка", "южноуральск", "новороссийск", "геленджик",
}


def _clean_city(candidate: Optional[str]) -> Optional[str]:
    """City only if it is a known Russian city; else None (better empty than wrong).

    Regex may grab "Нижний Новгород и область" — longest known-city prefix wins.
    Inflected forms ("в г. Москве") are de-inflected before the whitelist lookup.
    """
    if not candidate:
        return None
    words = candidate.strip().split()
    if not words or len(words[0]) < 3 or not re.search(r"[А-ЯЁа-яё]", words[0]):
        return None
    # try longest-to-shortest word prefix, with case-ending fallback on the last word
    for n in range(len(words), 0, -1):
        base = " ".join(words[:n])
        if base.lower() in _RU_CITIES:
            return base
        stem = _deinflect(base)
        if stem and stem.lower() in _RU_CITIES:
            return stem
    return None


def _deinflect(city: str) -> Optional[str]:
    """Crude Russian case mapping: "Москве"->"Москва", "Тюмени"->"Тюмень".
    Only returns a form that IS in the whitelist — never invents a city."""
    w = city.split()
    last = w[-1]
    for end, repl in (("ии", "ия"), ("ии", "ий"), ("ени", "ень"), ("е", "а"), ("и", "а"), ("у", "а"), ("е", ""), ("и", ""), ("у", ""), ("и", "ь"), ("е", "ь")):
        if last.endswith(end) and len(last) - len(end) >= 3:
            cand = " ".join(w[:-1] + [last[: len(last) - len(end)] + repl])
            if cand.lower() in _RU_CITIES:
                return cand
    return None


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
