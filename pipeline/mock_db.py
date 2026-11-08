"""Generate a MOCK oad.duckdb with the real schema and fake numbers.

Lets the API and frontend be built before the real pipeline finishes
(blueprint section 12, Phase 4). Every number here is synthetic; the event is
flagged data_mode = "mock" and the UI shows a MOCK banner.

    python pipeline/mock_db.py [--out data/oad.duckdb]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.utils.build import (
    overlooked_labels,
    run_backtest,
    score_event,
    vuln_thresholds,
    write_db,
)

rng = np.random.default_rng(7)
EV = yaml.safe_load((ROOT / "config" / "events.yaml").read_text())["events"][0]


def hex_grid(bbox, size):
    """Pointy-top hexagons covering bbox; returns list of (lon, lat, ring)."""
    minx, miny, maxx, maxy = bbox
    w = math.sqrt(3) * size
    h = 1.5 * size
    cells = []
    row = 0
    y = miny
    while y <= maxy:
        x = minx + (w / 2 if row % 2 else 0)
        while x <= maxx:
            ring = [
                [round(x + size * math.cos(math.radians(60 * i - 30)) * 1.0, 5),
                 round(y + size * math.sin(math.radians(60 * i - 30)) * 0.87, 5)]
                for i in range(6)
            ]
            ring.append(ring[0])
            cells.append((x, y, ring))
            x += w
        y += h * 0.87
        row += 1
    return cells


def main(out: Path):
    cells = hex_grid(EV["bbox"], 0.032)
    n = len(cells)
    lon = np.array([c[0] for c in cells])
    lat = np.array([c[1] for c in cells])
    cx, cy = EV["center"]
    # normalized coordinates (east positive, north positive)
    ex = (lon - cx) / 0.5
    ny = (lat - cy) / 0.4
    dist = np.sqrt(ex**2 + ny**2)

    zips = pd.DataFrame(
        {
            "zip": [f"M{i:04d}" for i in range(n)],
            "area_name": [f"Mock zone {i:03d}" for i in range(n)],
            "county_fips": "48201",
            "centroid_lat": lat,
            "centroid_lon": lon,
            "geom_geojson": [json.dumps({"type": "Polygon", "coordinates": [c[2]]}) for c in cells],
        }
    )

    # --- static: denser near the center; more vulnerable to the east/southeast
    hu = np.round(np.exp(rng.normal(8.9, 0.35, n)) * np.clip(1.4 - 0.5 * dist, 0.35, 1.4)).astype(int)
    vuln_field = 0.5 + 0.25 * ex - 0.15 * ny + rng.normal(0, 0.15, n)

    def pct(base, scale, noise):
        return np.clip(base + scale * vuln_field + rng.normal(0, noise, n), 0.005, 0.9)

    static = pd.DataFrame(
        {
            "zip": zips["zip"],
            "housing_units": hu,
            "pct_65plus": pct(0.08, 0.06, 0.03),
            "pct_noveh": pct(0.02, 0.12, 0.03),
            "pct_limeng": pct(0.02, 0.22, 0.05),
            "pct_mobile": np.clip(rng.gamma(0.6, 0.03, n) * (1 + dist), 0, 0.5),
            "pct_poverty": pct(0.05, 0.2, 0.05),
            "hist_nfip_claims_per_1k_hu": np.round(rng.gamma(1.5, 12, n) * (1 + 0.5 * ex.clip(0)), 1),
            "nri_flood_eal_score": np.round(np.clip(50 + 20 * ex + rng.normal(0, 12, n), 1, 99), 1),
        }
    )
    static["svi_overall"] = (
        static[["pct_noveh", "pct_limeng", "pct_poverty", "pct_65plus"]].rank(pct=True).mean(axis=1)
    ).rank(pct=True)

    # --- hazard: heaviest rain in a band east of the center (as in Harvey)
    rain = np.clip(28 + 14 * np.exp(-((ex - 0.6) ** 2) / 0.5) + 6 * np.sin(3 * ny) + rng.normal(0, 3, n), 12, 60)
    lowland = np.clip(0.5 + 0.3 * ex - 0.3 * ny + rng.normal(0, 0.2, n), 0, 1)
    hwm_count = rng.poisson(np.clip((rain - 25) / 6 * lowland, 0, None))
    hwm_max = np.where(hwm_count > 0, np.round(rng.gamma(2, 1.2, n) * lowland + 0.5, 1), 0.0)
    true_rate = 1 / (1 + np.exp(-(0.11 * (rain - 38) + 2.2 * (lowland - 0.5)))) * 0.45
    dmg = np.round(true_rate * 1000 * rng.lognormal(0, 0.25, n), 1)
    hazard = pd.DataFrame(
        {
            "event_id": EV["event_id"],
            "zip": zips["zip"],
            "day": 0,
            "rain_total_in": np.round(rain, 1),
            "hwm_count": hwm_count,
            "hwm_max_ft": hwm_max,
            "damage_pts_per_1k_hu": dmg,
            "damage_rising": rng.random(n) < 0.3 * lowland,
        }
    )
    ranks = hazard[["rain_total_in", "hwm_max_ft", "damage_pts_per_1k_hu"]].rank(pct=True)
    hazard["hazard_index"] = ranks.mean(axis=1).round(3)

    # --- truth: final home-damage registrations and registration timing
    final = rng.poisson(hu * true_rate)
    tau = 4.5 + 9 * static["pct_limeng"] + 12 * static["pct_noveh"] + 8 * static["pct_65plus"]
    stuck = rng.random(n) < 0.08  # a few genuinely overlooked areas
    tau = np.where(stuck, tau * 2.6, tau) * rng.lognormal(0, 0.15, n)
    days = np.arange(0, EV["max_day"] + 1)
    reg_rows = []
    for i in range(n):
        frac = 1 - np.exp(-np.maximum(days - 0.5, 0) / tau[i])
        cum = np.maximum.accumulate(rng.binomial(final[i], frac))
        allcum = np.round(cum * rng.uniform(1.25, 1.6)).astype(int)
        new = np.diff(np.concatenate([[0], allcum]))
        for d, c, a, nw in zip(days, cum, allcum, new):
            reg_rows.append((zips["zip"][i], int(d), int(nw), int(a), int(c)))
    regs = pd.DataFrame(reg_rows, columns=["zip", "day", "n_new", "n_cum", "n_cum_home_damage"])
    regs["n_cum_65plus"] = (regs["n_cum"] * 0.18).round().astype(int)
    regs["n_cum_mobile"] = (regs["n_cum"] * 0.04).round().astype(int)
    regs["n_cum_callcenter"] = (regs["n_cum"] * 0.3).round().astype(int)
    regs.insert(0, "event_id", EV["event_id"])

    # --- "model": truth with error, plus made-up linear contributions
    expected = final * rng.lognormal(0, 0.18, n) + 5
    contrib_cols = {
        "rain_total_in": 0.9, "damage_pts_per_1k_hu": 1.1, "hwm_max_ft": 0.4,
        "hist_nfip_claims_per_1k_hu": 0.3, "pct_mobile": 0.2, "pct_poverty": 0.15,
    }
    feat = hazard.merge(static, on="zip")
    z = (feat[list(contrib_cols)] - feat[list(contrib_cols)].mean()) / feat[list(contrib_cols)].std()
    contribs = [
        json.dumps({c: round(float(z.iloc[i][c] * w), 3) for c, w in contrib_cols.items()})
        for i in range(n)
    ]
    preds = pd.DataFrame(
        {
            "event_id": EV["event_id"],
            "zip": zips["zip"],
            "model_version": "mock-0",
            "expected_final": np.round(expected, 1),
            "lo80": np.round(expected * 0.8, 1),
            "hi80": np.round(expected * 1.22, 1),
            "contributions_json": contribs,
        }
    )

    thresholds = vuln_thresholds(static)
    gaps = score_event(EV["event_id"], EV["max_day"], preds, regs, static, hazard, thresholds)

    labels = overlooked_labels(regs, pd.DataFrame({"zip": zips["zip"], "final": final}))
    bt = run_backtest(EV["event_id"], gaps, labels, static, hazard)
    labels.insert(0, "event_id", EV["event_id"])

    # --- candidate sites
    m = 160
    sidx = rng.integers(0, n, m)
    sites = pd.DataFrame(
        {
            "site_id": [f"mock_site_{i:03d}" for i in range(m)],
            "name": [f"Mock lot {i:03d}" for i in range(m)],
            "kind": rng.choice(["parking", "school", "place_of_worship"], m),
            "lat": lat[sidx] + rng.normal(0, 0.006, m),
            "lon": lon[sidx] + rng.normal(0, 0.006, m),
            "zip": zips["zip"].to_numpy()[sidx],
            "source": "simulated",
        }
    )
    hz = hazard.set_index("zip")
    site_flags = pd.DataFrame(
        {
            "event_id": EV["event_id"],
            "site_id": sites["site_id"],
            "flooded": [bool(hz.loc[z, "hazard_index"] > 0.8 or hz.loc[z, "hwm_max_ft"] > 3.5) for z in sites["zip"]],
        }
    )

    events = pd.DataFrame(
        [
            {
                "event_id": EV["event_id"],
                "name": EV["name"],
                "disaster_number": EV["disaster_number"],
                "landfall_date": pd.Timestamp(EV["landfall_date"]).date(),
                "bbox": json.dumps(EV["bbox"]),
                "center": json.dumps(EV["center"]),
                "max_day": EV["max_day"],
                "data_mode": "mock",
                "counties": "Harris County area",
            }
        ]
    )
    thr = pd.DataFrame([{"metric": k, "value": v} for k, v in thresholds.items()])
    runs = pd.DataFrame(
        [{"model_version": "mock-0", "algorithm": "mock", "params_json": "{}", "cv_deviance": None,
          "cv_spearman": None, "trained_at": pd.Timestamp.now(tz="UTC").isoformat()}]
    )

    write_db(
        {
            "events": events,
            "zips": zips,
            "zip_static": static,
            "zip_hazard": hazard,
            "registrations_daily": regs,
            "predictions": preds,
            "gap_scores": gaps,
            "thresholds": thr,
            "sites": sites,
            "site_flags": site_flags,
            "backtest": bt,
            "backtest_labels": labels,
            "model_runs": runs,
        },
        out,
    )
    d5 = gaps[gaps.day == 5]
    print(f"day 5: {int(d5.significant.sum())} significant of {len(d5)} zones")
    print(bt[(bt.day == 5) & (bt.k == 10)][["method", "precision"]].to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "mock.duckdb"))
    main(Path(ap.parse_args().out))
