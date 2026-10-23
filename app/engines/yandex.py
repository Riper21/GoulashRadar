"""Yandex engine: secondary SERP. Skips gracefully on captcha (no retry storms)."""
from typing import List
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import httpx
from bs4 import BeautifulSoup

from .base import BaseEngine, Candidate, EngineResult
from ..store import get_store
from ..config import CONFIG

SEARCH_URL = "https://yandex.ru/search/?text={q}&lr=213"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


class YandexEngine(BaseEngine):
    name = "yandex"

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
                headers={
                    "User-Agent": _UA,
                    "Accept-Language": "ru-RU,ru;q=0.9",
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(SEARCH_URL.format(q=quote_plus(q)))
            html = resp.text

            # SmartCaptcha or bot-wall: give up immediately, no retries
            if resp.status_code != 200 or "SmartCaptcha" in html or "challenge" in html[:3000].lower():
                self.breaker.record_failure()
                return EngineResult([], error="captcha")

            candidates = self._parse(html)
            if not candidates:
                # empty page without organic results — treat as soft failure
                self.breaker.record_failure()
                return EngineResult([], error="no organic")

            self.breaker.record_success()
            store.put_serp(self.name, query_norm, html)
            return EngineResult(candidates)
        except (httpx.HTTPError, httpx.StreamError) as e:
            self.breaker.record_failure()
            return EngineResult([], error=str(e))

    def _parse(self, html: str) -> List[Candidate]:
        soup = BeautifulSoup(html, "lxml")
        out: List[Candidate] = []
        seen = set()
        # organic results: <a class="organic__url">
        for a in soup.select("a.organic__url, a.Linkorganic__url, a.OrganicTitle-Link"):
            href = a.get("href", "")
            if not href.startswith("http"):
                continue
            domain = urlparse(href).netloc.lower()
            if not domain or "yandex" in domain:
                continue
            if href in seen:
                continue
            seen.add(href)
            title_el = a.select_one(".organic__url-text, .OrganicTitle-LinkText") or a
            title = title_el.get_text(strip=True)
            out.append(Candidate(url=href, title=title, engine=self.name, domain=domain))
        return out
