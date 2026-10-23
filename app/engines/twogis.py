"""2GIS engine: structured directory of orgs.

NOTE: web 2gis.ru renders via JS (bot-wall for httpx). This engine works only
with an official Catalog API key — set SR_TWOGIS_API_KEY. Without key it stays
disabled and is skipped gracefully (see README: honest limitation).
"""
import json
import re
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import BaseEngine, Candidate, EngineResult
from ..store import get_store
from ..config import CONFIG

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

_CITY_SLUGS = {
    "москва": "moscow", "санкт-петербург": "spb", "новосибирск": "novosibirsk",
    "екатеринбург": "ekaterinburg", "казань": "kazan", "нижний новгород": "n_novgorod",
    "челябинск": "chelyabinsk", "самара": "samara", "ростов-на-дону": "rostov",
    "краснодар": "krasnodar", "воронеж": "voronezh", "пермь": "perm",
}


class TwoGisEngine(BaseEngine):
    name = "twogis"

    def __init__(self):
        super().__init__()
        self.api_key = CONFIG.twogis_api_key

    async def search(self, query: str, city: str) -> EngineResult:
        if not self.api_key:
            return EngineResult([], error="no api key (disabled)")
        if not self.enabled or not self.breaker.allow():
            return EngineResult([], error="breaker open")

        city_slug = _CITY_SLUGS.get((city or "").lower().strip(), "moscow")
        q = f"{query} опт"
        query_norm = f"2gis-api|{city_slug}|{q.lower().strip()}"

        store = get_store()
        cached_html = store.get_serp(self.name, query_norm, CONFIG.serp_ttl_s)
        if cached_html:
            return EngineResult(self._parse_api(json.loads(cached_html)), cached=True)

        await self.pace()
        url = (
            f"https://catalog.api.2gis.com/3.0/items?q={quote_plus(q)}"
            f"&location=37.62,55.75&sort=relevance&key={self.api_key}&page_size=15"
        )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                self.breaker.record_failure()
                return EngineResult([], error=f"status={resp.status_code}")
            data = resp.json()
            self.breaker.record_success()
            store.put_serp(self.name, query_norm, json.dumps(data, ensure_ascii=False))
            return EngineResult(self._parse_api(data))
        except (httpx.HTTPError, httpx.StreamError, json.JSONDecodeError) as e:
            self.breaker.record_failure()
            return EngineResult([], error=str(e))

    def _parse_api(self, data: dict) -> List[Candidate]:
        out: List[Candidate] = []
        seen = set()
        for item in (data.get("result", {}).get("items") or [])[:15]:
            org_id = item.get("org_id") or item.get("id")
            name = item.get("name") or ""
            if not name or org_id in seen:
                continue
            seen.add(org_id or name)
            address = item.get("address_name") or item.get("address") or ""
            out.append(Candidate(
                url=f"https://2gis.ru/firm/{org_id}",
                title=f"{name} — {address}" if address else name,
                engine=self.name,
                domain="2gis.ru",
            ))
        return out
