import sys
import time
import types

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.excel import ExcelError


def book(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Model"
    ws.append(["", "FY1", "FY2", "FY3", "FY4"])
    ws.append(["Units", 10, 11, 12, 13])
    ws.append(["Price", 2, None, None, None])
    ws.append(["Revenue", "=B2*B3", None, None, None])
    ws["C3"] = "=B3*(1+$B$6)"
    ws.append([])
    ws["A6"], ws["B6"] = "growth", 0.1
    wb.save(path)


@pytest.fixture()
def lib(monkeypatch):
    from app.state import S

    monkeypatch.setenv("TERMINAL_EXCEL_WRITE", "auto")
    import app.excel_ops as X
    monkeypatch.setattr(X, "BACKUP_MIN_INTERVAL", 0)
    return S.excel


def test_fill_right_shifts_relative_refs(lib):
    root = lib.roots[0]
    book(root / "ops_fill.xlsx")
    res = lib.fill("0/ops_fill.xlsx", "Model", "C3", "D3:E3")
    assert res["updates"] == {"D3": "=C3*(1+$B$6)", "E3": "=D3*(1+$B$6)"}
    lib.fill("0/ops_fill.xlsx", "Model", "B4", "C4:E4")
    ws = openpyxl.load_workbook(root / "ops_fill.xlsx")["Model"]
    assert ws["E4"].value == "=E2*E3"
    v = lib.view("0/ops_fill.xlsx")
    cells = v["sheets"][0]["cells"]
    assert abs(cells["E4"]["v"] - 13 * 2 * 1.1 ** 3) < 1e-9  # engine-computed (openpyxl has no cached values)


def test_trace_precedents_and_dependents(lib):
    root = lib.roots[0]
    book(root / "ops_trace.xlsx")
    t = lib.trace("0/ops_trace.xlsx", "Model", "C3", depth=1)
    assert {(p["sheet"], p["addr"]) for p in t["precedents"]} == {("Model", "B3"), ("Model", "B6")}
    t = lib.trace("0/ops_trace.xlsx", "Model", "B3", depth=2)
    deps = {(d["addr"], d["level"]) for d in t["dependents"]}
    assert ("B4", 1) in deps and ("C3", 1) in deps


def test_format_backup_diff_restore(lib):
    root = lib.roots[0]
    book(root / "ops_fmt.xlsx")
    fid = "0/ops_fmt.xlsx"
    lib.format_cells(fid, "Model", "B2:E2", {"bold": True, "number_format": "#,##0.0", "font_color": "0000FF", "fill": "FFFF00"})
    c = openpyxl.load_workbook(root / "ops_fmt.xlsx")["Model"]["C2"]
    assert c.font.b and c.number_format == "#,##0.0" and c.font.color.rgb.endswith("0000FF") and c.fill.fgColor.rgb.endswith("FFFF00")
    time.sleep(1.1)  # backups are named per second
    lib.write_cells(fid, "Model", {"B2": "99"})
    backups = lib.backups(fid)
    assert len(backups) >= 2
    d = lib.diff_backup(fid, backups[0]["name"])  # newest backup = state before the B2 edit
    assert any(ch["addr"] == "B2" and ch["before"] == 10 and ch["after"] == 99 for ch in d["changes"])
    r = lib.restore(fid, backups[0]["name"])
    assert r["ok"] and openpyxl.load_workbook(root / "ops_fmt.xlsx")["Model"]["B2"].value == 10


def test_structure_rules_without_excel(lib):
    root = lib.roots[0]
    book(root / "ops_struct.xlsx")
    fid = "0/ops_struct.xlsx"
    with pytest.raises(ExcelError) as e:
        lib.structure(fid, "Model", "insert_rows", {"index": 3, "count": 1})
    assert e.value.status == 409 and "xlwings" in str(e.value)  # openpyxl would break formula references
    lib.structure(fid, "", "add_sheet", {"name": "Notes"})
    assert openpyxl.load_workbook(root / "ops_struct.xlsx").sheetnames == ["Model", "Notes"]


def test_new_workbook(lib):
    r = lib.create_workbook("Skeleton", years=["FY2025E", "FY2026E"])
    assert r["id"] == "0/Skeleton.xlsx"
    ws = openpyxl.load_workbook(lib.roots[0] / "Skeleton.xlsx")["Model"]
    assert ws["B1"].value == "FY2025E" and ws["A3"].font.color.rgb.endswith("0000FF")
    with pytest.raises(ExcelError):
        lib.create_workbook("Skeleton")


def test_xlwings_structure_format_and_live_values(lib, monkeypatch):
    import app.excel as E

    calls = []

    class FakeRange:
        def __init__(self, addr):
            self.addr = addr
            self.font = types.SimpleNamespace(bold=None, italic=None, color=None)
            self.number_format = None
            self.color = None
            self.api = types.SimpleNamespace()

        def insert(self, shift):
            calls.append(("insert", self.addr, shift))

        def delete(self, shift):
            calls.append(("delete", self.addr, shift))

    ranges = {}

    class FakeUsed:
        row, column = 1, 1

        def options(self, ndim):
            return types.SimpleNamespace(value=[["a", 1.0], [None, 2.5]])

    class FakeSheet:
        name = "Model"
        used_range = FakeUsed()

        def range(self, addr):
            return ranges.setdefault(addr, FakeRange(addr))

    path = str((lib.roots[0] / "ops_xw.xlsx").resolve())
    book(lib.roots[0] / "ops_xw.xlsx")
    sheets = types.SimpleNamespace(__getitem__=None)

    class Sheets(list):
        def __getitem__(self, k):
            return FakeSheet() if isinstance(k, str) else list.__getitem__(self, k)

        def add(self, name, after=None):
            calls.append(("add_sheet", name))

    user_book = types.SimpleNamespace(fullname=path, sheets=Sheets([FakeSheet()]), save=lambda: calls.append(("save",)),
                                      close=lambda: calls.append(("close",)), api=types.SimpleNamespace(Saved=False))
    fake = types.ModuleType("xlwings")
    fake.apps = [types.SimpleNamespace(books=[user_book])]
    monkeypatch.setitem(sys.modules, "xlwings", fake)
    monkeypatch.setattr(E, "xlwings_available", lambda: True)
    fid = "0/ops_xw.xlsx"
    lib.structure(fid, "Model", "insert_rows", {"index": 3, "count": 2})
    lib.structure(fid, "Model", "delete_cols", {"index": 2, "count": 1})
    lib.structure(fid, "Model", "add_sheet", {"name": "Comps"})
    lib.format_cells(fid, "Model", "B2:C2", {"bold": True, "fill": "FFFF00", "number_format": "0.0%"})
    assert ("insert", "3:4", "down") in calls and ("delete", "B:B", "left") in calls and ("add_sheet", "Comps") in calls
    assert ranges["B2:C2"].font.bold is True and ranges["B2:C2"].color == (255, 255, 0) and ranges["B2:C2"].number_format == "0.0%"
    assert ("close",) not in calls  # the user's open workbook is never closed
    live = lib.live_values(fid)
    assert live["open"] and live["dirty"] is True and live["values"]["Model"] == {"A1": "a", "B1": 1.0, "B2": 2.5}


def test_excel_ops_api():
    from app.main import app
    from app.state import S

    book(S.excel.roots[0] / "ops_api.xlsx")
    with TestClient(app) as c:
        r = c.post("/api/excel/fill", json={"id": "0/ops_api.xlsx", "sheet": "Model", "source": "C3", "target": "D3:E3"})
        assert r.status_code == 200 and r.json()["view"]["sheets"][0]["cells"]["E3"]["f"] == "=D3*(1+$B$6)"
        assert c.get("/api/excel/trace", params={"id": "0/ops_api.xlsx", "sheet": "Model", "addr": "E3"}).json()["precedents"]
        assert c.post("/api/excel/structure", json={"id": "0/ops_api.xlsx", "sheet": "Model", "op": "insert_rows",
                                                    "index": 2}).status_code == 409
        assert c.post("/api/excel/format", json={"id": "0/ops_api.xlsx", "sheet": "Model", "range": "A1",
                                                 "format": {"bold": True}}).status_code == 200
        assert c.get("/api/excel/backups", params={"id": "0/ops_api.xlsx"}).json()
        assert c.get("/api/excel/live", params={"id": "0/ops_api.xlsx"}).json()["open"] is False
        assert c.post("/api/excel/new", json={"name": "api_new"}).json()["id"] == "0/api_new.xlsx"
