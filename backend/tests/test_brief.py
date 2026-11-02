"""BRIEF: pure sections + generation (SIM), files in the coverage root, auto once a day after the configured time."""
import datetime as dt
import json

from fastapi.testclient import TestClient

from app import brief as B


def _bars(closes):
    t0 = int(dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc).timestamp())
    return [{"time": t0 + i * 86400, "open": c, "high": c, "low": c, "close": c, "volume": 1} for i, c in enumerate(closes)]


def test_sections():
    r = B.market_row("米10年金利", "TVC:US10Y", "bp", _bars([4.0] * 20 + [4.10, 4.25]))
    assert round(r["d1"]) == 15 and round(r["w1"]) == 25
    p = B.market_row("TOPIX", "TVC:TOPIX", "pct", _bars([100.0] * 21 + [110.0]))
    assert abs(p["d1"] - 10) < 1e-9 and abs(p["m1"] - 10) < 1e-9 and p["w1"] is not None
    assert B.market_row("x", "X", "pct", [])["error"]
    # ニュース・開示: coverage hits first (newest first), then keyword hits; filings by importance of the kind
    items = [{"title": "kw old", "keywords": ["利上げ"], "tickers": [], "published": "2026-11-01T01:00:00Z"},
             {"title": "cov", "keywords": [], "tickers": ["6857"], "published": "2026-11-01T00:00:00Z"},
             {"title": "kw new", "keywords": ["関税"], "tickers": [], "fetched": "2026-11-01T02:00:00Z"}]
    fil = [{"ticker": "6857", "kind": "臨時報告書", "desc": "a", "at": "2026-11-01T15:00"},
           {"ticker": "6857", "kind": "大量保有", "desc": "b", "at": "2026-11-01T09:00"}]
    inf = B.info_section(items, fil)
    assert [h["title"] for h in inf["hits"]] == ["cov", "kw new", "kw old"] and [f["kind"] for f in inf["filings"]] == ["大量保有", "臨時報告書"]
    assert len(B.info_section(items * 10, fil, n=5)["hits"]) == 5
    f = B.factor_section([{"factor": "バリュー", "1W": 2.0}, {"factor": "サイズ", "1W": -1.0}, {"factor": "ベータ", "1W": 0.5},
                          {"factor": "モメンタム", "1W": -3.0}, {"factor": "ボラ", "1W": None}])
    assert [x["factor"] for x in f["best"]] == ["バリュー", "ベータ", "サイズ"] and f["worst"][0]["factor"] == "モメンタム"
    snap = {"rows": [{"symbol": "TSE:6857", "direction": "LONG", "conviction": 3, "size_pct": 2.0, "flags": ["a"]},
                     {"symbol": "TSE:3436", "direction": "SHORT", "conviction": 2, "size_pct": 1.0},
                     {"symbol": "TSE:7203", "direction": "NEUTRAL", "conviction": 0, "size_pct": 0}],
            "quadrant": {"q": 1, "name": "回復"}, "book": {"gross_pct": 3.0, "net_pct": 1.0}, "errors": {"scanner": "x"},
            "sectors": {"JP17": [{"label": "電機・精密", "quadrant_ja": "主導"}, {"label": "銀行", "quadrant_ja": "減速"}],
                        "US11": [{"label": "Tech", "quadrant_ja": "主導"}]}}
    a = B.auto_section(snap, [{"symbol": "TSE:6857", "what": "verdict", "from": "NEUTRAL c0", "to": "LONG c3"},
                              {"symbol": "TSE:9999", "what": "new", "from": None, "to": "NEUTRAL c0"}])
    assert a["n_changes"] == 1
    assert a["longs"][0]["symbol"] == "TSE:6857" and a["shorts"][0]["symbol"] == "TSE:3436" and a["errors"] == ["scanner"]
    assert a["sectors"]["JP17"] == {"主導": ["電機・精密"], "減速": ["銀行"]}
    rows = [{"ticker": "6857", "id": "FY2027-2Q", "label": "FY2027 2Q", "date": "2026-11-01", "days": -1, "status": "発表済"},
            {"ticker": "3436", "id": "FY2026-3Q", "label": "FY2026 3Q", "date": "2026-11-03", "days": 1, "status": "確定"}]
    e = B.earnings_section(rows, {"6857": {"reaction_day": "2026-11-02", "r1": 0.09, "x1": 0.08, "vol_ratio": 5.0, "kind": "既知"}},
                           {"6857": {"avg_abs": 0.04, "n": 8}}, {"6857": {"direction": "LONG", "conviction": 3}})
    assert e["tomorrow"][0]["ticker"] == "3436" and abs(e["recent"][0]["reaction"]["vs_typical"] - 2.0) < 1e-9
    assert e["recent"][0]["auto"] == "LONG c3"
    up = {"6857": {"date": "2026-11-11", "days": 9, "status": "確定", "label": "FY2027 2Q"}, "3436": {"date": "2026-11-06", "days": 4, "status": "予定"}}
    pf = B.portfolio_section([{"symbol": "TSE:6857"}, {"symbol": "TSE:3436"}, {"symbol": "TSE:7203"}],
                             {"TSE:6857": 6_000_000.0, "TSE:3436": -2_000_000.0, "TSE:7203": 2_000_000.0}, up, {"6857": {"avg_abs": 0.05}})
    by = {r["ticker"]: r for r in pf["rows"]}
    assert set(by) == {"6857", "3436"} and abs(by["6857"]["weight_pct"] - 60) < 1e-9 and abs(by["6857"]["swing_pct_of_gross"] - 3.0) < 1e-9
    assert by["3436"]["swing_pct_of_gross"] is None and pf["unknown"] == 1 and abs(pf["total_swing_pct"] - 3.0) < 1e-9
    m = B.margin_section([{"ticker": "6857", "symbol": "TSE:6857", "name": "アドバンテスト"}, {"ticker": "AAPL", "symbol": "NASDAQ:AAPL"}],
                         lambda code: [{"date": "2026-10-24", "long": 100.0, "short": 50.0}, {"date": "2026-10-31", "long": 150.0, "short": 50.0}])
    assert m["rows"][0]["ratio"] == 3.0 and m["rows"][0]["ratio_prev"] == 2.0 and abs(m["rows"][0]["long_chg_pct"] - 50) < 1e-9
    md = B.render_md({"date": "2026-11-02", "generated_at": "2026-11-02T07:30:00", "markets": [r, p], "factors": f, "auto": a,
                      "earnings": e, "portfolio": pf, "margin": m, "health": {"provider": "sim", "demo": True, "items": {"データ": "sim"}}})
    for h in ("# 朝のブリーフ 2026-11-02", "## 市場", "## マクロ局面", "## ファクター", "## 三位一体 AUTO", "## 決算", "## ポートフォリオの決算リスク", "## 信用残", "DEMO"):
        assert h in md
    assert "+15bp" in md and "通常の 2.0 倍" in md and "セクター回転 日本（TOPIX-17）: 主導: 電機・精密 / 減速: 銀行" in md


