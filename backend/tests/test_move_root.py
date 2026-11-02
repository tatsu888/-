"""COV: move the whole coverage root (e.g. to OneDrive) — copy → verify → switch; the old folder is kept."""
from pathlib import Path

from fastapi.testclient import TestClient


def test_move_root_copies_verifies_and_switches(tmp_path):
    from app.main import app

    with TestClient(app) as c:   # tickers not used by other tests (the Excel library is process-wide)
        items = [{"ticker": "6920", "symbol": "TSE:6920", "name": "レーザーテック", "gics_group": "4530 | 半導体・半導体製造装置", "fye_month": 3},
                 {"ticker": "4062", "symbol": "TSE:4062", "name": "イビデン", "gics_group": "4530 | 半導体・半導体製造装置", "fye_month": 12}]
        old = tmp_path / "Local" / "Coverage"
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector", "root": str(old)}}})
        c.post("/api/coverage/folders", json={"apply": True})
        model = Path(c.post("/api/coverage/6920/excel").json()["created"])
        c.post("/api/earnings/refresh", json={"jpx": False, "tradingview": False})
        q = next(x for x in c.get("/api/earnings/6920").json()["quarters"] if x["state"] == "期中")
        c.put(f"/api/earnings/6920/{q['id']}", json={"notes": "OneDrive に移す前のメモ"})
        qdir = Path(c.post(f"/api/earnings/6920/{q['id']}/folder").json()["path"])
        (old / "~$lock.xlsx").write_text("x")                      # an Office lock file is never copied
        fid = next(f["id"] for f in c.get("/api/excel/files").json()["files"] if f["name"] == model.name)
        c.put("/api/store/excel_links", json={"value": {"TSE:6920": [fid]}})
        new = tmp_path / "OneDrive" / "Coverage"
        # guard rails
        assert c.post("/api/coverage/move_root", json={"to": "relative/path"}).status_code == 400
        assert c.post("/api/coverage/move_root", json={"to": str(old / "inside")}).status_code == 400
        # PREVIEW writes nothing
        plan = c.post("/api/coverage/move_root", json={"to": str(new)}).json()
        # 2 markers + model + calendar + its daily backup + notes.md (the lock file is skipped)
        assert plan["apply"] is False and plan["files"] == 6 and plan["n_conflicts"] == 0 and not new.exists()
        assert "_terminal" in plan["top"] and any(t.startswith("GICS4530_") for t in plan["top"])
        # APPLY: copy → verify → switch
        res = c.post("/api/coverage/move_root", json={"to": str(new), "apply": True}).json()
        assert res["switched"] and res["n_errors"] == 0 and res["n_mismatch"] == 0
        rel = model.relative_to(old)
        assert (new / rel).read_bytes() == model.read_bytes() and model.exists()           # the old folder is kept
        assert not (new / "~$lock.xlsx").exists()
        assert (new / qdir.relative_to(old) / "notes.md").read_text(encoding="utf-8").strip().endswith("OneDrive に移す前のメモ")
        lst = c.get("/api/coverage").json()
        assert lst["config"]["root_resolved"] == str(new.resolve())
        # the calendar (and its notes) now lives in the new root
        assert (new / "_terminal" / "earnings" / "calendar.json").is_file()
        assert next(x for x in c.get("/api/earnings/6920").json()["quarters"] if x["id"] == q["id"])["notes"] == "OneDrive に移す前のメモ"
        # the manual Excel link follows the file; the stock page sees the model in the new root
        link = c.get("/api/store/excel_links").json()["value"]["TSE:6920"][0]
        f = next(f for f in c.get("/api/excel/files").json()["files"] if f["id"] == link)
        assert Path(f["root"]).resolve() == new.resolve()
        # a destination holding a different file with the same name is refused
        other = tmp_path / "Other"
        (other / rel).parent.mkdir(parents=True)
        (other / rel).write_bytes(b"different")
        r = c.post("/api/coverage/move_root", json={"to": str(other), "apply": True})
        assert r.status_code == 409 and lst["config"]["root_resolved"] == c.get("/api/coverage").json()["config"]["root_resolved"]


def test_move_root_from_the_default_root_remaps_excel_links(tmp_path):
    """Default root = <first Excel folder>/Coverage: after the move the file ids change and the links follow."""
    from app.main import app

    with TestClient(app) as c:
        items = [{"ticker": "6787", "symbol": "TSE:6787", "name": "メイコー", "gics_group": "4520 | テクノロジー", "fye_month": 3}]
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "ticker"}}})
        model = Path(c.post("/api/coverage/6787/excel").json()["created"])
        fid = next(f["id"] for f in c.get("/api/excel/files").json()["files"] if Path(f["root"], f["path"]).resolve() == model.resolve())
        c.put("/api/store/excel_links", json={"value": {"TSE:6787": [fid]}})
        new = tmp_path / "OneDrive" / "Coverage"
        res = c.post("/api/coverage/move_root", json={"to": str(new), "apply": True}).json()
        assert res["switched"] and res["links_remapped"] == 1
        link = c.get("/api/store/excel_links").json()["value"]["TSE:6787"][0]
        f = next(f for f in c.get("/api/excel/files").json()["files"] if f["id"] == link)
        assert Path(f["root"], f["path"]).resolve() == (new / model.relative_to(model.parents[1])).resolve()
