"""2GIS engine: structured directory of orgs via official Catalog API (Places API).

Demo key (platform.2gis.ru) gives without extra permissions:
  name, city (adm_div), address, point, rubrics, schedule, org (legal name),
  has_site filter, city_id filter. Contacts (contact_groups) and ITIN require
  paid key permission — engine fills what it can, cards say «источник: 2ГИС».

Card data comes straight from the API — 2gis.ru firm pages are JS-only and
useless for httpx, so the orchestrator emits these cards without fetching.
"""
import json
from typing import List, Optional

import httpx

from .base import BaseEngine, Candidate, EngineResult
from ..store import get_store
from ..config import CONFIG

API_URL = "https://catalog.api.2gis.com/3.0/items"

# city slug -> 2GIS city_id (resolved via API, type=adm_div.city)
_CITY_IDS = {
    "москва": "4504222397630173",
    "санкт-петербург": "5348647327760881",
    "новосибирск": "141360258613345",
    "екатеринбург": "1267260165455895",
    "казань": "2956110025720010",
    "нижний новгород": "2674635049009413",
    "челябинск": "2111685095587875",
    "самара": "2533897560653928",
    "ростов-на-дону": "3378322490785844",
    "краснодар": "3237585002430511",
    "воронеж": "4363484909273106",
    "пермь": "2252422583943339",
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

        city_l = (city or "").lower().strip()
        city_id = _CITY_IDS.get(city_l)
        q = f"{query} опт" if query else query
        query_norm = f"2gis-api|{city_l}|{q.lower().strip()}"

        store = get_store()
        cached = store.get_serp(self.name, query_norm, CONFIG.serp_ttl_s)
        if cached:
            return self._result_from(json.loads(cached), cached=True)

        await self.pace()
        params = {
            "q": q,
            "key": self.api_key,
            "page_size": 10,  # demo key caps page_size at 10
            "fields": "items.adm_div,items.address,items.rubrics,items.org,items.schedule,items.name_ex",
        }
        if city_id:
            params["city_id"] = city_id
        else:
            # unknown city: fall back to location bias (Moscow center)
            params["location"] = "37.62,55.75"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(API_URL, params=params)
            if resp.status_code != 200:
                self.breaker.record_failure()
                return EngineResult([], error=f"status={resp.status_code}")
            data = resp.json()
            if (data.get("meta") or {}).get("code") != 200:
                self.breaker.record_failure()
                err = (data.get("meta") or {}).get("error") or {}
                return EngineResult([], error=err.get("message", "api error"))
            self.breaker.record_success()
            store.put_serp(self.name, query_norm, json.dumps(data, ensure_ascii=False))
            return self._result_from(data)
        except (httpx.HTTPError, httpx.StreamError, json.JSONDecodeError) as e:
            self.breaker.record_failure()
            return EngineResult([], error=str(e))

    def _result_from(self, data: dict, cached: bool = False) -> EngineResult:
        items = (data.get("result") or {}).get("items") or []
        out: List[Candidate] = []
        seen = set()
        for it in items:
            org_id = it.get("id")
            name = it.get("name") or ""
            if not name or org_id in seen:
                continue
            seen.add(org_id)
            out.append(Candidate(
                url=f"https://2gis.ru/firm/{org_id}",
                title=self._title(it, name),
                engine=self.name,
                domain="2gis.ru",
            ))
        return EngineResult(out, cached=cached)

    @staticmethod
    def _title(it: dict, name: str) -> str:
        rubrics = [r.get("name") for r in (it.get("rubrics") or []) if r.get("name")]
        address = it.get("address_name") or ""
        parts = [name]
        if rubrics:
            parts.append(", ".join(rubrics[:2]))
        if address:
            parts.append(address)
        return " — ".join(parts)


def twogis_page_data(it: dict) -> Optional["PageData"]:
    """PageData prebuilt from one 2GIS API item — no fetch, no LLM needed.

    Called by the orchestrator for 2GIS candidates: firm pages are JS-only,
    so extraction cascade would find nothing.
    """
    from ..extract.structured import PageData

    if not it:
        return None
    pd = PageData()
    name_ex = it.get("name_ex") or {}
    org = it.get("org") or {}
    pd.name = name_ex.get("primary") or it.get("name") or ""
    city = next((a.get("name") for a in (it.get("adm_div") or []) if a.get("type") == "city"), None)
    pd.city = city
    address = it.get("address_name")
    pd.address = f"{city}, {address}" if city and address else address
    pd.website = f"https://2gis.ru/firm/{it.get('id')}"
    pd.categories = [r.get("name") for r in (it.get("rubrics") or []) if r.get("name")][:4]
    legal = org.get("name")
    if legal and legal != pd.name:
        pd.categories = (pd.categories or []) + [f"юр. лицо: {legal}"]
    return pd


def cached_item_for(url: str) -> Optional[dict]:
    """Cached API JSON item for a 2GIS firm URL (2gis.ru/firm/<id>)."""
    org_id = url.rstrip("/").rsplit("/", 1)[-1]
    if not org_id.isdigit():
        return None
    store = get_store()
    for _key, html in store.recent_serps("twogis", CONFIG.serp_ttl_s):
        try:
            data = json.loads(html)
        except (ValueError, TypeError):
            continue
        for it in (data.get("result") or {}).get("items") or []:
            if str(it.get("id")) == org_id:
                return it
    return None
