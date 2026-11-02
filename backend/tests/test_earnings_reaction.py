"""決算時の株価反応: reaction day (known / detected), market-adjusted moves, drift, and the API on real vs SIM data."""
import datetime as dt
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import earnings_reaction as R


def trading_days(start: dt.date, n: int) -> list[dt.date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def bars(days, spikes=None, moves=None, base=100.0):
    """Deterministic daily bars; spikes {date: volume multiple}, moves {date: return}."""
    out, px = [], base
    for k, d in enumerate(days):
        px *= 1 + (moves or {}).get(d, 0.001 * ((k % 5) - 2))
        vol = 1_000_000 * (1 + 0.05 * (k % 7)) * (spikes or {}).get(d, 1.0)
        t = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())
        out.append({"time": t, "open": px, "high": px, "low": px, "close": px, "volume": vol})
    return out


def test_reaction_day_for_known_dates_and_detection():
    days = trading_days(dt.date(2026, 1, 5), 120)
    ann = days[60]                                  # after-close announcement → reacts the next day
    intraday = days[80]                             # intraday announcement → reacts the same day
    b = bars(days, spikes={days[61]: 5.0, intraday: 4.0}, moves={days[61]: 0.08, intraday: -0.05})
    ds, cl, vo = R.daily(b)
    assert R.reaction_at_known(ds, vo, ann.isoformat()) == (61, "引け後")
    assert R.reaction_at_known(ds, vo, intraday.isoformat()) == (80, "場中・寄り前")
    assert R.reaction_at_known(ds, vo, days[100].isoformat()) == (101, "引け後（仮定）")      # no spike at all
    sat = days[60] + dt.timedelta(days=(5 - days[60].weekday()) % 7 or 7)
    i, timing = R.reaction_at_known(ds, vo, sat.isoformat())
    assert timing == "休日の発表" and ds[i] > sat.isoformat()
    # unknown date: the spike within ±10 days of the estimate, ≥ 7 days after the quarter end
    hit = R.detect(ds, vo, (days[61] - dt.timedelta(days=4)).isoformat(), days[30].isoformat())
    assert hit["reaction_day"] == days[61].isoformat() and hit["announce"] == ann.isoformat() and hit["vol_ratio"] > 4
    assert R.detect(ds, vo, days[61].isoformat(), days[62].isoformat()) is None                 # not before the quarter end + 7
    assert R.detect(ds, vo, days[40].isoformat(), days[30].isoformat()) is None                 # no spike near the estimate
    mkt = {d: 1000.0 * (1.01 if d >= days[61].isoformat() else 1.0) for d in ds}
    m = R.metrics(ds, cl, vo, 61, mkt)
    assert abs(m["r1"] - 0.08) < 1e-9 and abs(m["x1"] - (0.08 - 0.01)) < 1e-9 and m["vol_ratio"] > 4
    assert m["r5"] is not None and m["drift"] is not None
    s = R.summarize([{**m, "kind": "既知"}, {**R.metrics(ds, cl, vo, 80, mkt), "kind": "検出"}])
    assert s["n"] == 2 and s["up"] == 1 and s["down"] == 1 and s["basis"] == "対市場" and s["detected"] == 1
    assert abs(s["avg_abs"] - (0.07 + 0.05) / 2) < 1e-9


def _setup(c, tmp_path):
    items = [{"ticker": "6857", "symbol": "TSE:6857", "name": "アドバンテスト", "gics_group": "4530 | 半導体", "fye_month": 3}]
    c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector", "root": str(tmp_path / "Cov")}}})
    c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})
    v = c.get("/api/earnings/6857").json()
    past = [q for q in v["quarters"] if q["earnings"]["date"] < dt.date.today().isoformat()]
    target = past[-1]                                   # the latest reported quarter: only an estimate so far
    est = dt.date.fromisoformat(target["earnings"]["date"])
    days = trading_days(dt.date.today() - dt.timedelta(days=760), 600)
    days = [d for d in days if d < dt.date.today()]
    react = next(d for d in days if d > est + dt.timedelta(days=2))
    return target, days, react


