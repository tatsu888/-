"""FEXP engine: recovers known exposures (incl. the next-day effect of late factors), orthogonal macro, Euler risk shares,
attribution identity, maps, rolling, scenario, no look-ahead, US securities without lags."""
import datetime as dt
import math
import random

import pytest

from app import fexpmodel as F


def _dates(n: int) -> list[str]:
    d, out = dt.date(2022, 1, 3), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def world(n: int = 760, seed: int = 1):
    """y = 1.1·M + 0.5·S + 0.4·FX_t + 0.3·FX_t−1 − 0.002·ΔJP10Y(bp) + ε; FX correlates with the market (b = 0.3)."""
    rnd = random.Random(seed)
    ds = _dates(n)
    g = lambda s: rnd.gauss(0, s)  # noqa: E731
    M = {d: g(0.010) for d in ds}
    S = {d: g(0.006) for d in ds}
    X = {d: 0.3 * M[d] + g(0.006) for d in ds}
    other_sec = {d: g(0.006) for d in ds}
    J = {d: g(2.0) for d in ds}
    y = {}
    for i, d in enumerate(ds[1:], 1):
        y[d] = 1.1 * M[d] + 0.5 * S[d] + 0.4 * X[d] + 0.3 * X[ds[i - 1]] - 0.002 * J[d] + g(0.008)
    series = {"mkt": M, "sec.1625": S, "sec.1617": other_sec, "fx.usdjpy": X, "rate.jp10": J}
    return ds, y, series


def test_recovers_exposures_with_the_next_day_effect():
    ds, y, series = world()
    cat = F.catalog("JP")
    ids = ["mkt", "sec.1625", "fx.usdjpy", "rate.jp10"]
    r = F.analyze(y, cat, series, ids, "JP", est=504, window=21, roll=126, roll_ids=["mkt", "fx.usdjpy"])
    ex = {e["id"]: e for e in r["exposures"]}
    assert r["lagged"] and r["n"] == 504
    assert abs(ex["mkt"]["beta"] - (1.1 + 0.4 * 0.3)) < 0.1                  # TOTAL market beta (FX is orthogonal to it)
    assert abs(ex["sec.1625"]["beta"] - 0.5) < 0.1
    fx = ex["fx.usdjpy"]
    assert fx["lagged"] and abs(fx["beta"] - 0.7) < 0.1 and abs(fx["next_day_pct"] - 0.3) < 0.1 and fx["t"] > 5
    assert abs(ex["rate.jp10"]["per_unit_pct"] - (-0.002 * 1000)) < 0.6 and ex["rate.jp10"]["unit"] == "10bp"
    # Euler risk shares add up to R²; specific = 1 − R²
    total = sum(r["risk"]["groups"].values())
    assert abs(total - r["r2"]) < 1e-9 and abs(r["risk"]["specific"] - (1 - r["r2"])) < 1e-12
    # attribution: total = Σ contributions + 個社要因, betas from before the window
    a = r["attribution"]
    assert a["est_to"] < a["from"] and abs(a["total_pct"] - (sum(f["contribution_pct"] for f in a["factors"]) + a["specific_pct"])) < 1e-9
    assert abs(a["series"][-1]["total"] - a["total_pct"]) < 1e-9
    # rolling: a beta per step, near the truth
    ro = r["rolling"]
    assert len(ro["dates"]) > 50 and abs(sum(ro["beta"]["fx.usdjpy"]) / len(ro["beta"]["fx.usdjpy"]) - 0.7) < 0.15


