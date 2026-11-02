import datetime as dt
import math
import random

from fastapi.testclient import TestClient

from app import pairscreen, rrg, themes, trackrecord, xray


def days(n, start=dt.date(2023, 1, 2)):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


def walk(rets, p=100.0):
    out = []
    for r in rets:
        p *= math.exp(r)
        out.append(p)
    return out


def bars_from(closes, start=1_600_000_000, vol=1e6):
    return [{"time": start + i * 86400, "open": c, "high": c, "low": c, "close": c, "volume": vol} for i, c in enumerate(closes)]


# ---------------- XRAY
def test_xray_hierarchical_shares_and_book():
    rng = random.Random(4)
    n = 400
    ds = days(n)
    m = [rng.gauss(0, 0.01) for _ in range(n)]
    st = [rng.gauss(0, 0.008) for _ in range(n)]
    sec = [rng.gauss(0, 0.006) for _ in range(n)]
    e = [rng.gauss(0, 0.005) for _ in range(n)]
    D = lambda v: dict(zip(ds, v))  # noqa: E731
    y = [a + 0.8 * b + c + d for a, b, c, d in zip(m, st, sec, e)]
    r = xray.decompose(D(y), ("TVC:TOPIX", D(m)), {"USDJPY": D(st)}, ("TSE:1631", D(sec)))
    s = r["shares"]
    assert abs(sum(s.values()) - 1) < 1e-9
    assert 0.35 < s["market"] < 0.6 and 0.12 < s["style"] < 0.35 and 0.1 < s["sector"] < 0.3 and s["idio"] < 0.25
    betas = {c["factor"]: c["beta"] for c in r["coefficients"]}
    assert abs(betas["Market TVC:TOPIX"] - 1) < 0.1 and abs(betas["USDJPY"] - 0.8) < 0.1
    pure = xray.decompose(D(e), ("TVC:TOPIX", D(m)), {}, None)
    assert pure["shares"]["idio"] > 0.95 and "個別要因" in pure["verdict"]
    fchg = {"Market TVC:TOPIX": D(m), "USDJPY": D(st), "Sector TSE:1631": D(sec)}
    hedged = xray.book([{"symbol": "A", "weight": 3}, {"symbol": "B", "weight": -3}], {"A": r, "B": r}, fchg)
    assert hedged["factor_var_share"] < 1e-9 and not hedged["flags"]
    naked = xray.book([{"symbol": "A", "weight": 10}], {"A": r}, fchg)
    assert naked["market_exposure_pct"] > 5 and any("ベータ調整後ネット" in f for f in naked["flags"])
    assert any("意図しないファクター" in f for f in naked["flags"])


def test_sector_etf_mapping():
    assert xray.sector_etf("TSE:8306", "Finance", "Major Banks") == "TSE:1631"
    assert xray.sector_etf("TSE:8801", "Finance", "Real Estate Development") == "TSE:1633"
    assert xray.sector_etf("TSE:7203", "Consumer Durables") == "TSE:1622"
    assert xray.sector_etf("NASDAQ:AAPL", "Electronic Technology") == "AMEX:XLK"


# ---------------- RRG
def test_rrg_quadrants_follow_relative_strength():
    n = 600
    rng = random.Random(1)
    b = walk([rng.gauss(0, 0.01) for _ in range(n)])
    up = [x * math.exp(0.0006 * i * (1 if i > 450 else 0) + 0.0) for i, x in enumerate(b)]   # starts outperforming late
    down = [x * math.exp(-0.002 * max(0, i - 520)) for i, x in enumerate(b)]                  # underperforming lately
    res = rrg.analyze({"UP": bars_from(up), "DOWN": bars_from(down)}, bars_from(b), {"UP": "up", "DOWN": "down"})
    q = {r["symbol"]: r["quadrant"] for r in res["rows"]}
    assert q["UP"] in ("Leading", "Weakening") and q["DOWN"] in ("Lagging", "Improving")
    assert rrg.quadrant(101, 101) == "Leading" and rrg.quadrant(99, 101) == "Improving"
    assert rrg.NEXT["Improving"] == "Leading"


# ---------------- THEME
def test_theme_phase_rules():
    assert themes.phase(1.5, 0.2).startswith("②→③")
    assert themes.phase(1.5, 2.0).startswith("③")
    assert themes.phase(0.2, 2.0).startswith("バスケット先行")
    assert themes.phase(-1.2, 0.0).startswith("事実が逆行")
    assert themes.phase(None, 0.1).startswith("①")


def test_theme_basket_flow_and_beta_neutral_spread():
    rng = random.Random(7)
    n = 520
    common = [rng.gauss(0, 0.012) for _ in range(n)]
    idx = walk([rng.gauss(0, 0.01) for _ in range(n)])
    # longs move together (basket flow) in the last 80 days, independently before
    def mem(seed):
        r2 = random.Random(seed)
        return walk([(common[i] if i > n - 80 else 0) + r2.gauss(0, 0.01) for i in range(n)])
    bars = {"L1": bars_from(mem(1)), "L2": bars_from(mem(2)), "L3": bars_from(mem(3)), "TVC:TOPIX": bars_from(idx)}
    theme = {"name": "t", "longs": [{"symbol": "L1"}, {"symbol": "L2"}, {"symbol": "L3"}], "shorts": [], "hedge": "TVC:TOPIX"}
    res = themes.analyze(theme, bars)
    assert res["flow"]["avg_corr"] > 0.5 and res["flow"]["dominant"]
    assert any("バスケット買い" in f for f in res["flags"])
    assert res["short_side"] == ["TVC:TOPIX"] and len(res["members"]) == 3
    assert themes.TEMPLATES and all(t["longs"] for t in themes.TEMPLATES)


