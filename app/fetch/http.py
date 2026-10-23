"""Page fetcher: robots.txt (cached), per-domain pacing + concurrency=1, page cache."""
import asyncio
import random
import time
from typing import Dict, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..config import CONFIG
from ..store import get_store

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
_UA_TOKEN = "supplier-radar-prototype"

_robots_cache: Dict[str, RobotFileParser] = {}
_robots_fetching: Dict[str, asyncio.Lock] = {}
_domain_semaphores: Dict[str, asyncio.Semaphore] = {}
_domain_last: Dict[str, float] = {}
_domain_lock = asyncio.Lock()

MIME_OK = ("text/html", "application/xhtml")


async def _get_robots(client: httpx.AsyncClient, domain: str) -> Optional[RobotFileParser]:
    if domain in _robots_cache:
        return _robots_cache[domain]
    lock = _robots_fetching.setdefault(domain, asyncio.Lock())
    async with lock:
        if domain in _robots_cache:  # double-check after lock
            return _robots_cache[domain]
        rp = RobotFileParser()
        try:
            resp = await client.get(f"https://{domain}/robots.txt", timeout=6.0)
            if resp.status_code == 200 and len(resp.text) < 512_000:
                rp.parse(resp.text.splitlines())
            else:
                rp.parse([])  # no robots -> allow all
        except (httpx.HTTPError, httpx.StreamError):
            rp.parse([])  # unreachable robots -> allow all
        _robots_cache[domain] = rp
        return rp


def can_fetch(rp: Optional[RobotFileParser], url: str) -> bool:
    if rp is None:
        return True
    try:
        return rp.can_fetch(_UA_TOKEN, url) and rp.can_fetch("*", url)
    except Exception:
        return True


async def _domain_gate(domain: str, min_delay: float = 1.2, max_delay: float = 3.0) -> None:
    """Per-domain pacing with jitter, concurrency=1 per domain."""
    sem = _domain_semaphores.get(domain)
    if sem is None:
        async with _domain_lock:
            sem = _domain_semaphores.setdefault(domain, asyncio.Semaphore(CONFIG.per_domain_concurrency))
    await sem.acquire()
    try:
        now = time.monotonic()
        wait = _domain_last.get(domain, 0.0) + random.uniform(min_delay, max_delay) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _domain_last[domain] = time.monotonic()
    finally:
        sem.release()


async def fetch_page(url: str, force: bool = False) -> Optional[str]:
    """Fetch a page with cache/robots/pacing. Returns HTML or None."""
    store = get_store()
    if not force:
        cached = store.get_page(url, CONFIG.page_ttl_s)
        if cached:
            return cached

    domain = urlparse(url).netloc.lower()
    headers = {"User-Agent": _UA, "Accept-Language": "ru-RU,ru;q=0.9",
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

    async with httpx.AsyncClient(timeout=CONFIG.fetch_timeout_s, follow_redirects=True, headers=headers) as client:
        rp = await _get_robots(client, domain)
        if not can_fetch(rp, url):
            return None
        await _domain_gate(domain)
        try:
            resp = await client.get(url)
        except (httpx.HTTPError, httpx.StreamError):
            return None

    ctype = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not any(m in ctype for m in MIME_OK):
        return None
    if len(resp.text) > 2_000_000:
        return None

    store.put_page(url, resp.text, resp.status_code)
    return resp.text
