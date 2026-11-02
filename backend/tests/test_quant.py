import math
import random

from fastapi.testclient import TestClient

from app import quant
from app.models import make_bar

DAY = 86400
T0 = 1_600_000_000 - 1_600_000_000 % DAY


def series(rets, start=100.0):
    out, p = [make_bar(T0, start, start, start, start, 0)], start
    for i, r in enumerate(rets, start=1):
        p *= 1 + r
        out.append(make_bar(T0 + DAY * i, p, p, p, p, 0))
    return out


def test_beta_recovers_true_beta():
    rng = random.Random(3)
    m = [rng.gauss(0, 0.01) for _ in range(500)]
    s = [0.0002 + 1.5 * x + rng.gauss(0, 0.002) for x in m]
    res = quant.beta_regression(series(s), series(m))
    assert abs(res["beta"] - 1.5) < 0.05
    assert abs(res["adjusted_beta"] - (0.67 * res["beta"] + 0.33)) < 1e-12
    assert res["r2"] > 0.9 and res["observations"] == 500


def test_spread_detects_cointegration_and_half_life():
    rng = random.Random(5)
    lb, spread = [math.log(100)], [0.0]
    for _ in range(600):
        lb.append(lb[-1] + rng.gauss(0, 0.01))
        spread.append(0.9 * spread[-1] + rng.gauss(0, 0.005))  # AR(1) phi=0.9 -> HL = ln2/-ln0.9 ≈ 6.6
    la = [0.8 * x + 0.5 + s for x, s in zip(lb, spread)]
    a = [make_bar(T0 + DAY * i, math.exp(v), math.exp(v), math.exp(v), math.exp(v), 0) for i, v in enumerate(la)]
    b = [make_bar(T0 + DAY * i, math.exp(v), math.exp(v), math.exp(v), math.exp(v), 0) for i, v in enumerate(lb)]
    res = quant.pair_spread(a, b)
    assert abs(res["hedge_ratio"] - 0.8) < 0.05
    assert res["cointegrated_at"] == "1%"
    assert 4 < res["half_life"] < 10
    # two independent random walks should usually NOT be cointegrated
    rw = [math.log(100)]
    for _ in range(600):
        rw.append(rw[-1] + rng.gauss(0, 0.01))
    c = [make_bar(T0 + DAY * i, math.exp(v), math.exp(v), math.exp(v), math.exp(v), 0) for i, v in enumerate(rw)]
    assert quant.pair_spread(c, b)["adf"]["t_stat"] > -3.9


def test_seasonality_table():
    bars = []
    import datetime as dt
    p = 100.0
    for y in (2021, 2022, 2023):
        for mth in range(1, 13):
            p *= 1.10 if mth == 1 else 1.0
            bars.append(make_bar(int(dt.datetime(y, mth, 28, tzinfo=dt.timezone.utc).timestamp()), p, p, p, p, 0))
    res = quant.seasonality(bars)
    jan = res["month_stats"][0]
    assert abs(jan["mean"] - 10) < 1e-9 and jan["pct_positive"] == 100 and jan["n"] == 2
    assert res["month_stats"][5]["mean"] == 0


def test_event_study_finds_abnormal_jump():
    rng = random.Random(9)
    m = [rng.gauss(0, 0.01) for _ in range(400)]
    s = [x + rng.gauss(0, 0.003) for x in m]
    events = []
    import datetime as dt
    for k in (200, 260, 320):
        s[k - 1] += 0.05  # +5% abnormal on day 0 (return index k-1 -> bar k)
        events.append(dt.datetime.fromtimestamp(T0 + DAY * k, tz=dt.timezone.utc).strftime("%Y-%m-%d"))
    res = quant.event_study(series(s), series(m), events, pre=3, post=3, est_window=100)
    assert res["n_events"] == 3
    day0 = res["relative_days"].index(0)
    assert res["mean_car"][day0] - res["mean_car"][day0 - 1] > 0.045
    assert all(e["ar_day0"] > 0.04 for e in res["events"])