def test_reactions_api_detects_on_real_data_and_never_writes_on_sim(tmp_path, monkeypatch):
    from app.main import app
    from app.state import S

    with TestClient(app) as c:
        target, days, react = _setup(c, tmp_path)
        stock = bars(days, spikes={react: 6.0}, moves={react: 0.09})
        topix = bars(days, base=2800.0)

        async def fake_history(symbol, interval, n, source=None):
            return topix if symbol == "TVC:TOPIX" else stock

        monkeypatch.setattr(S, "history", fake_history)
        # SIM: the reaction is shown, but nothing is written to the calendar
        monkeypatch.setattr(S, "provider", lambda source=None: _prov("sim"))
        r = c.get("/api/earnings/6857/reactions").json()
        row = next(x for x in r["rows"] if x["id"] == target["id"])
        assert r["real"] is False and row["kind"] == "検出" and row["reaction_day"] == react.isoformat()
        assert next(q for q in c.get("/api/earnings/6857").json()["quarters"] if q["id"] == target["id"])["earnings"]["status"] == "推定"
        # real data: the detected date replaces the estimate (status 検出, logged) and the typical move is stored
        monkeypatch.setattr(S, "provider", lambda source=None: _prov("tradingview"))
        r = c.get("/api/earnings/6857/reactions").json()
        row = next(x for x in r["rows"] if x["id"] == target["id"])
        prev = days[days.index(react) - 1].isoformat()
        assert r["real"] and r["detected_now"] >= 1 and row["announce"] == prev and abs(row["r1"] - 0.09) < 1e-6
        q = next(q for q in c.get("/api/earnings/6857").json()["quarters"] if q["id"] == target["id"])
        assert q["earnings"]["status"] == "検出" and q["earnings"]["date"] == prev and q["state"] == "発表済"
        assert "出来高の急増" in q["earnings"]["source"] and "tradingview" in q["earnings"]["source"]
        assert any(x["what"] == "決算日" and x["to"] == f"{prev} 検出" for x in c.get("/api/earnings/log").json()["log"])
        cov = {x["ticker"]: x for x in c.get("/api/coverage").json()["items"]}
        assert cov["6857"]["earnings"]["reaction"]["n"] >= 1 and cov["6857"]["earnings"]["reaction"]["provider"] == "tradingview"
        # the same quarter next year is now estimated from the detected date (前年同期 + 364)
        nxt = next(q for q in c.get("/api/earnings/6857").json()["quarters"] if q["id"] == f"FY{target['fy'] + 1}-{target['q']}Q")
        assert nxt["earnings"]["status"] == "推定" and prev in nxt["earnings"]["source"]
        # market evidence does not expire on the next mechanical refresh
        c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})
        assert next(q for q in c.get("/api/earnings/6857").json()["quarters"] if q["id"] == target["id"])["earnings"]["status"] == "検出"


async def _prov_coro(name):
    return SimpleNamespace(name=name)


def _prov(name):
    return _prov_coro(name)


def test_calendar_ics(tmp_path):
    from app.main import app

    with TestClient(app) as c:
        items = [{"ticker": "AAPL", "symbol": "NASDAQ:AAPL", "name": "Apple, Inc.; long name to force folding of the line", "fye_month": 9}]
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "ticker", "root": str(tmp_path / "Cov")}}})
        c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})
        r = c.get("/api/earnings/calendar.ics", params={"days": 200})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
        body = r.content.decode("utf-8")
        assert body.startswith("BEGIN:VCALENDAR\r\n") and body.rstrip().endswith("END:VCALENDAR") and "BEGIN:VEVENT" in body
        assert r"Apple\, Inc.\; long" in body.replace("\r\n ", "")          # escaped, and unfolded it reads back
        assert all(len(line.encode("utf-8")) <= 75 for line in body.split("\r\n"))
        assert "（推定）" in body
        assert "BEGIN:VEVENT" not in c.get("/api/earnings/calendar.ics", params={"days": 200, "estimates": False}).content.decode()
