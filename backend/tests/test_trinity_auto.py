import math
import random

from fastapi.testclient import TestClient

from app import trinity_auto as T


def test_percentile_to_score_matches_notion_distribution():
    assert T.percentile_to_score(0.0) == 1.0
    assert abs(T.percentile_to_score(0.1) - 2.6) < 1e-12
    assert 2.7 < T.percentile_to_score(0.5) < 3.4          # middle 80% stays neutral
    assert abs(T.percentile_to_score(0.9) - 3.4) < 1e-12
    assert T.percentile_to_score(1.0) == 5.0


def test_fundamental_rule_scores_rank_quality_and_value():
    scans = {}
    for i in range(10):
        scans[f"S{i}"] = {"return_on_equity": i, "operating_margin": i, "gross_margin": i, "total_revenue_yoy_growth_ttm": i,
                          "enterprise_value_ebitda_ttm": 20 - i, "price_earnings_ttm": 30 - i, "debt_to_equity": 2 - i * 0.1,
                          "free_cash_flow": 1}
    scans["S0"]["price_earnings_ttm"] = -5  # loss-making = worst PE
    r = T.fundamental_rule_scores(scans)
    assert r["S9"]["score"] >= 3.4 and r["S0"]["score"] <= 2.7
    dirs = [T.F.direction(r[s]["score"]) for s in scans]
    assert dirs.count("NEUTRAL") >= 6
    few = T.fundamental_rule_scores({k: scans[k] for k in ("S1", "S2", "S3")})
    assert few["S1"]["score"] is None and "比較対象" in few["S1"]["reason"]


def test_macro_fit_by_quadrant():
    assert T.macro_fit("Technology Services", 1.0, 4)["view"] == 1
    assert T.macro_fit("Technology Services", 1.0, 3)["view"] == -1
    assert T.macro_fit("Utilities", 0.5, 3)["view"] == 1
    assert T.macro_fit("Retail Trade", 1.5, 2)["view"] == 1     # high beta favoured in ピーキング
    assert T.macro_fit("Finance", 1.0, None)["view"] == 0


def test_verdict_conviction_and_arbitration():
    v = T.verdict("LONG", 1, 1, 20)
    assert v["conviction"] == 3 and v["size_pct"] == 3.0
    v = T.verdict("LONG", -1, 0, 60)
    assert v["conviction"] == 0 and v["size_pct"] == 0 and any("ペア" in f for f in v["flags"])
    v = T.verdict("SHORT", -1, 0, 30, moat_qualifies=True)
    assert v["size_pct"] == 0 and any("3.5句" in f for f in v["flags"])
    v = T.verdict("SHORT", -1, -1, 30, mcap_usd=5e8)
    assert v["size_pct"] == 0 and any("小型株" in f for f in v["flags"])
    assert T.verdict("NEUTRAL", 1, 1, 20)["direction"] == "NEUTRAL"
    assert T.verdict("LONG", 0, 0, 60)["size_pct"] == 0.5  # 3% × 1/3 × 30/60


def _bars(n, drift, vol_mult=1.0, seed=1):
    rng = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        p *= math.exp(drift + rng.gauss(0, 0.01))
        out.append({"time": 1_600_000_000 + i * 86400, "open": p, "high": p, "low": p, "close": p,
                    "volume": 1e6 * (vol_mult if i >= n - 20 else 1) * (1 + rng.random() * 0.1)})
    return out


def test_flow_view_crowded_top():
    f = T.flow_view(_bars(400, 0.003, vol_mult=4))
    assert f["crowded"] and f["view"] == -1 and f["zone"] == "天井寄り"
    g = T.flow_view(_bars(400, 0.0, vol_mult=0.2, seed=2))
    assert g["activity_pctl"] <= 10


