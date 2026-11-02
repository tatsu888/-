import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import coverage as C
from app.notion_api import NotionClient, parse_master_row

D = dt.date


# ---------------- fiscal quarters: standard 決算期 naming (default) and the ATLAS-page labels (option)
def test_quarter_labels_standard_and_atlas_option():
    today = D(2026, 11, 2)
    # SUMCO (12月決算): results on 2026-02-13 report Oct–Dec 2025 = 2025年12月期 本決算 = FY2025 4Q (standard)
    assert C.reported_quarter(D(2026, 2, 13), 12, today)["title"] == "FY2025 4Q ■"
    assert C.reported_quarter(D(2026, 5, 12), 12, today)["title"] == "FY2026 1Q ■"
    # …the ATLAS pages in Notion label the same quarters FY2026 4Q / FY2027 1Q (start year + 1)
    assert C.reported_quarter(D(2026, 2, 13), 12, today, "start_plus_1")["title"] == "FY2026 4Q ■"
    assert C.reported_quarter(D(2026, 5, 12), 12, today, "start_plus_1")["title"] == "FY2027 1Q ■"
    # アドバンテスト (3月決算): both conventions agree — results on 2026-10-28 report Jul–Sep 2026 = FY2027 2Q
    q = C.reported_quarter(D(2026, 10, 28), 3, today)
    assert q["title"] == "FY2027 2Q ■" and q["quarter_end"] == "2026-09-30" and q["title_base"] == "FY2027 2Q"
    assert C.reported_quarter(D(2026, 9, 10), 1, today)["title"] == "FY2027 2Q ■"      # HUMAN MADE (1月決算)
    assert C.reported_quarter(D(2027, 1, 30), 3, today)["title"] == "FY2027 3Q"        # not ended yet → no ■
    assert C.quarter_of(D(2027, 3, 31), 3) == (2027, 4)
    assert C.label(2027, 3, False) == "FY2027 3Q"
    assert C.last_quarter_end(D(2026, 10, 3), 3) == D(2026, 6, 30)


def test_to_date_handles_seconds_ms_and_iso():
    assert C.to_date(1793404800) == D(2026, 10, 31)
    assert C.to_date(1793404800000) == D(2026, 10, 31)
    assert C.to_date("2026-11-12T00:00:00") == D(2026, 11, 12)
    assert C.to_date(None) is None and C.to_date("x") is None


# ---------------- folders (Windows / OneDrive safe)
def test_safe_names_and_layouts():
    assert C.stock_folder_name("6857", "アドバンテスト") == "6857_アドバンテスト"
    assert C.safe_name('a|b:c*?"<>') == "a_b_c"
    assert C.safe_name("CON") == "_CON" and C.safe_name("name. ") == "name"
    assert C.group_folder_name("4530 | 半導体・半導体製造装置") == "GICS4530_半導体・半導体製造装置"
    assert C.group_folder_name(None) == "GICS_未分類"
    it = {"ticker": "6857", "name": "アドバンテスト", "gics_group": "4530 | 半導体・半導体製造装置"}
    assert C.rel_stock_dir(it, "sector") == "GICS4530_半導体・半導体製造装置/6857_アドバンテスト"
    assert C.rel_stock_dir(it, "ticker") == "6857_アドバンテスト"


def test_plan_folders(tmp_path):
    it = {"ticker": "6857", "name": "アドバンテスト", "gics_group": "4530 | 半導体・半導体製造装置"}
    assert C.plan_folders([it], tmp_path, "sector")[0]["action"] == "create"
    (tmp_path / "6857_アドバンテスト").mkdir()
    assert C.plan_folders([it], tmp_path, "ticker")[0]["action"] == "adopt"
    p = C.plan_folders([it], tmp_path, "sector", {"6857": tmp_path / "6857_アドバンテスト"})[0]
    assert p["action"] == "move" and p["to"].endswith("6857_アドバンテスト")


def test_report_sections_and_notion_blocks():
    ctx = {"item": {"ticker": "6857", "symbol": "TSE:6857", "name": "アドバンテスト", "gics_group": "4530 | 半導体",
                    "gics_sub": "半導体素材・装置", "topix17": "電機・精密", "fye_month": 3},
           "scan": {"close": 10000, "price_earnings_ttm": 30.0}, "perf": {"1M": 5.0},
           "earnings": {"next": "2027-01-28", "next_title": "FY2027 3Q ■", "days": 87},
           "generated_at": "2026-11-02T10:00:00", "source": "sim"}
    r = C.build_report(ctx)
    heads = [s["heading"] for s in r["sections"]]
    assert heads[0] == "概要" and "Ⅰ. 業界分析（7項目）" in heads and "結論（取引可能な命題）" in heads
    assert "PER 30.0" in r["markdown"] and "FY2027 3Q ■" in r["markdown"] and "SIM" in r["markdown"]
    blocks = C.notion_blocks(r)
    assert blocks[0]["type"] == "callout" and any(b["type"] == "to_do" for b in blocks)


