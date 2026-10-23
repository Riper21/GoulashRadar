"""Name cleanup: turn SEO page titles into company names."""
import re

_JUNK_PATTERNS = [
    r"купить\s+.*$", r"продажа\s+.*$", r"цена.*$", r"от\s+производителя.*$",
    r"оптом\s+в\s+.*$", r"\bв\s+наличии\b.*$", r"со\s+скидкой.*$", r"акция.*$",
    r"интернет[- ]магазин\s+(официальный\s+)?сайт", r"официальный\s+сайт.*$",
    r"\s+[-–—|]\s+[^–—|]*$",  # trailing « — сайт» / « | каталог» (spaces around separator)
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _JUNK_PATTERNS]

_LEGAL = re.compile(r"^(ООО|ОАО|ЗАО|ПАО|АО|ИП|НПО|ФГУП|ГУП)\b[«\s\"]*", re.IGNORECASE)


def clean_name(raw: str, domain: str = "") -> str:
    name = (raw or "").strip()
    for pat in _COMPILED:
        name = pat.sub("", name).strip(" -–—|.")
    if not name and domain:
        name = domain.replace("www.", "").split(".")[0]
    # normalize legal form: ООО «Ромашка»
    m = _LEGAL.match(name)
    if m and "«" not in name:
        pass  # keep as is
    return name[:80] if name else (domain or "Поставщик")


def shop_name_from_domain(domain: str) -> str:
    host = (domain or "").replace("www.", "").split(".")[0]
    return host[:40] if host else "Поставщик"
