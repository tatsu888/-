import datetime as dt
import math
import random

from fastapi.testclient import TestClient

from app import framework as F
from app import macro


def days(n):
    d0 = dt.date(2022, 1, 3)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def sheet_with(score, ai=None, prev=None):
    rows = [dict(r, score=score, ai_score=ai, prev_score=prev) for r in F.SCORE_FACTORS]
    return {"rows": rows, "reason": "test", "text": {"proposition": "x", "catalysts": "y"}}


def test_default_weights_sum_to_100():
    assert sum(r["weight"] for r in F.SCORE_FACTORS) == 100


def test_score_sheet_direction_thresholds():
    assert F.score_sheet(sheet_with(3.5))["direction"] == "LONG"
    assert F.score_sheet(sheet_with(3.4))["direction"] == "LONG"
    assert F.score_sheet(sheet_with(3.0))["direction"] == "NEUTRAL"
    assert F.score_sheet(sheet_with(2.7))["direction"] == "SHORT"
    r = F.score_sheet(sheet_with(4, ai=2, prev=3))
    assert r["total"] == 4 and r["ai_total"] == 2 and r["delta"] == 1
    assert len(r["divergence"]) == len(F.SCORE_FACTORS)
    assert len(r["changes"]) == len(F.SCORE_FACTORS)


def test_score_sheet_validation_and_moat_short_conflict():
    s = sheet_with(2.0)
    s["rows"][0]["weight"] = 50
    s["moat"] = {"brand": True}
    r = F.score_sheet(s)
    msgs = " ".join(i["msg"] for i in r["issues"])
    assert "Weight の合計" in msgs
    assert "3.5句に合致" in msgs
    s2 = sheet_with(2.0)
    s2["text"] = {}
    assert any("カタリスト必須" in i["msg"] for i in F.score_sheet(s2)["issues"])
    bad = sheet_with(6)
    assert any("範囲外" in i["msg"] for i in F.score_sheet(bad)["issues"])


def test_moat_weights_and_physical_filter():
    m = F.moat_score({"monopoly_network": 1, "cost_cospa": 1, "brand": 1, "technology": 1})
    assert m["score"] == 3.5
    m = F.moat_score({"technology": 1, "physical": ["technology"]})
    assert m["score"] == 0.25


def test_score_gap_anchors():
    assert F.score_gap_size(3.3, 2.8)["size_pct"] == 0.5
    assert abs(F.score_gap_size(4.4, 2.8)["size_pct"] - 2.0) < 1e-9
    assert F.score_gap_size(2.8, 3.3)["size_pct"] == 0


def test_kelly_coin_toss():
    k = F.kelly(0.5, 1.0, 0.5)  # 勝てば+100%、負ければ−50%
    assert abs(k["e"] - 0.25) < 1e-12
    assert abs(k["f"] - 0.5) < 1e-12
    assert abs(k["g_star"] - 0.5 * math.log(1.125)) < 1e-12
    assert k["recommended_pct"] == 3.0  # capped at long 3%
    neg = F.kelly(0.3, 0.1, 0.1)
    assert neg["e"] < 0 and neg["recommended_pct"] == 0 and neg["principles"][0]["ok"] is False
    ruin = F.kelly(0.999, 0.05, 1.0, ruin_prob=0.001)
    assert ruin["principles"][2]["ok"] is True  # F < 1 here


