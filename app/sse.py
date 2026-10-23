"""SSE event bus: per-job queues of pipeline events (stage, progress, card)."""
import asyncio
import json
from typing import AsyncGenerator, Dict, List, Optional


class JobEvent:
    def __init__(self, event: str, data: dict):
        self.event = event
        self.data = data

    def sse(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.event}\ndata: {payload}\n\n"


class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._history: Dict[str, List[JobEvent]] = {}
        self._done: set = set()

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        # replay history so late subscribers see everything
        for ev in self._history.get(job_id, []):
            q.put_nowait(ev)
        if job_id in self._done:
            q.put_nowait(JobEvent("done", {}))
        self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(job_id, [])
        if q in subs:
            subs.remove(q)

    def publish(self, job_id: str, event: str, data: dict) -> None:
        ev = JobEvent(event, data)
        self._history.setdefault(job_id, []).append(ev)
        if event == "done":
            self._done.add(job_id)
        for q in self._subscribers.get(job_id, []):
            q.put_nowait(ev)

    def finish(self, job_id: str) -> None:
        self.publish(job_id, "done", {})

    def is_done(self, job_id: str) -> bool:
        return job_id in self._done


bus = EventBus()


async def sse_stream(job_id: str) -> AsyncGenerator[str, None]:
    q = bus.subscribe(job_id)
    try:
        while True:
            try:
                ev: Optional[JobEvent] = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # keep-alive on idle, then KEEP LISTENING: closing here makes the
                # browser EventSource auto-reconnect and replay all card events
                yield ": keep-alive\n\n"
                continue
            yield ev.sse()
            if ev.event == "done":
                break
    finally:
        bus.unsubscribe(job_id, q)
