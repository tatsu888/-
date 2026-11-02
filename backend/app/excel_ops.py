"""Excel operations beyond cell values: formula fill/paste with relative references, formatting,
structure (insert/delete rows & columns, new sheet / workbook), backups + workbook diff + restore,
precedent/dependent tracing, and live (unsaved) values from an open workbook.

Same no-degradation rule as app/excel.py:
  * xlwings (real Excel) for everything when available (Windows/macOS);
  * openpyxl only for operations it can do safely on files without lossy parts. Row/column
    insertion is NEVER done with openpyxl (it does not update formula references → silent damage).
  * Every write is preceded by a file backup in <folder>/.terminal_backups/ (all modes).
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import formula as F

if TYPE_CHECKING:  # pragma: no cover
    from .excel import ExcelLibrary

BACKUP_DIR = ".terminal_backups"
BACKUP_MIN_INTERVAL = 60  # seconds — one snapshot per minute while typing quickly


# ---------------------------------------------------------------------------
# backups / restore / diff
# ---------------------------------------------------------------------------
def backup(path: Path, force: bool = False) -> str | None:
    d = path.parent / BACKUP_DIR
    d.mkdir(exist_ok=True)
    existing = list_backups(path)
    # throttle on the snapshot's own timestamp (copy2 keeps the source mtime, so st_mtime is not usable)
    if existing and not force:
        taken = time.mktime(time.strptime(existing[0]["taken"], "%Y%m%d-%H%M%S"))
        if time.time() - taken < BACKUP_MIN_INTERVAL:
            return existing[0]["name"]
    ts = time.strftime('%Y%m%d-%H%M%S')
    name, n = f"{path.stem}.{ts}{path.suffix}", 1
    while (d / name).exists():  # never overwrite an earlier snapshot taken in the same second
        name = f"{path.stem}.{ts}-{n}{path.suffix}"
        n += 1
    shutil.copy2(path, d / name)
    return name


def list_backups(path: Path) -> list[dict[str, Any]]:
    d = path.parent / BACKUP_DIR
    if not d.is_dir():
        return []
    stem = path.stem
    out = []
    import re

    pat = re.compile(r"^(\d{8}-\d{6})(?:-(\d+))?$")
    for p in d.glob(f"{stem}.*{path.suffix}"):
        m = pat.match(p.name[len(stem) + 1: -len(path.suffix)])
        if m:
            out.append({"name": p.name, "taken": m.group(1), "seq": int(m.group(2) or 0), "size": p.stat().st_size})
    out.sort(key=lambda b: (b["taken"], b["seq"]), reverse=True)
    return out


def backup_path(path: Path, name: str) -> Path:
    p = (path.parent / BACKUP_DIR / name).resolve()
    if p.parent != (path.parent / BACKUP_DIR).resolve() or not p.is_file() or not name.startswith(path.stem + "."):
        raise FileNotFoundError(name)
    return p


def read_cells(path: Path) -> dict[str, dict[str, tuple[Any, str | None]]]:
    """{sheet: {addr: (cached value, formula)}} — for diffing."""
    import openpyxl

    wf = openpyxl.load_workbook(path, data_only=False)
    wv = openpyxl.load_workbook(path, data_only=True)
    out: dict[str, dict[str, tuple[Any, str | None]]] = {}
    for ws in wf.worksheets:
        vs = wv[ws.title]
        cells = {}
        for row in ws.iter_rows():
            for c in row:
                f = c.value if isinstance(c.value, str) and c.value.startswith("=") else None
                v = vs[c.coordinate].value if f else c.value
                if v is not None or f:
                    cells[c.coordinate] = (v, f)
        out[ws.title] = cells
    return out


def diff_workbooks(old: Path, new: Path, limit: int = 3000) -> dict[str, Any]:
    from .excel import _jsonable

    a, b = read_cells(old), read_cells(new)
    changes = []
    for sheet in sorted(set(a) | set(b)):
        ca, cb = a.get(sheet, {}), b.get(sheet, {})
        for addr in sorted(set(ca) | set(cb), key=lambda x: (F.split_addr(x)[0], F.split_addr(x)[1])):
            va, vb = ca.get(addr, (None, None)), cb.get(addr, (None, None))
            if va != vb:
                changes.append({"sheet": sheet, "addr": addr, "before": _jsonable(va[0]), "before_f": va[1],
                                "after": _jsonable(vb[0]), "after_f": vb[1],
                                "kind": "formula" if va[1] != vb[1] else "value"})
                if len(changes) >= limit:
                    break
    return {"sheets_added": sorted(set(b) - set(a)), "sheets_removed": sorted(set(a) - set(b)),
            "changes": changes, "truncated": len(changes) >= limit}


# ---------------------------------------------------------------------------
# trace precedents / dependents
# ---------------------------------------------------------------------------
def trace(view: dict[str, Any], sheet: str, addr: str, depth: int = 1) -> dict[str, Any]:
    formulas = {(sh["name"], a): c["f"] for sh in view["sheets"] for a, c in sh["cells"].items() if c.get("f")}
    target = (sheet, F.norm_addr(addr))

    def prec(cell: tuple[str, str]) -> list[tuple[str, str]]:
        f = formulas.get(cell)
        return F.references(f, cell[0]) if f else []

    deps_index: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for cell, f in formulas.items():
        for ref in F.references(f, cell[0], max_cells=20000):
            deps_index.setdefault(ref, []).append(cell)

    def walk(start, fn) -> list[dict[str, Any]]:
        seen, frontier, out = {start}, [start], []
        for level in range(1, depth + 1):
            nxt = []
            for c in frontier:
                for r in fn(c):
                    if r not in seen:
                        seen.add(r)
                        nxt.append(r)
                        out.append({"sheet": r[0], "addr": r[1], "level": level})
            frontier = nxt
        return out

    return {"cell": {"sheet": target[0], "addr": target[1]}, "formula": formulas.get(target),
            "precedents": walk(target, prec), "dependents": walk(target, lambda c: deps_index.get(c, []))}


# ---------------------------------------------------------------------------
# fill (copy formulas with relative references)
# ---------------------------------------------------------------------------
def fill_updates(view: dict[str, Any], sheet: str, src: str, dst: str) -> dict[str, Any]:
    """Tile the source range over the destination range, shifting relative references like Excel.
    Returns {addr: value-or-formula} for write_cells."""
    sh = next((x for x in view["sheets"] if x["name"] == sheet), None)
    if sh is None:
        raise ValueError(f"sheet not found: {sheet}")

    def bounds(rng: str) -> tuple[int, int, int, int]:
        a, _, b = rng.upper().partition(":")
        (r1, c1), (r2, c2) = F.split_addr(a), F.split_addr(b or a)
        return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)

    sr1, sc1, sr2, sc2 = bounds(src)
    dr1, dc1, dr2, dc2 = bounds(dst)
    h, w = sr2 - sr1 + 1, sc2 - sc1 + 1
    if (dr2 - dr1 + 1) * (dc2 - dc1 + 1) > 20000:
        raise ValueError("fill target too large (max 20000 cells)")
    out: dict[str, Any] = {}
    for r in range(dr1, dr2 + 1):
        for c in range(dc1, dc2 + 1):
            srow, scol = sr1 + (r - dr1) % h, sc1 + (c - dc1) % w
            if (srow, scol) == (r, c):
                continue
            cell = sh["cells"].get(f"{F.num_to_col(scol)}{srow}") or {}
            if cell.get("f"):
                out[f"{F.num_to_col(c)}{r}"] = F.shift_formula(cell["f"], r - srow, c - scol)
            else:
                v = cell.get("v")
                out[f"{F.num_to_col(c)}{r}"] = "" if v is None else v
    return out


# ---------------------------------------------------------------------------
# formatting & structure — xlwings (lossless) and openpyxl (safe subset)
# ---------------------------------------------------------------------------
H_ALIGN_XL = {"left": -4131, "center": -4108, "right": -4152, "general": 1}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def openpyxl_format(ws, rng: str, fmt: dict[str, Any]) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    for row in ws[rng] if ":" in rng else [[ws[rng]]]:
        for c in row:
            f = c.font
            if any(k in fmt for k in ("bold", "italic", "font_color")):
                c.font = Font(name=f.name, size=f.size, bold=fmt.get("bold", f.bold), italic=fmt.get("italic", f.italic),
                              underline=f.underline, strike=f.strike,
                              color=(fmt["font_color"].lstrip("#") if fmt.get("font_color") else None)
                              if "font_color" in fmt else f.color)
            if "number_format" in fmt:
                c.number_format = fmt["number_format"] or "General"
            if "fill" in fmt:
                c.fill = PatternFill("solid", fgColor=fmt["fill"].lstrip("#")) if fmt["fill"] else PatternFill(fill_type=None)
            if "align" in fmt:
                a = c.alignment
                c.alignment = Alignment(horizontal=fmt["align"], vertical=a.vertical, wrap_text=a.wrap_text, indent=a.indent)


def xlwings_format(rng, fmt: dict[str, Any]) -> None:
    if "bold" in fmt:
        rng.font.bold = bool(fmt["bold"])
    if "italic" in fmt:
        rng.font.italic = bool(fmt["italic"])
    if "font_color" in fmt:
        rng.font.color = _hex_to_rgb(fmt["font_color"]) if fmt["font_color"] else (0, 0, 0)
    if "number_format" in fmt:
        rng.number_format = fmt["number_format"] or "General"
    if "fill" in fmt:
        rng.color = _hex_to_rgb(fmt["fill"]) if fmt["fill"] else None
    if "align" in fmt:
        try:
            rng.api.HorizontalAlignment = H_ALIGN_XL[fmt["align"]]  # Windows COM
        except Exception:  # noqa: BLE001 - macOS: alignment via AppleScript not supported here
            pass


def xlwings_open(path: Path):
    """(book, own_app) — attach to the user's open workbook or open hidden."""
    import xlwings as xw  # type: ignore

    target = path.resolve()
    for app in xw.apps:
        for b in app.books:
            try:
                if Path(b.fullname).resolve() == target:
                    return b, None
            except Exception:  # noqa: BLE001
                continue
    own = xw.App(visible=False, add_book=False)
    own.display_alerts = False
    return own.books.open(str(target), update_links=False), own


