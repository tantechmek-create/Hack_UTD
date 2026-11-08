"""API contract tests against the mock database (built on the fly if missing)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK = ROOT / "data" / "mock.duckdb"
if not MOCK.exists():
    subprocess.run([sys.executable, str(ROOT / "pipeline" / "mock_db.py"), "--out", str(MOCK)],
                   check=True)
os.environ["DB_PATH"] = str(MOCK)

from api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)
EV = "harvey-2017"


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_events():
    evs = client.get("/events").json()
    assert evs and evs[0]["event_id"] == EV


def test_unknown_event_404():
    assert client.get("/events/nope/kpis?day=5").status_code == 404


def test_day_out_of_range_422():
    assert client.get(f"/events/{EV}/map?day=99").status_code == 422


def test_map_has_all_layers():
    fc = client.get(f"/events/{EV}/map?day=5").json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) > 100
    props = fc["features"][0]["properties"]
    for key in ("gap_score", "hazard_index", "svi", "expected_final", "significant"):
        assert key in props


def test_priorities_sorted_and_actionable():
    items = client.get(f"/events/{EV}/priorities?day=5&limit=20").json()["items"]
    assert len(items) == 20
    pr = [i["priority"] for i in items]
    assert pr == sorted(pr, reverse=True)
    assert all(i["actions"] and i["actions"][0]["code"] != "monitor" for i in items)


def test_zip_detail_matches_queue():
    top = client.get(f"/events/{EV}/priorities?day=5&limit=1").json()["items"][0]
    d = client.get(f"/events/{EV}/zips/{top['zip']}?day=5").json()
    assert d["gap"]["observed"] == top["observed"]
    assert len(d["series"]) == 30
    assert d["reasons"]


def test_plan_k3_returns_three_dry_sites():
    p = client.post(f"/events/{EV}/plan", json={"day": 5, "k": 3, "radius_km": 10}).json()
    assert len(p["sites"]) == 3
    assert 0 < p["coverage_pct"] <= 1


def test_backtest_and_forecast_and_brief():
    bt = client.get(f"/events/{EV}/backtest").json()
    assert {m["method"] for m in bt["metrics"]} >= {"ours", "rainfall_only", "svi_only"}
    fc = client.get(f"/events/{EV}/forecast?day=5").json()
    assert fc["remaining_need"] > 0 and fc["days_to_clear"] > 0
    r = client.get(f"/events/{EV}/brief?day=5")
    assert r.status_code == 200 and "Deployment brief" in r.text


@pytest.mark.parametrize("day", [0, 1, 30])
def test_edge_days(day):
    assert client.get(f"/events/{EV}/kpis?day={day}").status_code == 200
    assert client.get(f"/events/{EV}/map?day={day}").status_code == 200
