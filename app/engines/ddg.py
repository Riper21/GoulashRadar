"""DuckDuckGo HTML engine: no JS, parseable SERP. Primary engine."""
import re
from typing import List
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import BaseEngine, Candidate, EngineResult
from ..store import get_store
from ..config import CONFIG

SEARCH_URL = "https://html.duckduckgo.com/html/?q={q}&kl=ru-ru"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# result wrapper redirects: uddg=<real url>
_UDDG = re.compile(r"uddg=([^&]+)")


class DDGEngine(BaseEngine):
    name = "ddg"

    async def search(self, query: str, city: str) -> EngineResult:
        if not self.enabled or not self.breaker.allow():
            return EngineResult([], error="disabled" if not self.enabled else "breaker open")

        q = f"{query} опт {city}" if city else f"{query} опт"
        query_norm = q.lower().strip()

        store = get_store()
        cached_html = store.get_serp(self.name, query_norm, CONFIG.serp_ttl_s)
        if cached_html:
            return EngineResult(self._parse(cached_html), cached=True)

        await self.pace()
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": _UA, "Accept-Language": "ru-RU,ru;q=0.9"},
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(SEARCH_URL.format(q=quote_plus(q)))
            if resp.status_code != 200 or "anomaly" in resp.text[:2000].lower():
                self.breaker.record_failure()
                return EngineResult([], error=f"status={resp.status_code}")
            html = resp.text
            self.breaker.record_success()
            store.put_serp(self.name, query_norm, html)
            return EngineResult(self._parse(html))
        except (httpx.HTTPError, httpx.StreamError) as e:
            self.breaker.record_failure()
            return EngineResult([], error=str(e))

    def _parse(self, html: str) -> List[Candidate]:
        soup = BeautifulSoup(html, "lxml")
        out: List[Candidate] = []
        seen = set()
        for a in soup.select("a.result__a, div.results_links a[href*='uddg=']"):
            href = a.get("href", "")
            url = self._unwrap(href)
            if not url:
                continue
            domain = urlparse(url).netloc.lower()
            if domain in ("duckduckgo.com", "") or domain.endswith(".yandex.ru"):
                continue
            if url in seen:
                continue
            seen.add(url)
            title = a.get_text(strip=True)
            if title:
                out.append(Candidate(url=url, title=title, engine=self.name, domain=domain))
        return out

    @staticmethod
    def _unwrap(href: str) -> str:
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("http"):
            m = _UDDG.search(href)
            if m:
                from urllib.parse import unquote

                return unquote(m.group(1))
            return href
        return ""
