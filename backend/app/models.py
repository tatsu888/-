"""Normalized data shapes passed between providers, hub and API.

Quotes and bars are plain dicts (JSON-ready) so they can be pushed over the
websocket without conversion. The helpers below are the single place that
defines their keys — keep docs/API.md in sync when changing them.
"""
from __future__ import annotations

import time
from typing import Any, TypedDict


class Quote(TypedDict, total=False):
    symbol: str            # canonical "EXCHANGE:TICKER" (TradingView style)
    name: str | None
    exchange: str | None
    currency: str | None
    type: str | None       # stock / index / forex / crypto / futures ...
    last: float | None
    change: float | None
    change_pct: float | None
    open: float | None
    high: float | None
    low: float | None
    prev_close: float | None
    volume: float | None
    bid: float | None
    ask: float | None
    market_cap: float | None
    pe: float | None
    eps: float | None
    div_yield: float | None
    time: int | None       # epoch seconds of the last trade/update
    delay_sec: int | None  # 0 = real-time, 900 = 15min delayed, None = unknown
    source: str            # provider name: tradingview / yahoo / sim
    error: str | None


class Bar(TypedDict):
    time: int     # bar open time, epoch seconds UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


QUOTE_KEYS = tuple(Quote.__annotations__.keys())


def make_quote(symbol: str, source: str, **fields: Any) -> Quote:
    q: dict[str, Any] = {k: None for k in QUOTE_KEYS}
    q.update(fields)
    q["symbol"] = symbol
    q["source"] = source
    if q.get("time") is None:
        q["time"] = int(time.time())
    # derive change / change_pct when the source only gives last + prev_close
    last, prev = q.get("last"), q.get("prev_close")
    if last is not None and prev:
        if q.get("change") is None:
            q["change"] = last - prev
        if q.get("change_pct") is None:
            q["change_pct"] = (last - prev) / prev * 100.0
    return q  # type: ignore[return-value]


def make_bar(t: int, o: float, h: float, l: float, c: float, v: float | None) -> Bar:
    return {"time": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c),
            "volume": float(v or 0.0)}