def test_portfolio_risk_basic_identities():
    rng = random.Random(11)
    m = [rng.gauss(0, 0.01) for _ in range(300)]
    a = series([x + rng.gauss(0, 0.005) for x in m])
    b = series([0.5 * x + rng.gauss(0, 0.005) for x in m])
    res = quant.portfolio_risk([{"symbol": "A", "qty": 10}, {"symbol": "B", "qty": 10}], {"A": a, "B": b}, series(m))
    total = sum(p["contribution_pct"] for p in res["positions"].values())
    assert abs(total - 100) < 1e-6  # risk contributions add up to 100%
    assert res["var_99_1d_pct"] >= res["var_95_1d_pct"] > 0
    assert res["es_95_1d_pct"] >= res["var_95_1d_pct"]
    assert 0.5 < res["beta"] < 1.2 and len(res["stress_worst_benchmark_days"]) == 5


def test_peer_stats_percentile():
    rows = {"T": {"pe": 10}, "A": {"pe": 20}, "B": {"pe": 30}, "C": {"pe": None}}
    st = quant.peer_stats(rows, "T", ["pe"])["pe"]
    assert st["median"] == 20 and st["percentile"] == 0 and st["n"] == 3 and abs(st["vs_median_pct"] + 50) < 1e-9


def test_quant_endpoints_sim():
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/analytics/beta", params={"symbol": "NASDAQ:AAPL"}).json()
        assert "beta" in r and r["benchmark"] == "SP:SPX"
        r = c.get("/api/analytics/spread", params={"a": "NASDAQ:AAPL", "b": "NASDAQ:MSFT"}).json()
        assert "hedge_ratio" in r and r["series"]["spread"]
        r = c.get("/api/analytics/seasonality", params={"symbol": "SP:SPX"}).json()
        assert len(r["month_stats"]) == 12
        r = c.post("/api/analytics/event_study", json={"symbol": "NASDAQ:AAPL"}).json()
        assert r["auto_events"] is True
        r = c.post("/api/analytics/portfolio_risk", json={"positions": [{"symbol": "NASDAQ:AAPL", "qty": 100},
                                                                         {"symbol": "TSE:7203", "qty": -50}]}).json()
        assert "vol_annual" in r and "beta" in r
        r = c.get("/api/analytics/relative_value", params={"symbol": "NASDAQ:AAPL", "peers": "NASDAQ:MSFT,NASDAQ:GOOGL"}).json()
        assert r["stats"]["hist_1Y"]["n"] == 3
        assert c.get("/api/analytics/earnings", params={"symbols": "NASDAQ:AAPL"}).json()["rows"] == []


def test_portfolio_risk_fx_conversion():
    rng = random.Random(12)
    a = series([rng.gauss(0, 0.01) for _ in range(100)], start=100.0)    # USD stock
    j = series([rng.gauss(0, 0.01) for _ in range(100)], start=3000.0)   # JPY stock
    pos = [{"symbol": "NASDAQ:A", "qty": 10}, {"symbol": "TSE:J", "qty": 1}]
    raw = quant.portfolio_risk(pos, {"NASDAQ:A": a, "TSE:J": j}, None)
    conv = quant.portfolio_risk(pos, {"NASDAQ:A": a, "TSE:J": j}, None,
                                fx_to_base={"NASDAQ:A": 1.0, "TSE:J": 1 / 150})
    assert raw["positions"]["TSE:J"]["weight"] > 0.6          # JPY notional dominates without FX
    assert conv["positions"]["TSE:J"]["weight"] < 0.05        # 3000 JPY ≈ 20 USD vs ~1000 USD
    assert quant.currency_of("TSE:7203") == "JPY" and quant.currency_of("NASDAQ:AAPL") == "USD"


