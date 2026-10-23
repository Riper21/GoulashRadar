"""Unit tests for merge/identity resolution. No network."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.merge import Merger, identity_key_for, company_token
from app.schema import SupplierCard, Phone, Email, SourceRef


def _card(name, key=None, inn=None, phones=(), website=None, city=None, min_order=None):
    return SupplierCard(
        name=name,
        identity_key=key or f"k-{name}",
        inn=inn,
        phones=[Phone(raw=p, e164=p) for p in phones],
        emails=[Email(address="a@b.ru")],
        website=website,
        city=city,
        min_order=min_order,
        categories=["мука"],
        sources=[SourceRef(url=website or "https://x.ru", engine="ddg", fetched_at=datetime.utcnow())],
    )


def test_identity_by_inn():
    c = _card("ООО Ромашка", inn="7707083893", website="https://romashka.ru")
    assert identity_key_for(c, "") == "inn:7707083893"


def test_identity_by_phone():
    c = _card("Ромашка", phones=["+74951234567"], website="https://romashka.ru")
    assert identity_key_for(c, "") == "tel:+74951234567"


def test_identity_by_domain():
    c = _card("Ромашка", website="https://www.romashka.ru/catalog")
    assert identity_key_for(c, "") == "dom:romashka.ru"


def test_merge_same_inn():
    m = Merger()
    a = _card("ООО Ромашка", inn="7707083893", website="https://romashka.ru", min_order=None, city="Москва")
    b = _card("Ромашка — мука оптом", inn="7707083893", website="https://romashka-muka.ru", min_order="от 500 кг")
    new_a = m.add(a)
    new_b = m.add(b)
    assert new_a is not None
    assert new_b is None  # absorbed
    cards = m.all_cards()
    assert len(cards) == 1
    assert cards[0].min_order == "от 500 кг"
    assert cards[0].city == "Москва"
    assert len(cards[0].sources) == 2


def test_merge_same_domain_union_phones():
    m = Merger()
    a = _card("Мельница", website="https://muka.ru", phones=["+74951234567"])
    b = _card("Мельница комбинат", website="https://muka.ru/opt", phones=["+74991112233"])
    m.add(a)
    m.add(b)
    cards = m.all_cards()
    assert len(cards) == 1
    assert len(cards[0].phones) == 2
    # longer name wins
    assert cards[0].name == "Мельница комбинат"


def test_no_merge_different_domains():
    m = Merger()
    a = _card("Альфа", website="https://alfa.ru")
    b = _card("Бета", website="https://beta.ru")
    assert m.add(a) is not None
    assert m.add(b) is not None
    assert len(m.all_cards()) == 2


def test_company_token_drops_legal_forms():
    tok = company_token("ООО «Мельница-Комбинат»")
    assert "мельница" in tok and "ооо" not in tok and "комбинат" in tok


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
