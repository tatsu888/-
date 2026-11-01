"""FastAPI entry point.

Run (dev):   uvicorn app.main:app --reload --port 8000     (from backend/)
Docs:        http://localhost:8000/docs  (OpenAPI), docs/API.md
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics
from .alerts import CONDITIONS, AlertEngine
from .config import settings
from .hub import Client, Hub
from .intervals import INTERVAL_SECONDS, normalize_interval
from .models import Bar
from .providers import ProviderError, create_provider
from .providers.tv_web import TVWeb
from .store import ALLOWED_KEYS, Store
from .universe import TAPE, UNIVERSE

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("terminal")

DATA_DIR = Path(os.environ.get("TERMINAL_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
STARTED = time.time()


class State:
    provider = create_provider(settings)
    store = Store(DATA_DIR / "store.json")
    alerts = AlertEngine(store)
    hub = Hub(provider, settings.push_interval_sec, alerts)
    web = TVWeb()
    hist_cache: dict[tuple[str, str, int], tuple[float, list[Bar]]] = {}


S = State


@asynccontextmanager
async def lifespan(_: FastAPI):
    await S.provider.start()
    await S.hub.start()
    await S.hub.resync()  # subscribe alert symbols
    log.info("provider=%s started", S.provider.name)
    yield
    await S.hub.stop()
    await S.provider.stop()
    await S.web.close()


app = FastAPI(title="Analyst Terminal API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                   allow_headers=["*"])


def _interval(v: str) -> str:
    try:
        return normalize_interval(v)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _symbols(v: str) -> list[str]:
    syms = [s.strip() for s in v.split(",") if s.strip()]
    if not syms:
        raise HTTPException(400, "symbols required")
    if len(syms) > 200:
        raise HTTPException(400, "too many symbols (max 200)")
    return syms


async def history(symbol: str, interval: str, bars: int) -> list[Bar]:
    key = (symbol, interval, bars)
    ttl = 15 if INTERVAL_SECONDS[interval] < 86400 else 120
    hit = S.hist_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        data = await S.provider.get_history(symbol, interval, bars)
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    S.hist_cache[key] = (time.time(), data)
    if len(S.hist_cache) > 500:
        S.hist_cache.pop(next(iter(S.hist_cache)))
    return data


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {**S.provider.health(), "uptime_sec": int(time.time() - STARTED),
            "clients": len(S.hub.clients), "server_time": int(time.time())}


@app.get("/api/universe")
async def universe() -> dict[str, Any]:
    return {"lists": UNIVERSE, "tape": TAPE, "intervals": list(INTERVAL_SECONDS),
            "strategies": analytics.STRATEGIES, "alert_conditions": CONDITIONS}


# ---------------------------------------------------------------------------
# market data
# ---------------------------------------------------------------------------
@app.get("/api/quotes")
async def quotes(symbols: str = Query(..., description="comma separated, e.g. NASDAQ:AAPL,FX:USDJPY")):
    try:
        return await S.provider.get_quotes(_symbols(symbols))
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/history")
async def get_history(symbol: str, interval: str = "1D", bars: int = Query(300, ge=2, le=5000)):
    iv = _interval(interval)
    return {"symbol": symbol, "interval": iv, "bars": await history(symbol, iv, bars), "source": S.provider.name}


@app.get("/api/history.csv", response_class=PlainTextResponse)
async def get_history_csv(symbol: str, interval: str = "1D", bars: int = Query(1000, ge=2, le=5000)):
    iv = _interval(interval)
    data = await history(symbol, iv, bars)
    fname = f"{symbol.replace(':', '_')}_{iv}.csv"
    return PlainTextResponse(analytics.bars_to_csv(symbol, data), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)):
    try:
        return await S.provider.search(q, limit)
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/screener")
async def screener(market: str = "america", preset: str = "most_active", limit: int = Query(25, ge=1, le=100)):
    try:
        return await S.provider.screener(market, preset, limit)
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e


@app.get("/api/fundamentals")
async def fundamentals(symbol: str):
    """TradingView scanner fields + performance computed from daily history (works with every provider)."""
    out: dict[str, Any] = {"symbol": symbol, "fields": {}, "errors": []}
    if S.provider.name != "sim":
        try:
            out.update(await S.web.fundamentals(symbol))
        except ProviderError as e:
            out["errors"].append(str(e))
    try:
        daily = await history(symbol, "1D", 400)
        out["performance"] = analytics.performance(daily)
    except HTTPException as e:
        out["errors"].append(f"history: {e.detail}")
    out.setdefault("errors", [])
    return out


@app.get("/api/news")
async def news(symbol: str | None = None, lang: str = "en", limit: int = Query(50, ge=1, le=200)):
    errors: list[str] = []
    if S.provider.name == "sim":
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


@app.get("/api/calendar")
async def calendar(days_back: int = Query(1, ge=0, le=30), days_ahead: int = Query(7, ge=0, le=60),
                   countries: str = "US,JP,EU,GB,CN,DE"):
    if S.provider.name == "sim":
        return {"items": [], "errors": ["economic calendar disabled in SIM mode"]}
    now = dt.datetime.now(dt.timezone.utc)
    try:
        items = await S.web.calendar(now - dt.timedelta(days=days_back), now + dt.timedelta(days=days_ahead),
                                     [c.strip().upper() for c in countries.split(",") if c.strip()])
        return {"items": items, "errors": []}
    except ProviderError as e:
        return {"items": [], "errors": [str(e)]}


# ---------------------------------------------------------------------------
# analytics
# ---------------------------------------------------------------------------
@app.get("/api/analytics/technicals")
async def technicals(symbol: str, interval: str = "1D"):
    iv = _interval(interval)
    return {"symbol": symbol, "interval": iv, **analytics.technical_rating(await history(symbol, iv, 300))}


@app.get("/api/analytics/correlation")
async def correlation(symbols: str, interval: str = "1D", bars: int = Query(250, ge=10, le=2000)):
    iv = _interval(interval)
    syms = _symbols(symbols)[:30]
    results = await asyncio.gather(*(history(s, iv, bars) for s in syms), return_exceptions=True)
    series, errors = {}, {}
    for s, r in zip(syms, results):
        if isinstance(r, Exception):
            errors[s] = getattr(r, "detail", str(r))
        else:
            series[s] = r
    return {"interval": iv, **analytics.correlation_matrix(series), "errors": errors}


@app.get("/api/analytics/performance")
async def performance(symbols: str):
    syms = _symbols(symbols)[:50]
    results = await asyncio.gather(*(history(s, "1D", 400) for s in syms), return_exceptions=True)
    return {s: (analytics.performance(r) if not isinstance(r, Exception) else {"error": getattr(r, "detail", str(r))})
            for s, r in zip(syms, results)}


class BacktestReq(BaseModel):
    symbol: str
    interval: str = "1D"
    bars: int = Field(1000, ge=50, le=5000)
    strategy: str = "sma_cross"
    params: dict[str, Any] = {}
    allow_short: bool = False
    fee_bps: float = Field(5.0, ge=0, le=500)


@app.post("/api/analytics/backtest")
async def backtest(req: BacktestReq):
    iv = _interval(req.interval)
    data = await history(req.symbol, iv, req.bars)
    try:
        res = analytics.backtest(data, req.strategy, req.params, allow_short=req.allow_short,
                                 fee_bps=req.fee_bps, periods_per_year=analytics.periods_per_year(iv))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"symbol": req.symbol, "interval": iv, **res}


# ---------------------------------------------------------------------------
# persistence: alerts + generic store
# ---------------------------------------------------------------------------
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


@app.get("/api/alerts")
async def list_alerts():
    return S.alerts.list()


@app.post("/api/alerts")
async def create_alert(req: AlertReq):
    try:
        a = S.alerts.create(req.symbol, req.condition, req.value, req.note, req.once)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    await S.hub.resync()
    return a


@app.patch("/api/alerts/{alert_id}")
async def patch_alert(alert_id: str, req: AlertPatch):
    a = S.alerts.update(alert_id, **req.model_dump(exclude_none=True))
    if a is None:
        raise HTTPException(404, "alert not found")
    await S.hub.resync()
    return a


@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    if not S.alerts.delete(alert_id):
        raise HTTPException(404, "alert not found")
    await S.hub.resync()
    return {"ok": True}


@app.get("/api/store/{key}")
async def store_get(key: str):
    if key not in ALLOWED_KEYS or key == "alerts":
        raise HTTPException(404, f"unknown key; allowed: {[k for k in ALLOWED_KEYS if k != 'alerts']}")
    return {"key": key, "value": S.store.get(key)}


@app.put("/api/store/{key}")
async def store_put(key: str, body: dict[str, Any]):
    if key not in ALLOWED_KEYS or key == "alerts":
        raise HTTPException(404, "unknown key")
    return {"key": key, "value": S.store.set(key, body.get("value"))}


# ---------------------------------------------------------------------------
# websocket
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    client = Client(ws)
    await S.hub.add(client)
    await ws.send_json({"type": "hello", **S.provider.health()})
    try:
        while client.alive:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                try:
                    await S.hub.handle(client, msg)
                except (KeyError, TypeError) as e:
                    await ws.send_json({"type": "error", "message": f"bad message: {e}"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await S.hub.remove(client)


# ---------------------------------------------------------------------------
# static frontend (production build)
# ---------------------------------------------------------------------------
if settings.static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        f = settings.static_dir / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(settings.static_dir / "index.html")
