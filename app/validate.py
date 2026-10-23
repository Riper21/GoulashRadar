"""Deterministic validators: INN checksum, phone E.164, URL canonicalization, price sanity."""
import re
from typing import List, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# ---------- INN ----------

def _inn_checksum(digits: List[int], weights: List[int]) -> int:
    s = sum(d * w for d, w in zip(digits, weights))
    return s % 11 % 10


def valid_inn(inn: str) -> bool:
    inn = re.sub(r"\D", "", inn or "")
    if len(inn) == 10:
        d = [int(c) for c in inn]
        return _inn_checksum(d[:9], [2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    if len(inn) == 12:
        d = [int(c) for c in inn]
        ok1 = _inn_checksum(d[:10], [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
        ok2 = _inn_checksum(d[:11], [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11]
        return ok1 and ok2
    return False


INN_RE = re.compile(r"\b(?:ИНН|Inn)\s*[:\-—]?\s*(\d{10}|\d{12})\b", re.IGNORECASE)
INN_BARE_RE = re.compile(r"\b(\d{10}|\d{12})\b")


def extract_inn(text: str) -> Optional[str]:
    m = INN_RE.search(text)
    if m and valid_inn(m.group(1)):
        return m.group(1)
    for m in INN_BARE_RE.finditer(text):
        if valid_inn(m.group(1)):
            return m.group(1)
    return None


# ---------- phones ----------

_PHONE_CORE = re.compile(r"(?:\+?7|8)[\s\-(]*(\d{3})[\s\)-]*(\d{3})[\s\-(]*(\d{2})[\s\)-]*(\d{2})")


def normalize_phone(raw: str) -> Optional[str]:
    m = _PHONE_CORE.search(raw or "")
    if not m:
        return None
    e164 = "+7" + "".join(m.groups())
    return e164


def extract_phones(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for m in _PHONE_CORE.finditer(text):
        e164 = "+7" + "".join(m.groups())
        if e164 not in seen:
            seen.add(e164)
            out.append(e164)
    return out


# ---------- emails ----------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_emails(text: str) -> List[str]:
    seen = {}
    for m in _EMAIL_RE.finditer(text):
        addr = m.group(0).lower().strip(".")
        if addr not in seen:
            seen[addr] = True
    return list(seen)


# ---------- URLs ----------

_JUNK_PARAMS = ("utm_", "yclid", "gclid", "from", "fbclid", "_openstat", "etext")


def canonical_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
    except Exception:
        return url
    scheme = "https"
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    q = [(k, v) for k, v in parse_qsl(p.query) if not any(k.startswith(j) for j in _JUNK_PARAMS)]
    return urlunparse((scheme, netloc, path, "", urlencode(q), ""))


def safe_ext_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


# ---------- commercial fields ----------

_PRICE_RE = re.compile(
    r"(?:от|по)\s*([\d\s\u00a0.,]{1,12})\s*(?:₽|руб\.?|рублей|р\.)"
    r"(?:\s*(?:/|за)\s*(кг|шт|л|уп|литр|тонн\w*|т\.?|палет\w*|коробк\w*))?"
    r"|(?:[\d\s\u00a0.,]{2,12})\s*(?:₽|руб\.?|рублей)\s*(?:/|за)\s*(кг|шт|л|уп|литр|тонн\w*|т\.?|палет\w*|коробк\w*)",
    re.IGNORECASE,
)
_MIN_ORDER_RE = re.compile(
    r"мин(?:\.|имал\w+)?\s*(?:(?:объ[её]м|парти|заказ)\w*\s*){0,2}[:\-—–]?\s*(?:от\s*)?([\d\s\u00a0.,]{1,12})\s*(кг|т|тонн\w*|шт|л|уп|ящик\w*|палет\w*|руб\.?|₽|тыс\.?|р\.)",
    re.IGNORECASE,
)
_CERTS_HINTS = [
    "хассп", "haccp", "декларация еаэс", "сертификат соответствия",
    "iso 22000", "iso9001", "iso 9001", "ветеринарн", "молот", "система качества",
    "халал", "kosher", "кошер", "без гмо", "organic", "сертификат халяль",
]


def extract_price_range(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text)
    if not m:
        return None
    return m.group(0).strip()


def extract_min_order(text: str) -> Optional[str]:
    m = _MIN_ORDER_RE.search(text)
    if not m:
        return None
    return m.group(0).strip()


def extract_certs(text: str) -> List[str]:
    tl = text.lower()
    found = []
    for hint in _CERTS_HINTS:
        if hint in tl:
            found.append(hint.strip().upper() if len(hint) <= 5 else hint.strip().title())
    return found
