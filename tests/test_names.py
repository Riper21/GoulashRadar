"""Unit tests for name cleanup."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.names import clean_name


def test_clean_seo_title():
    assert clean_name("Купить муку от производителя оптом в Москве", "x.ru") in ("x", "x.ru")


def test_keep_hyphenated_names():
    assert clean_name("ТД «Опт-Торг HoReCa»", "x.ru") == "ТД «Опт-Торг HoReCa»"
    assert clean_name("Интернет-магазин оптом продукты", "d.ru") == "Интернет-магазин оптом продукты"


def test_strip_official_site():
    assert clean_name("ООО Мельница — официальный сайт", "x.ru") == "ООО Мельница"
    assert clean_name("Мой Хлеб - Официальный сайт!", "x.ru") == "Мой Хлеб"


def test_fallback_domain():
    assert clean_name("", "opt-union.ru") == "opt-union"
    assert clean_name(None, "site.ru") == "site"


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