def test_fx_pair_convention():
    assert quant.fx_pairs("JPY", "USD")[0] == ("FX:USDJPY", True)
    assert quant.fx_pairs("EUR", "USD")[0] == ("FX:EURUSD", False)
    assert quant.fx_pairs("USD", "JPY")[0] == ("FX:USDJPY", False)
    assert quant.fx_pairs("JPY", "EUR")[0] == ("FX:EURJPY", True)


def test_pair_backtest_profits_on_mean_reverting_spread_without_lookahead():
    rng = random.Random(21)
    lb, sp = [math.log(100)], [0.0]
    for _ in range(900):
        lb.append(lb[-1] + rng.gauss(0, 0.01))
        sp.append(0.85 * sp[-1] + rng.gauss(0, 0.01))
    la = [x + s + 0.3 for x, s in zip(lb, sp)]
    mk = lambda ls: [make_bar(T0 + DAY * i, math.exp(v), math.exp(v), math.exp(v), math.exp(v), 0) for i, v in enumerate(ls)]  # noqa: E731
    res = quant.pair_backtest(mk(la), mk(lb), hedge_window=120, z_window=40, fee_bps=2)
    assert res["stats"]["trades"] > 5 and res["stats"]["total_return_pct"] > 0
    # the hedge ratio estimate should be near the true 1.0
    assert abs(res["hedge"][-1]["value"] - 1.0) < 0.2
    # independent walks: no systematic edge expected (just check it runs)
    rw = [math.log(100)]
    for _ in range(900):
        rw.append(rw[-1] + rng.gauss(0, 0.01))
    assert "stats" in quant.pair_backtest(mk(rw), mk(lb))


def test_blotter_average_cost_long_short_flip():
    trades = [
        {"id": "1", "time": "2026-01-01", "symbol": "A", "side": "buy", "qty": 100, "price": 10, "fee": 1},
        {"id": "2", "time": "2026-01-02", "symbol": "A", "side": "buy", "qty": 100, "price": 12, "fee": 1},
        {"id": "3", "time": "2026-01-03", "symbol": "A", "side": "sell", "qty": 150, "price": 15, "fee": 1},
        {"id": "4", "time": "2026-01-04", "symbol": "A", "side": "sell", "qty": 100, "price": 14, "fee": 1},  # flip short 50
        {"id": "5", "time": "2026-01-05", "symbol": "A", "side": "buy", "qty": 50, "price": 13, "fee": 0},   # cover
    ]
    r = quant.blotter_positions(trades)
    p = r["positions"]["A"]
    # avg 11 → sell 150 @15: +600; sell 100 @14: close 50 @14 (+150), short 50 @14; cover @13: +50
    assert abs(p["realized"] - 800) < 1e-9 and p["qty"] == 0 and p["fees"] == 4
    assert abs(r["total_realized_net"] - 796) < 1e-9


def test_portfolio_risk_includes_fx_moves():
    rng = random.Random(4)
    j = series([0.0] * 100, start=3000.0)                       # flat in JPY
    fx = {}
    rate = 1 / 150
    import datetime as dt
    for i in range(101):
        fx[dt.datetime.fromtimestamp(T0 + DAY * i, tz=dt.timezone.utc).strftime("%Y-%m-%d")] = rate
        rate *= 1 + rng.gauss(0, 0.007)                          # USD per JPY moves
    a = series([0.0] * 100, start=100.0)
    pos = [{"symbol": "TSE:J", "qty": 1}, {"symbol": "NASDAQ:A", "qty": 1}]
    no_fx = quant.portfolio_risk(pos, {"TSE:J": j, "NASDAQ:A": a}, None, fx_to_base={"TSE:J": 1 / 150})
    with_fx = quant.portfolio_risk(pos, {"TSE:J": j, "NASDAQ:A": a}, None, fx_to_base={"TSE:J": 1 / 150},
                                   fx_series={"TSE:J": fx})
    assert no_fx["vol_annual"] == 0 and with_fx["vol_annual"] > 0 and with_fx["fx_included"] == ["TSE:J"]
