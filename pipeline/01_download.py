"""Step 1: pull every public source into data/raw/ (run once, before the demo).

    python pipeline/01_download.py                # everything automatable
    python pipeline/01_download.py ihp svi        # just some sources

Re-running skips files that already exist (data/raw is immutable).
Not automated: FEMA modeled damage points (the public Harvey layers now need an ArcGIS
token) and the NRI table (its download link moved). The pipeline runs without both.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.utils.openfema import fetch

RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
EVENTS = yaml.safe_load((ROOT / "config" / "events.yaml").read_text())["events"]
EV = EVENTS[0]
DR = EV["disaster_number"]

IHP_FIELDS = (
    "id,disasterNumber,fips,county,censusGeoid,damagedCity,damagedZipCode,applicantAge,"
    "householdComposition,ownRent,residenceType,registrationMethod,homeDamage,floodDamage,"
    "reportedDamage,rpfvl,waterLevel,destroyed,accessFunctionalNeeds,currentLocation,appliedDate"
)
NFIP_FIELDS = (  # v3 schema; openDate = when the claim was opened (an FNOL-like timing signal)
    "id,dateOfLoss,yearOfLoss,openDate,floodEvent,reportedZipCode,censusGeoid,countyCode,"
    "buildingDamageAmount,amountPaidOnBuildingClaim,occupancyType,primaryResidenceIndicator"
)


def _skip(path: Path) -> bool:
    if path.exists():
        print(f"✓ {path.relative_to(ROOT)} exists, skipping")
        return True
    print(f"↓ {path.relative_to(ROOT)}")
    return False


def _get(url: str, timeout: int = 600) -> bytes:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "overlooked-area-detector"})
    r.raise_for_status()
    return r.content


def declarations():
    out = RAW / f"declarations_{DR}.parquet"
    if _skip(out):
        return
    fetch("DisasterDeclarationsSummaries", f"disasterNumber eq {DR}").to_parquet(out)


def ihp():
    """Core source: one row per valid registrant, with appliedDate and ZIP."""
    out = RAW / f"ihp_{DR}.parquet"
    if _skip(out):
        return
    df = fetch(
        "IndividualsAndHouseholdsProgramValidRegistrations",
        f"disasterNumber eq {DR}",
        select=IHP_FIELDS,
    )
    df.to_parquet(out)
    print(f"  saved {len(df):,} registrations")


def nfip():
    """Texas NFIP claims: Harvey-window claims (ground truth) and pre-2017 history (feature)."""
    out = RAW / "nfip_tx.parquet"
    if _skip(out):
        return
    df = fetch("NfipClaims", "state eq 'TX'", select=NFIP_FIELDS, version="v3")
    df.to_parquet(out)
    print(f"  saved {len(df):,} TX claims")


def svi():
    out = RAW / "svi_2016_tx.csv"
    if _skip(out):
        return
    out.write_bytes(_get("https://svi.cdc.gov/Documents/Data/2016/csv/states/Texas.csv"))


def zcta():
    """2010 ZCTA polygons for Texas (SVI 2016 uses 2010 tracts, so stay on 2010 geography)."""
    out = RAW / "zcta2010_tx"
    if _skip(out):
        return
    data = _get("https://www2.census.gov/geo/tiger/TIGER2010/ZCTA5/2010/tl_2010_48_zcta510.zip")
    zipfile.ZipFile(io.BytesIO(data)).extractall(out)


def zcta_tract_rel():
    out = RAW / "zcta_tract_rel_10.parquet"
    if _skip(out):
        return
    data = _get("https://www2.census.gov/geo/docs/maps-data/data/rel/zcta_tract_rel_10.txt")
    df = pd.read_csv(io.BytesIO(data), dtype={"ZCTA5": str, "STATE": str, "COUNTY": str,
                                              "TRACT": str, "GEOID": str})
    df[df["STATE"] == "48"].to_parquet(out)


def stage4():
    """NOAA/NWS Stage IV daily (12Z-12Z) precipitation GeoTIFFs over the rain window."""
    out = RAW / "stageiv"
    out.mkdir(exist_ok=True)
    start, end = EV["rain_window"]
    for d in pd.date_range(start, end):
        f = out / f"{d:%Y%m%d}.tif"
        if f.exists():
            continue
        url = (
            "https://water.noaa.gov/resources/downloads/precip/stageIV/"
            f"{d:%Y/%m/%d}/nws_precip_1day_{d:%Y%m%d}_conus.tif"
        )
        print(f"↓ {f.relative_to(ROOT)}")
        f.write_bytes(_get(url))


def hwm():
    """USGS STN high-water marks for the event (STN moved to api.waterdata.usgs.gov)."""
    out = RAW / "hwm_harvey.parquet"
    if _skip(out):
        return
    url = f"https://api.waterdata.usgs.gov/stnservices/hwms/?event={EV['stn_event_id']}"
    df = pd.DataFrame(requests.get(url, timeout=600, headers={"Accept": "application/json"}).json())
    keep = ["id", "latitude_dd", "longitude_dd", "height_above_ground", "elev_ft", "environment",
            "stillwater", "hwm_quality", "flag_date", "waterbody"]
    df = df[[c for c in keep if c in df.columns]]
    df.to_parquet(out)
    print(f"  saved {len(df):,} high-water marks")


def schools():
    """Candidate team sites: NCES public school locations (2017-18) inside the event bbox."""
    out = RAW / "schools_nces_1718.parquet"
    if _skip(out):
        return
    url = ("https://nces.ed.gov/opengis/rest/services/K12_School_Locations/"
           "EDGE_GEOCODE_PUBLICSCH_1718/MapServer/0/query")
    x0, y0, x1, y1 = EV["bbox"]
    rows, offset = [], 0
    while True:
        r = requests.get(url, timeout=120, params={
            "where": "1=1", "geometry": f"{x0},{y0},{x1},{y1}",
            "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "NCESSCH,NAME,CITY,ZIP,LAT,LON",
            "returnGeometry": "false", "resultOffset": offset, "resultRecordCount": 1000, "f": "json",
        })
        r.raise_for_status()
        feats = r.json().get("features", [])
        rows += [f["attributes"] for f in feats]
        if len(feats) < 1000:
            break
        offset += len(feats)
    pd.DataFrame(rows).to_parquet(out)
    print(f"  saved {len(rows):,} schools")


SOURCES = {
    "declarations": declarations,
    "svi": svi,
    "zcta": zcta,
    "rel": zcta_tract_rel,
    "ihp": ihp,
    "nfip": nfip,
    "stage4": stage4,
    "hwm": hwm,
    "schools": schools,
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SOURCES)
    for name in wanted:
        SOURCES[name]()
    print("done")
