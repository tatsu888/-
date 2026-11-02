import datetime as dt
import io

from fastapi.testclient import TestClient

from app import earnings as E

D = dt.date


def test_fiscal_labels_standard_and_atlas():
    # standard 決算期 naming (default)
    assert E.fy_of(D(2026, 3, 31), 12) == (2026, 1)          # 2026年12月期 第1四半期
    assert E.fy_of(D(2025, 12, 31), 12) == (2025, 4)         # 2025年12月期 本決算
    assert E.fy_of(D(2026, 6, 30), 3) == (2027, 1)           # 2027年3月期 第1四半期
    assert E.fy_of(D(2026, 7, 31), 1) == (2027, 2)           # 2027年1月期 第2四半期
    # ATLAS pages (as found in Notion) differ only for 12月決算
    assert E.fy_of(D(2026, 3, 31), 12, "start_plus_1") == (2027, 1)
    assert E.fy_of(D(2026, 6, 30), 3, "start_plus_1") == (2027, 1)
    for conv in ("end", "start_plus_1"):
        for fye in (3, 12, 1, 6):
            for e in (D(2026, 3, 31), D(2026, 6, 30), D(2026, 9, 30), D(2026, 12, 31), D(2027, 1, 31), D(2026, 7, 31)):
                if (e.month - fye) % 3 == 0:
                    fy, q = E.fy_of(e, fye, conv)
                    assert E.quarter_end_of(fy, q, fye, conv) == e
    assert E.labels(2026, 4, 12)["label_ja"] == "2026年12月期 本決算"
    assert E.labels(2027, 2, 3)["label_ja"] == "2027年3月期 第2四半期"


def test_quarters_around_and_release_mapping():
    qs = E.quarters_around(D(2026, 11, 2), 3, 8, 4)
    assert len(qs) == 13 and qs[8]["id"] == "FY2027-3Q" and qs[8]["period_end"] == "2026-12-31"
    assert E.quarter_for_release(D(2026, 10, 28), 3)[:2] == (2027, 2)
    assert E.quarter_for_release(D(2026, 5, 12), 3)[:2] == (2026, 4)
    assert E.quarter_for_release(D(2026, 10, 3), 3)[:2] == (2027, 1)      # too soon after Sep 30 → previous quarter
    assert E.quarter_for_release(D(2026, 11, 10), 3, q_hint=2)[:2] == (2027, 2)


def test_parse_jpx_rows_with_title_rows_and_variants():
    rows = [["決算発表予定日一覧（2026年11月）"], [],
            ["決算発表予定日", "コード", "会社名", "決算期末", "業種名", "種別", "市場区分"],
            [dt.datetime(2026, 11, 12), 6857, "アドバンテスト", "2027年3月期", "電気機器", "第２四半期", "プライム"],
            ["2026/11/12", "3436", "ＳＵＭＣＯ", "12月", "金属製品", "第３四半期", "プライム"],
            ["2026/11/14", "456A", "HUMAN MADE", "1月", "小売業", "第３四半期", "グロース"],
            ["２０２６/１１/１３", "７２０３", "トヨタ自動車", "３月", "輸送用機器", "第２四半期", "プライム"],
            ["注記", None, None, None, None, None, None]]
    recs = E.parse_jpx_rows(rows)
    assert [r["ticker"] for r in recs] == ["6857", "3436", "456A", "7203"]
    assert recs[3]["date"] == "2026-11-13" and recs[3]["fye_month"] == 3 and recs[3]["q"] == 2      # full-width digits
    assert recs[0] == {"ticker": "6857", "date": "2026-11-12", "name": "アドバンテスト", "q": 2, "fye_month": 3, "fye_year": 2027}
    assert recs[1]["fye_month"] == 12 and recs[1]["q"] == 3 and recs[1]["fye_year"] is None


