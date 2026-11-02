import random

from fastapi.testclient import TestClient

from app import flows as FW


def mk(n, drift, vol_up=1.0, seed=1):
    rng = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        r = drift + rng.gauss(0, 0.005)
        p *= 1 + r
        hi, lo = p * 1.01, p * 0.99
        close = hi - 0.002 * p if drift > 0 else lo + 0.002 * p   # closes near the high in an uptrend (buying pressure)
        out.append({"time": 1_600_000_000 + i * 86400, "open": p, "high": hi, "low": lo, "close": close,
                    "volume": 1e6 * (vol_up if i >= n - 21 else 1)})
    return out


def test_metrics_inflow_vs_outflow():
    bench = mk(300, 0.0, seed=9)
    up = FW.metrics(mk(300, 0.004, vol_up=2.0), bench)
    dn = FW.metrics(mk(300, -0.004, vol_up=2.0, seed=2), bench)
    assert up["flow"] == "流入" and up["cmf"] > 0.5 and up["value_ratio"] > 1.5 and up["rs"] > 0
    assert dn["flow"] == "流出" and dn["cmf"] < -0.5


def test_creations_from_recorded_shares():
    hist = {"2026-09-01": {"X": 100.0}, "2026-09-24": {"X": 110.0}, "2026-10-01": {"X": 120.0}}
    c = FW.creations(hist, "X", 50.0)
    assert c["w1"] == (120 - 110) * 50 and c["m1"] == (120 - 100) * 50 and c["days_recorded"] == 3
    assert FW.creations({}, "X", 50.0)["w1"] is None


def test_summary_rules():
    rows = {s: {"flow_score": 0.6} for s in FW.RISK_ON} | {s: {"flow_score": -0.4} for s in FW.RISK_OFF}
    out = {r["rule"]: r["reading"] for r in FW.summarize(rows)}
    assert out["リスク資産 vs 安全資産"].startswith("リスクオン")


def test_flows_api_sim():
    from app.main import app

    with TestClient(app) as c:
        for lens in ("ASSET", "COUNTRY", "SECTOR_JP", "STYLE_US"):
            r = c.get("/api/flows", params={"lens": lens, "window": 21, "end_offset": 5}).json()
            assert r["rows"] and r["asof"] and any("flow_score" in x for x in r["rows"])
        assert c.get("/api/flows", params={"lens": "ASSET"}).json()["summary"]
