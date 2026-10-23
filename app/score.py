"""Transparent scoring: why this supplier ranks here. Breakdown shown in UI."""
from typing import List

from .schema import SupplierCard

# category keyword sets: one row = one food group, used as a relevance gate
_CAT_KEYWORDS = {
    "мука": ("мука", "мукомол", "крупа", "отруби", "крахмал", "bakery", "хлебопекар"),
    "кофе": ("кофе", "roast", "обжар", "бариста", "espresso"),
    "чай": ("чай", "tea"),
    "какао": ("какао", "шоколад", "кондитер", "chocolate"),
    "сахар": ("сахар", "sugar"),
    "масло": ("масло", "oil", "жир"),
    "сыр": ("сыр", "cheese", "молоч"),
    "молоч": ("молок", "молоч", "dairy"),
    "мяс": ("мяс", "meat", "птиц", "колбас"),
    "рыб": ("рыб", "fish", "морепродукт"),
    "овощ": ("овощ", "фрукт", "vegetable", "fruit", "плодоовощ"),
    "упаков": ("упаков", "пакет", "мешок", "коробк", "тара", "pack"),
    "специ": ("специ", "приправ", "пряност", "spice"),
    "напит": ("напит", "вод", "juice", "сок"),
    "консерв": ("консерв", "пресерв"),
}

# strong "wrong business" markers — hard penalty, not a gate (goods may be adjacent)
_WRONG_BUSINESS = (
    "одежд", "швей", "трикотаж", "обув", "мебел", "хозтовар", "отпугивател",
    "канцеляр", "строител", "автозапчаст", "зоотовар", "инструмент", "хим",
)


def _cat_keywords(category: str):
    """Keyword tuples whose root matches the query category (e.g. мука -> мука/мукомол...)."""
    cat = (category or "").lower()
    hits = []
    for root, kws in _CAT_KEYWORDS.items():
        if root in cat or any(kw in cat for kw in (root,)):
            hits.extend(kws)
    # always include the raw query words themselves
    hits.extend(w for w in cat.split() if len(w) > 3)
    return hits or [w for w in cat.split() if len(w) > 2]


def score_card(card: SupplierCard, category: str, city: str) -> dict:
    """Returns {'total': 0..100, 'parts': {...}} — every part explainable."""
    parts = {}

    # 1) data completeness (0-40)
    parts["completeness"] = round(card.completeness() * 40)

    # 2) verifiability (0-30): INN valid, has site, multiple sources
    v = 0
    if card.inn:
        v += 12
    if card.website:
        v += 8
    if len(card.sources) >= 2:
        v += 10
    parts["verifiability"] = min(v, 30)

    # 3) contacts (0-15): phone and email = ready to reach out
    c = 0
    if card.phones:
        c += 10
    if card.emails:
        c += 5
    parts["contacts"] = c

    # 4) relevance (0-15): city match + category match in name/categories
    r = 0
    if city and card.city and city.lower() in card.city.lower():
        r += 10
    cat_l = (category or "").lower()
    text_l = ((card.name or "") + " " + " ".join(card.categories or [])).lower()
    kws = _cat_keywords(category)
    kw_hit = sum(1 for kw in kws if kw and kw in text_l)
    if kw_hit:
        r += 5
    parts["relevance"] = min(r, 15)

    # 5) off-topic penalty: clothing/household/etc. shop in a food search
    wrong = sum(1 for w in _WRONG_BUSINESS if w in text_l)
    if wrong:
        parts["relevance"] = 0
        parts["off_topic"] = -min(10 * wrong, 35)

    total = min(max(sum(parts.get(k, 0) for k in ("completeness", "verifiability", "contacts", "relevance")) + parts.get("off_topic", 0), 0), 100)
    return {"total": total, "parts": parts}


VERDICTS = [
    (70, "Отличная кандидатура — можно связываться"),
    (50, "Хороший вариант, проверьте детали"),
    (30, "Данных мало — сверьтесь с источником"),
    (0, "Низкая полнота — используйте как запасной"),
]


def verdict(total: int) -> str:
    for threshold, label in VERDICTS:
        if total >= threshold:
            return label
    return VERDICTS[-1][1]


def rank_cards(cards: List[SupplierCard], category: str, city: str) -> List[dict]:
    """Cards with score attached, sorted by total desc."""
    scored = []
    for card in cards:
        s = score_card(card, category, city)
        scored.append({"card": card, "score": s["total"], "parts": s["parts"], "verdict": verdict(s["total"])})
    scored.sort(key=lambda x: -x["score"])
    return scored
