"""Analytics endpoints: technicals, correlation, performance, backtest,
factor analysis and lead-lag analysis. All accept ``source=`` to choose the
data provider (TradingView / Yahoo / SIM) for the underlying history."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import analytics, factors, leadlag
from .models import Bar
from .providers import ProviderError
from .state import S, interval_or_400, symbols_or_400

router = APIRouter(prefix="/api/analytics")
SOURCE = Query(None, description="tradingview | yahoo | sim (default: active provider)")


async def _many(symbols: list[str], interval: str, bars: int, source: str | None
                ) -> tuple[dict[str, list[Bar]], dict[str, str]]:
    res = await asyncio.gather(*(S.history(s, interval, bars, source) for s in symbols), return_exceptions=True)
    ok, err = {}, {}
    for s, r in zip(symbols, res):
        if isinstance(r, Exception):
            err[s] = getattr(r, "detail", str(r))
        else:
            ok[s] = r
    return ok, err


@router.get("/technicals")
async def technicals(symbol: str, interval: str = "1D", source: str | None = SOURCE):
    iv = interval_or_400(interval)
    return {"symbol": symbol, "interval": iv,
            **analytics.technical_rating(await S.history(symbol, iv, 300, source))}


@router.get("/correlation")
async def correlation(symbols: str, interval: str = "1D", bars: int = Query(250, ge=10, le=2000),
                      source: str | None = SOURCE):
    iv = interval_or_400(interval)
    series, errors = await _many(symbols_or_400(symbols, 30), iv, bars, source)
    return {"interval": iv, **analytics.correlation_matrix(series), "errors": errors}


@router.get("/performance")
async def performance(symbols: str, source: str | None = SOURCE):
    series, errors = await _many(symbols_or_400(symbols, 60), "1D", 400, source)
    out: dict[str, Any] = {s: analytics.performance(b) for s, b in series.items()}
    out.update({s: {"error": e} for s, e in errors.items()})
    return out


class BacktestReq(BaseModel):
    symbol: str
    interval: str = "1D"
    bars: int = Field(1000, ge=50, le=5000)
    strategy: str = "sma_cross"
    params: dict[str, Any] = {}
    allow_short: bool = False
    fee_bps: float = Field(5.0, ge=0, le=500)
    source: str | None = None


@router.post("/backtest")
async def backtest(req: BacktestReq):
    iv = interval_or_400(req.interval)
    data = await S.history(req.symbol, iv, req.bars, req.source)
    try:
        res = analytics.backtest(data, req.strategy, req.params, allow_short=req.allow_short,
                                 fee_bps=req.fee_bps, periods_per_year=analytics.periods_per_year(iv))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"symbol": req.symbol, "interval": iv, **res}


# ---- factor analysis -----------------------------------------------------
@router.get("/factors/etf")
async def factors_etf(set: str = "US", bars: int = Query(400, ge=60, le=2000), source: str | None = SOURCE):
    cfg = factors.FACTOR_SETS.get(set)
    if cfg is None:
        raise HTTPException(404, f"unknown factor set; choose from {list(factors.FACTOR_SETS)}")
    syms = [cfg["benchmark"], *cfg["factors"].values()]
    series, errors = await _many(syms, "1D", bars, source)
    if cfg["benchmark"] not in series:
        raise HTTPException(502, f"benchmark {cfg['benchmark']} unavailable: {errors.get(cfg['benchmark'])}")
    named = {name: series[sym] for name, sym in cfg["factors"].items() if sym in series}
    rep = factors.etf_factor_report(series[cfg["benchmark"]], named)
    return {"set": set, "benchmark": cfg["benchmark"], "symbols": cfg["factors"], **rep, "errors": errors}


@router.get("/factors/cross_section")
async def factors_cross_section(market: str = "america", limit: int = Query(500, ge=50, le=2000),
                                min_mcap: float = 1e9, quantiles: int = Query(5, ge=2, le=10)):
    """Requires TradingView scanner (independent of the active quote provider)."""
    try:
        rows = await S.web.scan_universe(market, factors.SCAN_FACTOR_COLUMNS, limit, min_mcap)
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    return {"market": market, **factors.cross_sectional_factors(rows, quantiles)}


# ---- lead-lag ------------------------------------------------------------
@router.get("/leadlag/themes")
async def leadlag_themes():
    return leadlag.THEMES


@router.get("/leadlag/pair")
async def leadlag_pair(leader: str, follower: str, market: str | None = None, max_lag: int = Query(5, ge=1, le=20),
                       window: int = Query(60, ge=20, le=250), bars: int = Query(750, ge=60, le=3000),
                       source: str | None = SOURCE):
    syms = [leader, follower] + ([market] if market else [])
    series, errors = await _many(syms, "1D", bars, source)
    if leader not in series or follower not in series:
        raise HTTPException(502, f"history unavailable: {errors}")
    res = leadlag.pair_analysis(series[leader], series[follower], max_lag, window,
                                series.get(market) if market else None)
    return {"leader": leader, "follower": follower, "market": market, **res, "errors": errors}


@router.get("/leadlag/scan")
async def leadlag_scan(leader: str, followers: str, market: str | None = None, max_lag: int = Query(5, ge=1, le=20),
                       bars: int = Query(750, ge=60, le=3000), source: str | None = SOURCE):
    fl = symbols_or_400(followers, 60)
    series, errors = await _many([leader, *fl] + ([market] if market else []), "1D", bars, source)
    if leader not in series:
        raise HTTPException(502, f"leader history unavailable: {errors.get(leader)}")
    rows = leadlag.scan_leader(series[leader], {s: series[s] for s in fl if s in series}, max_lag,
                               series.get(market) if market else None)
    return {"leader": leader, "market": market, "rows": rows, "errors": errors}


@router.get("/leadlag/theme/{theme_id}")
async def leadlag_theme(theme_id: str, residualize: bool = True, max_lag: int = Query(5, ge=1, le=20),
                        bars: int = Query(750, ge=60, le=3000), source: str | None = SOURCE):
    t = next((x for x in leadlag.THEMES if x["id"] == theme_id), None)
    if t is None:
        raise HTTPException(404, "unknown theme")
    return {"theme": t, **await leadlag_scan(t["leader"], ",".join(t["followers"]),
                                             t["market"] if residualize else None, max_lag, bars, source)}