def test_maps_scenario_and_no_look_ahead():
    ds, y, series = world()
    cat = F.catalog("JP")
    ids = ["mkt", "sec.1625", "fx.usdjpy"]
    r = F.analyze(y, cat, series, ids, "JP")
    sec = r["maps"]["セクター"]
    assert sec[0]["id"] == "sec.1625" and sec[0]["in_model"] and abs(sec[0]["t"]) > abs(sec[1]["t"])
    fx = r["maps"]["為替"][0]
    assert fx["id"] == "fx.usdjpy" and fx["total_beta"] > fx["beta"] - 0.2      # alone it also carries the market channel
    # scenario: +5 % USDJPY alone → ≈ 0.7 × 5 %; joint with the market = the raw model 1.1·M + 0.7·FX
    s1 = F.scenario(r["model"], {"fx.usdjpy": 5})
    assert abs(s1["expected_pct"] - 3.5) < 0.6 and s1["se_pct"] > 0
    s2 = F.scenario(r["model"], {"fx.usdjpy": 5, "mkt": -3})
    assert abs(s2["expected_pct"] - (1.1 * -3 + 0.7 * 5)) < 0.7
    assert {c["id"] for c in s2["contributions"]} == {"mkt", "fx.usdjpy"}
    # no look-ahead: data after the as-of date never changes the result
    cut = 40
    y2 = {d: (v * 3 if d > ds[-cut - 1] else v) for d, v in y.items()}
    a = F.analyze(y, cat, series, ids, "JP", end_offset=cut, maps=False)
    b = F.analyze(y2, cat, series, ids, "JP", end_offset=cut, maps=False)
    assert a["to"] == b["to"] and [e["beta"] for e in a["exposures"]] == [e["beta"] for e in b["exposures"]]
    assert a["attribution"]["total_pct"] == b["attribution"]["total_pct"]


def test_us_security_has_no_lags_and_missing_factors_warn():
    ds, y, series = world()
    cat = F.catalog("US")
    s = {"mkt": series["mkt"], "fx.dxy": series["fx.usdjpy"]}
    r = F.analyze(y, cat, s, ["mkt", "fx.dxy", "rate.us10"], "US", maps=False)
    assert not r["lagged"] and all(not e["lagged"] and e["next_day_pct"] is None for e in r["exposures"])
    assert any("米国 10 年金利" in w for w in r["warnings"])
    with pytest.raises(ValueError):
        F.analyze(y, cat, {}, ["mkt"], "US")


def test_series_helpers_and_catalog():
    closes = {"2026-01-05": 100.0, "2026-01-06": 110.0, "2026-01-07": 99.0}
    r = F.changes(closes)
    assert abs(r["2026-01-06"] - math.log(1.1)) < 1e-12 and F.changes({"a": 1.0, "b": 1.25}, "bp") == {"b": 25.0}
    assert F.lagged({"a": 1.0, "b": 2.0, "c": 3.0}) == {"b": 1.0, "c": 2.0}
    mk = {"2026-01-06": 0.01, "2026-01-07": -0.02}
    f = next(x for x in F.catalog("JP") if x["id"] == "sec.1625")
    xs = F.factor_series(f, {"TSE:1625": closes}, mk, {})
    assert abs(xs["2026-01-06"] - (math.log(1.1) - 0.01)) < 1e-12
    lib = next(x for x in F.catalog("JP") if x["id"] == "sty.value")
    assert F.factor_series(lib, {}, mk, {"value": {"d": 0.1}}) == {"d": 0.1}
    gv = next(x for x in F.catalog("US") if x["id"] == "sty.gv")
    sp = F.factor_series(gv, {"AMEX:IWF": closes, "AMEX:IWD": {"2026-01-05": 50.0, "2026-01-06": 50.0, "2026-01-07": 50.0}}, {}, {})
    assert abs(sp["2026-01-06"] - math.log(1.1)) < 1e-12
    assert F.weighted_returns({"A": {"d1": 0.02, "d2": 0.0}, "B": {"d1": -0.01}}, {"A": 0.5, "B": 0.5}) == {"d1": 0.005}
    jp = F.catalog("JP")
    assert len({f["id"] for f in jp}) == len(jp) and {f["group"] for f in jp} == set(F.GROUPS)
    assert all(f["late"] for f in jp if f["group"] in ("為替", "商品", "海外株")) and not any(f["late"] for f in F.catalog("US"))
    assert F.default_ids("JP", "sec.1625")[:3] == ["mkt", "sec.1625", "sty.size"]
    no_lib = {f["id"] for f in jp if f["kind"] != "lib"}
    assert "sty.etf.2516" in F.default_ids("JP", None, no_lib) and "sty.size" not in F.default_ids("JP", None, no_lib)
    part = no_lib | {"sty.mom_6m", "sty.volatility"}                         # price-based styles only (no scanner)
    assert [i for i in F.default_ids("JP", None, part) if i.startswith("sty.")] == ["sty.mom_6m", "sty.volatility"]
    assert "fx.dxy" in F.default_ids("US", "sec.XLK")


