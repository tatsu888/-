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


# ---------------------------------------------------------------- schema / validation / refs / diff / brief
def test_param_validation_errors_and_warnings():
    s = copy.deepcopy(SAMPLE)
    s["lines"]["capex"]["params"].pop("pct")
    with pytest.raises(ValueError, match="missing param 'pct'"):
        run(s, uncertainty=False)
    s = copy.deepcopy(SAMPLE)
    s["lines"]["capex"]["params"]["pcnt"] = 0.1
    res = run(s, uncertainty=False)
    assert any(c["id"] == "spec_warnings" and "pcnt" in c["message"] for c in res["checks"])


def test_schema_covers_every_method():
    from app.harness.lines import METHOD_PARAMS
    from app.harness.schema import spec_schema

    sch = spec_schema()
    titles = {o["title"] for o in sch["properties"]["lines"]["additionalProperties"]["oneOf"]}
    assert titles == set(METHOD_PARAMS)


def test_excel_refs_resolution():
    from app.harness.excel_refs import parse_range, resolve

    assert parse_range("'My Sheet'!b4:f4") == ("My Sheet", "B4", "F4")
    grid = {("Model", "B4:F4"): [[1000, 1050, 1120, 1180, 1250]], ("Model", "B9:B9"): [[0.3]]}
    reader = lambda fid, sh, rng: grid[(sh, rng)]  # noqa: E731
    spec = {"history": {"years": [1, 2, 3, 4, 5], "revenue": {"excel": "0/m.xlsx", "range": "Model!B4:F4"}},
            "assumptions": {"tax_rate": {"excel": "0/m.xlsx", "range": "Model!B9"}}}
    out, refs = resolve(spec, reader)
    assert out["history"]["revenue"] == [1000, 1050, 1120, 1180, 1250] and out["assumptions"]["tax_rate"] == 0.3
    assert {r["path"] for r in refs} == {"history.revenue", "assumptions.tax_rate"}
    with pytest.raises(ValueError):
        resolve({"x": {"excel": "f", "range": "nonsense"}}, reader)
    # unresolved refs are rejected by the runner (must go through the API resolver)
    s = copy.deepcopy(SAMPLE)
    s["assumptions"]["tax_rate"] = {"excel": "0/m.xlsx", "range": "Model!B9"}
    with pytest.raises(ValueError, match="unresolved excel reference"):
        run(s, uncertainty=False)


def test_apply_changes_guards_history_and_sources():
    from app.harness.diff import apply_changes, diff

    changes = [
        {"path": "lines.units.params.rates", "value": [0.05] * 5, "source": "industry body 2026/10"},
        {"path": "history.revenue", "value": [1, 2, 3, 4, 5, 6]},           # forbidden
        {"path": "lines.capex.params.pct", "value": 0.07},                  # no source -> rejected
        {"path": "valuation.terminal_growth", "value": 0.015},
    ]
    new, problems = apply_changes(SAMPLE, changes)
    assert new["lines"]["units"]["params"]["rates"] == [0.05] * 5
    assert new["lines"]["units"]["params"]["source"] == "industry body 2026/10"
    assert new["valuation"]["terminal_growth"] == 0.015
    assert new["history"] == SAMPLE["history"] and new["lines"]["capex"]["params"]["pct"] == 0.054
    assert len(problems) == 2
    paths = {d["path"] for d in diff(SAMPLE, new)}
    assert paths == {"lines.units.params.rates", "lines.units.params.source", "valuation.terminal_growth"}


def test_brief_contains_rules_spec_and_checks():
    from app.harness.brief import make_brief

    md = make_brief(SAMPLE, run(SAMPLE, uncertainty=False), "check margins")
    assert "数値を計算しない" in md and "check margins" in md and '"forecast_years"' in md
    assert "input_hash" in md and "[WARN]" in md or "[PASS]" in md


def test_templates_run_and_flag_todo_sources():
    from pathlib import Path
    tdir = Path(__file__).resolve().parents[2] / "models/templates"
    names = sorted(p.stem for p in tdir.glob("*.json"))
    assert {"manufacturer", "retail", "saas", "backlog_industrial", "generic_growth", "market_share"} <= set(names)
    for n in names:
        spec = json.loads((tdir / f"{n}.json").read_text())
        res = run(spec, uncertainty=False)
        st = {c["id"]: c["status"] for c in res["checks"]}
        assert st["assumption_sources"] == "WARN", n  # TODO placeholders are not real sources
        assert res["check_summary"]["FAIL"] == 0, (n, res["checks"])


def test_harness_api_versions_diff_apply(tmp_path):
    from fastapi.testclient import TestClient

    import openpyxl
    from app.main import app
    from app.state import S

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Model"
    ws.append(["revenue", 1000, 940, 1050, 1150, 1230, 1300])
    wb.save(S.excel.roots[0] / "harness_src.xlsx")
    with TestClient(app) as c:
        spec = copy.deepcopy(SAMPLE)
        spec["history"]["revenue"] = {"excel": "0/harness_src.xlsx", "range": "Model!B1:G1"}
        r = c.post("/api/harness/run", json=spec, params={"uncertainty": False})
        assert r.status_code == 200, r.text
        assert r.json()["meta"]["excel_refs"][0]["values"] == [1000, 940, 1050, 1150, 1230, 1300]
        assert c.put("/api/harness/models/t1", json=SAMPLE).json()["version"] == 1
        s2 = copy.deepcopy(SAMPLE)
        s2["valuation"]["terminal_growth"] = 0.02
        assert c.put("/api/harness/models/t1", json=s2).json()["version"] == 2
        assert c.put("/api/harness/models/t1", json=s2).json()["version"] == 2  # unchanged -> no new version
        d = c.get("/api/harness/models/t1/diff", params={"a": 1, "b": 2}).json()
        assert d["changes"] == [{"path": "valuation.terminal_growth", "before": 0.01, "after": 0.02, "kind": "changed"}]
        assert d["summary_b"]["dcf_price"] > d["summary_a"]["dcf_price"]
        ap = c.post("/api/harness/apply_changes", json={"spec": SAMPLE, "changes": {"changes": [
            {"path": "assumptions.tax_rate", "value": 0.25}]}}).json()
        assert ap["after"]["eps"][0] > ap["before"]["eps"][0] and not ap["rejected"]
        assert "数値を計算しない" in c.post("/api/harness/brief", json={"spec": SAMPLE}).text
        assert c.get("/api/harness/schema").json()["title"].startswith("Analyst Terminal")
        assert len(c.get("/api/harness/templates").json()) >= 6
