"""Excel workbook library: symbol linking, lossless read-only view, open-in-Excel,
change watching, optional write-back and non-destructive what-if recalculation.

Design principle (ユーザー要件): **Excel の機能を劣化させない**.
  * Viewing never writes the file. Values shown are the values Excel itself
    calculated and cached on save (openpyxl data_only=True) + formatting.
  * Editing happens in real Excel ("Open in Excel"); the browser view refreshes
    automatically when the file is saved (mtime watcher -> websocket push).
  * Editing from the browser (ユーザー要件: Windows で HTML から編集したい). TERMINAL_EXCEL_WRITE:
      auto      (default) xlwings if available (Windows/macOS + desktop Excel), otherwise
                openpyxl but only for files openpyxl can save without losing anything
      xlwings   always drive the real Excel application — lossless: Excel itself writes,
                recalculates and saves; if the workbook is open, the user's Excel window updates live
      openpyxl  direct file write; refused when the file contains parts openpyxl cannot
                preserve (charts, images, pivots, macros, ...). Always backs up first.
                Formula cached values are dropped by openpyxl, so they are recomputed by the
                terminal engine for display and by Excel on next open (fullCalcOnLoad)
      off       read-only
  * What-if: overrides are applied in memory and formulas are re-evaluated with
    app/formula.py; the file is untouched. Cells using functions the engine does
    not support keep Excel's cached value and are flagged "stale".
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import formula as F

SUPPORTED = {".xlsx", ".xlsm"}
LISTED = SUPPORTED | {".xls", ".xlsb"}
MAX_ROWS, MAX_COLS = 3000, 120

# zip parts that openpyxl drops or mangles on save
LOSSY_PARTS = {
    "xl/charts/": "charts", "xl/drawings/drawing": "drawings/shapes", "xl/media/": "images",
    "xl/ctrlProps/": "form controls", "xl/activeX/": "ActiveX controls",
    "xl/pivotTables/": "pivot tables", "xl/pivotCache/": "pivot caches", "xl/vbaProject.bin": "VBA macros",
    "xl/externalLinks/": "external links", "xl/slicers/": "slicers", "xl/slicerCaches/": "slicers",
    "xl/connections.xml": "data connections", "xl/queryTables/": "query tables",
    "xl/threadedComments/": "threaded comments", "xl/model/": "data model (Power Pivot)",
    "xl/timelines/": "timelines", "customXml/": "custom XML",
}

# Office default theme colours (theme index -> RGB) for approximate rendering
THEME = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47"]


@dataclass
class Root:
    path: Path


def _roots() -> list[Path]:
    data_dir = Path(os.environ.get("TERMINAL_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
    default = data_dir / "workbooks"
    raw = os.environ.get("TERMINAL_EXCEL_DIRS", "")
    roots = [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()] or [default]
    return roots


def write_mode() -> str:
    return os.environ.get("TERMINAL_EXCEL_WRITE", "auto").strip().lower() or "auto"


def xlwings_available() -> bool:
    """True when the real Excel application can be driven (Windows / macOS with xlwings installed)."""
    if sys.platform not in ("win32", "darwin"):
        return False
    try:
        import xlwings  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


class _ExcelThread:
    """All COM / AppleScript calls into Excel run on one dedicated thread (COM is apartment-threaded)."""

    def __init__(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="excel-com", initializer=self._init)

    @staticmethod
    def _init() -> None:
        try:
            import pythoncom  # type: ignore

            pythoncom.CoInitialize()
        except ImportError:
            pass

    def run(self, fn, *args):
        return self._pool.submit(fn, *args).result(timeout=120)


_EXCEL_THREAD: _ExcelThread | None = None


def _excel_thread() -> _ExcelThread:
    global _EXCEL_THREAD
    if _EXCEL_THREAD is None:
        _EXCEL_THREAD = _ExcelThread()
    return _EXCEL_THREAD


def _xlwings_write(path: Path, sheet: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Write through the Excel application. Attaches to the workbook if the user already has it open
    (their window updates immediately), otherwise opens it in a hidden Excel instance."""
    import xlwings as xw  # type: ignore

    target = path.resolve()
    book, own_app = None, None
    for app in xw.apps:
        for b in app.books:
            try:
                if Path(b.fullname).resolve() == target:
                    book = b
                    break
            except Exception:  # noqa: BLE001 - unsaved books have no path
                continue
        if book is not None:
            break
    if book is None:
        own_app = xw.App(visible=False, add_book=False)
        own_app.display_alerts = False
        book = own_app.books.open(str(target), update_links=False)
    try:
        ws = book.sheets[sheet]
        before: dict[str, Any] = {}
        for addr, val in updates.items():
            rng = ws.range(addr)
            f = rng.formula
            before[addr] = f if isinstance(f, str) and f.startswith("=") else _jsonable(rng.value)
            if isinstance(val, str) and val.startswith("="):
                rng.formula = val
            else:
                rng.value = _coerce_input(val)
        book.save()
        return {"before": before, "attached_to_open_workbook": own_app is None}
    finally:
        if own_app is not None:
            book.close()
            own_app.quit()