def test_exposure_rules():
    pos = [
        {"symbol": "A", "weight": 3.5, "sector": "IT", "subsector": "SPE", "pair": "p1", "beta": 1.0},
        {"symbol": "B", "weight": -3.5, "sector": "IT", "subsector": "SPE", "pair": "p1", "beta": 1.0,
         "short_type": "pair_leg", "mcap_usd": 5e11},
        {"symbol": "C", "weight": 2.0, "sector": "Fin", "subsector": "Bank", "pair": "p2", "beta": 1.5},
        {"symbol": "D", "weight": -2.0, "sector": "Ind", "subsector": "FA", "pair": "p2", "beta": 0.5,
         "short_type": "alpha", "mcap_usd": 5e8, "expected_downside_pct": 20},
    ]
    r = F.exposure_check(pos, "book", -6.0, {"p1": {"pair_sigma_pct": 31, "pair_correlation": 0.8}})
    by = {(c["layer"], c["rule"], c["subject"]): c["status"] for c in r["checks"]}
    assert by[("L1", "ロング1銘柄 3%（絶対上限3〜4%）", "A")] == "WARN"
    assert by[("L1", "ショート1銘柄 2%（絶対上限3%）", "B")] == "FAIL"
    assert by[("L1", "小型株ショート禁止（時価総額 約10億ドル未満）", "D")] == "FAIL"
    assert by[("L1", "アルファ・ショートは30〜40%以上の下落見込み", "D")] == "FAIL"
    assert by[("L2", "同一サブセクター内で組む（真のペア）", "p2")] == "FAIL"
    assert by[("L2", "Beta調整後 Net÷Gross 30%未満", "p2")] == "WARN"   # (2*1.5 - 2*0.5)/4 = 0.5
    assert by[("L2", "Pair Sigma 25〜30%未満（理想10%前後）", "p1")] == "FAIL"
    assert by[("L4", "セクター・ネット ±5%", "Fin")] == "PASS"
    assert any(c["rule"].startswith("ドローダウン") and c["status"] == "FAIL" for c in r["checks"])
    assert r["gross"] == 11 and r["net"] == 0
    f = F.exposure_check([{"symbol": "X", "weight": 6}], "fund")
    assert any(c["layer"] == "L6" and c["status"] == "FAIL" for c in f["checks"])


def _walk(rets, p=100.0):
    out = []
    for r in rets:
        p *= math.exp(r)
        out.append(p)
    return out


def test_pair_metrics_true_pair_low_sigma():
    rng = random.Random(3)
    n = 300
    mkt = [rng.gauss(0, 0.012) for _ in range(n)]
    a = [m + rng.gauss(0, 0.004) for m in mkt]
    b = [m + rng.gauss(0, 0.004) for m in mkt]
    ds = days(n)
    closes = {"A": dict(zip(ds, _walk(a))), "B": dict(zip(ds, _walk(b))), "M": dict(zip(ds, _walk(mkt)))}
    m = F.pair_metrics(closes, "A", "B", 1, -1, "M")
    assert m["pair_sigma_pct"] < 10
    assert m["pair_correlation"] > 0.8
    assert abs(m["beta_long"] - 1) < 0.15 and m["beta_net_gross"] < 0.1
    assert m["idio_share_long"] < 0.3
    assert 0 <= m["spread_percentile_20d"] <= 100
    s = F.pair_suitability(m, [[1, -1], [1, 1], [-1, 1]], True, "A-1")
    st = {c["criterion"][:6]: c["status"] for c in s["criteria"]}
    assert st["ペア内リター"] == "WARN"     # highly correlated legs → little dispersion to harvest
    assert any(c["status"] == "PASS" and "A-1" in str(c["value"]) for c in s["criteria"])


def test_short_model_1_requires_all_four():
    x = {"valuation_percentile": 96, "growth_path": [30, 20, 10], "crowding_pct": 90}
    r = F.short_models(x)
    m1 = r["models"][0]
    assert m1["status"] == "MATCH" and r["matches"][0].startswith("①")
    r = F.short_models({**x, "crowding_pct": 50})
    assert r["models"][0]["status"] == "NO"
    r = F.short_models({"revenue_growth_pct": 30, "op_margin_pct": -5, "fcf_negative": True, "market_cap_usd": 5e8})
    assert r["models"][2]["status"] == "MATCH"
    assert any("小型株" in g for g in r["guards"])
    assert r["models"][4]["status"] == "INCOMPLETE"  # unknown stays unknown


def test_top_bottom_turnover():
    hot = [12.0] * 30
    r = F.top_bottom(hot, {"ratio_percentile": 90, "buy_days": 8}, valuation_percentile=97)
    assert r["zone"] == "天井シグナル群に近い"
    cold = [5.0] * 300 + [0.5] * 20
    r = F.top_bottom(cold, None, dividend_yield_pct=5.0, risk_free_pct=1.0)
    assert r["zone"] == "底シグナル群に近い"
    mkt = F.top_bottom([4.0] * 25, scope="market")
    assert mkt["top"][0]["on"] is True  # 20 × 4% = 80% ≥ 70%


