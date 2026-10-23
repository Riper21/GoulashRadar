"""Debug: test Yandex + 2GIS engines standalone. Saves SERP HTML as fixtures."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

OUT = Path("tests/fixtures/pages")
OUT.mkdir(parents=True, exist_ok=True)


async def main():
    from app.engines.yandex import YandexEngine
    from app.engines.twogis import TwoGisEngine

    yx = YandexEngine()
    res = await yx.search("мука", "Москва")
    print(f"yandex: found={len(res.candidates)} error={res.error}")
    for c in res.candidates[:5]:
        print("  -", c.url[:80], "|", c.title[:40])

    tg = TwoGisEngine()
    res2 = await tg.search("мука", "Москва")
    print(f"twogis: found={len(res2.candidates)} error={res2.error}")
    for c in res2.candidates[:5]:
        print("  -", c.url[:80], "|", c.title[:40])


asyncio.run(main())