# ---------------- PFND
def test_pair_screen_orients_by_score_and_flags_wide_pairs():
    rng = random.Random(9)
    n = 300
    ds = days(n)
    mkt = [rng.gauss(0, 0.01) for _ in range(n)]
    A = [x + rng.gauss(0, 0.004) for x in mkt]
    B = [x + rng.gauss(0, 0.004) for x in mkt]
    C = [rng.gauss(0, 0.06) for _ in range(n)]
    rets = {k: dict(zip(ds, v)) for k, v in (("A", A), ("B", B), ("C", C), ("M", mkt))}
    closes = {k: dict(zip(ds, walk(v))) for k, v in (("A", A), ("B", B), ("C", C))}
    res = pairscreen.screen({"g": ["A", "B", "C"]}, rets, closes, {s: rets["M"] for s in "ABC"}, {"A": 2.8, "B": 4.4})
    top = res["pairs"][0]
    assert (top["long"], top["short"]) == ("B", "A") and top["verdict"] == "PASS" and abs(top["size_pct"] - 2.0) < 1e-9
    wide = next(p for p in res["pairs"] if "C" in (p["long"], p["short"]))
    assert wide["verdict"] == "FAIL" and wide["pair_sigma_pct"] > 30


# ---------------- TRAK
def test_track_record_round_trips_bayes_and_kelly():
    T = [
        {"id": "1", "time": "2026-01-05", "symbol": "X", "side": "buy", "qty": 100, "price": 100, "note": "#2%Japan"},
        {"id": "2", "time": "2026-01-20", "symbol": "X", "side": "sell", "qty": 100, "price": 110},
        {"id": "3", "time": "2026-02-02", "symbol": "Y", "side": "sell", "qty": 50, "price": 200, "note": "#alpha_short"},
        {"id": "4", "time": "2026-02-25", "symbol": "Y", "side": "buy", "qty": 50, "price": 210},
        {"id": "5", "time": "2026-03-02", "symbol": "X", "side": "buy", "qty": 100, "price": 100, "note": "#2%Japan"},
        {"id": "6", "time": "2026-03-09", "symbol": "X", "side": "sell", "qty": 50, "price": 104},
        {"id": "7", "time": "2026-03-16", "symbol": "X", "side": "sell", "qty": 50, "price": 108},
    ]
    r = trackrecord.analyze(T)
    trips = r["trips"]
    assert len(trips) == 4
    short = next(t for t in trips if t["symbol"] == "Y")
    assert short["side"] == "short" and abs(short["ret_pct"] + 5) < 1e-9 and short["pnl"] == -500
    g = r["groups"]["ALL"]
    assert g["wins"] == 3 and g["losses"] == 1
    assert abs(g["posterior"]["mean"] - 4 / 6 * 100) < 1e-9 and g["posterior"]["lo90"] < g["posterior"]["mean"] < g["posterior"]["hi90"]
    p, xw, xl = 4 / 6, (0.10 + 0.04 + 0.08) / 3, 0.05
    assert abs(g["e_pct"] - (p * xw - (1 - p) * xl) * 100) < 1e-9
    assert abs(g["kelly_f_pct"] - (p * xw - (1 - p) * xl) / (xw * xl) * 100) < 1e-6
    assert "#2%Japan" in r["groups"] and r["groups"]["#2%Japan"]["n"] == 3
    assert r["periods"]["month"]["periods"] == 3 and r["periods"]["month"]["target"] == 76.0


def test_insight_api_sim():
    from app.main import app

    with TestClient(app) as c:
        x = c.get("/api/insight/xray", params={"symbol": "TSE:7203", "sector_etf": "TSE:1622"}).json()
        assert abs(sum(x["shares"].values()) - 1) < 1e-6 and x["sector_etf"] == "TSE:1622"
        c.put("/api/framework/book", json={"positions": [{"symbol": "TSE:7203", "weight": 3}, {"symbol": "TSE:7267", "weight": -3}]})
        b = c.post("/api/insight/xray/book", json={}).json()
        assert b["positions"] == 2 and b["idio_var_share"] is not None
        r = c.get("/api/insight/rrg", params={"universe": "JP17"}).json()
        assert len(r["rows"]) == 17 and r["bench"] == "TVC:TOPIX"
        t = c.post("/api/insight/themes/from_template", json={"name": "2% Japan"}).json()
        a = c.get(f"/api/insight/themes/{t['id']}/analyze").json()
        assert a["phase"] and a["driver"]["z"] is not None and "spread_bn" in a["series"]
        p = c.post("/api/insight/pairs/screen", json={"groups": {"autos": ["TSE:7203", "TSE:7267", "TSE:7201"]}}).json()
        assert p["evaluated"] == 3
        c.put("/api/store/trades", json={"value": [
            {"id": "1", "time": "2026-01-05", "symbol": "TSE:7203", "side": "buy", "qty": 100, "price": 2000},
            {"id": "2", "time": "2026-01-20", "symbol": "TSE:7203", "side": "sell", "qty": 100, "price": 2100}]})
        tr = c.get("/api/insight/track").json()
        assert tr["groups"]["ALL"]["wins"] == 1
