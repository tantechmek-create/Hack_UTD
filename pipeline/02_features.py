"""Step 2: raw sources -> per-ZIP tables in data/processed/ (Parquet).

    python pipeline/02_features.py

Writes:
  zips.parquet                ZCTA polygons + centroid + name (study area only)
  zip_static.parquet          housing units, SVI components, flood-claim history
  zip_hazard.parquet          storm rainfall, high-water marks, hazard_index (day 0 = storm totals)
  registrations_daily.parquet cumulative FEMA registrations by ZIP and day (0..target_day)
  nfip_claims_event.parquet   Harvey NFIP claims per ZIP (validation only, never a model input)
  thresholds.parquet          75th percentile of each vulnerability column across Texas tracts

Geography: 2010 ZCTAs, because SVI 2016 is built on 2010 tracts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterstats import zonal_stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from core import scoring

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)
EV = yaml.safe_load((ROOT / "config" / "events.yaml").read_text())["events"][0]
LANDFALL = pd.Timestamp(EV["landfall_date"])
STUDY = set(EV["county_fips"])

MIN_HU = 300          # drop ZCTAs that are mostly non-residential (airports, parks, PO boxes)
HWM_MAX_FT = 20.0     # a few STN heights are survey errors (up to 152 ft); clip them
SVI_MAP = {           # SVI 2016 estimate-percent column -> our column (stored as 0..1)
    "EP_AGE65": "pct_65plus",
    "EP_NOVEH": "pct_noveh",
    "EP_LIMENG": "pct_limeng",
    "EP_MOBILE": "pct_mobile",
    "EP_POV": "pct_poverty",
}


def load_svi() -> pd.DataFrame:
    svi = pd.read_csv(RAW / "svi_2016_tx.csv", dtype={"FIPS": str})
    svi = svi.replace(-999, np.nan)
    pct = pd.DataFrame({dst: svi[src] / 100.0 for src, dst in SVI_MAP.items()})
    return pd.concat([svi, pct], axis=1).rename(columns={"FIPS": "tract", "RPL_THEMES": "svi_overall"})


def build_universe(svi: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Study ZCTAs = most of their population lives in the declared study counties."""
    rel = pd.read_parquet(RAW / "zcta_tract_rel_10.parquet")
    rel["county"] = rel["STATE"] + rel["COUNTY"]
    share = rel[rel["county"].isin(STUDY)].groupby("ZCTA5")["ZPOPPCT"].sum()
    zips = share[share >= 50].index

    rel = rel[rel["ZCTA5"].isin(zips)].copy()
    main_county = rel.sort_values("POPPT").groupby("ZCTA5")["county"].last()

    # tract -> ZCTA: housing units split by the tract's HU share; percentages weighted by
    # the population that tract contributes to the ZCTA
    cols = ["tract", "E_HU", "E_TOTPOP", "svi_overall", *SVI_MAP.values()]
    rel = rel.merge(svi[cols], left_on="GEOID", right_on="tract", how="left")
    rel["hu_part"] = rel["E_HU"] * rel["TRHUPCT"] / 100.0
    rel["pop_w"] = rel["E_TOTPOP"] * rel["TRPOPPCT"] / 100.0

    def wmean(g: pd.DataFrame, col: str) -> float:
        m = g[col].notna() & (g["pop_w"] > 0)
        return float(np.average(g.loc[m, col], weights=g.loc[m, "pop_w"])) if m.any() else np.nan

    rows = []
    for z, g in rel.groupby("ZCTA5"):
        r = {"zip": z, "housing_units": g["hu_part"].sum(), "population": g["pop_w"].sum()}
        for col in ["svi_overall", *SVI_MAP.values()]:
            r[col] = wmean(g, col)
        rows.append(r)
    static = pd.DataFrame(rows)
    static["housing_units"] = static["housing_units"].round().astype(int)
    static["county_fips"] = static["zip"].map(main_county)
    static = static[static["housing_units"] >= MIN_HU].reset_index(drop=True)
    return static, rel