def test_generate_saves_files_and_auto_once_a_day(tmp_path, monkeypatch):
    from app.main import app
    from app import api_brief as AB
    from app import api_trinity

    tdir_ = tmp_path / "trinity"
    (tdir_ / "history").mkdir(parents=True)
    monkeypatch.setattr(api_trinity, "tdir", lambda: tdir_)      # never touch the shared AUTO snapshots
    tdir = api_trinity.tdir

    with TestClient(app) as c:
        items = [{"ticker": "6857", "symbol": "TSE:6857", "name": "アドバンテスト", "gics_group": "4530 | 半導体", "fye_month": 3}]
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector", "root": str(tmp_path / "Cov")}}})
        c.put("/api/store/portfolio", json={"value": [{"id": "p1", "symbol": "TSE:6857", "qty": 100, "cost": 1}]})
        c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})
        today = dt.date.today()
        snap = {"rows": [{"symbol": "TSE:6857", "direction": "LONG", "conviction": 2, "size_pct": 1.5, "f": {"score": 3.6}}], "quadrant": {"q": 2, "name": "過熱"},
                "generated_at": f"{today}T07:00:00", "errors": {}}
        (tdir() / "latest.json").write_text(json.dumps(snap), encoding="utf-8")
        prev = {**snap, "rows": [{"symbol": "TSE:6857", "direction": "NEUTRAL", "conviction": 0, "size_pct": 0, "f": {"score": 3.0}}]}
        (tdir() / "history" / f"{today - dt.timedelta(days=1)}.json").write_text(json.dumps(prev), encoding="utf-8")
        r = c.post("/api/brief/generate").json()
        b = r["brief"]
        assert b["health"]["demo"] is True and len(b["markets"]) == len(B.MARKETS) and b["date"] == today.isoformat()
        assert b["auto"]["changes"][0]["to"] == "LONG c2"                      # vs the previous day's snapshot
        assert b["info"] == {"hits": [], "filings": []}                           # TOP has fetched nothing here
        assert (tmp_path / "Cov" / "_terminal" / "briefs" / f"{today}.md").read_text(encoding="utf-8").startswith(f"# 朝のブリーフ {today}")
        assert "## ニュース・開示（TOP）" in (tmp_path / "Cov" / "_terminal" / "briefs" / f"{today}.md").read_text(encoding="utf-8")
        assert c.get("/api/brief").json()["dates"][0] == today.isoformat() and c.get(f"/api/brief/{today}").status_code == 200
        assert c.get("/api/brief/2001-01-01").status_code == 404
        assert c.put("/api/brief/config", json={"time": "25:00"}).status_code == 400
        assert c.put("/api/brief/config", json={"time": "06:45", "auto": True}).json()["time"] == "06:45"
        # auto: not before the configured time, once a day
        (tmp_path / "Cov" / "_terminal" / "briefs" / f"{today}.json").unlink()
        early = dt.datetime.combine(today, dt.time(6, 0))
        import asyncio
        assert asyncio.run(AB.maybe_auto(None, early)) is None
        late = dt.datetime.combine(today, dt.time(7, 0))
        assert asyncio.run(AB.maybe_auto(None, late))["date"] == today.isoformat()
        assert asyncio.run(AB.maybe_auto(None, late)) is None
