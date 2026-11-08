"""Step 3: expected-need model (F3, blueprint section 8.1).

    python ml/train_expected.py

Target y_z = home-damage FEMA registrations in ZIP z by day `target_day` (60).
Exposure: housing units. A Poisson model with offset log(HU) is fit as the rate y/HU
with sample_weight = HU (identical likelihood for a log link).

Spatial CV: k-means(6) on ZIP centroids -> GroupKFold(6). Every ZIP's expected_final is
out-of-fold, from a model that never saw its neighbourhood. No Harvey registration or
Harvey NFIP numbers are features.

Writes data/processed/predictions.parquet and model_runs.parquet.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_poisson_deviance
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
EV = yaml.safe_load((ROOT / "config" / "events.yaml").read_text())["events"][0]

# Feature names match the frontend's FEATURE_NAMES.
# Only drivers of NEED go in. Barriers to REGISTERING (limited English, no vehicle, age 65+)
# are deliberately left out: with them the model learns that those areas register less
# (pct_limeng got a negative weight), lowers their expectation and hides the very gap we
# want to find. They still drive the actions. Leaving them out also scored better in
# spatial CV (deviance 492 vs 505).
FEATS = [
    "rain_total_in",
    "rain_sq",
    "hwm_max_ft",
    "hwm_count",
    "hist_nfip_claims_per_1k_hu",
    "pct_mobile",
    "pct_poverty",
]
LOG1P = ["hwm_max_ft", "hwm_count", "hist_nfip_claims_per_1k_hu"]
N_FOLDS = 6
GLM_ALPHA = 1e-3
# keep the GLM unless the challenger beats it by more than this share of deviance
GLM_PREFERENCE = 0.05


def design() -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray]:
    zips = pd.read_parquet(PROC / "zips.parquet")
    static = pd.read_parquet(PROC / "zip_static.parquet")
    hazard = pd.read_parquet(PROC / "zip_hazard.parquet")
    regs = pd.read_parquet(PROC / "registrations_daily.parquet")
    y = (
        regs[regs["day"] == EV["target_day"]]
        .set_index("zip")["n_cum_home_damage"]
        .rename("y")
    )
    d = (
        zips[["zip", "centroid_lat", "centroid_lon"]]
        .merge(static, on="zip")
        .merge(hazard.drop(columns=["event_id", "day"]), on="zip")
        .merge(y, left_on="zip", right_index=True)
    )
    d["rain_sq"] = d["rain_total_in"] ** 2
    X = d[FEATS].copy()
    for c in LOG1P:
        X[c] = np.log1p(X[c])
    X = X.fillna(X.median())
    hu = d["housing_units"].to_numpy(dtype=float)
    return d, X, d["y"].to_numpy(dtype=float), hu


def glm():
    return make_pipeline(StandardScaler(), PoissonRegressor(alpha=GLM_ALPHA, max_iter=3000))


def hgb():
    return HistGradientBoostingRegressor(
        loss="poisson", max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=10,
        random_state=0,
    )


def oof_predict(make, X, y, hu, groups) -> np.ndarray:
    rate = y / hu
    out = np.zeros(len(y))
    for tr, te in GroupKFold(N_FOLDS).split(X, y, groups):
        m = make()
        if hasattr(m, "steps"):
            m.fit(X.iloc[tr], rate[tr], poissonregressor__sample_weight=hu[tr])
        else:
            m.fit(X.iloc[tr], rate[tr], sample_weight=hu[tr])
        out[te] = m.predict(X.iloc[te]) * hu[te]
    return out


def oof_baseline(y, hu, groups) -> np.ndarray:
    """Registrations proportional to housing units, rate learned out-of-fold."""
    out = np.zeros(len(y))
    for tr, te in GroupKFold(N_FOLDS).split(y, y, groups):
        out[te] = hu[te] * y[tr].sum() / hu[tr].sum()
    return out


def evaluate(name, pred, y, hu) -> dict:
    pred = np.maximum(pred, 1e-6)
    return {
        "name": name,
        "deviance": float(mean_poisson_deviance(y, pred)),
        "spearman_per_hu": float(spearmanr(pred / hu, y / hu).statistic),
        "spearman_count": float(spearmanr(pred, y).statistic),
    }


def calibration(pred, y, bins=10) -> list[dict]:
    q = pd.qcut(pred, bins, labels=False, duplicates="drop")
    df = pd.DataFrame({"q": q, "pred": pred, "y": y}).groupby("q").sum()
    return [{"decile": int(i) + 1, "predicted": round(r.pred, 1), "actual": int(r.y)}
            for i, r in df.iterrows()]


def main():
    d, X, y, hu = design()
    groups = KMeans(N_FOLDS, n_init=10, random_state=0).fit_predict(
        d[["centroid_lat", "centroid_lon"]]
    )

    preds = {
        "baseline_hu": oof_baseline(y, hu, groups),
        "glm": oof_predict(glm, X, y, hu, groups),
        "hgb": oof_predict(hgb, X, y, hu, groups),
    }
    scores = {k: evaluate(k, v, y, hu) for k, v in preds.items()}
    for s in scores.values():
        print(f"  {s['name']:<12} deviance {s['deviance']:8.1f}   "
              f"spearman/HU {s['spearman_per_hu']:.3f}   spearman {s['spearman_count']:.3f}")

    g, h = scores["glm"]["deviance"], scores["hgb"]["deviance"]
    winner = "hgb" if h < g * (1 - GLM_PREFERENCE) else "glm"
    print(f"winner: {winner} (GLM kept unless the challenger is >{GLM_PREFERENCE:.0%} better)")
    mu = np.maximum(preds[winner], 1.0)

    # 80% interval: Poisson widened by overdispersion measured on out-of-fold residuals
    phi = float(np.mean((y - mu) ** 2 / mu))
    half = 1.2816 * np.sqrt(phi * mu)
    lo, hi = np.maximum(mu - half, 0), mu + half

    # explanations: full-data GLM, contribution = coef x standardized value (log-rate units)
    full = glm()
    full.fit(X, y / hu, poissonregressor__sample_weight=hu)
    z = full.named_steps["standardscaler"].transform(X)
    coef = full.named_steps["poissonregressor"].coef_
    contribs = [json.dumps({f: round(float(c * v), 3) for f, c, v in zip(FEATS, coef, row)})
                for row in z]

    version = f"{winner}-{dt.date.today():%Y%m%d}"
    out = pd.DataFrame({
        "event_id": EV["event_id"],
        "zip": d["zip"],
        "model_version": version,
        "expected_final": mu.round(1),
        "lo80": lo.round(1),
        "hi80": hi.round(1),
        "contributions_json": contribs,
    })
    out.to_parquet(PROC / "predictions.parquet", index=False)

    params = {
        "target": f"home-damage registrations by day {EV['target_day']}",
        "exposure": "housing_units (offset)",
        "features": FEATS,
        "log1p": LOG1P,
        "cv": f"GroupKFold({N_FOLDS}) on k-means centroid clusters",
        "glm_alpha": GLM_ALPHA,
        "overdispersion": round(phi, 2),
        "scores": scores,
        "calibration": calibration(mu, y),
        "glm_coefficients": {f: round(float(c), 4) for f, c in zip(FEATS, coef)},
    }
    pd.DataFrame([{
        "model_version": version,
        "algorithm": {"glm": "PoissonRegressor", "hgb": "HistGradientBoostingRegressor"}[winner],
        "params_json": json.dumps(params),
        "cv_deviance": scores[winner]["deviance"],
        "cv_spearman": scores[winner]["spearman_per_hu"],
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }]).to_parquet(PROC / "model_runs.parquet", index=False)
    print(f"overdispersion {phi:.1f}; wrote predictions ({len(out)}) and model_runs ({version})")
    print("GLM coefficients (standardized):", params["glm_coefficients"])


if __name__ == "__main__":
    main()
