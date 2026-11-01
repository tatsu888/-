import copy
import json
from pathlib import Path

import pytest

from app.harness import regression as R
from app.harness import timeseries as T
from app.harness.runner import run

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "models/examples/sample_manufacturer.json").read_text())


def test_ols_report_exact_fit_stats():
    x = [float(i) for i in range(12)]
    y = [1 + 2 * v + (0.1 if i % 2 else -0.1) for i, v in enumerate(x)]
    rep = R.ols_report(y, [[v] for v in x], ["x"])
    assert abs(rep["coefficients"][1]["coef"] - 2) < 0.02
    assert rep["r2"] > 0.99 and rep["coefficients"][1]["p"] < 1e-10
    pi = R.predict(rep, [[20.0]])[0]
    assert pi["lower"] < pi["forecast"] < pi["upper"]


def test_t_crit():
    assert abs(R.t_crit(10) - 2.228) < 1e-3


def test_elasticity_loglog():
    x = [1, 2, 4, 8, 16, 32]
    y = [3 * v ** 0.5 for v in x]
    assert abs(R.elasticity(y, x)["elasticity"] - 0.5) < 1e-9


def test_driver_forecast_level():
    res = R.driver_forecast([10, 12, 14, 16, 18, 20.5], {"d": [1, 2, 3, 4, 5, 6]}, {"d": [7, 8]})
    assert len(res["forecast"]) == 2 and res["forecast"][0]["forecast"] > 20


def test_timeseries_tools():
    assert abs(T.cagr(100, 121, 2) - 0.1) < 1e-12
    sf = T.seasonal_factors([10, 20, 30, 40] * 4, 4)
    assert abs(sum(sf) / 4 - 1) < 1e-12 and sf[3] > sf[0]
    assert T.holt([1, 2, 3, 4, 5], 2, 0.9, 0.9)[1] > 6
    bt = T.backtest_methods([float(i) for i in range(1, 21)])
    assert bt["best"] in ("trend_linear", "holt", "ar1")


def test_sample_model_runs_and_is_deterministic():
    a, b = run(SAMPLE), run(copy.deepcopy(SAMPLE))
    assert a["meta"]["output_hash"] == b["meta"]["output_hash"]
    d = a["projection"]["derived"]
    lines = a["projection"]["lines"]
    # identities
    for t in range(len(a["projection"]["years"])):
        assert abs(d["gross_profit"][t] - (lines["revenue"][t] - lines["cogs"][t])) < 1e-6
        assert abs(d["net_income"][t] - (d["pretax_profit"][t] - d["tax"][t] - d["minority_interest"][t])) < 1e-6
    assert a["valuation"]["dcf"]["price_per_share"] > 0
    assert set(a["scenarios"]) >= {"bull", "base", "bear", "_probability_weighted"}
    assert a["monte_carlo"]["valid"] > 0
    assert a["check_summary"]["FAIL"] == 0


def test_input_change_changes_hash():
    s = copy.deepcopy(SAMPLE)
    s["assumptions"]["tax_rate"] = 0.31
    assert run(s, uncertainty=False)["meta"]["input_hash"] != run(SAMPLE, uncertainty=False)["meta"]["input_hash"]


def test_guardrails_flag_bad_inputs():
    s = copy.deepcopy(SAMPLE)
    s["lines"]["units"]["params"]["rates"] = [0.6, 0.0, 0.0, 0.0, 0.0]  # +60% growth
    del s["lines"]["capex"]["params"]["source"]
    s["assumptions"]["tax_rate"] = 0.7
    res = run(s, uncertainty=False)
    status = {c["id"]: c["status"] for c in res["checks"]}
    assert status["revenue_growth_outlier"] == "WARN"
    assert status["assumption_sources"] == "WARN"
    assert status["tax_rate_bounds"] == "FAIL"


def test_terminal_growth_above_wacc_is_reported():
    s = copy.deepcopy(SAMPLE)
    s["valuation"]["terminal_growth"] = 0.2
    s.pop("exit_ev_ebitda", None)
    s["valuation"].pop("exit_ev_ebitda")
    res = run(s, uncertainty=False)
    assert "dcf" in res["valuation"]["errors"]


def test_revenue_builders():
    base = {"forecast_years": ["Y1", "Y2"], "history": {"years": ["Y0"], "revenue": [100]}}
    cases = {
        "market_share": {"market_size": {"values": [1000, 1100]}, "share": {"values": 0.1}},
        "customers_arpu": {"customers": {"values": [10, 11]}, "arpu": {"values": 10}},
        "capacity": {"capacity": {"values": 200}, "utilization": {"values": [0.5, 0.55]}, "price": {"values": 1}},
        "backlog": {"orders": {"values": [100, 100]}, "burn_rate": 0.5, "in_period_rate": 0.5, "backlog_start": 100},
        "stores": {"same_store_growth": 0.0, "new_stores": [0, 0], "sales_per_new_store": 1},
    }
    for m, params in cases.items():
        spec = {**base, "lines": {"revenue": {"method": m, "params": params}}}
        rev = run(spec, uncertainty=False)["projection"]["lines"]["revenue"]
        assert rev[0] == pytest.approx(100), m


def test_validation_errors():
    with pytest.raises(ValueError):
        run({"forecast_years": [], "lines": {}})
    with pytest.raises(ValueError):
        run({"forecast_years": ["Y1"], "lines": {"revenue": {"method": "nope"}}})
