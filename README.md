# Overlooked Area Detector

Finds the ZIP codes a disaster hit hard where few households are asking for help.
The demo replays Hurricane Harvey (DR-4332, Harris County and 7 neighboring counties) from
public data. The build plan is `frame_work.pdf`.

## Run it

```bash
make setup     # Python 3.12 venv (uv) + frontend deps
make data      # download -> features -> train -> build  => data/oad.duckdb (~2 min after downloads)
make api       # FastAPI on :8000 (docs at /docs)
make web       # Vite on :5173, proxies /api -> :8000
make test      # backend tests
```

`make mock` writes `data/mock.duckdb` with synthetic numbers. The API uses
`data/oad.duckdb` when it exists and otherwise falls back to the mock (the UI then shows a
MOCK banner). Set `DB_PATH` to pick a file explicitly.

## Pipeline

| Step | Script | Output |
|---|---|---|
| Download | `pipeline/01_download.py` | `data/raw/` (immutable; re-runs skip existing files) |
| Features | `pipeline/02_features.py` | `data/processed/*.parquet`: 216 ZCTAs, 2.4M housing units |
| Train | `ml/train_expected.py` | out-of-fold `predictions`, `model_runs` |
| Build | `pipeline/03_build_db.py` | `data/oad.duckdb`: gap scores for days 1-30, backtest, sites |

## Data sources

| Source | Used for | Status |
|---|---|---|
| OpenFEMA IHP valid registrations (DR-4332) | observed registrations by `appliedDate`, model target | ✓ 890,926 rows |
| OpenFEMA NFIP claims v3 (TX) | pre-2017 claim history (feature); Harvey claims (kept in DB, not used by the model) | ✓ |
| NOAA Stage IV daily precipitation | storm rainfall Aug 25 - Sep 1 | ✓ |
| USGS STN high-water marks (event 180) | count and max height per ZIP; flooded-site check | ✓ new host `api.waterdata.usgs.gov/stnservices` |
| CDC SVI 2016 (TX tracts) | housing units, vulnerability, Texas-relative thresholds | ✓ |
| Census 2010 ZCTA polygons + ZCTA-tract relationship | geography, tract->ZIP weights | ✓ |
| NCES public school locations 2017-18 | candidate team sites (1,485) | ✓ (Overpass/OSM was unavailable) |
| FEMA modeled damage points | blueprint hazard feature | ✗ public Harvey layers now need an ArcGIS token |
| FEMA National Risk Index | baseline flood risk | ✗ download link moved; column left empty |

## Where this departs from the blueprint, and why

1. **Barrier variables are not model features.** With limited English, no vehicle and age
   65+ as inputs, the model learned that those ZIPs register less (`pct_limeng` got a
   negative weight). It then lowered their expected need and hid the very gaps we want to
   find. Without them the model scores better in spatial CV (deviance 492 vs 505). These
   variables still drive the actions.
2. **Significance accounts for overdispersion.** Real counts vary about 270 times more
   than Poisson by day 5, so the plain Poisson test flagged 120 of 216 ZIPs. Each day we
   estimate a robust quasi-Poisson dispersion (median squared Pearson residual / 0.455) and
   test against a negative binomial with that variance. Now 2-6 ZIPs are significant at
   p < 0.01, and the priority list ranks every ZIP either way.
3. **Backtest ground truth is hindsight shortfall, not NFIP damage.** An NFIP-based
   "overlooked" label picked Bellaire, Meyerland and Memorial. Insured households file NFIP
   claims instead of FEMA registrations, so that label measured insurance coverage
   (Spearman 0.49 with SVI). The label is now: the 10% of ZIPs with the largest true
   day-7 shortfall, using each ZIP's actual day-60 registrations as its final need. Methods
   rank using only what was known on that day.

## Results (Harvey, spatial 6-fold CV)

- **Expected-need model:** Poisson GLM with housing units as exposure. Deviance is 492,
  against 786 for "registrations proportional to housing units". Spearman per housing unit
  is 0.58 (blueprint target 0.6). Gradient boosting scored worse (613), so the GLM is kept.
  The region-wide expectation is 415,662, against 400,140 actually registered by day 60.
- **Backtest, precision@10 on day 5:** our ranking 50%, gap vs. housing units 40%, SVI
  only 20%, rainfall only 0%, fewest registrations 0%. At @25 we tie the housing-units
  baseline (36%). The model's edge is real but modest. Its main limit is that rainfall is
  nearly uniform across Houston (33-41 in), so it cannot see which neighborhoods actually
  flooded. Better damage data (FEMA damage points, or an insurer's own claims) is the
  biggest available improvement.