class ExcelError(Exception):
    def __init__(self, msg: str, status: int = 400) -> None:
        super().__init__(msg)
        self.status = status


class ExcelLibrary:
    def __init__(self, roots: list[Path] | None = None) -> None:
        self.roots = roots or _roots()
        if not os.environ.get("TERMINAL_EXCEL_DIRS"):
            self.roots[0].mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, tuple[float, dict]] = {}
        self._models: dict[str, tuple[float, Any]] = {}
        self.watched: dict[str, float] = {}  # id -> last seen mtime
        self._own_writes: dict[str, float] = {}

    # ---- ids & paths ------------------------------------------------------
    def path_for(self, file_id: str) -> Path:
        try:
            idx, rel = file_id.split("/", 1)
            root = self.roots[int(idx)].resolve()
        except (ValueError, IndexError) as e:
            raise ExcelError("bad file id", 404) from e
        p = (root / rel).resolve()
        if root not in p.parents and p != root:
            raise ExcelError("path outside library", 403)
        if not p.is_file():
            raise ExcelError("file not found", 404)
        return p

    def list_files(self) -> list[dict[str, Any]]:
        out = []
        for i, root in enumerate(self.roots):
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fn in filenames:
                    p = Path(dirpath) / fn
                    if fn.startswith("~$") or p.suffix.lower() not in LISTED:
                        continue
                    st = p.stat()
                    rel = p.relative_to(root).as_posix()
                    out.append({"id": f"{i}/{rel}", "name": fn, "path": rel, "root": str(root),
                                "size": st.st_size, "mtime": st.st_mtime,
                                "viewable": p.suffix.lower() in SUPPORTED})
        out.sort(key=lambda f: -f["mtime"])
        return out

    # ---- symbol linking ---------------------------------------------------
    @staticmethod
    def ticker_tokens(symbol: str) -> list[str]:
        tk = symbol.split(":")[-1]
        toks = {tk}
        if tk.endswith(".T"):
            toks.add(tk[:-2])
        return [t for t in toks if t]

    def match_symbol(self, symbol: str, manual: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
        files = self.list_files()
        manual_ids = set((manual or {}).get(symbol, []))
        pats = [re.compile(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])", re.I) for t in self.ticker_tokens(symbol)]
        res = []
        for f in files:
            if f["id"] in manual_ids:
                res.append({**f, "link": "manual"})
            elif any(p.search(f["path"]) for p in pats):
                res.append({**f, "link": "auto"})
        res.sort(key=lambda f: (f["link"] != "manual", -f["mtime"]))
        return res

    # ---- lossless view ----------------------------------------------------
    def lossy_parts(self, path: Path) -> list[str]:
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        except zipfile.BadZipFile:
            return ["not a zip-based workbook"]
        found = {label for prefix, label in LOSSY_PARTS.items() if any(n.startswith(prefix) for n in names)}
        # legacy VML drawings are how Excel stores cell comments (openpyxl round-trips those);
        # VML without any comments part means form controls / legacy shapes → lossy
        if any(n.startswith("xl/drawings/vmlDrawing") for n in names) and not any(
                n.startswith("xl/comments") for n in names):
            found.add("legacy VML shapes")
        return sorted(found)

    def view(self, file_id: str, quote: F.QuoteLookup | None = None) -> dict[str, Any]:
        path = self.path_for(file_id)
        if path.suffix.lower() not in SUPPORTED:
            raise ExcelError(f"{path.suffix} cannot be rendered (use Open in Excel)", 415)
        mtime = path.stat().st_mtime
        self.watched[file_id] = mtime
        hit = self._cache.get(file_id)
        if hit and hit[0] == mtime:
            return hit[1]
        data = self._render(path)
        self._fill_uncached(data, quote)
        lossy = self.lossy_parts(path)
        mode, reason = self.effective_write(path, lossy)
        data.update(id=file_id, name=path.name, mtime=mtime, write_mode=mode or "off", write_reason=reason,
                    lossy_parts=lossy)
        self._cache[file_id] = (mtime, data)
        return data

    def _render(self, path: Path) -> dict[str, Any]:
        import openpyxl

        wb_f = openpyxl.load_workbook(path, data_only=False, read_only=False, keep_links=True)
        wb_v = openpyxl.load_workbook(path, data_only=True, read_only=False, keep_links=True)
        styles: dict[str, int] = {}
        style_list: list[dict[str, Any]] = []
        sheets = []
        for ws in wb_f.worksheets:
            wv = wb_v[ws.title]
            max_r, max_c = min(ws.max_row, MAX_ROWS), min(ws.max_column, MAX_COLS)
            cells: dict[str, Any] = {}
            for row in ws.iter_rows(min_row=1, max_row=max_r, max_col=max_c):
                for c in row:
                    f = c.value if isinstance(c.value, str) and c.value.startswith("=") else None
                    if c.data_type == "f" and f is None and c.value is not None:
                        f = str(c.value)  # ArrayFormula / DataTableFormula objects
                    v = wv[c.coordinate].value
                    st = self._style(c)
                    if v is None and f is None and st is None:
                        continue
                    entry: dict[str, Any] = {"v": _jsonable(v)}
                    if f:
                        entry["f"] = f
                    if c.number_format and c.number_format != "General":
                        entry["nf"] = c.number_format
                    if st is not None:
                        key = repr(sorted(st.items()))
                        if key not in styles:
                            styles[key] = len(style_list)
                            style_list.append(st)
                        entry["s"] = styles[key]
                    if c.comment is not None and c.comment.text:
                        entry["cm"] = c.comment.text[:1000]
                    if c.hyperlink is not None and (c.hyperlink.target or c.hyperlink.location):
                        entry["hl"] = c.hyperlink.target or f"#{c.hyperlink.location}"
                    cells[c.coordinate] = entry
            cols = {}
            for k, d in ws.column_dimensions.items():
                if d.width or d.hidden:
                    cols[k] = {"w": d.width, "hidden": bool(d.hidden)}
            rows = {}
            for k, d in ws.row_dimensions.items():
                if d.height or d.hidden:
                    rows[str(k)] = {"h": d.height, "hidden": bool(d.hidden)}
            sheets.append({
                "name": ws.title, "state": ws.sheet_state, "max_row": max_r, "max_col": max_c,
                "truncated": ws.max_row > MAX_ROWS or ws.max_column > MAX_COLS,
                "freeze": ws.freeze_panes, "merged": [str(m) for m in ws.merged_cells.ranges],
                "cols": cols, "rows": rows, "cells": cells,
                "tab_color": _color(ws.sheet_properties.tabColor),
                "gridlines": ws.sheet_view.showGridLines is not False,
                "cf": _conditional_formats(ws),
                "validations": _list_validations(ws),
            })
        return {"sheets": sheets, "styles": style_list}

    @staticmethod
    def _style(c) -> dict[str, Any] | None:
        st: dict[str, Any] = {}
        fnt = c.font
        if fnt is not None:
            if fnt.b:
                st["b"] = 1
            if fnt.i:
                st["i"] = 1
            if fnt.u:
                st["u"] = 1
            col = _color(fnt.color)
            if col and col != "000000":
                st["fc"] = col
        fill = c.fill
        if fill is not None and fill.fill_type == "solid":
            col = _color(fill.fgColor)
            if col:
                st["bg"] = col
        al = c.alignment
        if al is not None:
            if al.horizontal and al.horizontal != "general":
                st["ha"] = al.horizontal
            if al.indent:
                st["ind"] = al.indent
            if al.wrap_text:
                st["wrap"] = 1
        bd = c.border
        if bd is not None:
            for side, key in ((bd.top, "bt"), (bd.bottom, "bb"), (bd.left, "bl"), (bd.right, "br")):
                if side is not None and side.style:
                    st[key] = side.style
        return st or None

    @staticmethod
    def _fill_uncached(data: dict[str, Any], quote: F.QuoteLookup | None = None) -> None:
        """Files saved by tools other than Excel (openpyxl, pandas ...) have formulas without cached
        values. Fill those with the engine and flag them ``calc`` so the UI can mark them."""
        sheets = {sh["name"]: {a: {"f": c.get("f"), "v": c.get("v")} for a, c in sh["cells"].items()}
                  for sh in data["sheets"]}
        ev = F.Evaluator(sheets, quote)
        n = 0
        for sh in data["sheets"]:
            for addr, c in sh["cells"].items():
                if c.get("f") and c.get("v") is None:
                    c["v"] = _jsonable(ev.value(sh["name"], addr))
                    c["calc"] = True
                    n += 1
        data["engine_filled"] = n

    # ---- what-if (non-destructive) ----------------------------------------
    def whatif(self, file_id: str, overrides: dict[str, Any], quote: F.QuoteLookup | None = None) -> dict[str, Any]:
        """overrides: {"Sheet1!B5": 1.2 or "=B4*2"} -> recomputed values of formula cells that changed."""
        view = self.view(file_id)
        sheets: dict[str, dict[str, dict[str, Any]]] = {}
        for sh in view["sheets"]:
            sheets[sh["name"]] = {a: {"f": c.get("f"), "v": c.get("v")} for a, c in sh["cells"].items()}
        import copy

        base_ev = F.Evaluator(copy.deepcopy(sheets), quote)  # untouched copy = "before" values
        for key, val in overrides.items():
            sh, addr = key.rsplit("!", 1)
            addr = F.norm_addr(addr)
            cell = sheets.setdefault(sh, {}).setdefault(addr, {})
            if isinstance(val, str) and val.startswith("="):
                cell.update(f=val, v=None)
            else:
                cell.update(f=None, v=_coerce_input(val))
        ev = F.Evaluator(sheets, quote)
        changed: dict[str, Any] = {}
        for sh, cells in sheets.items():
            for addr, c in cells.items():
                if not c.get("f"):
                    continue
                new = ev.value(sh, addr)
                # report cells whose value moves because of the overrides
                if _differs(new, base_ev.value(sh, addr)):
                    changed[f"{sh}!{addr}"] = _jsonable(new)
        stale = sorted(f"{sh}!{a}" for sh, a in ev.stale)  # unsupported functions -> Excel cached value kept
        # cells driven by live market data (=TV(...)) are always returned
        live = {f"{sh}!{a}": _jsonable(ev.value(sh, a)) for sh, cells in sheets.items() for a, c in cells.items()
                if c.get("f") and "TV(" in c["f"].upper()}
        return {"changed": changed, "live": live, "stale": stale, "tv_symbols": sorted(ev.tv_symbols)}

    # ---- open in Excel / write-back --------------------------------------
    def open_native(self, file_id: str) -> dict[str, Any]:
        path = self.path_for(file_id)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:  # noqa: BLE001
            raise ExcelError(f"could not launch Excel on the server machine: {e}", 500) from e
        return {"ok": True, "path": str(path)}

    def effective_write(self, path: Path, lossy: list[str] | None = None) -> tuple[str | None, str]:
        """(mode, human-readable reason). mode None = read-only for this file."""
        mode = write_mode()
        if mode == "off":
            return None, "read-only (TERMINAL_EXCEL_WRITE=off)"
        if mode in ("auto", "xlwings") and xlwings_available():
            return "xlwings", "Excel 本体経由で保存 (劣化なし)"
        if mode == "xlwings":
            return None, "xlwings / デスクトップ版 Excel が使えません (pip install xlwings)"
        if mode not in ("auto", "openpyxl"):
            return None, f"unknown TERMINAL_EXCEL_WRITE={mode}"
        lossy = self.lossy_parts(path) if lossy is None else lossy
        if lossy:
            return None, ("直接書き込むと " + ", ".join(lossy) + " が失われるため編集不可。"
                          "Windows で xlwings を入れると Excel 本体経由で劣化なく編集できます")
        return "openpyxl", "ファイルへ直接保存 (自動バックアップ。数式の結果は Excel で開くと再計算)"

    def write_cells(self, file_id: str, sheet: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Write values/formulas ("=...") to cells. Returns the previous contents for undo."""
        path = self.path_for(file_id)
        mode, reason = self.effective_write(path)
        if mode is None:
            raise ExcelError(reason, 409 if "失われる" in reason else 403)
        from . import excel_ops as X

        bk = X.backup(path)  # every mode: lossless file copy first
        if mode == "xlwings":
            try:
                res = _excel_thread().run(_xlwings_write, path, sheet, updates)
            except ExcelError:
                raise
            except Exception as e:  # noqa: BLE001 - COM errors are opaque; surface them
                raise ExcelError(f"Excel (xlwings) error: {type(e).__name__}: {e}", 500) from e
        else:
            res = self._openpyxl_write(path, sheet, updates)
        self._mark_written(file_id, path)
        return {"ok": True, "mode": mode, "backup": bk, **res}

    def _mark_written(self, file_id: str, path: Path) -> None:
        self._own_writes[file_id] = path.stat().st_mtime
        self.watched[file_id] = path.stat().st_mtime
        self._cache.pop(file_id, None)

    # ---- formatting / structure / fill / trace / history (see excel_ops.py) ----
    def _require_write(self, path: Path) -> str:
        mode, reason = self.effective_write(path)
        if mode is None:
            raise ExcelError(reason, 409 if "失われる" in reason else 403)
        return mode

    def format_cells(self, file_id: str, sheet: str, rng: str, fmt: dict[str, Any]) -> dict[str, Any]:
        from . import excel_ops as X

        path = self.path_for(file_id)
        mode = self._require_write(path)
        X.backup(path)
        if mode == "xlwings":
            res = self._xl(path, sheet, "format", {"range": rng, "format": fmt})
        else:
            import openpyxl

            wb = openpyxl.load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm", keep_links=True)
            if sheet not in wb.sheetnames:
                raise ExcelError(f"sheet not found: {sheet}", 404)
            X.openpyxl_format(wb[sheet], rng, fmt)
            self._save_openpyxl(wb, path)
            res = {}
        self._mark_written(file_id, path)
        return {"ok": True, "mode": mode, **res}

    def structure(self, file_id: str, sheet: str, op: str, args: dict[str, Any]) -> dict[str, Any]:
        """insert_rows / delete_rows / insert_cols / delete_cols (Excel only) and add_sheet."""
        from . import excel_ops as X

        path = self.path_for(file_id)
        mode = self._require_write(path)
        if op != "add_sheet" and mode != "xlwings":
            raise ExcelError("行・列の挿入/削除は Excel 本体 (xlwings) が必要です — openpyxl は数式の参照を更新しないため"
                             "ファイルが壊れます。Windows で xlwings を入れるか OPEN IN EXCEL を使ってください", 409)
        X.backup(path)
        if mode == "xlwings":
            res = self._xl(path, sheet, op, args)
        else:
            import openpyxl

            wb = openpyxl.load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm", keep_links=True)
            name = str(args.get("name") or f"Sheet{len(wb.sheetnames) + 1}")
            if name in wb.sheetnames:
                raise ExcelError(f"sheet already exists: {name}", 409)
            wb.create_sheet(name)
            self._save_openpyxl(wb, path)
            res = {}
        self._mark_written(file_id, path)
        return {"ok": True, "mode": mode, **res}

    def _xl(self, path: Path, sheet: str, op: str, args: dict[str, Any]) -> dict[str, Any]:
        from . import excel_ops as X

        try:
            return _excel_thread().run(X.xlwings_apply, path, sheet, op, args)
        except Exception as e:  # noqa: BLE001
            raise ExcelError(f"Excel (xlwings) error: {type(e).__name__}: {e}", 500) from e

    @staticmethod
    def _save_openpyxl(wb, path: Path) -> None:
        wb.calculation.fullCalcOnLoad = True
        try:
            wb.save(path)
        except PermissionError as e:
            raise ExcelError("ファイルがロックされています (Excel で開いている?)。閉じるか xlwings を使ってください", 423) from e

    def fill(self, file_id: str, sheet: str, src: str, dst: str) -> dict[str, Any]:
        from . import excel_ops as X

        try:
            updates = X.fill_updates(self.view(file_id), sheet, src, dst)
        except ValueError as e:
            raise ExcelError(str(e), 400) from e
        if not updates:
            return {"ok": True, "before": {}, "updates": {}}
        res = self.write_cells(file_id, sheet, updates)
        return {**res, "updates": updates}

    def trace(self, file_id: str, sheet: str, addr: str, depth: int = 1) -> dict[str, Any]:
        from . import excel_ops as X

        return X.trace(self.view(file_id), sheet, addr, depth)

    def backups(self, file_id: str) -> list[dict[str, Any]]:
        from . import excel_ops as X

        return X.list_backups(self.path_for(file_id))

    def diff_backup(self, file_id: str, name: str) -> dict[str, Any]:
        from . import excel_ops as X

        path = self.path_for(file_id)
        try:
            old = X.backup_path(path, name)
        except FileNotFoundError as e:
            raise ExcelError("backup not found", 404) from e
        return {"backup": name, **X.diff_workbooks(old, path)}

    def restore(self, file_id: str, name: str) -> dict[str, Any]:
        from . import excel_ops as X

        path = self.path_for(file_id)
        if write_mode() == "off":
            raise ExcelError("read-only (TERMINAL_EXCEL_WRITE=off)", 403)
        try:
            old = X.backup_path(path, name)
        except FileNotFoundError as e:
            raise ExcelError("backup not found", 404) from e
        safety = X.backup(path, force=True)  # the current state is kept too
        try:
            shutil.copy2(old, path)
        except PermissionError as e:
            raise ExcelError("ファイルがロックされています — Excel で閉じてから復元してください", 423) from e
        self._mark_written(file_id, path)
        return {"ok": True, "restored": name, "previous_saved_as": safety}

    def live_values(self, file_id: str) -> dict[str, Any]:
        """Values from the workbook open in Excel (unsaved edits included). xlwings only."""
        from . import excel_ops as X

        path = self.path_for(file_id)
        if not xlwings_available():
            return {"open": False, "reason": "xlwings / desktop Excel not available"}
        try:
            res = _excel_thread().run(X.xlwings_live_values, path)
        except Exception as e:  # noqa: BLE001
            raise ExcelError(f"Excel (xlwings) error: {type(e).__name__}: {e}", 500) from e
        return res or {"open": False, "reason": "workbook is not open in Excel"}

    def create_workbook(self, name: str, years: list[str] | None = None, sheets: list[str] | None = None) -> dict[str, Any]:
        from . import excel_ops as X

        if write_mode() == "off":
            raise ExcelError("read-only (TERMINAL_EXCEL_WRITE=off)", 403)
        fname = Path(name).name
        if not fname.lower().endswith(".xlsx"):
            fname += ".xlsx"
        dest = self.roots[0] / fname
        if dest.exists():
            raise ExcelError(f"{fname} already exists", 409)
        X.new_workbook(dest, sheets, years)
        return {"id": f"0/{fname}", "name": fname}

    @staticmethod
    def _openpyxl_write(path: Path, sheet: str, updates: dict[str, Any]) -> dict[str, Any]:
        import openpyxl

        wb = openpyxl.load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm", keep_links=True)
        if sheet not in wb.sheetnames:
            raise ExcelError(f"sheet not found: {sheet}", 404)
        ws = wb[sheet]
        before: dict[str, Any] = {}
        for addr, val in updates.items():
            before[addr] = _jsonable(ws[addr].value)
            ws[addr] = val if isinstance(val, str) and val.startswith("=") else _coerce_input(val)
        wb.calculation.fullCalcOnLoad = True
        try:
            wb.save(path)
        except PermissionError as e:
            raise ExcelError("ファイルがロックされています (Excel で開いている?)。閉じるか xlwings を使ってください", 423) from e
        return {"before": before}

    def save_upload(self, filename: str, content: bytes) -> dict[str, Any]:
        name = Path(filename).name
        if Path(name).suffix.lower() not in LISTED:
            raise ExcelError("only .xlsx/.xlsm/.xls/.xlsb", 415)
        dest = self.roots[0] / "uploads" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return {"id": f"0/{dest.relative_to(self.roots[0]).as_posix()}"}

    def changed_files(self) -> list[tuple[str, float]]:
        """Watched files whose mtime changed since last view (for websocket push)."""
        out = []
        for fid, seen in list(self.watched.items()):
            try:
                m = self.path_for(fid).stat().st_mtime
            except ExcelError:
                self.watched.pop(fid, None)
                continue
            if m != seen:
                self.watched[fid] = m
                if self._own_writes.get(fid) != m:  # edits made from the terminal are not "external" saves
                    out.append((fid, m))
        return out


# ---------------------------------------------------------------------------
def _color(c) -> str | None:
    if c is None:
        return None
    try:
        if c.type == "rgb" and isinstance(c.rgb, str) and len(c.rgb) >= 6:
            if c.rgb.startswith("00") and len(c.rgb) == 8 and c.rgb != "00000000":
                return c.rgb[2:]
            return c.rgb[-6:] if c.rgb not in ("00000000",) else None
        if c.type == "theme" and c.theme is not None and 0 <= c.theme < len(THEME):
            base = THEME[c.theme]
            tint = c.tint or 0
            if tint:
                rgb = [int(base[i:i + 2], 16) for i in (0, 2, 4)]
                rgb = [int(v + (255 - v) * tint) if tint > 0 else int(v * (1 + tint)) for v in rgb]
                return "".join(f"{max(0, min(255, v)):02X}" for v in rgb)
            return base
        if c.type == "indexed" and c.indexed is not None:
            from openpyxl.styles.colors import COLOR_INDEX
            if c.indexed < len(COLOR_INDEX):
                return COLOR_INDEX[c.indexed][-6:]
    except Exception:  # noqa: BLE001
        return None
    return None


def _jsonable(v: Any) -> Any:
    import datetime as dt

    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, F.XLError):
        return str(v)
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


def _coerce_input(v: Any) -> Any:
    """Typed text -> Excel value, like typing into a cell: "1,234" -> 1234, "5%" -> 0.05, "TRUE" -> True."""
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        if s.upper() in ("TRUE", "FALSE"):
            return s.upper() == "TRUE"
        try:
            if s.endswith("%"):
                return float(s[:-1].replace(",", "")) / 100
            n = float(s.replace(",", ""))
            return int(n) if n.is_integer() and "." not in s and "e" not in s.lower() and abs(n) < 2**53 else n
        except ValueError:
            return s
    return v


def _differs(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) > 1e-9 * max(1.0, abs(a), abs(b))
    return a != b


QuoteFn = Callable[[str, str], Any]


# ---------------------------------------------------------------------------
# conditional formatting / data validation export (rendered by the XLS panel)
# ---------------------------------------------------------------------------
def _num(x: Any) -> Any:
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def _conditional_formats(ws) -> list[dict[str, Any]]:
    """Subset of Excel conditional formatting that can be evaluated in the browser:
    cellIs (comparison), colorScale (2/3 colours), dataBar. Others are reported as 'unsupported'."""
    out: list[dict[str, Any]] = []
    try:
        items = list(ws.conditional_formatting)
    except Exception:  # noqa: BLE001
        return out
    for cf in items:
        ranges = [str(r) for r in cf.sqref.ranges] if hasattr(cf.sqref, "ranges") else str(cf.sqref).split()
        for rule in cf.rules:
            r: dict[str, Any] = {"ranges": ranges, "type": rule.type, "priority": rule.priority,
                                 "stop": bool(rule.stopIfTrue)}
            if rule.type == "cellIs":
                r["operator"] = rule.operator
                r["values"] = [_num(f) for f in (rule.formula or [])]
                dxf = rule.dxf
                if dxf is not None:
                    if dxf.fill is not None:
                        r["fill"] = _color(dxf.fill.bgColor) or _color(dxf.fill.fgColor)
                    if dxf.font is not None:
                        r["font"] = _color(dxf.font.color)
                        r["bold"] = bool(dxf.font.b)
                if all(v is None for v in r["values"]):
                    r["type"] = "unsupported"  # formula-based thresholds (e.g. =$B$1) are not evaluated
            elif rule.type == "colorScale" and rule.colorScale is not None:
                cs = rule.colorScale
                r["cfvo"] = [{"type": v.type, "val": _num(v.val)} for v in cs.cfvo]
                r["colors"] = [_color(c) for c in cs.color]
            elif rule.type == "dataBar" and rule.dataBar is not None:
                r["color"] = _color(rule.dataBar.color)
            else:
                r["type"] = "unsupported" if rule.type not in ("cellIs", "colorScale", "dataBar") else rule.type
            out.append(r)
    return out


def _list_validations(ws) -> list[dict[str, Any]]:
    """List-type data validations with inline options ("A,B,C") or a same-sheet range."""
    out: list[dict[str, Any]] = []
    try:
        dvs = ws.data_validations.dataValidation
    except Exception:  # noqa: BLE001
        return out
    for dv in dvs:
        if dv.type != "list" or not dv.formula1:
            continue
        f1 = dv.formula1.strip()
        if f1.startswith('"') and f1.endswith('"'):
            options: list[Any] = [x.strip() for x in f1[1:-1].split(",")]
        else:
            ref = f1.lstrip("=").replace("$", "")
            if "!" in ref:
                continue  # other-sheet list sources not resolved
            try:
                options = [c.value for row in ws[ref] for c in (row if isinstance(row, tuple) else (row,)) if c.value is not None]
            except Exception:  # noqa: BLE001
                continue
        out.append({"ranges": [str(r) for r in dv.sqref.ranges], "options": options})
    return out
