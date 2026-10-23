"""Engine protocol: search query -> candidate URLs. Circuit breaker + pacing per engine."""
import asyncio
import random
import time
from typing import List, Optional

from ..config import CONFIG


class Candidate:
    def __init__(self, url: str, title: str, engine: str, domain: str):
        self.url = url
        self.title = title
        self.engine = engine
        self.domain = domain

    def __repr__(self):
        return f"<Candidate {self.engine}:{self.url}>"


class EngineResult:
    def __init__(self, candidates: List[Candidate], cached: bool = False, error: Optional[str] = None):
        self.candidates = candidates
        self.cached = cached
        self.error = error


class Breaker:
    """Circuit breaker: N consecutive errors -> open for cooldown seconds."""

    def __init__(self, threshold: int, cooldown_s: float):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.opened_at: Optional[float] = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if time.monotonic() - self.opened_at >= self.cooldown_s:
            self.opened_at = None
            self.failures = 0
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()

    def state(self) -> str:
        if self.opened_at is not None and not self.allow():
            return "open"
        return "closed" if self.failures == 0 else "half-open"

    def until_reset_s(self) -> float:
        if self.opened_at is None:
            return 0.0
        return max(0.0, self.cooldown_s - (time.monotonic() - self.opened_at))


class BaseEngine:
    name = "base"

    def __init__(self):
        cfg = next((e for e in CONFIG.engines if e.name == self.name), None)
        self.enabled = cfg.enabled if cfg else True
        self.breaker = Breaker(cfg.breaker_threshold, cfg.breaker_cooldown_s) if cfg else Breaker(3, 600)
        self._min_delay = cfg.min_delay_s if cfg else 1.5
        self._max_delay = cfg.max_delay_s if cfg else 4.0
        self._last_request = 0.0

    async def pace(self) -> None:
        """Enforce delay with jitter between requests to this engine."""
        now = time.monotonic()
        wait = self._last_request + random.uniform(self._min_delay, self._max_delay) - now
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    async def search(self, query: str, city: str) -> EngineResult:
        raise NotImplementedError

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "breaker": self.breaker.state(),
            "reset_in_s": round(self.breaker.until_reset_s()),
        }
