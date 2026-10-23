"""Transparent scoring: why this supplier ranks here. Breakdown shown in UI."""
from typing import List

from .schema import SupplierCard


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

    # 4) relevance (0-15): city match + category word in name
    r = 0
    if city and card.city and city.lower() in card.city.lower():
        r += 10
    cat_words = [w for w in (category or "").lower().split() if len(w) > 3]
    name_l = (card.name or "").lower() + " " + " ".join(card.categories or []).lower()
    if cat_words and any(w in name_l for w in cat_words):
        r += 5
    parts["relevance"] = min(r, 15)

    total = min(sum(parts.values()), 100)
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
