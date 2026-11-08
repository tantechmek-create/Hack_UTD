"""Greedy weighted maximum coverage for catastrophe-team placement (F7).

Repeatedly add the candidate site that covers the most still-uncovered priority weight
within `radius_km`. Greedy is within (1 - 1/e) ~ 63% of optimal for this problem.
"""

from __future__ import annotations

import numpy as np

EARTH_KM = 6371.0088


def haversine_matrix(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Distances in km between every point in set 1 (rows) and set 2 (cols)."""
    lat1, lon1 = np.radians(np.asarray(lat1))[:, None], np.radians(np.asarray(lon1))[:, None]
    lat2, lon2 = np.radians(np.asarray(lat2))[None, :], np.radians(np.asarray(lon2))[None, :]
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def greedy_max_coverage(
    site_lat, site_lon, zip_lat, zip_lon, weights, k: int, radius_km: float
) -> dict:
    """Return chosen site indices (in pick order), covered ZIP indices per site,
    covered weight per site, and overall coverage fraction."""
    w = np.asarray(weights, dtype=float)
    w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
    total = float(w.sum())
    n_sites = len(site_lat)
    if n_sites == 0 or total == 0 or k <= 0:
        return {"chosen": [], "covered": [], "gain": [], "coverage_pct": 0.0}

    cover = haversine_matrix(site_lat, site_lon, zip_lat, zip_lon) <= radius_km  # sites x zips
    uncovered = np.ones(len(w), dtype=bool)
    chosen, covered, gain = [], [], []
    for _ in range(min(k, n_sites)):
        gains = cover[:, uncovered] @ w[uncovered]
        if chosen:
            gains[chosen] = -1
        best = int(np.argmax(gains))
        if gains[best] <= 0:
            break
        newly = cover[best] & uncovered
        chosen.append(best)
        covered.append(np.flatnonzero(newly).tolist())
        gain.append(float(w[newly].sum()))
        uncovered &= ~cover[best]

    return {
        "chosen": chosen,
        "covered": covered,
        "gain": gain,
        "coverage_pct": float(sum(gain) / total),
    }