def test_gates_progress_requires_every_item():
    ans = {f"macro:{i}": "yes" for i in range(4)}
    r = F.gates_progress(ans)
    assert r["gates"][0]["status"] == "PASS" and r["blocked_at"].startswith("②")
    ans["fundamental:0"] = "no"
    assert F.gates_progress(ans)["gates"][1]["status"] == "FAIL"


def test_growth_liquidity_quadrant():
    rng = random.Random(5)
    n = 1200
    ds = days(n)
    up = _walk([0.001 + rng.gauss(0, 0.005) for _ in range(n)])
    flat = _walk([rng.gauss(0, 0.005) for _ in range(n)])
    data = {"COMEX:HG1!": dict(zip(ds, up)), "TVC:GOLD": dict(zip(ds, flat)),
            "TVC:US10Y": dict(zip(ds, [4 + i * 0.001 for i in range(n)])),
            "TVC:DXY": dict(zip(ds, _walk([-0.0005 + rng.gauss(0, 0.003) for _ in range(n)]))),
            "TVC:US02Y": dict(zip(ds, [4 - i * 0.0005 for i in range(n)])),
            "AMEX:HYG": dict(zip(ds, up)), "NASDAQ:IEF": dict(zip(ds, flat)), "NASDAQ:QQQ": dict(zip(ds, up))}
    r = macro.growth_liquidity(data)
    assert r["current"]["q"] in (1, 2, 3, 4)
    assert r["next"]["q"] == macro.GL_NEXT[r["current"]["q"]]
    assert len(r["trail"]) == 126
    assert macro.quadrant(1, 1) == 1 and macro.quadrant(1, -1) == 2 and macro.quadrant(-1, -1) == 3 and macro.quadrant(-1, 1) == 4


def test_framework_api_sim():
    from app.main import app

    with TestClient(app) as c:
        meta = c.get("/api/framework/meta").json()
        assert meta["weights_placeholder"] is True and len(meta["gates"]) == 5
        rows = [dict(r, score=4) for r in meta["score_factors"]]
        r = c.post("/api/framework/scorecards/TSE:7203", json={"rows": rows, "subsector": "Autos", "reason": "r"}).json()
        assert r["version"] == 1 and r["result"]["direction"] == "LONG"
        rows2 = [dict(r, score=2) for r in meta["score_factors"]]
        r = c.post("/api/framework/scorecards/TSE:7203", json={"rows": rows2, "subsector": "Autos"}).json()
        assert r["result"]["prev_total"] == 4 and r["result"]["delta"] == -2
        c.post("/api/framework/scorecards/TSE:7267", json={"rows": rows, "subsector": "Autos"})
        pairs = c.get("/api/framework/pairs_from_scores").json()["pairs"]
        assert pairs and pairs[0]["long"]["symbol"] == "TSE:7267" and pairs[0]["size_pct"] == 2.0
        k = c.post("/api/framework/kelly", json={"pw": 0.6, "xw": 0.3, "xl": 0.15}).json()
        assert abs(k["e"] - (0.6 * 0.3 - 0.4 * 0.15)) < 1e-12
        idea = c.post("/api/framework/ideas", json={"title": "2% Japan", "answers": {"macro:0": "yes"}}).json()
        assert idea["progress"]["gates"][0]["yes"] == 1
        reset = c.post("/api/framework/ideas/monthly_reset").json()
        assert reset["ideas"] == 1
        assert c.get("/api/framework/ideas").json()["ideas"][0]["answers"] == {}
        pr = c.post("/api/framework/pair", json={"long": "NASDAQ:AAPL", "short": "NASDAQ:MSFT"}).json()
        assert "pair_sigma_pct" in pr and len(pr["criteria"]) == 5
        ex = c.post("/api/framework/exposure", json={"positions": [
            {"symbol": "NASDAQ:AAPL", "weight": 2, "pair": "x", "sector": "IT", "subsector": "HW"},
            {"symbol": "NASDAQ:MSFT", "weight": -2, "pair": "x", "sector": "IT", "subsector": "HW", "short_type": "pair_leg"}]}).json()
        assert "x" in ex["pair_stats"] and ex["summary"]["PASS"] >= 1
        sm = c.post("/api/framework/short_models", json={"symbol": "NASDAQ:AAPL", "inputs": {}}).json()
        assert "drawdown_from_high_pct" in sm["auto"]
        gl = c.get("/api/macro/growth_liquidity").json()
        assert "current" in gl or "error" in gl