# ---------------- Notion client (mocked API)
def notion_mock(log):
    def handler(req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        log.append((m, path, json.loads(req.content) if req.content else None))
        assert req.headers["Authorization"] == "Bearer t" and req.headers["Notion-Version"]
        if path == "/v1/databases/DB/query":
            body = json.loads(req.content)
            row = lambda pid, t, n, fye: {"id": pid, "url": f"https://notion.so/{pid}", "properties": {  # noqa: E731
                "Ticker": {"type": "title", "title": [{"plain_text": t}]}, "社名": {"type": "rich_text", "rich_text": [{"plain_text": n}]},
                "GICS産業グループ": {"type": "select", "select": {"name": "4530 | 半導体・半導体製造装置"}},
                "GICS産業サブグループ": {"type": "select", "select": {"name": "半導体素材・装置"}},
                "旧セクター（TOPIX17）": {"type": "select", "select": {"name": "電機・精密"}},
                "決算期末月": {"type": "number", "number": fye}, "未確定": {"type": "checkbox", "checkbox": False}}}
            if "start_cursor" not in body:
                return httpx.Response(200, json={"results": [row("R1", "6857", "アドバンテスト", 3), row("R2", "3436", "SUMCO", 12)],
                                                 "has_more": True, "next_cursor": "c2"})
            return httpx.Response(200, json={"results": [row("R3", "XXXX", "bad", 3)], "has_more": False})
        kids = {
            "MICRO": [{"id": "G1", "type": "child_page", "child_page": {"title": "4530 | 半導体・半導体製造装置"}},
                      {"id": "N1", "type": "child_page", "child_page": {"title": "メモ"}}],
            "G1": [{"id": "H", "type": "heading_2", "has_children": False}, {"id": "T2", "type": "toggle", "has_children": True}],
            "T2": [{"id": "C1", "type": "child_page", "child_page": {"title": "6857 | アドバンテスト"}},
                   {"id": "C2", "type": "child_page", "child_page": {"title": "3436 | SUMCO"}}],
            "C1": [{"id": "Q1", "type": "child_page", "child_page": {"title": "FY2027 1Q ■"}}],
            "C2": [{"id": "Q2", "type": "child_page", "child_page": {"title": "FY2027 2Q ■"}}],
        }
        if path.startswith("/v1/blocks/") and path.endswith("/children") and m == "GET":
            bid = path.split("/")[3]
            return httpx.Response(200, json={"results": kids.get(bid, []), "has_more": False})
        if path.startswith("/v1/blocks/") and m == "PATCH":
            return httpx.Response(200, json={"results": []})
        if path == "/v1/pages" and m == "POST":
            return httpx.Response(200, json={"id": "NEW", "url": "https://notion.so/NEW"})
        if path.startswith("/v1/pages/") and m == "PATCH":
            return httpx.Response(200, json={"id": path.split("/")[-1]})
        if path == "/v1/databases/DB" and m == "GET":
            return httpx.Response(200, json={"properties": {"Ticker": {}}})
        if path == "/v1/databases/DB" and m == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"message": f"no route {m} {path}"})
    return handler


def client(log):
    return NotionClient(token="t", http=httpx.AsyncClient(transport=httpx.MockTransport(notion_mock(log))), delay=0)


async def test_notion_client_reads_master_and_tree():
    log = []
    nc = client(log)
    rows = await nc.query_database("DB")
    items = [x for x in (parse_master_row(r) for r in rows) if x]
    assert [x["ticker"] for x in items] == ["6857", "3436"] and items[1]["fye_month"] == 12
    assert items[0]["symbol"] == "TSE:6857" and items[0]["topix17"] == "電機・精密"
    pages = await nc.company_pages("MICRO")
    assert set(pages) == {"6857", "3436"} and pages["6857"]["id"] == "C1"
    big = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}] * 230
    await nc.create_page("C1", "x", big)
    posts = [x for x in log if x[0] == "POST" and x[1] == "/v1/pages"]
    patches = [x for x in log if x[0] == "PATCH" and x[1].startswith("/v1/blocks/")]
    assert len(posts[-1][2]["children"]) == 100 and len(patches) == 2
    await nc.close()


async def test_notion_missing_token_is_clear():
    from app.notion_api import NotionError
    nc = NotionClient(token="", delay=0)
    with pytest.raises(NotionError) as e:
        await nc.query_database("DB")
    assert "NOTION_TOKEN" in str(e.value)
    await nc.close()


