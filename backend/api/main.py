"""FastAPI app: thin HTTP layer over backend/core. Interactive docs at /docs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `core` importable

from core import planning, queries
from core.db import get_db

app = FastAPI(
    title="Overlooked Area Detector API",
    description="Finds disaster-hit ZIP codes that are not asking for help, from public data.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(queries.NotFound)
async def _nf(_: Request, e: queries.NotFound):
    return JSONResponse(status_code=404, content={"detail": str(e)})


@app.exception_handler(queries.BadDay)
async def _bd(_: Request, e: queries.BadDay):
    return JSONResponse(status_code=422, content={"detail": str(e)})


Day = Query(5, ge=0, le=365, description="Days since landfall")


@app.get("/health")
def health():
    db = get_db()
    return {"status": "ok", "mode": "db", "db": db.path.name}


@app.get("/events")
def events():
    return queries.list_events()


@app.get("/events/{event_id}")
def event(event_id: str):
    return queries.get_event(event_id)


@app.get("/events/{event_id}/map")
def map_day(event_id: str, day: int = Day):
    return queries.map_geojson(event_id, day)


@app.get("/events/{event_id}/kpis")
def kpis(event_id: str, day: int = Day):
    return queries.kpis(event_id, day)


@app.get("/events/{event_id}/priorities")
def priorities(
    event_id: str,
    day: int = Day,
    limit: int = Query(20, ge=1, le=500),
    significant_only: bool = False,
    action: str | None = None,
):
    return queries.priorities(event_id, day, limit, significant_only, action)


@app.get("/events/{event_id}/zips/{zip_code}")
def zip_detail(event_id: str, zip_code: str, day: int = Day):
    return queries.zip_detail(event_id, zip_code, day)


class PlanRequest(BaseModel):
    day: int = Field(5, ge=0)
    k: int = Field(4, ge=1, le=10)
    radius_km: float = Field(10, ge=1, le=30)
    exclude_flooded: bool = True


@app.post("/events/{event_id}/plan")
def plan(event_id: str, req: PlanRequest):
    return planning.make_plan(event_id, req.day, req.k, req.radius_km, req.exclude_flooded)


@app.get("/events/{event_id}/backtest")
def backtest(event_id: str):
    return queries.backtest(event_id)


@app.get("/events/{event_id}/forecast")
def forecast(
    event_id: str,
    day: int = Day,
    visits_per_day: float = Query(6, gt=0, le=50),
    adjusters: int = Query(1000, ge=1, le=100_000),
):
    return planning.forecast(event_id, day, visits_per_day, adjusters)


@app.get("/events/{event_id}/brief")
def brief(
    event_id: str,
    day: int = Day,
    format: str = Query("md", pattern="^(md|markdown)$"),
    k: int = Query(4, ge=1, le=10),
    radius_km: float = Query(10, ge=1, le=30),
    visits_per_day: float = Query(6, gt=0, le=50),
    adjusters: int = Query(1000, ge=1),
):
    md = planning.brief_markdown(event_id, day, k, radius_km, visits_per_day, adjusters)
    if not md:
        raise HTTPException(500, "brief failed")
    return PlainTextResponse(
        md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="brief_{event_id}_day{day}.md"'},
    )