def test_evaluate_and_diff():
    inputs = {"A": {"bars": _bars(300, 0.0), "scan": {"sector": "Technology Services"}},
              "B": {"bars": _bars(300, 0.0, seed=3), "scan": {"sector": "Utilities"}}}
    gl = {"current": {"q": 4, "name": "4. ボトミング"}, "next": {"q": 1}}
    snap = T.evaluate(inputs, gl, {"A": {"total": 3.8, "direction": "LONG"}})
    a = next(r for r in snap["rows"] if r["symbol"] == "A")
    assert a["f"]["source"] == "SCORE" and a["direction"] == "LONG" and a["m"]["view"] == 1 and a["conviction"] >= 2
    b = next(r for r in snap["rows"] if r["symbol"] == "B")
    assert b["direction"] == "NEUTRAL"   # no fundamental view → no position (macro never creates one)
    snap2 = T.evaluate(inputs, {"current": {"q": 3, "name": "3. スローダウン"}}, {"A": {"total": 3.8, "direction": "LONG"}})
    ch = T.diff(snap, snap2)
    assert any(c["what"] == "quadrant" for c in ch) and any(c["symbol"] == "A" and c["what"] == "verdict" for c in ch)


def test_context_flags_and_theme_diff():
    inputs = {"A": {"bars": _bars(300, 0.0), "scan": {"sector": "Technology Services"},
                    "sector_rrg": {"etf": "TSE:1626", "label": "情報通信", "quadrant": "Lagging"},
                    "xray": {"market": 0.6, "style": 0.2, "sector": 0.1, "idio": 0.1, "verdict": "x"}},
              "B": {"bars": _bars(300, 0.0, seed=3), "scan": {"sector": "Utilities"}, "days_to_earnings": 12}}
    gl = {"current": {"q": 4, "name": "4"}}
    snap = T.evaluate(inputs, gl, {"A": {"total": 3.8, "direction": "LONG"}, "B": {"total": 2.2, "direction": "SHORT"}})
    a = next(r for r in snap["rows"] if r["symbol"] == "A")
    assert any("セクター・フローが逆行" in f for f in a["flags"]) and any("個別要因 10%" in f for f in a["flags"])
    assert a["gates"]["①マクロ"] == "FAIL"
    b = next(r for r in snap["rows"] if r["symbol"] == "B")
    assert any("決算まで 12 日" in f for f in b["flags"])
    prev = {"rows": snap["rows"], "themes": [{"id": "t1", "name": "X", "phase": "① 初動前／様子見"}]}
    cur = {"rows": snap["rows"], "themes": [{"id": "t1", "name": "X", "phase": "②→③ エントリーゾーン（未波及）"}]}
    ch = T.diff(prev, cur)
    assert ch == [{"symbol": "THEME X", "what": "theme", "from": "① 初動前／様子見", "to": "②→③ エントリーゾーン（未波及）"}]


def test_trinity_api_sim():
    from app.main import app

    with TestClient(app) as c:
        c.put("/api/trinity/config", json={"extra": ["NASDAQ:AAPL", "TSE:7203"], "exclude": []})
        cfg = c.get("/api/trinity/config").json()
        assert "NASDAQ:AAPL" in cfg["universe"] and not any(s.startswith("FX:") for s in cfg["universe"])
        snap = c.post("/api/trinity/run").json()
        assert snap["universe"] >= 2 and snap["rows"] and "book" in snap
        lat = c.get("/api/trinity/latest").json()
        assert lat["snapshot"]["generated_at"] == snap["generated_at"]
        h = c.get("/api/trinity/history/NASDAQ:AAPL").json()
        assert len(h["history"]) == 1
        assert "sectors" in snap and "themes" in snap
        row = next(r for r in snap["rows"] if r["symbol"] == "NASDAQ:AAPL")
        assert "sector_rrg" in row and row["xray"] and abs(sum(v for k, v in row["xray"].items() if k != "verdict") - 1) < 1e-6
        t = c.post("/api/insight/themes/from_template", json={"name": "ESG Backlash"}).json()
        snap2 = c.post("/api/trinity/run").json()
        assert any(x["id"] == t["id"] and x["phase"] for x in snap2["themes"])
