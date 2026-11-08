"""Read models for each endpoint. Routers stay thin; all SQL lives here."""

from __future__ import annotations

import json
from functools import lru_cache

from core import scoring
from core.db import get_db


class NotFound(Exception):
    pass


class BadDay(Exception):
    pass


def _f(x, nd=3):
    return None if x is None else round(float(x), nd)


def list_events() -> list[dict]:
    rows = get_db().rows("SELECT * FROM events ORDER BY landfall_date DESC")
    return [_event_out(r) for r in rows]


def _event_out(r: dict) -> dict:
    return {
        "event_id": r["event_id"],
        "name": r["name"],
        "disaster_number": r["disaster_number"],
        "landfall_date": str(r["landfall_date"]),
        "bbox": json.loads(r["bbox"]),
        "center": json.loads(r["center"]),
        "max_day": r["max_day"],
        "data_mode": r["data_mode"],
        "counties": r.get("counties"),
    }


@lru_cache(maxsize=32)
def get_event(event_id: str) -> dict:
    r = get_db().one("SELECT * FROM events WHERE event_id = ?", [event_id])
    if not r:
        raise NotFound(f"unknown event {event_id}")
    return _event_out(r)


def check_day(event_id: str, day: int) -> dict:
    ev = get_event(event_id)
    if not 0 <= day <= ev["max_day"]:
        raise BadDay(f"day must be between 0 and {ev['max_day']}")
    return ev


def _date_for(ev: dict, day: int) -> str:
    import datetime as dt

    return str(dt.date.fromisoformat(ev["landfall_date"]) + dt.timedelta(days=day))


@lru_cache(maxsize=128)
def _thresholds() -> dict[str, float]:
    return {r["metric"]: r["value"] for r in get_db().rows("SELECT * FROM thresholds")}


ZIP_JOIN = """
FROM zips z
JOIN zip_static s USING (zip)
LEFT JOIN zip_hazard h ON h.zip = z.zip AND h.event_id = ? AND h.day = 0
LEFT JOIN predictions p ON p.zip = z.zip AND p.event_id = ?
LEFT JOIN gap_scores g ON g.zip = z.zip AND g.event_id = ? AND g.day = ?
"""


@lru_cache(maxsize=256)
def map_geojson(event_id: str, day: int) -> dict:
    """One GeoJSON feature per ZIP carrying every layer's metric, so switching
    layers in the UI needs no new request."""
    check_day(event_id, day)
    rows = get_db().rows(
        f"""SELECT z.zip, z.area_name, z.geom_geojson,
                   s.housing_units, s.svi_overall,
                   h.rain_total_in, h.hazard_index,
                   p.expected_final,
                   g.expected_by_day, g.observed, g.gap_score, g.unmet_estimate,
                   g.p_value, g.significant, g.priority, g.rank, g.actions_json
            {ZIP_JOIN}""",
        [event_id, event_id, event_id, day],
    )
    feats = []
    for r in rows:
        acts = json.loads(r["actions_json"]) if r["actions_json"] else []
        feats.append(
            {
                "type": "Feature",
                "id": r["zip"],
                "geometry": json.loads(r["geom_geojson"]),
                "properties": {
                    "zip": r["zip"],
                    "area": r["area_name"],
                    "housing_units": r["housing_units"],
                    "svi": _f(r["svi_overall"]),
                    "rain_in": _f(r["rain_total_in"], 1),
                    "hazard_index": _f(r["hazard_index"]),
                    "expected_final": _f(r["expected_final"], 0),
                    "expected_by_day": _f(r["expected_by_day"], 0),
                    "observed": r["observed"],
                    "gap_score": _f(r["gap_score"]),
                    "unmet": _f(r["unmet_estimate"], 0),
                    "significant": bool(r["significant"]) if r["significant"] is not None else False,
                    "priority": _f(r["priority"], 0),
                    "rank": r["rank"],
                    "lead_action": acts[0] if acts else None,
                },
            }
        )
    return {"type": "FeatureCollection", "features": feats}


