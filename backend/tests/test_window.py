from fastapi.testclient import TestClient

from app import window as W


def bars(dates):
    import datetime as dt
    return [{"time": int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp()), "close": 1.0} for d in dates]


def test_cut_series_aligns_by_date_not_count():
    jp = bars(["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"])
    us = bars(["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-06", "2026-10-07"])
    out, cut = W.cut_series({"JP": jp, "US": us}, 2, "JP")
    assert cut == "2026-10-05"
    assert [W.bar_date(b) for b in out["US"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    same, c0 = W.cut_series({"JP": jp}, 0, "JP")
    assert same["JP"] is jp and c0 == "2026-10-07"
    assert W.cut_closes({"A": {"2026-10-01": 1, "2026-10-09": 2}}, "2026-10-05") == {"A": {"2026-10-01": 1}}


def test_asof_endpoints_sim():
    from app.main import app

    with TestClient(app) as c:
        b0 = c.get("/api/analytics/beta", params={"symbol": "TSE:7203", "benchmark": "TVC:TOPIX", "bars": 250}).json()
        b1 = c.get("/api/analytics/beta", params={"symbol": "TSE:7203", "benchmark": "TVC:TOPIX", "bars": 250, "end_offset": 120}).json()
        assert b0["beta"] != b1["beta"]
        r = c.get("/api/insight/rrg", params={"universe": "JP17", "end_weeks": 26}).json()
        assert r["asof"] and len(r["rows"]) == 17
        p = c.post("/api/framework/pair", json={"long": "TSE:7203", "short": "TSE:7267", "end_offset": 60, "sigma_window": 42}).json()
        assert p["asof"] and p["pair_sigma_pct"] > 0
