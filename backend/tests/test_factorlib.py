import datetime as dt
import math
import random

from fastapi.testclient import TestClient

from app import factorlib as FL


def days(n):
    d0 = dt.date(2023, 1, 2)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def walk(rets, p=100.0):
    out = []
    for r in rets:
        p *= math.exp(r)
        out.append(p)
    return out


def test_style_returns_capture_momentum_and_size():
    rng = random.Random(1)
    n, N = 520, 30
    ds = days(n)
    mkt = [rng.gauss(0, 0.01) for _ in range(n)]
    closes, scan = {}, {}
    for i in range(N):
        drift = 0.002 if i < N // 2 else -0.002          # persistent winners / losers → momentum works
        rets = [m + drift + rng.gauss(0, 0.004) for m in mkt]
        closes[f"S{i}"] = dict(zip(ds, walk(rets)))
        scan[f"S{i}"] = {"market_cap_basic": 1e9 * (i + 1)}  # larger index = larger cap = loser → size factor < 0
    market = dict(zip(ds[1:], mkt[1:]))
    out = FL.style_returns(closes, market, scan)
    mom = list(out["mom_3m"].values())
    size = list(out["size"].values())
    assert len(mom) > 200 and sum(mom) / len(mom) > 0.003
    assert sum(size) / len(size) < -0.003
    assert "beta" in out and "volatility" in out


def test_attribution_recovers_factor_vs_specific():
    rng = random.Random(2)
    n = 400
    ds = days(n)
    m = [rng.gauss(0, 0.01) for _ in range(n)]
    st = [rng.gauss(0, 0.006) for _ in range(n)]
    factors = {FL.MARKET: dict(zip(ds, m)), "スタイル:モメンタム 6m": dict(zip(ds, st))}
    driven = {d: 1.2 * a + 0.5 * b + rng.gauss(0, 0.001) for d, a, b in zip(ds, m, st)}
    r = FL.attribute(driven, factors, window=21, est=252)
    b = {x["factor"]: x["beta"] for x in r["factors"]}
    assert abs(b[FL.MARKET] - 1.2) < 0.05 and abs(b["スタイル:モメンタム 6m"] - 0.5) < 0.1
    assert r["verdict"] == "ファクター・スタイル主導" and r["factor_share"] > 0.9
    assert abs(sum(r["groups_pct"].values()) + r["specific_pct"] - r["total_pct"]) < 1e-9
    noise = {d: rng.gauss(0, 0.02) for d in ds}
    r2 = FL.attribute(noise, factors, window=21, est=252)
    assert r2["verdict"] == "個社要因主導"
    # as-of: stepping back moves the window
    r3 = FL.attribute(driven, factors, window=21, est=252, end_offset=50)
    assert r3["to"] < r["to"] and r3["est_to"] < r3["from"]


def test_performance_windows():
    s = {d: 0.001 for d in days(200)}
    p = FL.performance(s)
    assert abs(p["1M"] - (math.exp(0.021) - 1) * 100) < 1e-9 and p["n"] == 200


def test_factor_and_stock_page_api_sim():
    from app.main import app

    tse = ["TSE:7203", "TSE:7267", "TSE:7201", "TSE:6758", "TSE:6501", "TSE:6503", "TSE:8306", "TSE:8316", "TSE:8411",
           "TSE:9984", "TSE:6857", "TSE:8035", "TSE:6954", "TSE:6273", "TSE:4063", "TSE:4502", "TSE:9432", "TSE:2914"]
    with TestClient(app) as c:
        c.put("/api/trinity/config", json={"extra": tse, "sources": []})
        b = c.post("/api/factors/build").json()
        assert b["universe"] == len(tse) and b["factors"] >= 5
        lib = c.get("/api/factors/library").json()
        groups = {r["group"] for r in lib["rows"]}
        assert {"スタイル", "マクロ", "セクター"} <= groups and lib["library"]["universe"] == len(tse)
        a = c.get("/api/factors/attribution/TSE:7203", params={"window": 21, "end_offset": 10}).json()
        assert a["verdict"] in ("個社要因主導", "混在", "ファクター・スタイル主導")
        assert any(f["factor"].startswith("スタイル:") for f in a["factors"]) and len(a["series"]) == 21
        pg = c.get("/api/stock/TSE:7203/page").json()
        assert pg["perf"] and pg["chart"] and "margin" in pg and "chip" in pg
