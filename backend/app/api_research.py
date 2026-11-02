"""Research endpoints: Japan margin balances (MRGN) and attention / social trends (TRND)."""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from . import margin as M
from .state import DATA_DIR, S

router = APIRouter(prefix="/api")
_margin: M.MarginStore | None = None


def mstore() -> M.MarginStore:
    global _margin
    if _margin is None or _margin.path.parent.parent != DATA_DIR:
        _margin = M.MarginStore(DATA_DIR)
    return _margin


def _import(content: bytes, filename: str, date: str | None) -> dict[str, Any]:
    try:
        rows = M.read_file(content, filename)
        recs = M.parse_rows(rows, M._date(date) if date else None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return mstore().add(recs)


@router.post("/margin/import")
async def margin_import(file: UploadFile = File(...), date: str | None = Form(None)):
    """Upload a JPX weekly margin file (CSV / XLSX). ``date`` (YYYY-MM-DD) if the file has no date."""
    return _import(await file.read(), file.filename or "upload.csv", date)


class UrlReq(BaseModel):
    url: str
    date: str | None = None


@router.post("/margin/import_url")
async def margin_import_url(req: UrlReq):
    if not req.url.startswith("https://"):
        raise HTTPException(400, "https URL required")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(req.url)
            r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"download failed: {e}") from e
    name = req.url.split("?")[0].rsplit("/", 1)[-1] or "download.csv"
    return _import(r.content, name, req.date)


@router.get("/margin/dates")
async def margin_dates():
    st = mstore()
    return {"dates": st.dates(), "codes": len(st.data)}


@router.get("/margin/ranking")
async def margin_ranking(date: str | None = None, min_long: float = 0):
    res = M.ranking(mstore(), date, min_long)
    res["rows"] = [{k: M.finite(v) for k, v in r.items()} for r in res["rows"]]
    return res


@router.get("/margin/stock")
async def margin_stock(symbol: str, source: str | None = None):
    code = symbol.split(":")[-1]
    series = mstore().series(code)
    bars = None
    if series:
        try:
            bars = await S.history(f"TSE:{code}" if ":" not in symbol else symbol, "1D", 750, source)
        except HTTPException:
            bars = None
    res = M.stock_analysis(series, bars)
    return {"symbol": symbol, "code": code, **res}


# ---- attention: Google Trends / X / StockTwits (TRND) ----------------------
from . import attention as A  # noqa: E402
from .providers.base import ProviderError  # noqa: E402


@router.get("/trends/google")
async def google_trends(keywords: str, geo: str = "", timeframe: str = "today 12-m", symbol: str | None = None,
                        source: str | None = None):
    kws = [k.strip() for k in keywords.split(",") if k.strip()][:5]
    if not kws:
        raise HTTPException(400, "keywords required")
    gt = A.GoogleTrends()
    try:
        res = await gt.interest(kws, geo, timeframe)
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    finally:
        await gt.close()
    if symbol:
        try:
            bars = await S.history(symbol, "1D", 1500, source)
            closes = {__import__("datetime").datetime.fromtimestamp(b["time"], tz=__import__("datetime").timezone.utc)
                      .strftime("%Y-%m-%d"): b["close"] for b in bars}
            res["vs_price"] = {k: A.attention_vs_price([p for p in s if not p["partial"]], closes) for k, s in res["series"].items()}
        except HTTPException as e:
            res["vs_price_error"] = str(e.detail)
    return res


@router.get("/social/x")
async def social_x(query: str, lang: str | None = None):
    x = A.XClient()
    try:
        return await x.analyze(query, lang)
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    finally:
        await x.close()


@router.get("/social/stocktwits")
async def social_stocktwits(symbol: str | None = None):
    st = A.StockTwits()
    try:
        if symbol:
            return await st.symbol(symbol.split(":")[-1])
        return {"trending": await st.trending()}
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    finally:
        await st.close()
