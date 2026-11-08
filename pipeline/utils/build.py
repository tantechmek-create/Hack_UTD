"""Shared build steps used by both the real pipeline and the mock generator.

- score_event:  gap_scores for days 1..max_day (F4, F6 actions/reasons)
- run_backtest: precision@k of our ranking vs single-signal baselines (F8)
- write_db:     write all tables into one DuckDB file, sorted for fast day reads
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from core import scoring

STATIC_COLS = ["svi_overall", *scoring.VULN_COLS]
HAZARD_COLS = [
    "rain_total_in",
    "hwm_count",
    "hwm_max_ft",
    "damage_pts_per_1k_hu",
    "hazard_index",
    "damage_rising",
]


def score_event(
    event_id: str,
    max_day: int,
    preds: pd.DataFrame,      # zip, expected_final
    regs: pd.DataFrame,       # zip, day, n_cum_home_damage
    static: pd.DataFrame,     # zip, svi_overall, pct_*
    hazard: pd.DataFrame,     # zip, rain_total_in, ..., hazard_index, damage_rising
    thresholds: dict[str, float],
) -> pd.DataFrame:
    base = (
        preds[["zip", "expected_final"]]
        .merge(static[["zip", *STATIC_COLS]], on="zip", how="left")
        .merge(hazard[["zip", *HAZARD_COLS]], on="zip", how="left")
    )
    regs = regs[["zip", "day", "n_cum_home_damage"]]
    out = []
    for day in range(1, max_day + 1):
        obs = (
            regs[regs["day"] <= day]
            .sort_values("day")
            .groupby("zip")["n_cum_home_damage"]
            .last()
            .rename("observed")
        )
        d = base.merge(obs, left_on="zip", right_index=True, how="left")
        d["observed"] = d["observed"].fillna(0).astype(int)
        # dispersion estimated per day from the data (see scoring.estimate_dispersion)
        d = scoring.add_priority(scoring.compute_gaps(d, dispersion=None))
        recs = d.to_dict("records")
        d["actions_json"] = [json.dumps(scoring.actions_for(r, thresholds)) for r in recs]
        d["reasons_json"] = [json.dumps(scoring.reasons_for(r, thresholds)) for r in recs]
        d["day"] = day
        out.append(d)
    gs = pd.concat(out, ignore_index=True)
    gs.insert(0, "event_id", event_id)
    keep = [
        "event_id", "zip", "day", "pace_ratio", "expected_by_day", "observed", "gap_score",
        "unmet_estimate", "p_value", "significant", "priority", "rank", "actions_json",
        "reasons_json",
    ]
    return gs[keep]


def overlooked_labels(
    regs: pd.DataFrame,       # zip, day, n_cum_home_damage (must reach label_day)
    final: pd.DataFrame,      # zip, final: home-damage registrations by day 60 (hindsight)
    label_day: int = 7,
    top_share: float = 0.10,
) -> pd.DataFrame:
    """Hindsight ground truth: where were the most households missing on `label_day`?

    With the whole event in hand we know each ZIP's real final need (registrations by
    day 60), so we can measure the true shortfall on day 7 without any model:
        R7          = sum(registered by day 7) / sum(final)
        true_unmet  = max(final x R7 - registered by day 7, 0)
    Overlooked = the top 10% of ZIPs by true_unmet. A method passes if, on days 3-7, it
    points at those ZIPs while it only knows what was known then (our model's expectation
    is out-of-fold and never sees final counts).

    Why not NFIP damage: NFIP claims track flood INSURANCE. Insured, wealthier ZIPs file
    NFIP claims instead of FEMA registrations, so "few registrations per NFIP claim"
    measured insurance coverage (Spearman 0.49 with SVI), not being overlooked.
    """
    obs = regs[regs["day"] == label_day].set_index("zip")["n_cum_home_damage"]
    d = final[["zip", "final"]].copy()
    d["obs"] = d["zip"].map(obs).fillna(0)
    r = d["obs"].sum() / max(d["final"].sum(), 1)
    d["share_by_label_day"] = np.where(d["final"] > 0, d["obs"] / d["final"].clip(lower=1), np.nan)
    d["true_unmet"] = np.maximum(d["final"] * r - d["obs"], 0)
    n_true = max(1, int(round(top_share * len(d))))
    d["overlooked"] = d["true_unmet"].rank(ascending=False, method="first") <= n_true
    return d[["zip", "final", "share_by_label_day", "true_unmet", "overlooked"]]


def run_backtest(
    event_id: str,
    gap_scores: pd.DataFrame,
    labels: pd.DataFrame,
    static: pd.DataFrame,
    hazard: pd.DataFrame,
    days=(3, 5, 7),
    ks=(10, 25),
) -> pd.DataFrame:
    truth = set(labels.loc[labels["overlooked"], "zip"])
    eligible = set(labels["zip"])
    rows = []
    for day in days:
        g = gap_scores[(gap_scores["day"] == day) & gap_scores["zip"].isin(eligible)]
        g = g.merge(static[["zip", "svi_overall", "housing_units"]], on="zip").merge(
            hazard[["zip", "rain_total_in"]], on="zip"
        )
        # same gap logic, but "expected" simply proportional to housing units: the test of
        # whether the model adds anything over counting homes
        rate = g["observed"].sum() / g["housing_units"].sum()
        g["unmet_hu"] = np.maximum(g["housing_units"] * rate - g["observed"], 0)
        rankings = {
            "ours": g.sort_values("priority", ascending=False)["zip"].tolist(),
            "housing_pace": g.sort_values("unmet_hu", ascending=False)["zip"].tolist(),
            "rainfall_only": g.sort_values("rain_total_in", ascending=False)["zip"].tolist(),
            "svi_only": g.sort_values("svi_overall", ascending=False)["zip"].tolist(),
            # "who is quiet": fewest registrations so far
            "raw_registrations": g.sort_values("observed", ascending=True)["zip"].tolist(),
        }
        for method, order in rankings.items():
            for k in ks:
                top = order[:k]
                hits = sum(z in truth for z in top)
                rows.append(
                    {
                        "event_id": event_id,
                        "day": day,
                        "method": method,
                        "k": k,
                        "precision": hits / k if k else 0.0,
                        "recall": hits / len(truth) if truth else 0.0,
                        "hits": hits,
                        "n_true": len(truth),
                    }
                )
    return pd.DataFrame(rows)


def write_db(tables: dict[str, pd.DataFrame], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    for name, df in tables.items():
        sort = [c for c in ("event_id", "day", "zip") if c in df.columns]
        if sort:
            df = df.sort_values(sort)
        con.register("df_view", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM df_view")
        con.unregister("df_view")
    con.close()
    tmp.replace(path)  # atomic swap so a running API never sees a half-written file
    print(f"wrote {path} ({', '.join(f'{k}={len(v):,}' for k, v in tables.items())})")


def vuln_thresholds(df: pd.DataFrame, q: float = 0.75) -> dict[str, float]:
    return {c: float(np.nanquantile(df[c], q)) for c in scoring.VULN_COLS if c in df}