def test_fexp_api_sim():
    """SIM data (DEMO): a stock with the style library, a basket, PORT, the scenario, the coverage comparison."""
    from fastapi.testclient import TestClient

    from app.main import app

    tse = ["TSE:7203", "TSE:7267", "TSE:7201", "TSE:6758", "TSE:6501", "TSE:6503", "TSE:8306", "TSE:8316", "TSE:8411",
           "TSE:9984", "TSE:6857", "TSE:8035", "TSE:6954", "TSE:6273", "TSE:4063", "TSE:4502", "TSE:9432", "TSE:2914"]
    with TestClient(app) as c:
        c.put("/api/trinity/config", json={"extra": tse, "sources": []})
        assert c.post("/api/factors/build").status_code == 200                  # the coverage style library
        items = [{"ticker": "7203", "symbol": "TSE:7203", "name": "トヨタ自動車", "topix17": "自動車・輸送機", "fye_month": 3},
                 {"ticker": "6857", "symbol": "TSE:6857", "name": "アドバンテスト", "topix17": "電機・精密", "fye_month": 3}]
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector"}}})
        r = c.get("/api/fexp", params={"target": "TSE:7203", "end_offset": 5}).json()
        assert r["region"] == "JP" and r["sector_id"] == "sec.1622" and r["has_library"] and r["lagged"]
        ids = {e["id"] for e in r["exposures"]}
        assert {"mkt", "sec.1622", "fx.usdjpy", "sty.mom_6m"} <= ids and not r["warnings"]
        assert {"セクター", "為替", "スタイル", "海外株"} <= set(r["maps"]) and len(r["maps"]["セクター"]) == 17
        assert abs(sum(r["risk"]["groups"].values()) - r["r2"]) < 1e-9 and r["attribution"]["window"] == 21
        assert r["rolling"]["dates"] and "fx.usdjpy" in r["rolling"]["ids"]
        assert any(f["id"] == "fx.eurjpy" and not f["in_model"] for f in r["catalog"])
        s = c.post("/api/fexp/scenario", json={"key": r["key"], "shocks": {"fx.usdjpy": -5, "mkt": -2}}).json()
        assert s["expected_pct"] is not None and {x["id"] for x in s["contributions"]} >= {"mkt", "fx.usdjpy"}
        assert c.post("/api/fexp/scenario", json={"key": "nope", "shocks": {}}).status_code == 409
        # the user's own factor set
        r2 = c.get("/api/fexp", params={"target": "TSE:7203", "factors": "mkt,fx.usdjpy,fx.eurjpy,fx.usdcnh"}).json()
        assert [e["id"] for e in r2["exposures"]][:1] == ["mkt"] and {e["group"] for e in r2["exposures"]} == {"マーケット", "為替"}
        assert c.get("/api/fexp", params={"target": "TSE:7203", "factors": "mkt,nope"}).status_code == 400
        # a US stock: US factors, no lags; a basket; PORT in yen
        u = c.get("/api/fexp", params={"target": "NASDAQ:AAPL"}).json()
        assert u["region"] == "US" and not u["lagged"] and any(e["id"] == "sty.mtum" for e in u["exposures"])
        b = c.get("/api/fexp", params={"target": "TSE:7203,TSE:6857"}).json()
        assert b["kind"] == "basket" and b["weights"] == {"TSE:7203": 0.5, "TSE:6857": 0.5} and b["sector_id"] is None
        c.put("/api/store/portfolio", json={"value": [{"id": "1", "symbol": "TSE:7203", "qty": 100, "cost": 1},
                                                      {"id": "2", "symbol": "NASDAQ:AAPL", "qty": -10, "cost": 1}]})
        p = c.get("/api/fexp", params={"target": "PORT"}).json()
        assert p["kind"] == "port" and abs(sum(abs(v) for v in p["weights"].values()) - 1) < 1e-9 and p["weights"]["NASDAQ:AAPL"] < 0
        assert c.get("/api/fexp", params={"target": "7203 X"}).status_code == 400
        # every coverage stock side by side
        cv = c.get("/api/fexp/coverage").json()
        assert [x["symbol"] for x in cv["rows"]] == ["TSE:7203", "TSE:6857"] and cv["columns"]["JP"][0]["key"] == "mkt"
        row = cv["rows"][1]
        assert row["sector_id"] == "sec.1625" and row["cells"]["sector"]["label"].startswith("電機・精密") and row["att_1m"]
        c.put("/api/store/portfolio", json={"value": []})
