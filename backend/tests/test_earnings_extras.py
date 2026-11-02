"""Earnings alerts, daily calendar backups + restore, quarter documents (list / open / transcript import)."""
import datetime as dt
import json

from fastapi.testclient import TestClient


def _setup(c, tmp_path, tickers=(("6857", "アドバンテスト"),)):
    items = [{"ticker": t, "symbol": f"TSE:{t}", "name": n, "gics_group": "4530 | 半導体", "fye_month": 3} for t, n in tickers]
    c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector", "root": str(tmp_path / "Cov")}}})
    c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})


def test_alerts_tomorrow_once_and_big_reactions(tmp_path):
    from app.main import app
    from app import api_earnings as AE

    with TestClient(app) as c:
        _setup(c, tmp_path, (("6857", "アドバンテスト"), ("3436", "SUMCO")))
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        q = c.get("/api/earnings/6857").json()["next"]
        c.put(f"/api/earnings/6857/{q['id']}", json={"earnings_date": tomorrow})          # 手入力 → alert
        cal = AE.load()
        due = AE.alerts_due(cal)
        assert [(x["ticker"], x["kind"]) for x in due] == [("6857", "明日決算")]
        assert AE.alerts_due(cal) == []                                                    # once a day
        # big reaction: ≥ 2× the typical move on the latest trading day, with ≥ 4 past reactions
        res = {"summary": {"n": 6, "avg_abs": 0.04}, "last_day": "2026-11-02",
               "rows": [{"id": "FY2027-2Q", "label": "FY2027 2Q", "reaction_day": "2026-11-02", "r1": 0.11, "x1": 0.09},
                        {"id": "FY2027-1Q", "label": "FY2027 1Q", "reaction_day": "2026-08-07", "r1": 0.2, "x1": 0.2}]}
        big = AE.big_reactions(cal, "6857", res)
        assert len(big) == 1 and abs(big[0]["times"] - 2.25) < 1e-9 and AE.big_reactions(cal, "6857", res) == []
        assert AE.big_reactions(cal, "3436", {**res, "summary": {"n": 3, "avg_abs": 0.04}}) == []    # too few past reactions


def test_daily_backup_and_restore(tmp_path):
    from app.main import app
    from app import api_earnings as AE

    with TestClient(app) as c:
        _setup(c, tmp_path)
        q = c.get("/api/earnings/6857").json()["next"]
        c.put(f"/api/earnings/6857/{q['id']}", json={"notes": "バックアップ前のメモ"})
        bk = c.get("/api/earnings/backups").json()["files"]
        assert bk and bk[0]["name"] == f"calendar-{dt.date.today()}.json"
        # the backup holds the state before today's first change; restore it
        c.put(f"/api/earnings/6857/{q['id']}", json={"notes": "壊してしまったメモ"})
        r = c.post("/api/earnings/backups/restore", json={"name": bk[0]["name"]}).json()
        assert r["restored"] == bk[0]["name"]
        names = [f["name"] for f in c.get("/api/earnings/backups").json()["files"]]
        assert any(n.startswith("calendar-before-restore-") for n in names)
        assert any(x["what"] == "復元" for x in c.get("/api/earnings/log").json()["log"])
        assert c.post("/api/earnings/backups/restore", json={"name": "../calendar.json"}).status_code == 404
        assert json.loads(AE.cal_path().read_text(encoding="utf-8"))["companies"]["6857"]


def test_quarter_documents_and_transcript_import(tmp_path):
    from app.main import app

    with TestClient(app) as c:
        _setup(c, tmp_path)
        q = c.get("/api/earnings/6857").json()["next"]
        assert c.get(f"/api/earnings/6857/{q['id']}/files").json()["exists"] is False
        folder = tmp_path / "Cov" / "x"
        from pathlib import Path
        folder = Path(c.post(f"/api/earnings/6857/{q['id']}/folder").json()["path"])
        (folder / "決算短信.pdf").write_bytes(b"%PDF-1.4")
        (folder / "説明会_書き起こし.txt").write_bytes("当社の受注は堅調に推移しました。HBM 向けのテスタ需要が拡大しています。".encode("cp932"))
        (folder / "~$model.xlsx").write_text("lock")
        files = c.get(f"/api/earnings/6857/{q['id']}/files").json()["files"]
        assert [f["name"] for f in files] == ["決算短信.pdf", "説明会_書き起こし.txt"]           # notes.md / lock files hidden
        assert c.post(f"/api/earnings/6857/{q['id']}/files/open", json={"name": "../notes.md"}).status_code == 404
        assert c.post(f"/api/earnings/6857/{q['id']}/files/transcript", json={"name": "決算短信.pdf"}).status_code == 400
        r = c.post(f"/api/earnings/6857/{q['id']}/files/transcript", json={"name": "説明会_書き起こし.txt"}).json()
        assert r["symbol"] == "TSE:6857" and r["period"] == q["label"] and r["encoding"] == "cp932"
        items = c.get("/api/transcripts/TSE:6857").json()["items"]
        assert items[-1]["period"] == q["label"] and items[-1]["title"] == "説明会_書き起こし.txt" and items[-1]["chars"] > 20