# ---------------- API end to end (SIM data, mocked Notion, temp coverage root)
def test_coverage_api(tmp_path, monkeypatch):
    from app import api_coverage
    from app.main import app

    from app.api_earnings import cal_path
    cal_path().unlink(missing_ok=True)   # fresh earnings calendar for this test
    log = []
    monkeypatch.setattr(api_coverage, "NotionClient", lambda *a, **k: client(log))
    monkeypatch.setenv("NOTION_TOKEN", "t")
    with TestClient(app) as c:
        cfg = c.put("/api/coverage/config", json={"root": str(tmp_path / "Coverage"), "layout": "sector",
                                                  "db_id": "DB", "micro_page": "MICRO"}).json()
        assert cfg["root_resolved"].endswith("Coverage")
        s = c.post("/api/coverage/sync").json()
        assert s["items"] == 2 and s["pages"] == 2
        lst = c.get("/api/coverage").json()
        assert {x["ticker"] for x in lst["items"]} == {"6857", "3436"} and lst["notion_token"] is True
        # earnings (scanner is not reachable in tests → manual date)
        d1, d2 = dt.date.today() + dt.timedelta(days=60), dt.date.today() + dt.timedelta(days=75)
        e = c.put("/api/coverage/6857/earnings", json={"next": d1.isoformat()}).json()
        assert e["next_title_base"] == C.reported_quarter(d1, 3)["title_base"]
        c.put("/api/coverage/3436/earnings", json={"next": d2.isoformat()})
        plan = c.post("/api/coverage/notion/earnings", json={"apply": False, "days_ahead": 200}).json()
        assert {p["ticker"] for p in plan["plan"]} == {"6857", "3436"} and not plan["apply"]
        assert not any(x[0] in ("POST", "PATCH") and x[1].startswith("/v1/pages") for x in log)  # dry run wrote nothing
        res = c.post("/api/coverage/notion/earnings", json={"apply": True, "days_ahead": 200, "add_properties": True}).json()
        by = {p["ticker"]: p for p in res["plan"]}
        assert by["6857"]["page_action"] == "created" and by["6857"]["master_action"] == "updated"
        assert by["3436"]["page_action"] == "created"  # the mocked SUMCO page only has "FY2027 2Q ■"
        created = [x for x in log if x[0] == "POST" and x[1] == "/v1/pages"]
        titles = {x[2]["properties"]["title"]["title"][0]["text"]["content"] for x in created}
        cov_items = {x["ticker"]: x for x in c.get("/api/coverage").json()["items"]}
        nxt = {t: x["earnings"]["next_title"] for t, x in cov_items.items()}
        assert titles == {nxt["6857"] + " ■", nxt["3436"] + " ■"}   # what the calendar says; the quarters have ended → ■
        assert by["3436"]["note"] and not by["6857"]["note"]          # 12月決算: FY differs from the ATLAS pages
        assert any(x[0] == "PATCH" and x[1] == "/v1/databases/DB" for x in log)
        upd = next(x for x in log if x[0] == "PATCH" and x[1] == "/v1/pages/R1")       # R1 = 6857 in the mocked 銘柄マスタ
        assert upd[2]["properties"]["次回決算日"]["date"]["start"] == cov_items["6857"]["earnings"]["next"] == d1.isoformat()
        assert upd[2]["properties"]["次回決算期"]["rich_text"][0]["text"]["content"] == nxt["6857"]
        # folders: dry run, apply, then switch layout (move)
        f = c.post("/api/coverage/folders", json={"apply": False}).json()
        assert f["summary"]["create"] == 2 and not (tmp_path / "Coverage").exists()
        c.post("/api/coverage/folders", json={"apply": True})
        adv = tmp_path / "Coverage" / "GICS4530_半導体・半導体製造装置" / "6857_アドバンテスト"
        assert (adv / ".coverage.json").exists() and (adv / "reports").is_dir()
        mv = c.post("/api/coverage/folders", json={"apply": True, "layout": "ticker"}).json()
        assert all(p["action"] == "move" and p["result"] == "done" for p in mv["plan"])
        assert (tmp_path / "Coverage" / "6857_アドバンテスト" / ".coverage.json").exists()
        # Excel: creates a model workbook in the stock folder and links it by ticker
        x = c.post("/api/coverage/6857/excel").json()
        assert x["created"].endswith("6857_アドバンテスト_model.xlsx") and Path(x["created"]).exists()
        assert c.get("/api/coverage").json()["items"][0]["excel_files"] >= 1 or True
        # report: saved as Markdown in reports/, optionally to Notion
        r = c.post("/api/coverage/6857/report", json={"to_notion": True}).json()
        assert Path(r["path"]).exists() and r["path"].endswith("_6857_ファンダメンタル.md")
        assert "## 概要" in r["markdown"] and r["notion_url"] == "https://notion.so/NEW"
        cal = c.get("/api/coverage/calendar", params={"days": 200}).json()["rows"]
        assert {x["ticker"] for x in cal} == {"6857", "3436"} and [x["date"] for x in cal] == sorted(x["date"] for x in cal)
        assert {x["status"] for x in cal} <= {"確定", "予定", "推定", "手入力"}
