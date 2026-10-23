"""Central configuration: budgets, limits, TTLs, engine settings."""
import os
from dataclasses import dataclass, field
from typing import List


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class EngineConfig:
    name: str
    enabled: bool = True
    # circuit breaker
    breaker_threshold: int = 3
    breaker_cooldown_s: float = 600.0
    # pacing between requests
    min_delay_s: float = 1.5
    max_delay_s: float = 4.0


@dataclass
class LLMConfig:
    enabled: bool = True
    api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    max_calls_per_job: int = 15
    max_cost_usd_per_job: float = 0.10
    day_budget_usd: float = 5.0
    timeout_s: float = _env_float("LLM_TIMEOUT_S", 60.0)


@dataclass
class Config:
    db_path: str = field(default_factory=lambda: os.getenv("SR_DB_PATH", "supplier_radar.db"))
    port: int = _env_int("SR_PORT", 8000)
    twogis_api_key: str = field(default_factory=lambda: os.getenv("SR_TWOGIS_API_KEY", ""))

    # pipeline
    job_deadline_s: float = _env_float("SR_JOB_DEADLINE_S", 120.0)
    max_candidates: int = _env_int("SR_MAX_CANDIDATES", 40)
    max_pages_per_job: int = _env_int("SR_MAX_PAGES_PER_JOB", 25)

    # cache TTLs (seconds)
    serp_ttl_s: float = _env_float("SR_SERP_TTL_S", 48 * 3600)
    page_ttl_s: float = _env_float("SR_PAGE_TTL_S", 7 * 24 * 3600)

    # fetcher
    fetch_timeout_s: float = _env_float("SR_FETCH_TIMEOUT_S", 12.0)
    per_domain_concurrency: int = _env_int("SR_PER_DOMAIN_CONCURRENCY", 1)

    engines: List[EngineConfig] = field(default_factory=lambda: [
        EngineConfig("ddg", True, 3, 600.0, 1.5, 4.0),
        # yandex: often captcha for datacenter IPs; enable via SR_YANDEX=1 if allowed
        EngineConfig("yandex", os.getenv("SR_YANDEX", "0") == "1", 3, 600.0, 2.5, 5.0),
        # twogis: requires SR_TWOGIS_API_KEY (official Catalog API)
        EngineConfig("twogis", os.getenv("SR_TWOGIS", "0") == "1", 3, 600.0, 0.5, 1.0),
        EngineConfig("bing", True, 3, 600.0, 1.5, 4.0),
    ])

    llm: LLMConfig = field(default_factory=LLMConfig)

    # taxonomy for autocomplete
    categories = [
        "мука", "сахар", "масло растительное", "крупы", "макаронные изделия",
        "мясо", "птица", "рыба и морепродукты", "молочная продукция",
        "сыры", "овощи", "фрукты", "ягоды замороженные",
        "специи и приправы", "консервация", "кофе", "чай", "какао и шоколад",
        "орехи и сухофрукты", "яйца", "выпечка и полуфабрикаты",
        "упаковка для кофе", "упаковка бумажная", "контейнеры пищевые",
        "плёнка и стрейч", "инвентарь кухонный", "химия профессиональная",
    ]

    top_cities = [
        "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург",
        "Казань", "Нижний Новгород", "Челябинск", "Самара",
        "Ростов-на-Дону", "Краснодар", "Воронеж", "Пермь",
    ]


CONFIG = Config()
