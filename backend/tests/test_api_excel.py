import os

import openpyxl
from fastapi.testclient import TestClient


def make_book(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Model"
    ws["A1"], ws["B1"] = "Revenue", 100
    ws["A2"], ws["B2"] = "Margin", 0.1
    ws["A3"], ws["B3"] = "Profit", "=B1*B2"
    ws["B3"].number_format = "#,##0.0"
    ws["A1"].font = openpyxl.styles.Font(bold=True)
    wb.save(path)


def test_excel_view_link_whatif_and_readonly():
    from app.main import app
    from app.state import S

    root = S.excel.roots[0]
    make_book(root / "7203_Toyota_model.xlsx")
    with TestClient(app) as c:
        files = c.get("/api/excel/files").json()["files"]
        assert any(f["name"] == "7203_Toyota_model.xlsx" for f in files)
        linked = c.get("/api/excel/for_symbol", params={"symbol": "TSE:7203"}).json()
        assert linked and linked[0]["link"] == "auto"
        fid = linked[0]["id"]
        v = c.get("/api/excel/view", params={"id": fid}).json()
        cells = v["sheets"][0]["cells"]
        assert cells["B3"]["f"] == "=B1*B2" and cells["B3"]["nf"] == "#,##0.0"
        assert v["styles"][cells["A1"]["s"]]["b"] == 1
        w = c.post("/api/excel/whatif", json={"id": fid, "overrides": {"Model!B1": 200}}).json()
        assert w["changed"]["Model!B3"] == 20
        # read-only by default: no degradation of the source file
        assert c.post("/api/excel/write", json={"id": fid, "sheet": "Model", "updates": {"B1": 1}}).status_code == 403
        # path traversal guard
        assert c.get("/api/excel/view", params={"id": "0/../../etc/passwd"}).status_code in (403, 404)


def test_openpyxl_write_refuses_lossy_and_backs_up(tmp_path, monkeypatch):
    from app.state import S

    monkeypatch.setenv("TERMINAL_EXCEL_WRITE", "openpyxl")
    root = S.excel.roots[0]
    make_book(root / "plain.xlsx")
    res = S.excel.write_cells("0/plain.xlsx", "Model", {"B1": "150"})
    assert res["ok"]
    assert openpyxl.load_workbook(root / "plain.xlsx")["Model"]["B1"].value == 150
    assert any((root / ".terminal_backups").iterdir())
    os.environ.pop("TERMINAL_EXCEL_WRITE", None)


def test_api_smoke_sim():
    from app.main import app

    with TestClient(app) as c:
        assert c.get("/api/health").json()["provider"] == "sim"
        h = c.get("/api/history", params={"symbol": "NASDAQ:AAPL", "interval": "1h", "bars": 50}).json()
        assert len(h["bars"]) == 50 and h["interval"] == "60"
        assert c.get("/api/history", params={"symbol": "X", "interval": "7m"}).status_code == 400
        assert c.get("/api/analytics/leadlag/theme/us_semis_jp").status_code == 200
        r = c.post("/api/harness/run", json={"forecast_years": ["Y1"], "lines": {"revenue": {"method": "values",
                                                                                               "params": {"values": 1}}}})
        assert r.status_code == 200
        x = c.post("/api/harness/export.xlsx", json=c.get("/api/harness/models/sample_manufacturer",
                                                          params={"example": True}).json())
        assert x.status_code == 200 and x.content[:2] == b"PK"
        a = c.post("/api/alerts", json={"symbol": "NASDAQ:AAPL", "condition": "above", "value": 1}).json()
        assert a["active"]
        assert c.delete(f"/api/alerts/{a['id']}").json()["ok"]
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            ws.send_json({"op": "subscribe", "symbols": ["FX:USDJPY"]})
            assert ws.receive_json()["type"] in ("quotes", "bar")
