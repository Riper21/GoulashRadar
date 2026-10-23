"""SQLite store: jobs, serp/page cache, suppliers. Thread-safe via check_same_thread=False + lock."""
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel

from .schema import SupplierCard
from .config import CONFIG


def model_json(model: BaseModel) -> str:
    return model.model_dump_json()


def parse_card(raw: str) -> SupplierCard:
    return SupplierCard.model_validate_json(raw)

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def _now() -> str:
    return datetime.utcnow().isoformat()


class Store:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or CONFIG.db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---------- jobs ----------

    def create_job(self, job_id: str, category: str, city: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, category, city, status, created_at) VALUES (?,?,?,?,?)",
                (job_id, category.strip().lower(), city.strip().lower(), "running", _now()),
            )
            self._conn.commit()

    def finish_job(self, job_id: str, status: str, stats: Optional[dict] = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status=?, finished_at=?, stats=? WHERE id=?",
                (status, _now(), json.dumps(stats or {}), job_id),
            )
            self._conn.commit()

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    # ---------- serp cache ----------

    def get_serp(self, engine: str, query_norm: str, ttl_s: float) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT html, fetched_at FROM serp_cache WHERE engine=? AND query_norm=?",
                (engine, query_norm),
            ).fetchone()
        if not row or not row["html"]:
            return None
        age = datetime.utcnow() - datetime.fromisoformat(row["fetched_at"])
        if age > timedelta(seconds=ttl_s):
            return None
        return row["html"]

    def put_serp(self, engine: str, query_norm: str, html: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO serp_cache (engine, query_norm, html, fetched_at) VALUES (?,?,?,?)",
                (engine, query_norm, html, _now()),
            )
            self._conn.commit()

    def recent_serps(self, engine: str, ttl_s: float, limit: int = 50) -> list:
        """[(query_norm, html)] for an engine, newest first, within ttl."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT query_norm, html, fetched_at FROM serp_cache WHERE engine=?"
                " ORDER BY fetched_at DESC LIMIT ?",
                (engine, limit),
            ).fetchall()
        out = []
        for r in rows:
            age = datetime.utcnow() - datetime.fromisoformat(r["fetched_at"])
            if age > timedelta(seconds=ttl_s):
                continue
            out.append((r["query_norm"], r["html"]))
        return out

    # ---------- page cache ----------

    def get_page(self, url: str, ttl_s: float) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT html, fetched_at FROM page_cache WHERE url=?", (url,)
            ).fetchone()
        if not row or not row["html"]:
            return None
        age = datetime.utcnow() - datetime.fromisoformat(row["fetched_at"])
        if age > timedelta(seconds=ttl_s):
            return None
        return row["html"]

    def put_page(self, url: str, html: str, status_code: int = 200) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO page_cache (url, html, status_code, fetched_at) VALUES (?,?,?,?)",
                (url, html, status_code, _now()),
            )
            self._conn.commit()

    # ---------- suppliers ----------

    def upsert_supplier(self, card: SupplierCard) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO suppliers (identity_key, card_json, updated_at) VALUES (?,?,?)",
                (card.identity_key, model_json(card), _now()),
            )
            self._conn.commit()

    def link_job(self, job_id: str, identity_key: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO job_suppliers (job_id, identity_key) VALUES (?,?)",
                (job_id, identity_key),
            )
            self._conn.commit()

    def get_supplier(self, identity_key: str) -> Optional[SupplierCard]:
        with self._lock:
            row = self._conn.execute(
                "SELECT card_json FROM suppliers WHERE identity_key=?", (identity_key,)
            ).fetchone()
        if not row:
            return None
        return parse_card(row["card_json"])

    def job_suppliers(self, job_id: str) -> List[SupplierCard]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.card_json FROM job_suppliers js JOIN suppliers s ON s.identity_key = js.identity_key WHERE js.job_id=?",
                (job_id,),
            ).fetchall()
        return [parse_card(r["card_json"]) for r in rows]

    def job_keys(self, job_id: str) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT identity_key FROM job_suppliers WHERE job_id=?", (job_id,)
            ).fetchall()
        return [r["identity_key"] for r in rows]

    def find_recent_job(self, category: str, city: str, ttl_s: float, before: Optional[str] = None) -> Optional[dict]:
        """Last done job for the same normalized category+city within TTL.

        before: ISO timestamp — find the next done job strictly older (for skipping
        jobs whose ru_only mode doesn't match the current request).
        """
        cutoff = (datetime.utcnow() - timedelta(seconds=ttl_s)).isoformat()
        with self._lock:
            if before:
                row = self._conn.execute(
                    "SELECT * FROM jobs WHERE category=? AND city=? AND status='done' "
                    "AND created_at >= ? AND created_at < ? ORDER BY created_at DESC LIMIT 1",
                    (category.strip().lower(), city.strip().lower(), cutoff, before),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM jobs WHERE category=? AND city=? AND status='done' "
                    "AND created_at >= ? AND finished_at IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                    (category.strip().lower(), city.strip().lower(), cutoff),
                ).fetchone()
        return dict(row) if row else None

    # alias used by orchestrator when skipping mismatched ru_only jobs
    def find_recent_job_before(self, category: str, city: str, ttl_s: float, before: str) -> Optional[dict]:
        return self.find_recent_job(category, city, ttl_s, before=before)


_store: Optional[Store] = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
