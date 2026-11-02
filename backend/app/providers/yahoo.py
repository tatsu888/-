"""Yahoo Finance provider (unofficial chart/search endpoints, polling).

Used as an alternative/backup to TradingView. Symbols stay in TradingView
notation at the API boundary and are translated with ``to_yahoo``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from ..intervals import bucket_start
from ..models import Bar, Quote, make_bar, make_quote
from ..universe import label_for
from .base import BarKey, Provider, ProviderError

log = logging.getLogger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"

# explicit TradingView -> Yahoo symbol map (indices, futures, rates ...)
SYMBOL_MAP: dict[str, str] = {
    "SP:SPX": "^GSPC", "NASDAQ:NDX": "^NDX", "DJ:DJI": "^DJI", "TVC:RUT": "^RUT", "TVC:VIX": "^VIX",
    "TVC:SX5E": "^STOXX50E", "TVC:UKX": "^FTSE", "XETR:DAX": "^GDAXI", "TVC:CAC40": "^FCHI",
    "TVC:NI225": "^N225", "TVC:TOPIX": "^TOPX", "TVC:HSI": "^HSI", "SSE:000001": "000001.SS",
    "TVC:KOSPI": "^KS11", "TVC:DXY": "DX-Y.NYB",
    "TVC:US10Y": "^TNX", "TVC:US30Y": "^TYX",  # no reliable Yahoo symbol for US02Y/DE10Y/GB10Y/JP10Y
    "TVC:GOLD": "GC=F", "TVC:SILVER": "SI=F", "TVC:USOIL": "CL=F", "TVC:UKOIL": "BZ=F",
    "COMEX:HG1!": "HG=F", "NYMEX:NG1!": "NG=F",
}
_EXCHANGE_SUFFIX = {"TSE": ".T", "LSE": ".L", "XETR": ".DE", "HKEX": ".HK", "TSX": ".TO", "ASX": ".AX",
                    "EURONEXT": ".PA", "SIX": ".SW", "KRX": ".KS"}

# canonical interval -> (yahoo interval, range); 240 is resampled from 60m
_INTERVALS: dict[str, tuple[str, str]] = {
    "1": ("1m", "5d"), "5": ("5m", "1mo"), "15": ("15m", "1mo"), "30": ("30m", "1mo"),
    "60": ("60m", "6mo"), "240": ("60m", "2y"), "1D": ("1d", "5y"), "1W": ("1wk", "10y"),
    "1M": ("1mo", "max"),
}


def to_yahoo(symbol: str) -> str:
    if symbol in SYMBOL_MAP:
        return SYMBOL_MAP[symbol]
    if ":" not in symbol:
        return symbol
    ex, tk = symbol.split(":", 1)
    if ex in ("FX", "FX_IDC", "OANDA", "FOREXCOM") and len(tk) == 6:
        return f"{tk}=X"
    if ex in ("BINANCE", "COINBASE", "BITSTAMP", "KRAKEN", "BYBIT"):
        for quote in ("USDT", "USDC", "USD"):
            if tk.endswith(quote):
                return f"{tk[: -len(quote)]}-USD"
    return tk + _EXCHANGE_SUFFIX.get(ex, "")


def resample(bars: list[Bar], interval: str) -> list[Bar]:
    out: dict[int, Bar] = {}
    for b in bars:
        t = bucket_start(b["time"], interval)
        cur = out.get(t)
        if cur is None:
            out[t] = make_bar(t, b["open"], b["high"], b["low"], b["close"], b["volume"])
        else:
            out[t] = make_bar(t, cur["open"], max(cur["high"], b["high"]), min(cur["low"], b["low"]),
                              b["close"], cur["volume"] + b["volume"])
    return [out[t] for t in sorted(out)]


def parse_chart(data: dict) -> tuple[dict, list[Bar]]:
    try:
        res = data["chart"]["result"][0]
    except (KeyError, IndexError, TypeError) as e:
        err = (data.get("chart") or {}).get("error") if isinstance(data, dict) else None
        raise ProviderError(f"yahoo chart: {err or 'no result'}") from e
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue
        bars.append(make_bar(t, o, h, l, c, (q.get("volume") or [0] * len(ts))[i]))
    return meta, bars


class YahooProvider(Provider):
    name = "yahoo"
    description = "Yahoo Finance (unofficial, polling)"

    def __init__(self, poll_sec: float = 5.0, http: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self.poll_sec = poll_sec
        self._http = http or httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        self._quote_syms: set[str] = set()
        self._bar_subs: set[BarKey] = set()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self.status = "connected"
        self._task = asyncio.create_task(self._loop(), name="yahoo-poll")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        await self._http.aclose()
        self.status = "stopped"

    async def _chart(self, symbol: str, interval: str, rng: str) -> tuple[dict, list[Bar]]:
        try:
            r = await self._http.get(CHART_URL.format(sym=to_yahoo(symbol)),
                                     params={"interval": interval, "range": rng, "includePrePost": "false"})
            data = r.json()
        except Exception as e:  # noqa: BLE001
            self.status, self.status_detail = "error", str(e)
            raise ProviderError(f"yahoo request failed: {e}") from e
        self.status, self.status_detail = "connected", ""
        return parse_chart(data)

    def _meta_quote(self, symbol: str, meta: dict[str, Any]) -> Quote:
        return make_quote(
            symbol, self.name,
            name=meta.get("longName") or meta.get("shortName") or label_for(symbol),
            exchange=meta.get("exchangeName"), currency=meta.get("currency"),
            type=(meta.get("instrumentType") or "").lower() or None,
            last=meta.get("regularMarketPrice"),
            prev_close=meta.get("chartPreviousClose") or meta.get("previousClose"),
            high=meta.get("regularMarketDayHigh"), low=meta.get("regularMarketDayLow"),
            volume=meta.get("regularMarketVolume"), time=meta.get("regularMarketTime"),
            delay_sec=None,
        )

    async def _loop(self) -> None:
        while True:
            for sym in list(self._quote_syms):
                try:
                    meta, _ = await self._chart(sym, "1d", "1d")
                    await self.emit_quote(self._meta_quote(sym, meta))
                except ProviderError as e:
                    log.debug("yahoo poll %s: %s", sym, e)
            for sym, iv in list(self._bar_subs):
                try:
                    bars = await self.get_history(sym, iv, 2)
                    if bars:
                        await self.emit_bar(sym, iv, bars[-1])
                except ProviderError as e:
                    log.debug("yahoo bars %s: %s", sym, e)
            await asyncio.sleep(self.poll_sec)

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        async def one(s: str) -> Quote:
            try:
                meta, _ = await self._chart(s, "1d", "1d")
                return self._meta_quote(s, meta)
            except ProviderError as e:
                return make_quote(s, self.name, error=str(e))
        return list(await asyncio.gather(*(one(s) for s in symbols)))

    async def get_history(self, symbol: str, interval: str, bars: int) -> list[Bar]:
        yi, rng = _INTERVALS[interval]
        _, out = await self._chart(symbol, yi, rng)
        if interval == "240":
            out = resample(out, "240")
        return out[-bars:]

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        try:
            r = await self._http.get(SEARCH_URL, params={"q": query, "quotesCount": limit, "newsCount": 0})
            items = r.json().get("quotes", [])
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"yahoo search failed: {e}") from e
        return [{"symbol": it.get("symbol"), "ticker": it.get("symbol"), "exchange": it.get("exchange", ""),
                 "description": it.get("longname") or it.get("shortname") or "", "type": it.get("quoteType", "")}
                for it in items[:limit]]

    async def set_quote_symbols(self, symbols: set[str]) -> None:
        self._quote_syms = set(symbols)

    async def set_bar_subscriptions(self, subs: set[BarKey]) -> None:
        self._bar_subs = set(subs)
