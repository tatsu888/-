"""Market data, provider switching, alerts and generic store endpoints."""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import analytics
from .alerts import CONDITIONS
from .intervals import INTERVAL_SECONDS
from .providers import PROVIDERS, ProviderError
from .state import STARTED, S, interval_or_400, symbols_or_400
from .store import ALLOWED_KEYS
from .universe import TAPE, UNIVERSE

router = APIRouter(prefix="/api")
SOURCE = Query(None, description="override data source for this request: tradingview | yahoo | sim")


@router.get("/health")
async def health() -> dict[str, Any]:
    prov = S.registry.active
    return {**prov.health(), "uptime_sec": int(time.time() - STARTED),
            "clients": len(S.hub.clients) if S.hub else 0, "server_time": int(time.time())}


@router.get("/providers")
async def providers():
    return {"active": S.registry.active_name, "providers": S.registry.describe()}


class ProviderReq(BaseModel):
    name: str


@router.post("/providers/active")
async def switch_provider(req: ProviderReq):
    """Manual data-source switch (TradingView / Yahoo / SIM). Persisted in store.settings."""
    if req.name not in PROVIDERS:
        raise HTTPException(400, f"choose from {list(PROVIDERS)}")
    prov = await S.provider(req.name)
    S.registry.active_name = req.name
    await S.hub.set_provider(prov)
    settings = S.store.get("settings") or {}
    S.store.set("settings", {**settings, "provider": req.name})
    return {"active": req.name, "providers": S.registry.describe()}


@router.get("/universe")
async def universe() -> dict[str, Any]:
    from .factors import FACTOR_SETS
    from .leadlag import THEMES

    return {"lists": UNIVERSE, "tape": TAPE, "intervals": list(INTERVAL_SECONDS),
            "strategies": analytics.STRATEGIES, "alert_conditions": CONDITIONS,
            "factor_sets": FACTOR_SETS, "themes": THEMES, "providers": list(PROVIDERS)}


@router.get("/quotes")
async def quotes(symbols: str, source: str | None = SOURCE):
    prov = await S.provider(source)
    try:
        return await prov.get_quotes(symbols_or_400(symbols))
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/history")
async def history(symbol: str, interval: str = "1D", bars: int = Query(300, ge=2, le=5000),
                  source: str | None = SOURCE):
    iv = interval_or_400(interval)
    data = await S.history(symbol, iv, bars, source)
    return {"symbol": symbol, "interval": iv, "bars": data, "source": source or S.registry.active_name}


@router.get("/history.csv", response_class=PlainTextResponse)
async def history_csv(symbol: str, interval: str = "1D", bars: int = Query(1000, ge=2, le=5000),
                      source: str | None = SOURCE):
    iv = interval_or_400(interval)
    data = await S.history(symbol, iv, bars, source)
    fname = f"{symbol.replace(':', '_')}_{iv}.csv"
    return PlainTextResponse(analytics.bars_to_csv(symbol, data), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/search")
async def search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50), source: str | None = SOURCE):
    prov = await S.provider(source)
    try:
        return await prov.search(q, limit)
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/screener")
async def screener(market: str = "america", preset: str = "most_active", limit: int = Query(25, ge=1, le=100),
                   source: str | None = SOURCE):
    prov = await S.provider(source)
    try:
        return await prov.screener(market, preset, limit)
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/fundamentals")
async def fundamentals(symbol: str, source: str | None = SOURCE):
    """TradingView scanner fields + performance computed from daily history (any provider)."""
    out: dict[str, Any] = {"symbol": symbol, "fields": {}, "errors": []}
    if (source or S.registry.active_name) != "sim":
        try:
            out.update(await S.web.fundamentals(symbol))
        except ProviderError as e:
            out["errors"].append(str(e))
    try:
        out["performance"] = analytics.performance(await S.history(symbol, "1D", 400, source))
    except HTTPException as e:
        out["errors"].append(f"history: {e.detail}")
    return out


@router.get("/news")
async def news(symbol: str | None = None, lang: str = "en", limit: int = Query(50, ge=1, le=200)):
    errors: list[str] = []
    if S.registry.active_name == "sim":
        return {"items": [], "source": None, "errors": ["news disabled in SIM mode"]}
    try:
        return {"items": await S.web.news(symbol, lang, limit), "source": "tradingview", "errors": errors}
    except ProviderError as e:
        errors.append(str(e))
    if symbol:
        from .providers.yahoo import to_yahoo
        try:
            return {"items": await S.web.yahoo_news(to_yahoo(symbol), limit), "source": "yahoo", "errors": errors}
        except ProviderError as e:
            errors.append(str(e))
    return {"items": [], "source": None, "errors": errors}


@router.get("/calendar")
async def calendar(days_back: int = Query(1, ge=0, le=30), days_ahead: int = Query(7, ge=0, le=60),
                   countries: str = "US,JP,EU,GB,CN,DE"):
    if S.registry.active_name == "sim":
        return {"items": [], "errors": ["economic calendar disabled in SIM mode"]}
    now = dt.datetime.now(dt.timezone.utc)
    try:
        items = await S.web.calendar(now - dt.timedelta(days=days_back), now + dt.timedelta(days=days_ahead),
                                     [c.strip().upper() for c in countries.split(",") if c.strip()])
        return {"items": items, "errors": []}
    except ProviderError as e:
        return {"items": [], "errors": [str(e)]}


# ---- alerts --------------------------------------------------------------
class AlertReq(BaseModel):
    symbol: str
    condition: str
    value: float
    note: str = ""
    once: bool = True


class AlertPatch(BaseModel):
    active: bool | None = None
    value: float | None = None
    note: str | None = None


@router.get("/alerts")
async def list_alerts():
    return S.alerts.list()


@router.post("/alerts")
async def create_alert(req: AlertReq):
    try:
        a = S.alerts.create(req.symbol, req.condition, req.value, req.note, req.once)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await S.hub.resync()
    return a


@router.patch("/alerts/{alert_id}")
async def patch_alert(alert_id: str, req: AlertPatch):
    a = S.alerts.update(alert_id, **req.model_dump(exclude_none=True))
    if a is None:
        raise HTTPException(404, "alert not found")
    await S.hub.resync()
    return a


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    if not S.alerts.delete(alert_id):
        raise HTTPException(404, "alert not found")
    await S.hub.resync()
    return {"ok": True}


# ---- generic store (watchlists, portfolio, notes, layout, settings ...) ----
_PRIVATE = {"alerts"}


@router.get("/store/{key}")
async def store_get(key: str):
    if key not in ALLOWED_KEYS or key in _PRIVATE:
        raise HTTPException(404, f"unknown key; allowed: {[k for k in ALLOWED_KEYS if k not in _PRIVATE]}")
    return {"key": key, "value": S.store.get(key)}


@router.put("/store/{key}")
async def store_put(key: str, body: dict[str, Any]):
    if key not in ALLOWED_KEYS or key in _PRIVATE:
        raise HTTPException(404, "unknown key")
    return {"key": key, "value": S.store.set(key, body.get("value"))}


@router.get("/diagnose")
async def diagnose(symbols: bool = True, format: str = "json"):
    """Self-diagnosis of every upstream endpoint (needs internet). format=markdown for an AI-pasteable report."""
    from .diagnose import run_diagnostics, to_markdown

    rep = await run_diagnostics(symbols)
    if format == "markdown":
        return PlainTextResponse(to_markdown(rep))
    return rep
