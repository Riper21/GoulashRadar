"""Supplier Radar — FastAPI app: search, SSE, supplier cards, compare, health."""
import asyncio
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()  # .env: LLM_API_KEY, SR_* — must run before config import

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from .config import CONFIG
from .orchestrator import start_search, ENGINES
from .schema import SearchRequest, SupplierCard
from .score import score_card, verdict
from .sse import sse_stream
from .store import get_store

_ROOT = Path(__file__).resolve().parent.parent  # repo root, CWD-independent
_INDEX = _ROOT / "templates" / "index.html"

app = FastAPI(title="Supplier Radar", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")

# allow Chrome extension / local tooling to call the API directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def index():
    # static HTML (no Jinja): platform telemetry wraps ASGI and breaks TemplateResponse
    return FileResponse(_INDEX)


@app.get("/api/config")
async def autocomplete_config():
    """Category/city lists for the datalists (rendered client-side now)."""
    return {"categories": CONFIG.categories, "cities": CONFIG.top_cities}


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


@app.post("/api/jobs/{job_id}/suppliers/csv")
async def job_suppliers_csv(job_id: str, body: dict):
    """Export job cards as XLSX (Excel-safe: encoding and columns guaranteed).

    Client POSTs user notes (localStorage) so they land in the file:
    {"notes": {"<identity_key>": "text"}}. CSV was dropped on purpose:
    BOM + sep=; conflict inside Excel (ANSI fallback -> mojibake).
    """
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    store = get_store()
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    notes = (body or {}).get("notes") or {}
    cards = store.job_suppliers(job_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Поставщики"
    header = ["Название", "Скор", "Город", "Телефон", "Email", "Сайт", "Мин. заказ",
              "Цена", "Доставка", "ИНН", "Сертификаты", "Заметка", "Источник"]
    ws.append(header)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="016048")
    for cell in ws[1]:
        cell.font = head_font
        cell.fill = head_fill
    for card in cards:
        s = score_card(card, job["category"], job["city"])
        row = [
            card.name,
            s["total"],
            card.city or "",
            ", ".join(p.e164 or p.raw for p in card.phones),
            ", ".join(e.address for e in card.emails),
            card.website or "",
            card.min_order or "",
            card.price_range or "",
            (card.delivery or "").replace("\r", " ").replace("\n", " ")[:120],
            card.inn or "",
            ", ".join(card.certs),
            notes.get(card.identity_key, ""),
            ", ".join(s.url for s in card.sources),
        ]
        ws.append(row)

    # readable column widths; freeze header; autofilter = a real table feel
    widths = [28, 7, 16, 22, 24, 40, 14, 12, 40, 14, 18, 24, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{len(cards) + 1}"

    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="suppliers.xlsx"'},
    )


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
