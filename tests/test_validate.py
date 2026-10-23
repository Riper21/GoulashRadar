"""Unit tests for deterministic validators. No network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.validate import (
    valid_inn, extract_inn, normalize_phone, extract_phones,
    extract_emails, canonical_url, extract_min_order, extract_price_range,
    extract_certs,
)


def test_inn_checksum():
    # valid 10-digit INN (checksum-verified test values)
    assert valid_inn("7707083893")
    assert valid_inn("7816265100")
    # invalid checksum
    assert not valid_inn("7707083894")
    assert not valid_inn("7816265103")
    # wrong length
    assert not valid_inn("12345")


def test_extract_inn_from_text():
    text = "ООО Ромашка ИНН 7707083893, г. Москва"
    assert extract_inn(text) == "7707083893"
    # bare INN fallback
    assert extract_inn("код плательщика 7816265100") == "7816265100"
    # no valid INN
    assert extract_inn("телефон 84951234567") is None


def test_phone_normalization():
    assert normalize_phone("+7 (495) 123-45-67") == "+74951234567"
    assert normalize_phone("8 999 123 45 67") == "+79991234567"
    assert normalize_phone("12345") is None


def test_extract_phones_dedup():
    text = "Тел: +7 (495) 123-45-67, +7 495 123 45 67, 8-999-111-22-33"
    phones = extract_phones(text)
    assert phones == ["+74951234567", "+79991112233"]


def test_extract_emails():
    emails = extract_emails("Пишите: sale@company.ru, INFO@Company.RU")
    assert emails == ["sale@company.ru", "info@company.ru"]


def test_canonical_url():
    assert canonical_url("http://WWW.Example.ru/path/?utm_source=x&id=1") == "https://example.ru/path?id=1"
    assert canonical_url("https://site.ru/") == "https://site.ru/"
    assert canonical_url("https://site.ru/catalog/") == "https://site.ru/catalog"


def test_min_order():
    text = "Минимальная партия от 500 кг, отгрузка со склада"
    assert extract_min_order(text) is not None
    text2 = "мин. заказ: 10000 руб"
    assert extract_min_order(text2) is not None
    assert extract_min_order("доставка по городу") is None


def test_price_range():
    text = "мука высший сорт от 62 ₽/кг при заказе от тонны"
    assert extract_price_range(text) is not None


def test_certs():
    text = "Сертификаты: ХАССП, ISO 22000, декларация ЕАЭС"
    certs = extract_certs(text)
    assert any("хассп" in c.lower() for c in certs)
    assert any("iso" in c.lower() for c in certs)


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
