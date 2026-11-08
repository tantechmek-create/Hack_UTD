# Overlooked Area Detector: one command per stage.
UV  ?= $(shell command -v uv || echo $(HOME)/Library/Python/3.9/bin/uv)
PY  := .venv/bin/python

.PHONY: setup mock data download features train build api web test check

setup:            ## Python 3.12 env + frontend deps
	$(UV) sync --python 3.12 --extra pipeline
	cd frontend && npm install

mock:             ## fake data/mock.duckdb so API + UI work before the pipeline
	$(PY) pipeline/mock_db.py

download:         ## Phase 1: pull public sources into data/raw/
	$(PY) -u pipeline/01_download.py

features:         ## Phase 2: raw -> data/processed/*.parquet (ZIP universe, hazard, registrations)
	$(PY) pipeline/02_features.py

train:            ## Phase 3: expected-need model (Poisson GLM vs boosting, spatial CV)
	$(PY) ml/train_expected.py

build:            ## Phase 4: gap scores days 1..30, backtest, sites -> data/oad.duckdb
	$(PY) pipeline/03_build_db.py

data: download features train build   ## full real build, end to end

api:              ## FastAPI on :8000 (docs at /docs)
	cd backend && ../.venv/bin/uvicorn api.main:app --reload --port 8000

web:              ## Vite dev server on :5173 (proxies /api -> :8000)
	cd frontend && npm run dev

test:             ## backend unit + API contract tests
	$(PY) -m pytest -q

check: test       ## tests + frontend type-check/build
	cd frontend && npm run build
