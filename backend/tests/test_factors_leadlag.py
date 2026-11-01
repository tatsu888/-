import math
import random

from app import factors, leadlag
from app.models import make_bar
from app.stats import f_sf, ols, spearman


def series(rets, start=100.0, t0=0):
    out, p = [], start
    for i, r in enumerate(rets):
        p *= math.exp(r)
        out.append(make_bar(t0 + 86400 * i, p, p, p, p, 0))
    return out


def test_f_sf_known_value():
    # F(1, 10) critical value at 5% ≈ 4.965
    assert abs(f_sf(4.965, 1, 10) - 0.05) < 1e-3


def test_ols_recovers_coefficients():
    X = [[1.0, x] for x in range(20)]
    y = [3 + 2 * x for x in range(20)]
    beta, rss = ols(X, y)
    assert abs(beta[0] - 3) < 1e-9 and abs(beta[1] - 2) < 1e-9 and rss < 1e-12


def test_leadlag_detects_one_day_lead():
    rng = random.Random(1)
    x = [rng.gauss(0, 0.01) for _ in range(400)]
    y = [0.0] + [0.8 * x[i - 1] + rng.gauss(0, 0.004) for i in range(1, 400)]
    res = leadlag.pair_analysis(series(x), series(y), max_lag=3)
    assert res["ccf"]["best_lead"]["lag"] == 1
    assert res["ccf"]["best_lead"]["corr"] > 0.8
    assert res["granger"][0]["p_value"] < 1e-6
    assert res["granger_reverse_lag1"]["p_value"] > 0.01


def test_scan_leader_ranks_true_follower_first():
    rng = random.Random(2)
    x = [rng.gauss(0, 0.01) for _ in range(300)]
    follower = [0.0] + [0.6 * x[i - 1] + rng.gauss(0, 0.005) for i in range(1, 300)]
    noise = [rng.gauss(0, 0.01) for _ in range(300)]
    rows = leadlag.scan_leader(series(x), {"F": series(follower), "N": series(noise)})
    assert rows[0]["symbol"] == "F" and rows[0]["best_lag"] == 1 and rows[0]["significant"]


def test_etf_factor_report_excess_returns():
    bmk = series([0.0] * 30)
    fac = series([0.0] * 5 + [math.log(1.1)] + [0.0] * 24)
    rep = factors.etf_factor_report(bmk, {"F": fac})
    assert abs(rep["rows"][0]["1M"]) < 1e-9  # 10% move happened > 21 sessions ago
    assert rep["curves"]["F"][-1]["value"] > 109


def test_cross_section_value_factor_sign():
    rows = []
    for i in range(100):
        pe = 5 + i  # cheap stocks first
        rows.append({"price_earnings_ttm": pe, "market_cap_basic": 1e9 * (i + 1), "Perf.W": 0.0,
                     "Perf.1M": 20 - i * 0.2, "Perf.3M": 0.0, "Perf.Y": 10.0, "sector": "S" + str(i % 3)})
    res = factors.cross_sectional_factors(rows)
    value = next(f for f in res["factors"] if f["factor"] == "Value (E/P)")
    assert value["1M"] > 0 and value["ic_1M"] > 0.99
    assert res["universe_size"] == 100 and len(res["sectors"]) == 3


def test_spearman_ties():
    assert abs(spearman([1, 2, 2, 3], [1, 2, 2, 3]) - 1) < 1e-12
