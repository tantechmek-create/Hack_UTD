import numpy as np
import pandas as pd
import pytest
from core import scoring
from core.optimizer import greedy_max_coverage


def _gaps(expected_final, observed):
    return scoring.compute_gaps(
        pd.DataFrame({"zip": [f"z{i}" for i in range(len(observed))],
                      "expected_final": expected_final, "observed": observed})
    )


def test_gap_math_single_zip_pace_one():
    # Two ZIPs whose totals make R_N = 1, so expected_by_day == expected_final.
    d = _gaps([100, 100], [30, 170]).iloc[0]
    assert d.expected_by_day == pytest.approx(100)
    assert d.gap_score == pytest.approx(0.70)
    assert d.unmet_estimate == pytest.approx(70)
    assert bool(d.significant)


def test_small_expectation_never_significant():
    d = _gaps([10, 10], [0, 20]).iloc[0]
    assert d.expected_by_day == pytest.approx(10)
    assert d.p_value < 0.01           # very unlikely...
    assert not bool(d.significant)    # ...but below the 20-household floor


def test_pace_calibration_sums_match():
    rng = np.random.default_rng(0)
    ef = rng.uniform(50, 2000, 200)
    obs = rng.integers(0, 600, 200)
    d = _gaps(ef, obs)
    assert d.expected_by_day.sum() == pytest.approx(obs.sum())


def test_gap_floored_at_zero_for_ahead_of_pace():
    d = _gaps([100, 100], [150, 50]).iloc[0]
    assert d.gap_score == 0 and d.unmet_estimate == 0


@pytest.mark.parametrize(
    "unmet,svi,sig,expected",
    [(768, 0.82, True, 1083), (80, 0.40, True, 96), (48, 0.95, True, 71)],
)
def test_priority_reproduces_blueprint_table(unmet, svi, sig, expected):
    assert round(scoring.priority(unmet, svi, sig)) == expected


def test_priority_halves_when_not_significant():
    assert scoring.priority(100, 0.0, False) == pytest.approx(50)


THR = {"pct_65plus": 0.15, "pct_noveh": 0.10, "pct_limeng": 0.15, "pct_mobile": 0.05}


def test_action_rules():
    row = dict(significant=True, gap_score=0.6, unmet_estimate=500, pct_65plus=0.2,
               pct_noveh=0.01, pct_limeng=0.01, pct_mobile=0.0, hazard_index=0.3)
    acts = scoring.actions_for(row, THR)
    assert acts[0] == "canvass"
    assert "welfare_check_65plus" in acts


def test_monitor_when_on_pace_and_not_significant():
    row = dict(significant=False, gap_score=0.1, unmet_estimate=5, pct_65plus=0.5)
    assert scoring.actions_for(row, THR) == ["monitor"]


def test_significant_small_gap_is_not_just_monitored():
    # Blueprint ZIP B: gap 0.09 but p = 0.004 -> still gets a response action.
    row = dict(significant=True, gap_score=0.09, unmet_estimate=80)
    assert scoring.actions_for(row, THR) != ["monitor"]


def test_optimizer_picks_middle_of_line():
    # five ZIPs on a line ~5.5 km apart, equal weights; sites at each ZIP
    lat = np.full(5, 29.76)
    lon = -95.5 + np.arange(5) * 0.057
    res = greedy_max_coverage(lat, lon, lat, lon, np.ones(5), k=1, radius_km=12)
    assert res["chosen"] == [2]
    assert res["coverage_pct"] == pytest.approx(1.0)


def test_optimizer_respects_k_and_weights():
    lat = np.array([29.7, 29.7, 30.2])
    lon = np.array([-95.4, -95.39, -95.4])
    w = np.array([1, 1, 10])
    res = greedy_max_coverage(lat, lon, lat, lon, w, k=1, radius_km=3)
    assert res["chosen"] == [2]


# --- overdispersion (real data is ~100-400x Poisson) ---------------------------
def test_dispersion_one_is_plain_poisson():
    from scipy.stats import poisson
    p = scoring.lower_tail_p(np.array([40.0]), np.array([60.0]), 1.0)
    assert p[0] == pytest.approx(poisson.cdf(40, 60))


def test_dispersion_widens_the_test():
    narrow = scoring.lower_tail_p(np.array([40.0]), np.array([60.0]), 1.0)[0]
    wide = scoring.lower_tail_p(np.array([40.0]), np.array([60.0]), 20.0)[0]
    assert wide > narrow


def test_dispersion_estimate_is_robust_to_a_few_real_gaps():
    rng = np.random.default_rng(1)
    lam = rng.uniform(100, 2000, 300)
    obs = rng.poisson(lam).astype(float)
    assert scoring.estimate_dispersion(lam, obs) == pytest.approx(1.0, abs=0.3)
    obs[:20] = 0  # 20 silent ZIPs must not inflate the estimate (median, not mean)
    assert scoring.estimate_dispersion(lam, obs) < 1.5


def test_estimated_dispersion_flags_fewer_on_noisy_data():
    rng = np.random.default_rng(2)
    ef = rng.uniform(200, 3000, 200)
    obs = np.round(ef * 0.4 * rng.lognormal(0, 0.4, 200))  # noisy, nobody truly silent
    df = pd.DataFrame({"zip": [str(i) for i in range(200)], "expected_final": ef, "observed": obs})
    pois = scoring.compute_gaps(df, dispersion=1.0).significant.sum()
    quasi = scoring.compute_gaps(df, dispersion=None).significant.sum()
    assert quasi < pois and quasi <= 10


def test_reasons_skip_missing_values():
    row = {"rain_total_in": 34.0, "hwm_count": 0, "damage_pts_per_1k_hu": float("nan"),
           "pct_65plus": float("nan"), "expected_by_day": 100.0, "observed": 20}
    texts = [r["text"] for r in scoring.reasons_for(row, THR)]
    assert not any("nan" in t for t in texts)
    assert texts[0].startswith("Storm rainfall")


# --- backtest label --------------------------------------------------------------
def test_hindsight_label_picks_largest_true_shortfall():
    from pipeline.utils.build import overlooked_labels

    final = pd.DataFrame({"zip": list("abcdefghij"), "final": [1000] * 10})
    obs7 = [500] * 8 + [100, 450]  # region pace ~0.455; 'i' is far behind, 'j' slightly
    regs = pd.DataFrame({"zip": list("abcdefghij"), "day": 7, "n_cum_home_damage": obs7})
    lab = overlooked_labels(regs, final, top_share=0.1).set_index("zip")
    assert lab.overlooked.sum() == 1 and bool(lab.loc["i", "overlooked"])
