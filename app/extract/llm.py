"""LLM extraction level 4: strict evidence contract, budgets, graceful degradation."""
import json
import time
from pathlib import Path
from typing import List, Optional

import httpx

from ..config import CONFIG
from .structured import PageData, page_text_for_llm
from ..validate import normalize_phone, valid_inn

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "extract_supplier.v1.md"

# day budget shared across jobs (process-level)
_day_cost = {"date": time.strftime("%Y-%m-%d"), "spent": 0.0}


class LLMBudgetExceeded(Exception):
    pass


class _Budget:
    def __init__(self, job_stats: dict):
        self.stats = job_stats

    def check(self, est_cost: float) -> None:
        if not CONFIG.llm.enabled:
            raise LLMBudgetExceeded("llm disabled")
        today = time.strftime("%Y-%m-%d")
        if _day_cost["date"] != today:
            _day_cost.update({"date": today, "spent": 0.0})
        if self.stats.get("llm_calls", 0) >= CONFIG.llm.max_calls_per_job:
            raise LLMBudgetExceeded("per-job call cap")
        if self.stats.get("cost_usd", 0.0) + est_cost > CONFIG.llm.max_cost_usd_per_job:
            raise LLMBudgetExceeded("per-job cost cap")
        if _day_cost["spent"] + est_cost > CONFIG.llm.day_budget_usd:
            raise LLMBudgetExceeded("day cost cap")

    def charge(self, est_cost: float) -> None:
        self.stats["llm_calls"] = self.stats.get("llm_calls", 0) + 1
        self.stats["cost_usd"] = round(self.stats.get("cost_usd", 0.0) + est_cost, 4)
        _day_cost["spent"] = round(_day_cost["spent"] + est_cost, 4)


def _validate_evidence(value: str, evidence: str, page_text: str) -> bool:
    """Evidence must be a real substring of the page text (whitespace-insensitive)."""
    if not value or not evidence:
        return False
    norm = lambda s: " ".join(s.split()).lower()
    return norm(evidence) in norm(page_text)


async def llm_extract(html: str, job_stats: dict) -> Optional[PageData]:
    """LLM level: returns PageData with only evidence-verified fields, or None on failure."""
    if not CONFIG.llm.enabled or not CONFIG.llm.api_key:
        return None

    text = page_text_for_llm(html, limit=2000, smart=True)
    if len(text) < 400:
        return None  # too little content for meaningful extraction

    est_cost = 0.004  # conservative estimate for ~3K in + ~0.6K out, mini-class model
    budget = _Budget(job_stats)
    budget.check(est_cost)

    prompt = PROMPT_PATH.read_text(encoding="utf-8").replace("{text}", text)
    payload = {
        "model": CONFIG.llm.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    # endpoint flakiness: one silent retry on 5xx/timeout (second attempt only)
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=CONFIG.llm.timeout_s) as client:
                resp = await client.post(
                    f"{CONFIG.llm.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {CONFIG.llm.api_key}"},
                    json=payload,
                )
        except (httpx.HTTPError, httpx.StreamError):
            if attempt == 1:
                continue
            return None  # network fail -> fall back to heuristics silently
        if resp.status_code == 200:
            break
        if resp.status_code >= 500 and attempt == 1:
            continue  # transient proxy error, retry once
        return None

    try:
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    budget.charge(est_cost)
    return _parse_contract(data, text)


def _parse_contract(data: dict, page_text: str) -> PageData:
    """Apply evidence verification field-by-field; unverifiable fields are dropped."""
    pd = PageData()

    def single(field: str, target: str) -> Optional[str]:
        node = data.get(field)
        if isinstance(node, dict):
            v, e = node.get("value"), node.get("evidence")
            if isinstance(v, str) and v.strip() and _validate_evidence(v, e, page_text):
                return v.strip()
        return None

    def multi(field: str) -> List[str]:
        out: List[str] = []
        node = data.get(field)
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    v, e = item.get("value"), item.get("evidence")
                    if isinstance(v, str) and v.strip() and _validate_evidence(v, e, page_text):
                        out.append(v.strip())
        return out

    pd.name = single("name", "name")
    pd.website = single("website", "website")
    pd.address = single("address", "address")
    pd.city = single("city", "city")
    pd.min_order = single("min_order", "min_order")
    pd.price_range = single("price_range", "price_range")
    pd.delivery = single("delivery", "delivery")

    inn = single("inn", "inn")
    if inn and valid_inn(inn):
        pd.inn = inn

    for p in multi("phones"):
        norm = normalize_phone(p)
        if norm and norm not in pd.phones:
            pd.phones.append(norm)

    for e in multi("emails"):
        if "@" in e and e not in pd.emails:
            pd.emails.append(e)

    pd.certs = multi("certs")[:5]
    pd.categories = multi("categories")[:5]
    return pd
