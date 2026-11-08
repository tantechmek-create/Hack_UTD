"""Small paging client for the OpenFEMA API (no key needed).

Max 10,000 records per call; page with $skip. Results are cached to Parquet by the
callers so the demo never touches the network.
"""

from __future__ import annotations

import time

import pandas as pd
import requests

BASE = "https://www.fema.gov/api/open/"
UA = {"User-Agent": "overlooked-area-detector (hackathon research)"}


def count(entity: str, flt: str, version: str = "v2") -> int:
    r = requests.get(
        f"{BASE}{version}/{entity}",
        params={"$filter": flt, "$top": 1, "$count": "true", "$format": "json"},
        headers=UA,
        timeout=120,
    )
    r.raise_for_status()
    return int(r.json()["metadata"]["count"])


def fetch(
    entity: str,
    flt: str,
    select: str | None = None,
    version: str = "v2",
    page: int = 10_000,
    limit: int | None = None,
    order_by: str | None = "id",
    verbose: bool = True,
) -> pd.DataFrame:
    """Download every row matching `flt`. `limit` caps the total for quick probes."""
    rows: list[dict] = []
    skip = 0
    total = None
    while True:
        top = page if limit is None else min(page, limit - len(rows))
        params = {"$filter": flt, "$top": top, "$skip": skip, "$format": "json"}
        if select:
            params["$select"] = select
        if order_by:
            params["$orderby"] = order_by  # stable order so paging never skips/duplicates
        if total is None:
            params["$count"] = "true"
        for attempt in range(5):
            try:
                r = requests.get(f"{BASE}{version}/{entity}", params=params, headers=UA, timeout=180)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                wait = 2**attempt * 5
                if verbose:
                    print(f"  retry {attempt + 1} after {wait}s: {e}")
                time.sleep(wait)
        else:
            raise RuntimeError(f"OpenFEMA request failed repeatedly at skip={skip}")
        js = r.json()
        if total is None:
            total = js.get("metadata", {}).get("count")
        batch = js[entity]
        rows += batch
        if verbose:
            print(f"  {entity}: {len(rows):,} / {total if total is not None else '?'}")
        if len(batch) < top or (limit is not None and len(rows) >= limit):
            return pd.DataFrame(rows)
        skip += top
