"""Gap, priority, action and reason logic (blueprint sections 8.2 and 9).

Shared by the pipeline (which precomputes gap_scores for days 1..30) and the API,
so every number shown in the app is computed one way only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson

# --- Tunables (kept in one place so the pitch can quote them) -----------------
P_THRESHOLD = 0.01          # Poisson lower-tail p-value for "significantly quiet"
MIN_EXPECTED = 20           # never flag a ZIP whose expectation so far is below this
SVI_WEIGHT = 0.5            # priority multiplier: 1 + SVI_WEIGHT * SVI
NONSIG_WEIGHT = 0.5         # priority multiplier for non-significant gaps
CANVASS_UNMET = 300         # unmet households that justify a mobile claims unit
MONITOR_GAP = 0.2           # gap below this (and not significant) = on pace
HAZARD_ACCESS = 0.8         # hazard_index above this = area may still be flooded

VULN_COLS = ["pct_65plus", "pct_noveh", "pct_limeng", "pct_mobile", "pct_poverty"]


# --- Gap detection (F4) -------------------------------------------------------
def pace_ratio(observed_total: float, expected_final_total: float) -> float:
    """R_N = sum observed by day N / sum expected final. Adjusts for region-wide pace."""
    if expected_final_total <= 0:
        return 0.0
    return float(observed_total) / float(expected_final_total)


def estimate_dispersion(expected: np.ndarray, observed: np.ndarray) -> float:
    """Quasi-Poisson dispersion for one event-day, robust to the gaps we are looking for.

    Real registrations vary far more than Poisson (model error, neighbourhood effects):
    on Harvey day 5 the squared Pearson residuals are ~270x Poisson. A plain Poisson test
    then flags half the map. We use the median squared Pearson residual divided by 0.455
    (the median of chi-square with 1 df), so a minority of truly quiet ZIPs cannot inflate
    the estimate and hide themselves. Floored at 1 (never narrower than Poisson).
    """
    lam = np.asarray(expected, dtype=float)
    obs = np.asarray(observed, dtype=float)
    m = lam >= MIN_EXPECTED
    if m.sum() < 10:
        return 1.0
    r2 = (obs[m] - lam[m]) ** 2 / lam[m]
    return float(max(1.0, np.median(r2) / 0.4549))


def lower_tail_p(obs: np.ndarray, lam: np.ndarray, dispersion: float = 1.0) -> np.ndarray:
    """P(X <= obs) for X with mean lam and variance dispersion x lam.

    dispersion == 1 is the blueprint's Poisson test; above 1 it is a negative binomial
    with the same mean and the wider variance.
    """
    lam = np.maximum(np.asarray(lam, dtype=float), 1e-9)
    if dispersion <= 1.0 + 1e-9:
        return poisson.cdf(obs, lam)
    return nbinom.cdf(obs, lam / (dispersion - 1.0), 1.0 / dispersion)


def compute_gaps(df: pd.DataFrame, dispersion: float | None = 1.0) -> pd.DataFrame:
    """Score one event-day.

    Input columns: zip, expected_final, observed (cumulative home-damage registrations
    by day N; the same quantity the model predicts, so the ratio compares like with like).
    dispersion: 1.0 = Poisson test (blueprint); None = estimate it from this day's data.
    Returns a copy with expected_by_day, gap_score, unmet_estimate, p_value, significant.
    """
    out = df.copy()
    r = pace_ratio(out["observed"].sum(), out["expected_final"].sum())
    lam = out["expected_final"].to_numpy(dtype=float) * r
    obs = out["observed"].to_numpy(dtype=float)

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(lam > 0, obs / lam, 1.0)
    out["pace_ratio"] = r
    out["expected_by_day"] = lam
    out["gap_score"] = np.clip(1.0 - ratio, 0.0, 1.0)
    out["unmet_estimate"] = np.maximum(lam - obs, 0.0)
    if dispersion is None:
        dispersion = estimate_dispersion(lam, obs)
    out["dispersion"] = dispersion
    out["p_value"] = np.where(lam > 0, lower_tail_p(obs, lam, dispersion), 1.0)
    out["significant"] = (out["p_value"] < P_THRESHOLD) & (lam >= MIN_EXPECTED)
    return out


# --- Priority (F6) ------------------------------------------------------------
def priority(unmet: float, svi: float, significant: bool) -> float:
    """priority = unmet x (1 + 0.5 x SVI) x (1.0 if significant else 0.5)."""
    svi = 0.0 if svi is None or (isinstance(svi, float) and math.isnan(svi)) else svi
    return float(unmet) * (1.0 + SVI_WEIGHT * svi) * (1.0 if significant else NONSIG_WEIGHT)


def add_priority(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["priority"] = [
        priority(u, s, g)
        for u, s, g in zip(out["unmet_estimate"], out["svi_overall"], out["significant"])
    ]
    out["rank"] = out["priority"].rank(ascending=False, method="first").astype(int)
    return out


# --- Actions (section 9 rule table) -------------------------------------------
@dataclass(frozen=True)
class Action:
    code: str
    label: str
    why: str


ACTIONS = {
    "canvass": Action("canvass", "Mobile claims unit / canvass team", "Large missing volume"),
    "welfare_check_65plus": Action(
        "welfare_check_65plus", "Welfare checks · 65+", "Less likely to use apps or travel"
    ),
    "onsite_assistance": Action(
        "onsite_assistance", "On-site help · transport", "Cannot reach a claims center"
    ),
    "multilingual_outreach": Action(
        "multilingual_outreach", "Multilingual outreach", "Language barrier to registering"
    ),
    "structural_inspections": Action(
        "structural_inspections", "Mobile-home inspections", "Mobile homes fail first"
    ),
    "coordinate_access": Action(
        "coordinate_access", "Coordinate access with responders", "Area may still be flooded"
    ),
    "targeted_outreach": Action(
        "targeted_outreach", "Targeted outreach", "Quiet relative to expected need"
    ),
    "monitor": Action("monitor", "Monitor", "On pace"),
}


def actions_for(row: dict, thresholds: dict[str, float]) -> list[str]:
    """Return action codes; the first is the lead action.

    `thresholds` holds the 75th-percentile cut for each vulnerability column
    (relative to Texas tracts in the real pipeline).

    A ZIP that is on pace (gap < 0.2) and not significant only gets "monitor".
    A significant ZIP is never just monitored, even with a small gap percentage:
    that resolves the blueprint's ZIP B example (gap 0.09 but p = 0.004).
    """
    sig = bool(row.get("significant"))
    if not sig and row.get("gap_score", 0.0) < MONITOR_GAP:
        return ["monitor"]

    acts: list[str] = []
    if sig and row.get("unmet_estimate", 0.0) >= CANVASS_UNMET:
        acts.append("canvass")
    for col, code in [
        ("pct_65plus", "welfare_check_65plus"),
        ("pct_noveh", "onsite_assistance"),
        ("pct_limeng", "multilingual_outreach"),
        ("pct_mobile", "structural_inspections"),
    ]:
        t = thresholds.get(col)
        v = _num(row, col)
        if t is not None and v is not None and v >= t:
            acts.append(code)
    if (_num(row, "hazard_index") or 0.0) >= HAZARD_ACCESS and bool(row.get("damage_rising")):
        acts.append("coordinate_access")
    if not acts:
        acts.append("targeted_outreach")
    return acts


# --- Reasons ("why flagged", F5) ----------------------------------------------
NICE = {
    "pct_65plus": "residents are 65+",
    "pct_noveh": "of households have no vehicle",
    "pct_limeng": "speak limited English",
    "pct_mobile": "of homes are mobile homes",
    "pct_poverty": "live below poverty",
}


def _num(row: dict, key: str) -> float | None:
    """Value as a float, or None when missing/NaN (real data has gaps, e.g. no damage points)."""
    v = row.get(key)
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def reasons_for(row: dict, thresholds: dict[str, float]) -> list[dict]:
    """Plain-language reasons with a data label each (real / predicted)."""
    out: list[dict] = []
    rain = _num(row, "rain_total_in")
    if rain is not None:
        out.append({"text": f"Storm rainfall ~{rain:.0f} in", "label": "real"})
    hwm = _num(row, "hwm_count")
    if hwm:
        out.append(
            {
                "text": f"{int(hwm)} high-water marks, max {_num(row, 'hwm_max_ft') or 0:.1f} ft",
                "label": "real",
            }
        )
    dmg = _num(row, "damage_pts_per_1k_hu")
    if dmg:
        out.append(
            {
                "text": f"{dmg / 10:.1f} modeled damaged buildings per 100 homes",
                "label": "real",
            }
        )
    for col in VULN_COLS:
        t = thresholds.get(col)
        v = _num(row, col)
        if t is not None and v is not None and v >= t:
            out.append({"text": f"{v:.0%} {NICE[col]} (top quarter)", "label": "real"})
    if row.get("expected_by_day") is not None:
        out.append(
            {
                "text": (
                    f"Expected ~{row['expected_by_day']:,.0f} registrations by now, "
                    f"observed {int(row['observed']):,}"
                ),
                "label": "predicted",
            }
        )
    return out
