"""Analytics endpoints: technicals, correlation, performance, backtest,
factor analysis and lead-lag analysis. All accept ``source=`` to choose the
data provider (TradingView / Yahoo / SIM) for the underlying history."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import analytics, factors, fourier, leadlag, quant
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
                      end_offset: int = Query(0, ge=0, le=2000), source: str | None = SOURCE):
    from .window import cut_series

    iv = interval_or_400(interval)
    series, errors = await _many(symbols_or_400(symbols, 30), iv, bars + end_offset, source)
    series, cut = cut_series(series, end_offset)
    series = {k: v[-bars:] for k, v in series.items()}
    return {"interval": iv, **analytics.correlation_matrix(series), "errors": errors, "asof": cut}


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


# ---- quant tools (BETA / SPRD / SEAS / EVT / PORT RISK / RV / EARN) -------
@router.get("/beta")
async def beta(symbol: str, benchmark: str = "SP:SPX", interval: str = "1D", bars: int = Query(500, ge=30, le=3000),
               end_offset: int = Query(0, ge=0, le=2000), source: str | None = SOURCE):
    from .window import cut_series

    iv = interval_or_400(interval)
    series, errors = await _many([symbol, benchmark], iv, bars + end_offset, source)
    if len(series) < 2:
        raise HTTPException(502, f"history unavailable: {errors}")
    series, _ = cut_series(series, end_offset, symbol)
    series = {k: v[-bars:] for k, v in series.items()}
    res = quant.beta_regression(series[symbol], series[benchmark], analytics.periods_per_year(iv))
    return {"symbol": symbol, "benchmark": benchmark, "interval": iv, **res}


@router.get("/spread")
async def spread(a: str, b: str, window: int = Query(60, ge=10, le=500), entry_z: float = 2.0,
                 bars: int = Query(750, ge=60, le=3000), source: str | None = SOURCE):
    series, errors = await _many([a, b], "1D", bars, source)
    if len(series) < 2:
        raise HTTPException(502, f"history unavailable: {errors}")
    return {"a": a, "b": b, **quant.pair_spread(series[a], series[b], window, entry_z)}


@router.get("/seasonality")
async def seasonality(symbol: str, bars: int = Query(3000, ge=60, le=5000), source: str | None = SOURCE):
    data = await S.history(symbol, "1D", bars, source)
    return {"symbol": symbol, **quant.seasonality(data)}


class EventReq(BaseModel):
    symbol: str
    benchmark: str = "SP:SPX"
    events: list[str] = []          # ISO dates; empty -> auto-detect large-move days
    pre: int = Field(5, ge=0, le=30)
    post: int = Field(10, ge=1, le=60)
    est_window: int = Field(120, ge=30, le=500)
    source: str | None = None


@router.post("/event_study")
async def event_study(req: EventReq):
    series, errors = await _many([req.symbol, req.benchmark], "1D", 1500, req.source)
    if len(series) < 2:
        raise HTTPException(502, f"history unavailable: {errors}")
    events = req.events or quant.big_move_days(series[req.symbol])
    res = quant.event_study(series[req.symbol], series[req.benchmark], events, req.pre, req.post, req.est_window)
    return {"symbol": req.symbol, "benchmark": req.benchmark, "auto_events": not req.events, **res}


class RiskReq(BaseModel):
    positions: list[dict[str, Any]]   # [{symbol, qty}]
    benchmark: str | None = "SP:SPX"
    base_currency: str = "USD"
    include_fx: bool = True           # convert each position's returns into the base currency
    lookback: int = Field(252, ge=30, le=2000)
    source: str | None = None


@router.post("/portfolio_risk")
async def portfolio_risk(req: RiskReq):
    syms = sorted({p["symbol"] for p in req.positions if p.get("symbol") and p.get("qty")})
    if not syms:
        raise HTTPException(400, "no positions")
    series, errors = await _many(syms + ([req.benchmark] if req.benchmark else []), "1D", req.lookback + 30, req.source)
    pos = [{"symbol": p["symbol"], "qty": float(p["qty"])} for p in req.positions if p.get("symbol") in series]
    base = req.base_currency.upper()
    fx, fx_err = await _fx_to_base(syms, base, req.source)
    errors.update(fx_err)
    fx_series = await _fx_series(syms, base, req.lookback + 30, req.source) if req.include_fx else {}
    res = quant.portfolio_risk(pos, {s: series[s] for s in syms if s in series},
                               series.get(req.benchmark) if req.benchmark else None, req.lookback,
                               fx, base, fx_series)
    return {**res, "errors": errors}


async def _fx_series(symbols: list[str], base: str, bars: int, source: str | None) -> dict[str, dict[str, float]]:
    """{symbol: {date: base per 1 unit of the symbol's currency}} for non-base-currency symbols."""
    out: dict[str, dict[str, float]] = {}
    cache: dict[str, dict[str, float]] = {}
    for s in symbols:
        ccy = quant.currency_of(s)
        if ccy == base:
            continue
        if ccy not in cache:
            cache[ccy] = {}
            for pair, invert in quant.fx_pairs(ccy, base):
                try:
                    b = await S.history(pair, "1D", bars, source)
                except HTTPException:
                    continue
                if b:
                    cache[ccy] = {d: (1 / v if invert else v) for d, v in quant.closes_by_date(b).items()}
                    break
        if cache[ccy]:
            out[s] = cache[ccy]
    return out


class PairBtReq(BaseModel):
    a: str
    b: str
    hedge_window: int = Field(120, ge=20, le=750)
    z_window: int = Field(60, ge=10, le=500)
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 4.0
    fee_bps: float = Field(5.0, ge=0, le=200)
    bars: int = Field(1500, ge=200, le=5000)
    source: str | None = None


@router.post("/pair_backtest")
async def pair_backtest(req: PairBtReq):
    series, errors = await _many([req.a, req.b], "1D", req.bars, req.source)
    if len(series) < 2:
        raise HTTPException(502, f"history unavailable: {errors}")
    return {"a": req.a, "b": req.b, **quant.pair_backtest(series[req.a], series[req.b], req.hedge_window, req.z_window,
                                                          req.entry_z, req.exit_z, req.stop_z, req.fee_bps)}


@router.get("/blotter")
async def blotter():
    """Positions & realized P&L derived from the trade blotter (store key 'trades')."""
    return quant.blotter_positions(S.store.get("trades") or [])


async def _fx_to_base(symbols: list[str], base: str, source: str | None) -> tuple[dict[str, float], dict[str, str]]:
    """Latest FX rate (units of base per 1 unit of each symbol's currency) using FX:XXXYYY daily closes."""
    rates: dict[str, float] = {}
    errors: dict[str, str] = {}
    cache: dict[str, float | None] = {base: 1.0}
    for s in symbols:
        ccy = quant.currency_of(s)
        if ccy not in cache:
            cache[ccy] = None
            for pair, invert in quant.fx_pairs(ccy, base):
                try:
                    bars = await S.history(pair, "1D", 5, source)
                    if bars:
                        cache[ccy] = 1 / bars[-1]["close"] if invert else bars[-1]["close"]
                        break
                except HTTPException as e:
                    errors[f"fx {pair}"] = str(e.detail)
        if cache[ccy] is None:
            errors[f"fx {ccy}{base}"] = "rate unavailable — value not converted"
        rates[s] = cache[ccy] or 1.0
    return rates, errors


RV_FIELDS = ["market_cap_basic", "price_earnings_ttm", "price_book_ratio", "enterprise_value_ebitda_ttm",
             "dividend_yield_recent", "return_on_equity", "gross_margin", "operating_margin", "net_margin",
             "debt_to_equity", "beta_1_year", "Perf.1M", "Perf.YTD", "Perf.Y"]
RV_FALLBACK = ["market_cap_basic", "price_earnings_ttm", "price_book_ratio", "dividend_yield_recent",
               "return_on_equity", "beta_1_year", "Perf.1M", "Perf.Y"]


@router.get("/relative_value")
async def relative_value(symbol: str, peers: str, source: str | None = SOURCE):
    """Peer comparison: scanner fundamentals (TradingView) + performance from history (any source)."""
    syms = [symbol] + [p for p in symbols_or_400(peers, 40) if p != symbol]
    rows: dict[str, dict[str, Any]] = {s: {} for s in syms}
    errors: dict[str, str] = {}
    if (source or S.registry.active_name) != "sim":
        try:
            scanned = await S.web.scan_symbols(syms, ["description", *RV_FIELDS], ["description", *RV_FALLBACK])
            for s, d in scanned.items():
                if s in rows:
                    rows[s].update(d)
        except ProviderError as e:
            errors["scanner"] = str(e)
    series, herr = await _many(syms, "1D", 400, source)
    errors.update(herr)
    for s, b in series.items():
        perf = analytics.performance(b)
        rows[s].update({"hist_1M": perf.get("1M"), "hist_YTD": perf.get("YTD"), "hist_1Y": perf.get("1Y"),
                        "vol_1Y": perf.get("VOL_1Y")})
    fields = RV_FIELDS + ["hist_1M", "hist_YTD", "hist_1Y", "vol_1Y"]
    return {"symbol": symbol, "peers": syms, "rows": rows, "stats": quant.peer_stats(rows, symbol, fields),
            "errors": errors}


EARN_COLUMNS = ["description", "earnings_release_next_date", "earnings_release_date",
                "earnings_per_share_forecast_next_fq", "earnings_per_share_fq", "revenue_forecast_next_fq",
                "market_cap_basic", "close", "change"]
EARN_FALLBACK = ["description", "earnings_release_next_date", "earnings_release_date", "close", "change"]


@router.get("/earnings")
async def earnings(symbols: str):
    """Next / last earnings dates and estimates for a list of symbols (TradingView scanner; columns unverified)."""
    syms = symbols_or_400(symbols, 150)
    if S.registry.active_name == "sim":
        return {"rows": [], "errors": ["earnings calendar disabled in SIM mode"]}
    try:
        data = await S.web.scan_symbols(syms, EARN_COLUMNS, EARN_FALLBACK)
    except ProviderError as e:
        return {"rows": [], "errors": [str(e)]}
    rows = [{"symbol": s, **d} for s, d in data.items()]
    rows.sort(key=lambda r: r.get("earnings_release_next_date") or 9e18)
    return {"rows": rows, "errors": []}



# ---- Fourier / cycles (CYCL) ----------------------------------------------
@router.get("/fourier")
async def fourier_analysis(symbol: str, interval: str = "1D", bars: int = Query(750, ge=64, le=5000),
                           k: int = Query(3, ge=1, le=10), horizon: int = Query(20, ge=1, le=250),
                           detrend: str = "loglinear", source: str | None = SOURCE):
    iv = interval_or_400(interval)
    data = await S.history(symbol, iv, bars, source)
    closes = [b["close"] for b in data]
    if detrend not in ("loglinear", "linear"):
        raise HTTPException(400, "detrend must be loglinear or linear")
    try:
        pg = fourier.periodogram(closes, detrend, top=10)
        fc = fourier.harmonic_forecast(closes, horizon, k, detrend)
        bt = fourier.backtest(closes, min(horizon, max(5, len(closes) // 10)), k, detrend,
                              min_train=max(64, len(closes) // 2))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    step = data[-1]["time"] - data[-2]["time"] if len(data) > 1 else 86400
    future_t = [data[-1]["time"] + step * (i + 1) for i in range(horizon)]
    return {"symbol": symbol, "interval": iv, "periodogram": {**pg, "spectrum": pg["spectrum"][:400]},
            "fit": {k2: v for k2, v in fc.items() if k2 not in ("fitted", "forecast", "lower", "upper")},
            "series": {"price": [{"time": b["time"], "value": b["close"]} for b in data],
                       "fitted": [{"time": b["time"], "value": v} for b, v in zip(data, fc["fitted"])],
                       "forecast": [{"time": t, "value": v} for t, v in zip(future_t, fc["forecast"])],
                       "lower": [{"time": t, "value": v} for t, v in zip(future_t, fc["lower"])],
                       "upper": [{"time": t, "value": v} for t, v in zip(future_t, fc["upper"])]},
            "backtest": bt,
            "note": "In-sample fit (R²) says little; judge by the out-of-sample skill vs naive."}
