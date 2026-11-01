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
    return _wrap(S.excel.view, id)


@router.get("/download")
async def download(id: str):
    p = _wrap(S.excel.path_for, id)
    return FileResponse(p, filename=p.name)


class WhatIfReq(BaseModel):
    id: str
    overrides: dict[str, Any]


@router.post("/whatif")
async def whatif(req: WhatIfReq):
    return _wrap(S.excel.whatif, req.id, req.overrides, _quote)


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
    return _wrap(S.excel.write_cells, req.id, req.sheet, req.updates)


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    return _wrap(S.excel.save_upload, file.filename or "upload.xlsx", data)
