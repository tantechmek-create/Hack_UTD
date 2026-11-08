"""DuckDB access. The API opens the database read-only; it never trains or rebuilds."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]


def resolve_db_path() -> Path:
    env = os.getenv("DB_PATH")
    if env:
        p = Path(env)
        return p if p.is_absolute() else ROOT / p
    real = ROOT / "data" / "oad.duckdb"
    return real if real.exists() else ROOT / "data" / "mock.duckdb"


class DB:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else resolve_db_path()
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} not found. Run `make mock` (fake data) or `make data` (real data)."
            )
        self._con = duckdb.connect(str(self.path), read_only=True)
        self._lock = threading.Lock()

    def rows(self, sql: str, params: list | tuple = ()) -> list[dict]:
        # DuckDB connections are not thread-safe; a cursor per call keeps FastAPI's
        # threadpool happy without reopening the file.
        with self._lock:
            cur = self._con.cursor()
        res = cur.execute(sql, params)
        cols = [d[0] for d in res.description]
        return [dict(zip(cols, r)) for r in res.fetchall()]

    def one(self, sql: str, params: list | tuple = ()) -> dict | None:
        r = self.rows(sql, params)
        return r[0] if r else None


_db: DB | None = None


def get_db() -> DB:
    global _db
    if _db is None:
        _db = DB()
    return _db
