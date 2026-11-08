"""Team placement (F7), claim-surge forecast and deployment brief (F9)."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

import numpy as np
from jinja2 import Environment, FileSystemLoader

from core import queries
from core.db import get_db
from core.optimizer import greedy_max_coverage

PLANS: dict[str, dict] = {}  # DB is read-only on the host, so plans live in memory


def make_plan(event_id: str, day: int, k: int, radius_km: float, exclude_flooded: bool) -> dict:
    queries.check_day(event_id, day)
    db = get_db()
    zips = [
        r for r in queries._priorities_all(event_id, day)
        if json.loads(r["actions_json"]) != ["monitor"] and (r["priority"] or 0) > 0
    ]
    sites = db.rows(
        """SELECT s.site_id, s.name, s.kind, s.lat, s.lon, s.zip, s.source,
                  coalesce(f.flooded, false) AS flooded
           FROM sites s LEFT JOIN site_flags f ON f.site_id = s.site_id AND f.event_id = ?""",
        [event_id],
    )
    excluded = sum(1 for s in sites if s["flooded"]) if exclude_flooded else 0
    if exclude_flooded:
        sites = [s for s in sites if not s["flooded"]]

    res = greedy_max_coverage(
        [s["lat"] for s in sites], [s["lon"] for s in sites],
        [z["centroid_lat"] for z in zips], [z["centroid_lon"] for z in zips],
        [z["priority"] for z in zips], k=k, radius_km=radius_km,
    )
    out_sites = []
    for idx, cov, gain in zip(res["chosen"], res["covered"], res["gain"]):
        s = sites[idx]
        cz = [zips[i] for i in cov]
        out_sites.append(
            {
                "site_id": s["site_id"],
                "name": s["name"],
                "kind": s["kind"],
                "lat": s["lat"],
                "lon": s["lon"],
                "source": s["source"],
                "covered_zips": [z["zip"] for z in cz],
                "covered_priority": round(gain, 0),
                "households_covered": round(sum(z["unmet_estimate"] or 0 for z in cz), 0),
                "top_zips": [
                    {"zip": z["zip"], "area": z["area_name"]}
                    for z in sorted(cz, key=lambda z: -z["priority"])[:3]
                ],
            }
        )
    plan = {
        "plan_id": f"p_{event_id}_d{day}_k{k}_{uuid.uuid4().hex[:6]}",
        "event_id": event_id,
        "day": day,
        "k": k,
        "radius_km": radius_km,
        "exclude_flooded": exclude_flooded,
        "sites_excluded_flooded": excluded,
        "sites": out_sites,
        "coverage_pct": round(res["coverage_pct"], 3),
        "households_covered": round(sum(s["households_covered"] for s in out_sites), 0),
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    PLANS[plan["plan_id"]] = plan
    return plan


def forecast(event_id: str, day: int, visits_per_day: float = 6, adjusters: int = 1000) -> dict:
    ev = queries.check_day(event_id, day)
    db = get_db()
    total = db.one("SELECT sum(expected_final) AS t FROM predictions WHERE event_id = ?", [event_id])["t"]
    curve = db.rows(
        """SELECT day, sum(observed) AS observed FROM gap_scores
           WHERE event_id = ? GROUP BY day ORDER BY day""",
        [event_id],
    )
    obs_now = next((c["observed"] for c in curve if c["day"] == day), 0)
    # remaining need per ZIP, floored at zero, then summed
    rem = db.one(
        """SELECT sum(greatest(p.expected_final - coalesce(g.observed, 0), 0)) AS r
           FROM predictions p LEFT JOIN gap_scores g
             ON g.zip = p.zip AND g.event_id = p.event_id AND g.day = ?
           WHERE p.event_id = ?""",
        [day, event_id],
    )["r"] or 0.0
    capacity = max(visits_per_day * adjusters, 1e-9)
    return {
        "event_id": event_id,
        "day": day,
        "date": queries._date_for(ev, day),
        "expected_final_total": round(float(total), 0),
        "observed_to_date": int(obs_now or 0),
        "remaining_need": round(float(rem), 0),
        "visits_per_adjuster_per_day": visits_per_day,
        "adjusters": adjusters,
        "adjuster_days_needed": round(float(rem) / max(visits_per_day, 1e-9), 0),
        "days_to_clear": round(float(rem) / capacity, 1),
        "curve": [
            {"day": c["day"], "observed": int(c["observed"]), "expected_final": round(float(total), 0)}
            for c in curve
        ],
        "data_labels": {"observed_to_date": "real", "remaining_need": "predicted"},
    }


_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / "templates")),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def brief_markdown(event_id: str, day: int, k: int = 4, radius_km: float = 10,
                   visits_per_day: float = 6, adjusters: int = 1000) -> str:
    ev = queries.get_event(event_id)
    k_ = queries.kpis(event_id, day)
    pr = queries.priorities(event_id, day, limit=10)
    plan = make_plan(event_id, day, k, radius_km, True)
    fc = forecast(event_id, day, visits_per_day, adjusters)
    return _env.get_template("brief.md.j2").render(
        ev=ev, k=k_, pr=pr, plan=plan, fc=fc, np=np,
        generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