def nfip_tables(static: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    n = pd.read_parquet(RAW / "nfip_tx.parquet")
    n["zip"] = n["reportedZipCode"].astype(str).str.extract(r"(\d{5})")[0]
    n["dol"] = pd.to_datetime(n["dateOfLoss"]).dt.tz_localize(None)
    n["opened"] = pd.to_datetime(n["openDate"]).dt.tz_localize(None)

    # history: every claim with a loss date before this event (a pre-event feature)
    hist = n[n["dol"] < LANDFALL - pd.Timedelta(days=30)].groupby("zip").size()
    hist_per_1k = (hist.reindex(static["zip"]).fillna(0).to_numpy() /
                   static["housing_units"].to_numpy() * 1000)

    # this event: validation only
    ev = n[(n["floodEvent"] == EV["nfip_flood_event"]) & n["zip"].isin(static["zip"])].copy()
    ev["open_day"] = (ev["opened"] - LANDFALL).dt.days
    ev["damaged"] = ev["buildingDamageAmount"].fillna(0) > 0
    claims = ev.groupby("zip").agg(
        claims=("id", "size"),
        claims_damaged=("damaged", "sum"),
        building_damage_usd=("buildingDamageAmount", "sum"),
        claims_by_day3=("open_day", lambda s: int((s <= 3).sum())),
    ).reset_index()
    claims.insert(0, "event_id", EV["event_id"])
    return pd.Series(hist_per_1k, index=static["zip"]).round(2), claims


def rain_totals(zips: gpd.GeoDataFrame) -> pd.Series:
    start, end = EV["rain_window"]
    total, meta = None, None
    for d in pd.date_range(start, end):
        with rasterio.open(RAW / "stageiv" / f"{d:%Y%m%d}.tif") as r:
            a = r.read(1, masked=True).filled(0).astype("float64")
            a[a < 0] = 0
            total = a if total is None else total + a
            meta = (r.crs, r.transform)
    crs, transform = meta
    geoms = zips.to_crs(crs.to_wkt()).geometry
    # Stage IV cells are ~4.8 km, larger than many urban ZCTAs: all_touched keeps every ZCTA
    stats = zonal_stats(geoms, total, affine=transform, stats=["mean"], all_touched=True, nodata=-1)
    return pd.Series([s["mean"] for s in stats], index=zips["zip"].to_numpy()).round(1)


def hwm_stats(zips: gpd.GeoDataFrame) -> pd.DataFrame:
    h = pd.read_parquet(RAW / "hwm_harvey.parquet")
    h["ft"] = pd.to_numeric(h["height_above_ground"], errors="coerce").clip(upper=HWM_MAX_FT)
    pts = gpd.GeoDataFrame(h, geometry=gpd.points_from_xy(h.longitude_dd, h.latitude_dd), crs=4326)
    j = gpd.sjoin(pts, zips[["zip", "geometry"]], predicate="within")
    agg = j.groupby("zip").agg(hwm_count=("id", "size"), hwm_max_ft=("ft", "max"))
    return agg.reindex(zips["zip"]).fillna({"hwm_count": 0, "hwm_max_ft": 0.0})


def registrations(static: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    r = pd.read_parquet(RAW / f"ihp_{EV['disaster_number']}.parquet")
    r["zip"] = r["damagedZipCode"].astype(str).str.extract(r"(\d{5})")[0]
    r = r[r["zip"].isin(static["zip"])].copy()
    r["day"] = (pd.to_datetime(r["appliedDate"]).dt.tz_localize(None) - LANDFALL).dt.days
    r["day"] = r["day"].clip(lower=0)  # a handful pre-register before landfall
    target_day = EV["target_day"]
    r = r[r["day"] <= target_day]

    r["home"] = r["homeDamage"].fillna(False).astype(bool)
    r["age65"] = r["applicantAge"] == "65+"
    r["mobile"] = r["residenceType"] == "M"
    r["callcenter"] = r["registrationMethod"] == "C"

    daily = r.groupby(["zip", "day"]).agg(
        n_new=("id", "size"), home=("home", "sum"), age65=("age65", "sum"),
        mobile=("mobile", "sum"), callcenter=("callcenter", "sum"),
    )
    full = pd.MultiIndex.from_product([static["zip"], range(target_day + 1)], names=["zip", "day"])
    daily = daily.reindex(full, fill_value=0).reset_index()
    g = daily.groupby("zip")
    out = pd.DataFrame({
        "event_id": EV["event_id"],
        "zip": daily["zip"],
        "day": daily["day"],
        "n_new": daily["n_new"],
        "n_cum": g["n_new"].cumsum(),
        "n_cum_home_damage": g["home"].cumsum(),
        "n_cum_65plus": g["age65"].cumsum(),
        "n_cum_mobile": g["mobile"].cumsum(),
        "n_cum_callcenter": g["callcenter"].cumsum(),
    })
    out[out.columns[3:]] = out[out.columns[3:]].astype(int)
    # most common city name the registrants gave, for a human-readable label
    city = r.groupby("zip")["damagedCity"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else "")
    return out, city


def main():
    svi = load_svi()
    static, _ = build_universe(svi)

    shp = gpd.read_file(RAW / "zcta2010_tx" / "tl_2010_48_zcta510.shp")
    shp = shp.rename(columns={"ZCTA5CE10": "zip"})[["zip", "geometry"]].to_crs(4326)
    zips = shp.merge(static[["zip", "county_fips"]], on="zip")
    static = static[static["zip"].isin(zips["zip"])].reset_index(drop=True)
    print(f"{len(static)} ZCTAs in the study area, {static.housing_units.sum():,} housing units")

    hist, claims = nfip_tables(static)
    static["hist_nfip_claims_per_1k_hu"] = static["zip"].map(hist)
    static["nri_flood_eal_score"] = np.nan  # NRI table not downloadable automatically

    regs, city = registrations(static)

    # ---- zips (geometry simplified ~50 m for the browser)
    cent = zips.to_crs(3083).geometry.centroid.to_crs(4326)
    zips["centroid_lat"] = cent.y.round(5)
    zips["centroid_lon"] = cent.x.round(5)
    simp = zips.to_crs(3083).geometry.simplify(50).to_crs(4326)
    zips["geom_geojson"] = [json.dumps(g.__geo_interface__) for g in simp]
    zips["area_name"] = [
        f"{city.get(z, '').title()} {z}".strip() if city.get(z) else f"ZIP {z}" for z in zips["zip"]
    ]

    # ---- hazard (day 0 = storm totals)
    hz = hwm_stats(zips)
    hazard = pd.DataFrame({
        "event_id": EV["event_id"],
        "zip": zips["zip"].to_numpy(),
        "day": 0,
        "rain_total_in": rain_totals(zips).to_numpy(),
        "hwm_count": hz["hwm_count"].astype(int).to_numpy(),
        "hwm_max_ft": hz["hwm_max_ft"].round(1).to_numpy(),
        # FEMA modeled damage points are not publicly downloadable any more (token-gated);
        # left empty rather than substituting Harvey NFIP claims, which are the validation label
        "damage_pts_per_1k_hu": np.nan,
        "damage_rising": False,
    })
    ranks = hazard[["rain_total_in", "hwm_max_ft"]].rank(pct=True)
    hazard["hazard_index"] = ranks.mean(axis=1).round(3)

    # ---- thresholds relative to Texas tracts (blueprint section 9)
    thr = pd.DataFrame(
        [{"metric": c, "value": float(svi[c].quantile(0.75))} for c in scoring.VULN_COLS]
    )

    zips_out = pd.DataFrame(zips.drop(columns="geometry"))[
        ["zip", "area_name", "county_fips", "centroid_lat", "centroid_lon", "geom_geojson"]
    ]
    static_out = static[[
        "zip", "housing_units", "population", "svi_overall", *scoring.VULN_COLS,
        "hist_nfip_claims_per_1k_hu", "nri_flood_eal_score",
    ]]
    for name, df in {
        "zips": zips_out, "zip_static": static_out, "zip_hazard": hazard,
        "registrations_daily": regs, "nfip_claims_event": claims, "thresholds": thr,
    }.items():
        df.to_parquet(OUT / f"{name}.parquet", index=False)
        print(f"  {name}: {len(df):,} rows")

    final = regs[regs.day == EV["target_day"]]
    print(f"home-damage registrations by day {EV['target_day']}: {final.n_cum_home_damage.sum():,}"
          f" (all: {final.n_cum.sum():,})")
    print(hazard[["rain_total_in", "hwm_count", "hwm_max_ft"]].describe().round(1).to_string())


if __name__ == "__main__":
    main()
