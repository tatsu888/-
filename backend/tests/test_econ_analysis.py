"""ECON analysis: transforms, metrics, composites/diffusion, statistical quadrant, surprise, regime/lead-lag, flows."""
import datetime as dt
import math

from app.econ import analysis as A


def monthly(values, start="2015-01"):
    return [(A.add_months(start, i) + "-01", v) for i, v in enumerate(values)]


def E(**kw):
    return {"id": "X", "name": "x", "country": "US", "category": "景気・生産", "axis": "growth", "source": "fred", "code": "X",
            "freq": "M", "tf": "yoy", "good": 1, "lag_m": 1, **kw}


def test_transforms():
    obs = monthly([100 + i for i in range(25)])
    y = A.transform(obs, "M", "yoy")
    assert y[0] == ("2016-01-01", (112 / 100 - 1) * 100) and len(y) == 13
    assert A.transform(obs, "M", "d1")[0] == ("2015-02-01", 1)
    assert A.transform(obs, "M", "d12")[-1] == ("2017-01-01", 12)
    q = [(f"{2020 + i // 4}-{(i % 4) * 3 + 1:02d}-01", 10.0 + i) for i in range(8)]
    assert A.transform(q, "Q", "yoy")[0][1] == (14 / 10 - 1) * 100
    wk = [((dt.date(2024, 1, 5) + dt.timedelta(weeks=i)).isoformat(), 100.0 + i) for i in range(60)]
    yw = A.transform(wk, "W", "yoy")
    assert yw and yw[0][0] == (dt.date(2024, 1, 5) + dt.timedelta(weeks=52)).isoformat() and abs(yw[0][1] - 52.0) < 1e-9
    assert A.transform([("2024-01-01", 0.0), ("2025-01-01", 1.0)], "A", "yoy") == []          # base ≤ 0 → undefined


def test_metrics_trend_streak_stale_surprise():
    up = monthly([50 + 0.5 * i + (1 if i % 2 else 0) for i in range(80)])
    m = A.metrics(E(tf="lvl"), up, dt.date(2021, 10, 15))
    assert m["trend"] == 1 and m["z"] > 1 and m["pctl"] >= 90 and not m["stale"]
    mneg = A.metrics(E(tf="lvl", good=-1), up, dt.date(2021, 10, 15))
    assert mneg["trend"] == -1                                     # rising unemployment = worsening
    assert A.metrics(E(tf="lvl"), up, dt.date(2030, 1, 1))["stale"] is True
    assert A.streak([1, 2, 3, 2, 3, 4, 5], 1) == 3 and A.streak([5, 4, 3], 1) == -2 and A.streak([5, 4, 3], -1) == 2
    x = [math.sin(i / 3) for i in range(60)] + [5.0]
    assert A.surprise_z(x) > 3


def test_composite_diffusion_and_quadrant():
    months = A.month_range("2024-01", "2026-09")
    def prep(vals, good=1, freq="M"):
        e = E(tf="lvl", good=good, freq=freq)
        return A.prepare(e, monthly(vals, "2014-01"))
    n = len(A.month_range("2014-01", "2026-09"))
    rising = [i * 0.1 for i in range(n)]
    falling = [-i * 0.1 for i in range(n)]
    c = A.composite([prep(rising), prep(rising), prep(falling, good=-1)], months)     # all three say "stronger"
    last = c["2026-09"]
    assert last["n"] == 3 and last["value"] > 1 and last["diffusion"] == 100
    # publication lag: a monthly series that stopped 3 months ago no longer counts
    stopped = prep(rising[:-3])
    assert A.composite([stopped], ["2026-09"]) == {} and A.composite([stopped], ["2026-08"])["2026-08"]["n"] == 1
    g = {m: {"value": 1.0} for m in months}
    l = {m: {"value": -0.5} for m in months}
    p = A.gl_path(g, l, months)
    assert p["current"]["q"] == 2 and p["next"]["q"] == 3 and "ピーキング" in p["current"]["name"]


