"""Supplier Radar — FastAPI app: search, SSE, supplier cards, compare, health."""
import asyncio
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()  # .env: LLM_API_KEY, SR_* — must run before config import

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .config import CONFIG
from .orchestrator import start_search, ENGINES
from .schema import SearchRequest, SupplierCard
from .score import score_card, verdict
from .sse import sse_stream
from .store import get_store

app = FastAPI(title="Supplier Radar", version="0.1.0")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# allow Chrome extension / local tooling to call the API directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "categories": CONFIG.categories, "cities": CONFIG.top_cities},
    )


@app.post("/api/search")
async def api_search(req: SearchRequest):
    ok, err = req.sane()
    if not ok:
        raise HTTPException(status_code=422, detail=err)
    job_id = await start_search(req.category, req.city, req.force_refresh, req.ru_only)
    return {"job_id": job_id, "cached": False}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    return StreamingResponse(
        sse_stream(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/suppliers/{identity_key}")
async def supplier_detail(identity_key: str):
    card = get_store().get_supplier(identity_key)
    if not card:
        raise HTTPException(404, "supplier not found")
    return {"card": card.model_dump(mode="json")}


@app.get("/api/compare")
async def compare(ids: str):
    keys = [i.strip() for i in ids.split(",") if i.strip()][:4]
    cards = []
    for k in keys:
        c = get_store().get_supplier(k)
        if c:
            cards.append(c.model_dump(mode="json"))
    return {"cards": cards}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = get_store().get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.get("/api/jobs/{job_id}/suppliers")
async def job_suppliers(job_id: str):
    """All cards of a job (REST snapshot) — used by the Chrome widget.

    Cards are re-scored with the job's original category/city so totals
    match what the web UI shows via SSE.
    """
    store = get_store()
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    cards = store.job_suppliers(job_id)
    result = []
    for card in cards:
        s = score_card(card, job["category"], job["city"])
        result.append(
            {"card": card.model_dump(mode="json"), "score": s, "verdict": verdict(s["total"])}
        )
    result.sort(key=lambda x: -x["score"]["total"])
    return {"job": {"id": job_id, "status": job["status"]}, "suppliers": result}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "0.2.0",
        "engines": [e.health() for e in ENGINES],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=CONFIG.port)
