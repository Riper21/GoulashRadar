"""Debug: fetch DDG/Bing SERP and inspect selectors. Writes HTML dumps for fixtures."""
import asyncio
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
OUT = Path("tests/fixtures/pages")
OUT.mkdir(parents=True, exist_ok=True)


async def fetch(url: str, name: str):
    async with httpx.AsyncClient(
        headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        try:
            resp = await client.get(url)
        except Exception as e:
            print(f"[{name}] FETCH ERROR: {e}")
            return None
    print(f"[{name}] status={resp.status_code} len={len(resp.text)}")
    (OUT / f"{name}.html").write_text(resp.text, encoding="utf-8")
    return resp.text


def inspect_ddg(html: str):
    soup = BeautifulSoup(html, "lxml")
    for sel in ["a.result__a", "div.results_links", "div.result", "div.web-result", "a[data-testid='result-title-a']"]:
        found = soup.select(sel)
        print(f"  ddg selector {sel!r}: {len(found)}")
    links = soup.select("a[href]")
    print(f"  ddg total <a href>: {len(links)}")
    uddg = [a for a in links if "uddg=" in (a.get("href") or "")]
    print(f"  ddg uddg links: {len(uddg)}")
    for a in uddg[:5]:
        print("   ", a.get("href")[:100])


def inspect_bing(html: str):
    soup = BeautifulSoup(html, "lxml")
    for sel in ["li.b_algo", "ol#b_results li", "h2 a"]:
        found = soup.select(sel)
        print(f"  bing selector {sel!r}: {len(found)}")
    for a in soup.select("li.b_algo h2 a")[:5]:
        print("   ", (a.get("href") or "")[:100])


async def main():
    q = sys.argv[1] if len(sys.argv) > 1 else "мука опт Москва"
    from urllib.parse import quote_plus

    ddg = await fetch(f"https://html.duckduckgo.com/html/?q={quote_plus(q)}", "ddg_debug")
    if ddg:
        inspect_ddg(ddg)
    bing = await fetch(f"https://www.bing.com/search?q={quote_plus(q)}&setlang=ru", "bing_debug")
    if bing:
        inspect_bing(bing)


asyncio.run(main())
