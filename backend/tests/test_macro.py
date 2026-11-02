import datetime as dt
import math
import random

from fastapi.testclient import TestClient

from app import macro


def days(n):
    d0 = dt.date(2023, 1, 2)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def test_build_series_specs():
    ds = days(3)
    data = {"A": dict(zip(ds, [10, 11, 12])), "B": dict(zip(ds, [5, 5, 6])), "C": dict(zip(ds, [2, 4, 4]))}
    assert macro.build({"spread": ["A", "B"]}, data)[ds[2]] == 6
    assert macro.build({"ratio": ["A", "B"]}, data)[ds[1]] == 11 / 5
    assert macro.build({"inv": "C"}, data)[ds[1]] == 0.25
    b = macro.build({"basket": ["A", "C"]}, data)
    assert b[ds[0]] == 100 and abs(b[ds[1]] - 100 * (1.1 + 2.0) / 2) < 1e-9
    assert macro.symbols_in({"ratio": [{"basket": ["X", {"inv": "Y"}]}, "Z"]}) == ["X", "Y", "Z"]


def test_signed_z_and_propagation_lag_detected():
    rng = random.Random(7)
    n = 900
    shock = [rng.gauss(0, 0.01) for _ in range(n)]
    lag = 10

    def walk(rets, start=100.0):
        out, p = [], start
        for r in rets:
            p *= math.exp(r)
            out.append(p)
        return out
    ds = days(n)
    t1 = walk(shock)
    t2 = walk([0.0] * 5 + shock[:-5])
    t3 = walk([0.0] * lag + [x + rng.gauss(0, 0.002) for x in shock[:-lag]])
    inv = walk([-x for x in shock])                                   # dir −1 item moving opposite
    data = {"T1": dict(zip(ds, t1)), "T2": dict(zip(ds, t2)), "T3": dict(zip(ds, t3)), "INV": dict(zip(ds, inv))}
    items = [
        {"id": "a", "label": "a", "cls": "株式", "tier": 1, "series": {"sym": "T1"}, "kind": "price", "dir": 1},
        {"id": "i", "label": "i", "cls": "株式", "tier": 1, "series": {"sym": "INV"}, "kind": "price", "dir": -1},
        {"id": "b", "label": "b", "cls": "株式", "tier": 2, "series": {"sym": "T2"}, "kind": "price", "dir": 1},
        {"id": "c", "label": "c", "cls": "株式", "tier": 3, "series": {"sym": "T3"}, "kind": "price", "dir": 1},
    ]
    res = macro.analyze(items, data, z_window=20, max_lag=30)
    sz = {it["id"]: it["signals"]["sz"] for it in res["items"]}
    assert abs(sz["a"] - sz["i"]) < 0.05  # direction flip makes the inverted series agree
    ll = {(x["from"], x["to"]): x for x in res["tier_leadlag"]}
    assert ll[(1, 3)]["best_lag_days"] == lag and ll[(1, 2)]["best_lag_days"] == 5
    leaders = next(it for it in res["items"] if it["id"] == "c")["leaders"]
    assert leaders[0]["lag"] in (lag, lag - 5) and leaders[0]["corr"] > 0.5
    assert res["gaps"][0]["cls"] == "株式"


def test_gap_states():
    items = [{"cls": "通貨", "tier": 1, "signals": {"sz": 2.0}}, {"cls": "通貨", "tier": 3, "signals": {"sz": -0.5}},
             {"cls": "株式", "tier": 2, "signals": {"sz": 1.5}}, {"cls": "株式", "tier": 3, "signals": {"sz": 1.4}},
             {"cls": "コモディティ", "tier": 1, "signals": {"sz": -1.8}}]
    g = {x["cls"]: x["state"] for x in macro.propagation_gaps(items)}
    assert g["通貨"].startswith("未波及") and g["株式"] == "波及済" and g["コモディティ"].startswith("下流なし")


def test_macro_api_sim():
    from app.main import app

    with TestClient(app) as c:
        m = c.get("/api/macro/map").json()
        assert len(m["items"]) >= 30 and not m["custom"]
        r = c.get("/api/macro/propagation", params={"bars": 600}).json()
        assert {it["id"] for it in r["items"]} >= {"frontier_eq", "jp_style", "dm_credit"}
        assert all("sz" in it["signals"] or "error" in it["signals"] for it in r["items"])
        assert r["gaps"] and r["composites"]
        d = c.get("/api/macro/dashboard", params={"bars": 800}).json()
        assert d["dashboard"][0]["rows"] and d["regime"]["current"]["regime"]
        bad = c.put("/api/macro/map", json={"items": [{"id": "x"}]})
        assert bad.status_code == 400
        assert c.put("/api/macro/map", json={"items": m["items"][:3]}).json()["count"] == 3
        assert c.get("/api/macro/map").json()["custom"] is True
        c.delete("/api/macro/map")