@lru_cache(maxsize=256)
def kpis(event_id: str, day: int) -> dict:
    ev = check_day(event_id, day)
    r = get_db().one(
        """SELECT sum(expected_final) AS expected_final FROM predictions WHERE event_id = ?""",
        [event_id],
    )
    g = get_db().one(
        """SELECT sum(observed) AS registered, sum(expected_by_day) AS expected_by_day,
                  sum(unmet_estimate) FILTER (WHERE significant) AS unmet_sig,
                  sum(unmet_estimate) AS unmet,
                  count(*) FILTER (WHERE significant) AS n_significant,
                  count(*) AS n_zips, any_value(pace_ratio) AS pace_ratio
           FROM gap_scores WHERE event_id = ? AND day = ?""",
        [event_id, day],
    )
    too_early = day < 2 or (g and (g["registered"] or 0) < 200)
    return {
        "event_id": event_id,
        "day": day,
        "date": _date_for(ev, day),
        "expected_final": _f(r["expected_final"], 0),
        "registered": int(g["registered"] or 0) if g else 0,
        "expected_by_day": _f(g["expected_by_day"], 0) if g else None,
        "unmet": _f(g["unmet_sig"], 0) if g and g["unmet_sig"] is not None else 0,
        "n_significant": int(g["n_significant"] or 0) if g else 0,
        "n_zips": int(g["n_zips"] or 0) if g else 0,
        "pace_ratio": _f(g["pace_ratio"]) if g else None,
        "too_early": bool(too_early),
        "data_labels": {
            "expected_final": "predicted",
            "registered": "real",
            "unmet": "predicted",
            "n_significant": "predicted",
        },
    }


def _action_objs(codes: list[str]) -> list[dict]:
    return [
        {"code": c, "label": scoring.ACTIONS[c].label, "why": scoring.ACTIONS[c].why}
        for c in codes
        if c in scoring.ACTIONS
    ]


@lru_cache(maxsize=256)
def _priorities_all(event_id: str, day: int) -> tuple:
    rows = get_db().rows(
        f"""SELECT z.zip, z.area_name, z.centroid_lat, z.centroid_lon, s.svi_overall,
                   s.pct_65plus, s.pct_noveh, s.pct_limeng, s.pct_mobile,
                   g.expected_by_day, g.observed, g.gap_score, g.unmet_estimate, g.p_value,
                   g.significant, g.priority, g.rank, g.actions_json
            {ZIP_JOIN}
            WHERE g.zip IS NOT NULL
            ORDER BY g.rank""",
        [event_id, event_id, event_id, day],
    )
    return tuple(rows)


def priorities(event_id: str, day: int, limit: int = 20, significant_only: bool = False,
               action: str | None = None) -> dict:
    ev = check_day(event_id, day)
    items = []
    for r in _priorities_all(event_id, day):
        if significant_only and not r["significant"]:
            continue
        acts = json.loads(r["actions_json"])
        if action and action not in acts:
            continue
        if acts == ["monitor"]:
            continue  # on pace: not a to-do
        items.append(
            {
                "rank": len(items) + 1,
                "zip": r["zip"],
                "area": r["area_name"],
                "lat": r["centroid_lat"],
                "lon": r["centroid_lon"],
                "expected_by_day": _f(r["expected_by_day"], 0),
                "observed": r["observed"],
                "gap_score": _f(r["gap_score"]),
                "unmet_estimate": _f(r["unmet_estimate"], 0),
                "p_value": float(r["p_value"]),
                "significant": bool(r["significant"]),
                "svi": _f(r["svi_overall"]),
                "priority": _f(r["priority"], 0),
                "actions": _action_objs(acts),
                "data_labels": {"observed": "real", "expected_by_day": "predicted"},
            }
        )
        if len(items) >= limit:
            break
    return {"event_id": event_id, "day": day, "date": _date_for(ev, day), "items": items}