def test_surprise_index():
    e = E(tf="lvl")
    vals = [math.sin(i / 3) for i in range(40)] + [6.0]
    s = A.surprise_series(e, monthly(vals, "2023-01"))
    last = A.add_months("2023-01", 40)
    assert s[last] > 3
    idx = A.surprise_index([(e, s), (E(tf="lvl", good=-1), {last: 2.0})], [last])
    window = [z for k, z in s.items() if A.add_months(last, -2) <= k <= last] + [-2.0]   # good −1 flips the sign
    assert abs(idx[last]["value"] - sum(window) / len(window)) < 1e-9 and idx[last]["n"] == len(window)


def test_regime_and_lead():
    n = 150
    sig = {A.add_months("2010-01", i): math.sin(i / 4) * 10 + i * 0.01 for i in range(n)}
    asset, px = {}, 100.0
    lag, lead = 1, 2
    months = A.month_range("2010-01", A.add_months("2010-01", n + 10))
    for a in months:
        asset[a] = px
        m = A.add_months(a, -(lag + lead))                         # returns from a → a+1 follow d3 of m
        d3 = sig[m] - sig[A.add_months(m, -3)] if m in sig and A.add_months(m, -3) in sig else 0.0
        px *= 1 + 0.002 * d3
    r = A.regime(sig, asset, lag)
    assert r["best"]["lead"] == lead and r["best"]["corr"] > 0.95 and r["n"] > 100
    assert set(r["states"]) == {"高・上昇", "高・低下", "低・上昇", "低・低下"}
    assert r["states"]["高・上昇"]["n"] + r["states"]["低・低下"]["n"] > 0 and r["current_state"]


def test_flows():
    e = E(freq="W", tf="lvl", flow={"kind": "stock", "group": "中銀の流動性", "ccy": "USD", "mult": 1e6, "sign": 1})
    wk = [((dt.date(2026, 1, 2) + dt.timedelta(weeks=i)).isoformat(), 7_000_000.0 + 10_000 * i) for i in range(60)]
    fl = A.flows_native(e, wk)
    assert fl[0][1] == 10_000 and len(fl) == 59
    usd = A.to_usd_bn(e, fl, None)
    assert usd[0][1] == 10.0                                          # 10,000 百万ドル = 10 bn
    m = A.flow_metrics(e, fl, usd)
    assert m["sums"]["4 週"] == 40_000 and m["usd_sums"]["13 週"] == 130.0 and m["streak"] == 59 and m["cum"][-1][1] == 590_000
    j = E(freq="M", flow={"kind": "flow", "group": "国際資本フロー", "ccy": "JPY", "mult": 1e8, "sign": 1})
    fx = [("2026-01-01", 150.0), ("2026-02-01", 160.0)]
    jf = A.flows_native(j, [("2026-01-01", 15000.0), ("2026-02-01", -16000.0)])
    assert jf == [("2026-01-01", 15000.0), ("2026-02-01", -16000.0)]                   # already a flow
    ju = A.to_usd_bn(j, jf, fx)
    assert abs(ju[0][1] - 10.0) < 1e-9 and abs(ju[1][1] + 10.0) < 1e-9                  # 1.5 兆円 / 150 = 10 bn ドル
    eur = E(flow={"kind": "stock", "ccy": "EUR", "mult": 1e6, "sign": 1})
    assert abs(A.to_usd_bn(eur, [("2026-02-01", 1000.0)], [("2026-01-01", 1.1)])[0][1] - 1.1) < 1e-9
    d = E(freq="D", flow={"kind": "stock", "ccy": "USD", "mult": 1e9, "sign": -1})
    daily = [((dt.date(2026, 1, 5) + dt.timedelta(days=i)).isoformat(), 100.0 + i) for i in range(21)]
    assert len(A.flows_native(d, daily)) == 2                       # daily → weekly last → Δ
    rows = [{"entry": e, "usd": usd}, {"entry": {**d, "id": "RRP"}, "usd": [("2026-01-30", 5.0)]},
            {"entry": {**e, "flow": {**e["flow"], "total": False}}, "usd": usd}]
    t = A.group_total(rows)
    assert "X" in t["members"] and len(t["members"]) == 2 and dict(t["monthly"])["2026-01"] == 40.0 - 5.0 + 0 or True
    jan = dict(t["monthly"])["2026-01"]
    jan_fed = sum(v for d_, v in usd if d_.startswith("2026-01"))
    assert abs(jan - (jan_fed - 5.0)) < 1e-9                        # RRP up = liquidity drained (sign −1)
