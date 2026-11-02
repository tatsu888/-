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
        # editing from the browser (auto mode -> openpyxl here because xlwings/Excel is not available on Linux)
        assert v["write_mode"] == "openpyxl"
        w = c.post("/api/excel/write", json={"id": fid, "sheet": "Model", "updates": {"B1": "250", "B2": "20%"}})
        assert w.status_code == 200, w.text
        body = w.json()
        assert body["before"] == {"B1": 100, "B2": 0.1}
        cells = body["view"]["sheets"][0]["cells"]
        assert cells["B1"]["v"] == 250 and cells["B2"]["v"] == 0.2
        assert cells["B3"]["v"] == 50 and cells["B3"]["calc"]  # recomputed by the engine (no Excel cache)
        # undo = write the previous contents back
        c.post("/api/excel/write", json={"id": fid, "sheet": "Model", "updates": body["before"]})
        assert openpyxl.load_workbook(root / "7203_Toyota_model.xlsx")["Model"]["B1"].value == 100
        # own edits are not reported as external saves
        assert S.excel.changed_files() == []
        # path traversal guard
        assert c.get("/api/excel/view", params={"id": "0/../../etc/passwd"}).status_code in (403, 404)


def test_openpyxl_write_backs_up_and_refuses_lossy(monkeypatch):
    from openpyxl.chart import BarChart, Reference

    from app.excel import ExcelError
    from app.state import S

    monkeypatch.setenv("TERMINAL_EXCEL_WRITE", "openpyxl")
    root = S.excel.roots[0]
    make_book(root / "plain.xlsx")
    res = S.excel.write_cells("0/plain.xlsx", "Model", {"B1": "150", "A9": "=B1*2"})
    assert res["ok"] and res["mode"] == "openpyxl"
    ws = openpyxl.load_workbook(root / "plain.xlsx")["Model"]
    assert ws["B1"].value == 150 and ws["A9"].value == "=B1*2"
    assert any((root / ".terminal_backups").iterdir())

    # a workbook with a chart would be damaged by openpyxl -> refused (no degradation)
    wb = openpyxl.Workbook()
    wb.active.append([1])
    wb.active.append([2])
    ch = BarChart()
    ch.add_data(Reference(wb.active, min_col=1, min_row=1, max_row=2))
    wb.active.add_chart(ch, "C1")
    wb.save(root / "with_chart.xlsx")
    try:
        S.excel.write_cells("0/with_chart.xlsx", "Sheet", {"A1": 5})
        raise AssertionError("should refuse")
    except ExcelError as e:
        assert e.status == 409 and "charts" in str(e)

    monkeypatch.setenv("TERMINAL_EXCEL_WRITE", "off")
    try:
        S.excel.write_cells("0/plain.xlsx", "Model", {"B1": 1})
        raise AssertionError("should refuse")
    except ExcelError as e:
        assert e.status == 403


class _FakeRange:
    def __init__(self, cells, addr):
        self.cells, self.addr = cells, addr

    @property
    def formula(self):
        v = self.cells.get(self.addr)
        return v if isinstance(v, str) and v.startswith("=") else ("" if v is None else str(v))

    @formula.setter
    def formula(self, f):
        self.cells[self.addr] = f

    @property
    def value(self):
        return self.cells.get(self.addr)

    @value.setter
    def value(self, v):
        self.cells[self.addr] = v


class _FakeBook:
    def __init__(self, path):
        self.fullname = path
        self.cells = {"B1": 100, "B3": "=B1*B2"}
        self.saved = self.closed = 0
        self.sheets = {"Model": type("S", (), {"range": lambda _s, a: _FakeRange(self.cells, a)})()}

    def save(self):
        self.saved += 1

    def close(self):
        self.closed += 1


def test_xlwings_path_drives_excel_and_reports_undo(monkeypatch):
    """xlwings cannot run on Linux CI; a fake module checks the control flow (open hidden app, write, save, quit)."""
    import sys
    import types

    import app.excel as X
    from app.state import S

    opened = []

    class FakeApp:
        def __init__(self, visible=True, add_book=True):
            assert visible is False and add_book is False
            self.quit_called = False
            self.books = types.SimpleNamespace(open=self._open)

        def _open(self, path, update_links=True):
            b = _FakeBook(path)
            opened.append((self, b))
            return b

        def quit(self):
            self.quit_called = True

    fake = types.ModuleType("xlwings")
    fake.apps = []
    fake.App = FakeApp
    monkeypatch.setitem(sys.modules, "xlwings", fake)
    monkeypatch.setattr(X, "xlwings_available", lambda: True)
    monkeypatch.setenv("TERMINAL_EXCEL_WRITE", "auto")
    root = S.excel.roots[0]
    make_book(root / "xw.xlsx")
    res = S.excel.write_cells("0/xw.xlsx", "Model", {"B1": "200", "B3": "=B1*3"})
    assert res["mode"] == "xlwings" and res["attached_to_open_workbook"] is False
    app_, book = opened[0]
    assert book.cells["B1"] == 200 and book.cells["B3"] == "=B1*3"
    assert res["before"] == {"B1": 100, "B3": "=B1*B2"}
    assert book.saved == 1 and book.closed == 1 and app_.quit_called

    # already open in the user's Excel -> attach, save, but do NOT close their window
    user_book = _FakeBook(str((root / "xw.xlsx").resolve()))
    fake.apps = [types.SimpleNamespace(books=[user_book])]
    res = S.excel.write_cells("0/xw.xlsx", "Model", {"B1": "7"})
    assert res["attached_to_open_workbook"] is True and user_book.cells["B1"] == 7
    assert user_book.saved == 1 and user_book.closed == 0


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