def test_resolution_priority_and_estimates():
    today = D(2026, 11, 2)
    q = {"id": "FY2027-2Q", "fy": 2027, "q": 2, "period_start": "2026-07-01", "period_end": "2026-09-30"}
    c_jpx = {"date": "2026-11-12", "status": "確定", "source": "JPX", "fetched": "t2"}
    c_tv = {"date": "2026-11-13", "status": "予定", "source": "TV", "fetched": "t2"}
    assert E.resolve(q, [c_tv, c_jpx], None, 40, today)["source"] == "JPX"
    assert E.resolve(q, [c_tv], None, 40, today)["status"] == "予定"
    past = E.resolve(q, [c_jpx], None, 40, D(2026, 11, 20))
    assert past["status"] == "発表済"
    pinned = {**q, "earnings": {"date": "2026-11-20", "status": "手入力", "source": "手入力"}}
    assert E.resolve(pinned, [c_jpx], None, 40, today)["date"] == "2026-11-20"
    prev = {"earnings": {"date": "2025-11-11", "status": "発表済"}}
    est = E.resolve(q, [], prev, 40, today)
    assert est["status"] == "推定" and est["date"] == "2026-11-10" and "前年同期" in est["source"]
    lag = E.resolve(q, [], None, 40, today)
    assert lag["date"] == "2026-11-09" and lag["status"] == "推定"     # Sep 30 + 40 = Nov 9 (Mon)
    hist = [{"q": 1, "period_end": "2026-06-30", "earnings": {"date": "2026-08-05", "status": "発表済"}},
            {"q": 2, "period_end": "2025-09-30", "earnings": {"date": "2025-11-07", "status": "発表済"}},
            {"q": 4, "period_end": "2026-03-31", "earnings": {"date": "2026-05-12", "status": "発表済"}}]
    assert E.typical_lag(hist, 2) == 37          # median of the Q1–Q3 lags 36 and 38
    assert E.typical_lag(hist, 4) == 45          # one sample only → default


def jpx_xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_earnings_api_end_to_end(tmp_path):
    from app.main import app

    from app.api_earnings import cal_path
    cal_path().unlink(missing_ok=True)   # fresh earnings calendar for this test
    today = dt.date.today()
    with TestClient(app) as c:
        items = [{"ticker": "6857", "symbol": "TSE:6857", "name": "アドバンテスト", "gics_group": "4530 | 半導体", "fye_month": 3},
                 {"ticker": "3436", "symbol": "TSE:3436", "name": "SUMCO", "gics_group": "4530 | 半導体", "fye_month": 3}]  # Notion says 3 (wrong)
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector", "root": str(tmp_path / "Cov")}}})
        # an official schedule ~3 weeks ahead: 6857 reports the quarter that ended before it; SUMCO is a 12月決算 company
        d1 = today + dt.timedelta(days=20)
        e1 = E.quarter_for_release(d1, 3)
        d2 = today + dt.timedelta(days=25)
        e2 = E.quarter_for_release(d2, 12)
        kind = {1: "第１四半期", 2: "第２四半期", 3: "第３四半期", 4: "本決算"}
        x = jpx_xlsx([["決算発表予定日", "コード", "会社名", "決算期末", "種別"],
                      [d1.isoformat().replace("-", "/"), "6857", "アドバンテスト", "3月", kind[e1[1]]],
                      [d2.isoformat().replace("-", "/"), "3436", "SUMCO", "12月", kind[e2[1]]]])
        r = c.post("/api/earnings/jpx/import", files={"file": ("kessan.xlsx", x)}).json()
        assert r["records"] == 2
        v = c.get("/api/earnings/6857").json()
        assert v["next"]["date"] == d1.isoformat() and v["next"]["status"] == "確定" and v["next"]["id"] == E.qid(e1[0], e1[1])
        s = c.get("/api/earnings/3436").json()
        assert s["company"]["fye_month"] == 12 and s["company"]["fye_source"].startswith("JPX")     # corrected from Notion's 3
        assert s["next"]["date"] == d2.isoformat()
        log = c.get("/api/earnings/log").json()["log"]
        assert any(x["what"].startswith("決算期末月") and x["ticker"] == "3436" and x["from"] == 3 and x["to"] == 12 for x in log)
        # a manual pin is never overwritten by the machine
        pin = (today + dt.timedelta(days=21)).isoformat()
        c.put(f"/api/earnings/6857/{v['next']['id']}", json={"earnings_date": pin, "notes": "前回は引け後"})
        c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})
        v2 = c.get("/api/earnings/6857").json()
        assert v2["next"]["date"] == pin and v2["next"]["status"] == "手入力"
        q = next(x for x in v2["quarters"] if x["id"] == v["next"]["id"])
        assert q["notes"] == "前回は引け後"
        # unpin → back to the official date
        c.put(f"/api/earnings/6857/{v['next']['id']}", json={"earnings_date": ""})
        assert c.get("/api/earnings/6857").json()["next"]["status"] == "確定"
        # COV and the calendar read the independent system
        cov = {x["ticker"]: x for x in c.get("/api/coverage").json()["items"]}
        assert cov["6857"]["earnings"]["next"] == d1.isoformat() and cov["6857"]["earnings"]["next_status"] == "確定"
        cal = c.get("/api/earnings/calendar").json()["rows"]
        assert {x["ticker"]: x for x in cal if x["status"] == "確定"}.keys() == {"6857", "3436"}
        # quarter folder in the stock's own folder
        f = c.post(f"/api/earnings/6857/{v['next']['id']}/folder").json()
        assert f["path"].endswith(v["next"]["id"].replace("-", "_")) and (tmp_path / "Cov").exists()
        # every quarter of the company exists as a "page" (8 back + current + 4 ahead)
        assert len(v2["quarters"]) == 13


