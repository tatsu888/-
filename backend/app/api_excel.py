"""Excel library endpoints (see app/excel.py for the no-degradation design)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .excel import ExcelError, write_mode
from .state import S

router = APIRouter(prefix="/api/excel")


def _wrap(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ExcelError as e:
        raise HTTPException(e.status, str(e)) from e


def _quote(sym: str, field: str) -> Any:
    q = S.hub.last_quotes.get(sym) if S.hub else None
    return q.get(field) if q else None


@router.get("/files")
async def files():
    return {"roots": [str(r) for r in S.excel.roots], "write_mode": write_mode(), "files": S.excel.list_files()}


@router.get("/for_symbol")
async def for_symbol(symbol: str):
    return _wrap(S.excel.match_symbol, symbol, S.store.get("excel_links"))


class LinkReq(BaseModel):
    symbol: str
    file_id: str
    linked: bool = True


@router.post("/link")
async def link(req: LinkReq):
    _wrap(S.excel.path_for, req.file_id)
    links = dict(S.store.get("excel_links") or {})
    cur = [x for x in links.get(req.symbol, []) if x != req.file_id]
    if req.linked:
        cur.append(req.file_id)
    links[req.symbol] = cur
    S.store.set("excel_links", links)
    return {"symbol": req.symbol, "links": cur}


@router.get("/view")
async def view(id: str):
    return _wrap(S.excel.view, id, _quote)


@router.get("/download")
async def download(id: str):
    p = _wrap(S.excel.path_for, id)
    return FileResponse(p, filename=p.name)


class WhatIfReq(BaseModel):
    id: str
    overrides: dict[str, Any]


@router.post("/whatif")
async def whatif(req: WhatIfReq):
    res = _wrap(S.excel.whatif, req.id, req.overrides, _quote)
    if res["tv_symbols"] and S.hub:  # make sure TV() symbols are streaming so values fill in
        missing = [s for s in res["tv_symbols"] if s not in S.hub.last_quotes]
        if missing:
            try:
                prov = await S.provider()
                for q in await prov.get_quotes(missing):
                    S.hub.last_quotes[q["symbol"]] = q
                res = _wrap(S.excel.whatif, req.id, req.overrides, _quote)
            except Exception:  # noqa: BLE001
                pass
    return res


class OpenReq(BaseModel):
    id: str


@router.post("/open")
async def open_native(req: OpenReq):
    return _wrap(S.excel.open_native, req.id)


class WriteReq(BaseModel):
    id: str
    sheet: str
    updates: dict[str, Any]


@router.post("/write")
async def write(req: WriteReq):
    """Edit cells (values or "=formulas"). Returns previous contents (for undo) and the refreshed view."""
    import asyncio

    try:
        res = await asyncio.to_thread(S.excel.write_cells, req.id, req.sheet, req.updates)
    except ExcelError as e:
        raise HTTPException(e.status, str(e)) from e
    res["view"] = _wrap(S.excel.view, req.id, _quote)
    return res


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    return _wrap(S.excel.save_upload, file.filename or "upload.xlsx", data)


# ---- formatting / structure / fill / trace / history ------------------------
class FormatReq(BaseModel):
    id: str
    sheet: str
    range: str
    format: dict[str, Any]   # bold, italic, font_color "RRGGBB"|null, fill "RRGGBB"|null, number_format, align


async def _thread(fn, *a):
    import asyncio

    try:
        return await asyncio.to_thread(fn, *a)
    except ExcelError as e:
        raise HTTPException(e.status, str(e)) from e


@router.post("/format")
async def format_cells(req: FormatReq):
    res = await _thread(S.excel.format_cells, req.id, req.sheet, req.range, req.format)
    res["view"] = _wrap(S.excel.view, req.id, _quote)
    return res


class StructReq(BaseModel):
    id: str
    sheet: str = ""
    op: str                  # insert_rows | delete_rows | insert_cols | delete_cols | add_sheet
    index: int = 1
    count: int = 1
    name: str = ""


@router.post("/structure")
async def structure(req: StructReq):
    res = await _thread(S.excel.structure, req.id, req.sheet, req.op,
                        {"index": req.index, "count": req.count, "name": req.name})
    res["view"] = _wrap(S.excel.view, req.id, _quote)
    return res


class FillReq(BaseModel):
    id: str
    sheet: str
    source: str              # e.g. "C5:C7"
    target: str              # e.g. "D5:H7" — relative references shift like Excel


@router.post("/fill")
async def fill(req: FillReq):
    res = await _thread(S.excel.fill, req.id, req.sheet, req.source, req.target)
    res["view"] = _wrap(S.excel.view, req.id, _quote)
    return res


@router.get("/trace")
async def trace(id: str, sheet: str, addr: str, depth: int = 1):
    return _wrap(S.excel.trace, id, sheet, addr, max(1, min(depth, 5)))


@router.get("/backups")
async def backups(id: str):
    return _wrap(S.excel.backups, id)


@router.get("/diff")
async def diff(id: str, backup: str):
    return await _thread(S.excel.diff_backup, id, backup)


class RestoreReq(BaseModel):
    id: str
    backup: str


@router.post("/restore")
async def restore(req: RestoreReq):
    return await _thread(S.excel.restore, req.id, req.backup)


@router.get("/live")
async def live(id: str):
    return await _thread(S.excel.live_values, id)


class NewReq(BaseModel):
    name: str
    years: list[str] | None = None
    sheets: list[str] | None = None


@router.post("/new")
async def new_workbook(req: NewReq):
    return _wrap(S.excel.create_workbook, req.name, req.years, req.sheets)