def xlwings_close(book, own_app) -> None:
    if own_app is not None:
        book.close()
        own_app.quit()


def xlwings_apply(path: Path, sheet: str, op: str, args: dict[str, Any]) -> dict[str, Any]:
    book, own = xlwings_open(path)
    try:
        if op == "add_sheet":
            book.sheets.add(args["name"], after=book.sheets[len(book.sheets) - 1])
        else:
            ws = book.sheets[sheet]
            if op == "format":
                xlwings_format(ws.range(args["range"]), args["format"])
            elif op in ("insert_rows", "delete_rows"):
                r, n = int(args["index"]), int(args.get("count", 1))
                rng = ws.range(f"{r}:{r + n - 1}")
                rng.insert("down") if op == "insert_rows" else rng.delete("up")
            elif op in ("insert_cols", "delete_cols"):
                c, n = int(args["index"]), int(args.get("count", 1))
                rng = ws.range(f"{F.num_to_col(c)}:{F.num_to_col(c + n - 1)}")
                rng.insert("right") if op == "insert_cols" else rng.delete("left")
            else:
                raise ValueError(f"unknown op {op}")
        book.save()
        return {"attached_to_open_workbook": own is None}
    finally:
        xlwings_close(book, own)


def xlwings_live_values(path: Path) -> dict[str, Any] | None:
    """Values of a workbook that is OPEN in Excel (including unsaved edits). None if not open."""
    import xlwings as xw  # type: ignore

    target = path.resolve()
    for app in xw.apps:
        for b in app.books:
            try:
                if Path(b.fullname).resolve() != target:
                    continue
            except Exception:  # noqa: BLE001
                continue
            out: dict[str, dict[str, Any]] = {}
            for sh in b.sheets:
                ur = sh.used_range
                vals = ur.options(ndim=2).value
                r0, c0 = ur.row, ur.column
                cells = {}
                for i, row in enumerate(vals or []):
                    for j, v in enumerate(row):
                        if v is not None:
                            from .excel import _jsonable

                            cells[f"{F.num_to_col(c0 + j)}{r0 + i}"] = _jsonable(v)
                out[sh.name] = cells
            return {"open": True, "dirty": not b.api.Saved if hasattr(b.api, "Saved") else None, "values": out}
    return None


def new_workbook(path: Path, sheets: list[str] | None = None, years: list[str] | None = None) -> None:
    """Create a new .xlsx (optionally a simple model skeleton: header row of years, blue-input style legend)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (sheets or ["Model"])[0]
    for name in (sheets or [])[1:]:
        wb.create_sheet(name)
    if years:
        ws.append(["(units)", *years])
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E78")
        ws.column_dimensions["A"].width = 28
        ws["A3"] = "Legend: blue = input, black = formula"
        ws["A3"].font = Font(italic=True, color="0000FF")
    wb.save(path)