def test_rekey_keeps_pages_and_archives_misaligned():
    qs = {q["id"]: q for q in E.quarters_around(D(2026, 11, 2), 3, 2, 1)}
    assert list(qs) == ["FY2027-1Q", "FY2027-2Q", "FY2027-3Q", "FY2027-4Q"]
    qs["FY2027-2Q"]["notes"] = "memo"
    new, dropped = E.rekey(qs, 12)                       # Notion said 3月, really 12月 → same period ends
    assert list(new) == ["FY2026-2Q", "FY2026-3Q", "FY2026-4Q", "FY2027-1Q"] and not dropped
    assert new["FY2026-3Q"]["notes"] == "memo" and new["FY2026-3Q"]["label_ja"] == "2026年12月期 第3四半期"
    atlas, _ = E.rekey(new, 12, "start_plus_1")
    assert atlas["FY2027-3Q"]["notes"] == "memo"          # ATLAS label of the same period
    none, dropped2 = E.rekey(qs, 2)                       # 2月決算: no common quarter ends → archived, not deleted
    assert not none and len(dropped2) == 4


def test_fye_correction_and_convention_keep_quarter_pages(tmp_path):
    from app.main import app

    from app.api_earnings import cal_path
    cal_path().unlink(missing_ok=True)
    today = dt.date.today()
    with TestClient(app) as c:
        items = [{"ticker": "3436", "symbol": "TSE:3436", "name": "SUMCO", "gics_group": "4530 | 半導体", "fye_month": 3}]
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector", "root": str(tmp_path / "Cov")}}})
        # first run: only the (wrong) Notion FYE is known → estimates on 3月決算 labels
        c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})
        v = c.get("/api/earnings/3436").json()
        assert v["company"]["fye_source"] == "Notion 銘柄マスタ" and all(x["earnings"]["status"] == "推定" for x in v["quarters"])
        cur = next(x for x in v["quarters"] if x["state"] == "期中")
        c.put(f"/api/earnings/3436/{cur['id']}", json={"notes": "注目: 300mm 稼働率"})
        # the official schedule says 12月決算 → the quarter pages are re-labelled, the note stays on its period
        d = today + dt.timedelta(days=30)
        e = E.quarter_for_release(d, 12)
        x = jpx_xlsx([["決算発表予定日", "コード", "会社名", "決算期末", "種別"],
                      [d.isoformat(), "3436", "SUMCO", "12月", {1: "第１四半期", 2: "第２四半期", 3: "第３四半期", 4: "本決算"}[e[1]]]])
        c.post("/api/earnings/jpx/import", files={"file": ("k.xlsx", x)})
        v2 = c.get("/api/earnings/3436").json()
        same = next(q for q in v2["quarters"] if q["period_end"] == cur["period_end"])
        assert same["notes"] == "注目: 300mm 稼働率" and same["label_ja"].endswith("12月期 " + same["label_ja"].split(" ")[-1])
        assert len({q["period_end"] for q in v2["quarters"]}) == len(v2["quarters"])      # no duplicate pages
        assert v2["next"]["date"] == d.isoformat() and v2["next"]["status"] == "確定"
        # a revised JPX date (same season) replaces the old record instead of competing with it
        x2 = jpx_xlsx([["決算発表予定日", "コード", "会社名", "決算期末", "種別"],
                       [(d + dt.timedelta(days=1)).isoformat(), "3436", "SUMCO", "12月", {1: "第１四半期", 2: "第２四半期", 3: "第３四半期", 4: "本決算"}[e[1]]]])
        c.post("/api/earnings/jpx/import", files={"file": ("k2.xlsx", x2)})
        assert c.get("/api/earnings/3436").json()["next"]["date"] == (d + dt.timedelta(days=1)).isoformat()
        # switching the FY label convention keeps notes and pins
        c.put("/api/earnings/config", json={"convention": "start_plus_1"})
        v3 = c.get("/api/earnings/3436").json()
        same3 = next(q for q in v3["quarters"] if q["period_end"] == cur["period_end"])
        assert same3["notes"] == "注目: 300mm 稼働率" and same3["fy"] == same["fy"] + 1
        c.put("/api/earnings/config", json={"convention": "end"})
        # a manual FYE override is logged and also keeps the pages
        c.put("/api/earnings/3436/fye", json={"month": 12})
        assert c.get("/api/earnings/3436").json()["company"]["fye_source"] == "手入力"