def zip_detail(event_id: str, zip_code: str, day: int) -> dict:
    check_day(event_id, day)
    db = get_db()
    r = db.one(
        f"""SELECT z.*, s.*, h.rain_total_in, h.hwm_count, h.hwm_max_ft,
                   h.damage_pts_per_1k_hu, h.hazard_index, h.damage_rising,
                   p.expected_final, p.lo80, p.hi80, p.contributions_json, p.model_version,
                   g.expected_by_day, g.observed, g.gap_score, g.unmet_estimate, g.p_value,
                   g.significant, g.priority, g.rank, g.actions_json, g.reasons_json
            {ZIP_JOIN} WHERE z.zip = ?""",
        [event_id, event_id, event_id, day, zip_code],
    )
    if not r:
        raise NotFound(f"unknown zip {zip_code}")

    # daily series: observed cumulative vs the pace-adjusted expectation curve
    series = db.rows(
        """SELECT g.day, g.observed, g.expected_by_day, g.significant
           FROM gap_scores g WHERE g.event_id = ? AND g.zip = ? ORDER BY g.day""",
        [event_id, zip_code],
    )
    thr = _thresholds()
    medians = db.one(
        "SELECT " + ", ".join(f"median({c}) AS {c}" for c in scoring.VULN_COLS) + " FROM zip_static"
    )
    vulnerability = [
        {
            "key": c,
            "label": scoring.NICE[c],
            "value": _f(r[c]),
            "median": _f(medians[c]),
            "p75": _f(thr.get(c)),
            "high": r[c] is not None and thr.get(c) is not None and r[c] >= thr[c],
        }
        for c in scoring.VULN_COLS
    ]
    contribs = json.loads(r["contributions_json"]) if r["contributions_json"] else {}
    history = [s["day"] for s in series if s["significant"]]
    return {
        "event_id": event_id,
        "day": day,
        "zip": zip_code,
        "area": r["area_name"],
        "lat": r["centroid_lat"],
        "lon": r["centroid_lon"],
        "housing_units": r["housing_units"],
        "svi": _f(r["svi_overall"]),
        "hazard": {
            "rain_total_in": _f(r["rain_total_in"], 1),
            "hwm_count": r["hwm_count"],
            "hwm_max_ft": _f(r["hwm_max_ft"], 1),
            "damage_pts_per_1k_hu": _f(r["damage_pts_per_1k_hu"], 1),
            "hazard_index": _f(r["hazard_index"]),
        },
        "prediction": {
            "expected_final": _f(r["expected_final"], 0),
            "lo80": _f(r["lo80"], 0),
            "hi80": _f(r["hi80"], 0),
            "model_version": r["model_version"],
            "contributions": sorted(
                [{"feature": k, "value": v} for k, v in contribs.items()],
                key=lambda x: -abs(x["value"]),
            ),
        },
        "gap": None
        if r["gap_score"] is None
        else {
            "expected_by_day": _f(r["expected_by_day"], 0),
            "observed": r["observed"],
            "gap_score": _f(r["gap_score"]),
            "unmet_estimate": _f(r["unmet_estimate"], 0),
            "p_value": float(r["p_value"]),
            "significant": bool(r["significant"]),
            "priority": _f(r["priority"], 0),
            "rank": r["rank"],
            "status": "flagged" if r["significant"] else (
                "on_pace" if r["gap_score"] < scoring.MONITOR_GAP else "watch"
            ),
        },
        "flag_history": {
            "first_flagged_day": history[0] if history else None,
            "last_flagged_day": history[-1] if history else None,
            "resolved": bool(history) and history[-1] < day,
        },
        "reasons": json.loads(r["reasons_json"]) if r["reasons_json"] else [],
        "actions": _action_objs(json.loads(r["actions_json"])) if r["actions_json"] else [],
        "vulnerability": vulnerability,
        "series": [
            {"day": s["day"], "observed": s["observed"], "expected": _f(s["expected_by_day"], 1)}
            for s in series
        ],
    }


def backtest(event_id: str) -> dict:
    get_event(event_id)
    db = get_db()
    rows = db.rows(
        "SELECT day, method, k, precision, hits, n_true FROM backtest WHERE event_id = ? "
        "ORDER BY day, k, method",
        [event_id],
    )
    labels = db.rows(
        "SELECT zip, overlooked FROM backtest_labels WHERE event_id = ?", [event_id]
    )
    top_ours = db.rows(
        "SELECT zip FROM gap_scores WHERE event_id = ? AND day = 5 ORDER BY rank LIMIT 25",
        [event_id],
    )
    return {
        "event_id": event_id,
        "metrics": rows,
        "definition": (
            "Ground truth, in hindsight: each ZIP's real final need is its home-damage "
            "registrations by day 60. On day 7 the region had received a share R of that; "
            "a ZIP's true shortfall is final x R minus what it had registered. Overlooked = "
            "the 10% of ZIPs with the largest true shortfall. Each method ranks ZIPs using "
            "only what was known on that day; our expected need is out-of-fold and never "
            "sees final counts."
        ),
        "labels": {r["zip"]: bool(r["overlooked"]) for r in labels},
        "top25_day5": [r["zip"] for r in top_ours],
    }
