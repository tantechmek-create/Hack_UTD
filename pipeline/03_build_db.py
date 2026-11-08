"""Step 4: processed Parquet + predictions -> gap scores, backtest, sites -> data/oad.duckdb.

    python pipeline/03_build_db.py [--out data/oad.duckdb]

The API reads only this file. It is written to a temp file and swapped in atomically.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.utils.build import overlooked_labels, run_backtest, score_event, write_db

RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
EV = yaml.safe_load((ROOT / "config" / "events.yaml").read_text())["events"][0]

COUNTY_NAMES = {
    "48201": "Harris", "48157": "Fort Bend", "48339": "Montgomery", "48039": "Brazoria",
    "48167": "Galveston", "48071": "Chambers", "48291": "Liberty", "48473": "Waller",
}
SITE_FLOOD_RADIUS_M = 800   # a high-water mark this close ...
SITE_FLOOD_FT = 1.5         # ... at least this high above ground = site likely flooded


def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(PROC / f"{name}.parquet")


def build_sites(zips: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Candidate team sites = public schools (NCES 2017-18) inside study ZIPs.

    A site is 'flooded' if a USGS high-water mark >= 1.5 ft above ground lies within 800 m.
    """
    s = pd.read_parquet(RAW / "schools_nces_1718.parquet")
    pts = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.LON, s.LAT), crs=4326)
    polys = gpd.GeoDataFrame(
        zips[["zip"]], geometry=[shape(json.loads(g)) for g in zips["geom_geojson"]], crs=4326
    )
    pts = gpd.sjoin(pts, polys, predicate="within").drop(columns="index_right")
    sites = pd.DataFrame({
        "site_id": "nces_" + pts["NCESSCH"].astype(str),
        "name": pts["NAME"].str.title(),
        "kind": "school",
        "lat": pts["LAT"].round(5),
        "lon": pts["LON"].round(5),
        "zip": pts["zip"],
        "source": "NCES EDGE public schools 2017-18",
    }).drop_duplicates("site_id").reset_index(drop=True)

    h = pd.read_parquet(RAW / "hwm_harvey.parquet")
    h["ft"] = pd.to_numeric(h["height_above_ground"], errors="coerce")
    h = h[h["ft"] >= SITE_FLOOD_FT]
    hwm = gpd.GeoDataFrame(h, geometry=gpd.points_from_xy(h.longitude_dd, h.latitude_dd), crs=4326)
    sp = gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites.lon, sites.lat), crs=4326)
    near = gpd.sjoin(sp.to_crs(3083), hwm.to_crs(3083)[["geometry"]], predicate="dwithin",
                     distance=SITE_FLOOD_RADIUS_M)
    flooded = set(near["site_id"])
    flags = pd.DataFrame({
        "event_id": EV["event_id"],
        "site_id": sites["site_id"],
        "flooded": sites["site_id"].isin(flooded),
    })
    return sites, flags


def main(out: Path):
    zips = load("zips")
    static = load("zip_static")
    hazard = load("zip_hazard")
    regs = load("registrations_daily")
    preds = load("predictions")
    runs = load("model_runs")
    claims = load("nfip_claims_event")
    thr_df = load("thresholds")
    thresholds = dict(zip(thr_df["metric"], thr_df["value"]))

    # the app shows days 0..max_day; the day-60 counts were only needed for training
    regs_app = regs[regs["day"] <= EV["max_day"]].reset_index(drop=True)
    gaps = score_event(EV["event_id"], EV["max_day"], preds, regs_app, static, hazard, thresholds)

    # hindsight ground truth for the backtest (uses the day-60 counts the app never shows)
    final = (regs[regs["day"] == EV["target_day"]][["zip", "n_cum_home_damage"]]
             .rename(columns={"n_cum_home_damage": "final"}))
    labels = overlooked_labels(regs, final)
    bt = run_backtest(EV["event_id"], gaps, labels, static, hazard)
    labels.insert(0, "event_id", EV["event_id"])

    sites, flags = build_sites(zips)

    counties = [COUNTY_NAMES.get(c, c) for c in EV["county_fips"]]
    events = pd.DataFrame([{
        "event_id": EV["event_id"],
        "name": EV["name"],
        "disaster_number": EV["disaster_number"],
        "landfall_date": pd.Timestamp(EV["landfall_date"]).date(),
        "bbox": json.dumps(EV["bbox"]),
        "center": json.dumps(EV["center"]),
        "max_day": EV["max_day"],
        "data_mode": "real",
        "counties": f"{counties[0]} County and {len(counties) - 1} neighboring counties",
    }])

    write_db({
        "events": events,
        "zips": zips,
        "zip_static": static,
        "zip_hazard": hazard,
        "registrations_daily": regs_app,
        "predictions": preds,
        "gap_scores": gaps,
        "thresholds": thr_df,
        "sites": sites,
        "site_flags": flags,
        "backtest": bt,
        "backtest_labels": labels,
        "model_runs": runs,
        "nfip_claims_event": claims,
    }, out)

    for day in (3, 5, 7):
        d = gaps[gaps.day == day]
        print(f"day {day}: pace R={d.pace_ratio.iat[0]:.3f}  significant {int(d.significant.sum())}"
              f"/{len(d)}  unmet(sig) ~{d.loc[d.significant, 'unmet_estimate'].sum():,.0f}")
    print(f"sites: {len(sites)} ({int(flags.flooded.sum())} flooded)   "
          f"overlooked labels: {int(labels.overlooked.sum())}/{len(labels)}")
    for k in (10, 25):
        print(f"precision@{k}:")
        print(bt[bt.k == k].pivot(index="method", columns="day", values="precision").round(2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "oad.duckdb"))
    main(Path(ap.parse_args().out))