def test_tradingview_dates_are_stable_across_refreshes(tmp_path, monkeypatch):
    """Re-seeing the same TradingView date must not flip it to 推定 (or log a change) on the next run."""
    from app.main import app

    from app.api_earnings import cal_path
    from app.state import S
    cal_path().unlink(missing_ok=True)
    today = dt.date.today()
    nd, ld = today + dt.timedelta(days=10), today - dt.timedelta(days=80)

    def ts(d):
        return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())

    async def fake_scan(symbols, cols, fallback=None):
        return {s: {"earnings_release_next_date": ts(nd), "earnings_release_date": ts(ld)} for s in symbols}

    with TestClient(app) as c:
        monkeypatch.setattr(S.web, "scan_symbols", fake_scan)
        items = [{"ticker": "6857", "symbol": "TSE:6857", "name": "アドバンテスト", "fye_month": 3}]
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector", "root": str(tmp_path / "Cov")}}})
        for _ in range(3):
            r = c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": True}).json()
            v = c.get("/api/earnings/6857").json()
            assert v["next"]["date"] == nd.isoformat() and v["next"]["status"] == "予定" and v["next"]["source"] == "TradingView（次回）"
            assert v["last"]["date"] == ld.isoformat()
        assert r["n_changes"] == 0
        # a refresh without TradingView (e.g. after a JPX upload) keeps TradingView's last view
        c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})
        assert c.get("/api/earnings/6857").json()["next"]["status"] == "予定"
