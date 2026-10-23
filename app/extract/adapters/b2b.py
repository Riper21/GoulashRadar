"""Level-1 adapters for known B2B directories. Each adapter: domain -> PageData from listing/company page."""
from typing import List
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..structured import PageData
from ...validate import extract_inn, extract_phones, extract_emails


def _domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


class BaseAdapter:
    domains: List[str] = []

    def match(self, url: str) -> bool:
        d = _domain_of(url)
        return any(d == dm or d.endswith("." + dm) for dm in self.domains)

    def parse(self, html: str, url: str) -> PageData:
        raise NotImplementedError


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


class PulscenAdapter(BaseAdapter):
    """pulscen.ru: company pages with structured spans."""
    domains = ["pulscen.ru"]

    def parse(self, html: str, url: str) -> PageData:
        pd = PageData()
        soup = BeautifulSoup(html, "lxml")
        og = soup.find("meta", property="og:site_name")
        h1 = soup.find("h1")
        pd.name = _text(h1) or (og.get("content") if og else None)
        if soup.select_one("[data-qa='company-name']"):
            pd.name = _text(soup.select_one("[data-qa='company-name']"))
        addr = soup.select_one(".address, [itemprop='address']")
        pd.address = _text(addr) or None
        for tel in soup.select("[itemprop='telephone'], a[href^='tel:']"):
            t = tel.get_text(strip=True)
            if t and t not in pd.phones:
                pd.phones.append(t)
        for em in soup.select("a[href^='mailto:']"):
            a = em.get("href", "").replace("mailto:", "").split("?")[0]
            if a and a not in pd.emails:
                pd.emails.append(a)
        pd.inn = extract_inn(soup.get_text(" ", strip=True)[:8000])
        return pd


class SuplBizAdapter(BaseAdapter):
    """supl.biz: supplier listings."""
    domains = ["supl.biz"]

    def parse(self, html: str, url: str) -> PageData:
        pd = PageData()
        soup = BeautifulSoup(html, "lxml")
        h1 = soup.find("h1")
        pd.name = _text(h1) or None
        for tel in soup.select("a[href^='tel:'], .phone, [class*='phone']"):
            t = tel.get_text(strip=True)
            if t and len(t) > 5 and t not in pd.phones:
                pd.phones.append(t)
        for em in soup.select("a[href^='mailto:']"):
            a = em.get("href", "").replace("mailto:", "").split("?")[0]
            if a and a not in pd.emails:
                pd.emails.append(a)
        return pd


class TiuAdapter(BaseAdapter):
    """tiu.ru / opt-union style: company pages with common patterns."""
    domains = ["tiu.ru", "opt-union.ru", "b2b-center.ru", "foodbay.com", "agroserver.ru", "orgpage.ru"]

    def parse(self, html: str, url: str) -> PageData:
        pd = PageData()
        soup = BeautifulSoup(html, "lxml")
        h1 = soup.find("h1")
        og = soup.find("meta", property="og:site_name")
        pd.name = _text(h1) or (og.get("content") if og else None)
        for tel in soup.select("a[href^='tel:']"):
            t = tel.get("href", "").replace("tel:", "").strip()
            if t and t not in pd.phones:
                pd.phones.append(t)
        for em in soup.select("a[href^='mailto:']"):
            a = em.get("href", "").replace("mailto:", "").split("?")[0]
            if a and a not in pd.emails:
                pd.emails.append(a)
        addr = soup.select_one("[itemprop='address'], .address, [class*='address']")
        pd.address = _text(addr) or None
        text = soup.get_text(" ", strip=True)
        pd.inn = extract_inn(text[:8000])
        return pd


ADAPTERS: List[BaseAdapter] = [PulscenAdapter(), SuplBizAdapter(), TiuAdapter()]


def adapter_for(url: str):
    for a in ADAPTERS:
        if a.match(url):
            return a
    return None
