"""TradingView web endpoints that do not depend on the quote provider:
news headlines, economic calendar and per-symbol fundamentals (scanner).

Plus a Yahoo RSS fallback for news. All are unofficial — see docs/DATA_SOURCES.md.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from . import tv_protocol as P
from .base import ProviderError

log = logging.getLogger(__name__)

NEWS_URL = "https://news-headlines.tradingview.com/v2/headlines"
CAL_URL = "https://economic-calendar.tradingview.com/events"
SCAN_URL = "https://scanner.tradingview.com/{market}/scan"
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"

FUNDAMENTAL_COLUMNS = [
    "name", "description", "type", "exchange", "currency", "close", "change", "volume",
    "market_cap_basic", "price_earnings_ttm", "earnings_per_share_basic_ttm", "price_book_ratio",
    "dividend_yield_recent", "sector", "industry", "number_of_employees", "beta_1_year",
    "price_52_week_high", "price_52_week_low", "average_volume_10d_calc", "total_revenue", "net_income",
    "gross_margin", "operating_margin", "return_on_equity", "debt_to_equity",
    "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.YTD", "Perf.Y",
    "Recommend.All", "Recommend.MA", "Recommend.Other", "RSI",
]
MINIMAL_COLUMNS = ["name", "description", "type", "exchange", "currency", "close", "change", "volume",
                   "market_cap_basic"]

# exchange prefix -> scanner market
_MARKETS = {
    "NASDAQ": "america", "NYSE": "america", "AMEX": "america", "NYSEARCA": "america", "CBOE": "america",
    "OTC": "america", "BATS": "america", "TSE": "japan", "OSE": "japan", "NAG": "japan", "FSE": "japan",
    "SSE": "china", "SZSE": "china", "HKEX": "hongkong", "LSE": "uk", "XETR": "germany", "FWB": "germany",
    "EURONEXT": "france", "TSX": "canada", "ASX": "australia", "KRX": "korea", "TWSE": "taiwan",
    "NSE": "india", "BSE": "india", "BINANCE": "crypto", "COINBASE": "crypto", "BITSTAMP": "crypto",
    "KRAKEN": "crypto", "BYBIT": "crypto", "FX": "forex", "FX_IDC": "forex", "OANDA": "forex",
    "FOREXCOM": "forex", "TVC": "cfd", "SP": "cfd", "DJ": "cfd", "COMEX": "futures", "NYMEX": "futures",
    "CME": "futures", "CBOT": "futures", "CME_MINI": "futures",
}


def market_for(symbol: str) -> str:
    return _MARKETS.get(symbol.split(":", 1)[0].upper(), "global")


def _detail(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}: {e.response.text[:300]}"
    return f"{type(e).__name__}: {e}"


class TVWeb:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=15, headers={"Origin": P.ORIGIN, "Referer": P.ORIGIN + "/",
                                                                   "User-Agent": P.USER_AGENT})

    async def close(self) -> None:
        await self.http.aclose()

    # ---- news -----------------------------------------------------------
    async def news(self, symbol: str | None, lang: str = "en", limit: int = 50) -> list[dict[str, Any]]:
        params = {"client": "web", "lang": lang, "streaming": "false"}
        if symbol:
            params["symbol"] = symbol
        else:
            params["category"] = "base"
        try:
            r = await self.http.get(NEWS_URL, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"tradingview news failed: {_detail(e)}") from e
        items = data.get("items", []) if isinstance(data, dict) else data
        out = []
        for it in items[:limit]:
            path = it.get("storyPath") or ""
            out.append({
                "id": it.get("id"), "title": it.get("title"), "source": it.get("source") or it.get("provider"),
                "published": it.get("published"), "urgency": it.get("urgency"),
                "symbols": [s.get("symbol") for s in it.get("relatedSymbols", []) if isinstance(s, dict)],
                "url": it.get("link") or (P.ORIGIN + path if path else None),
            })
        return out

    async def yahoo_news(self, ticker: str, limit: int = 50) -> list[dict[str, Any]]:
        try:
            r = await self.http.get(YAHOO_RSS, params={"s": ticker, "region": "US", "lang": "en-US"},
                                    headers={"Origin": "", "Referer": ""})
            r.raise_for_status()
            root = ET.fromstring(r.text)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"yahoo rss failed: {_detail(e)}") from e
        return parse_rss(root, limit)

    # ---- economic calendar ------------------------------------------------
    async def calendar(self, start: dt.datetime, end: dt.datetime, countries: list[str]) -> list[dict[str, Any]]:
        params = {"from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "to": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                  "countries": ",".join(countries)}
        try:
            r = await self.http.get(CAL_URL, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"economic calendar failed: {_detail(e)}") from e
        rows = data.get("result", []) if isinstance(data, dict) else []
        out = [{
            "id": x.get("id"), "date": x.get("date"), "country": x.get("country"), "title": x.get("title"),
            "indicator": x.get("indicator"), "period": x.get("period"), "importance": x.get("importance"),
            "actual": x.get("actual"), "forecast": x.get("forecast"), "previous": x.get("previous"),
            "unit": x.get("unit"), "scale": x.get("scale"), "currency": x.get("currency"),
        } for x in rows]
        return sorted(out, key=lambda e: e.get("date") or "")

    # ---- universe scan (cross-sectional factor analysis) -------------------
    async def scan_universe(self, market: str, columns: list[str], limit: int = 500,
                            min_mcap: float = 0.0) -> list[dict[str, Any]]:
        body = {
            "columns": columns,
            "filter": [{"left": "market_cap_basic", "operation": "greater", "right": min_mcap},
                       {"left": "type", "operation": "equal", "right": "stock"}],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "range": [0, limit], "options": {"lang": "en"}, "markets": [market],
        }
        try:
            r = await self.http.post(SCAN_URL.format(market=market), content=json.dumps(body),
                                     headers={"Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"scanner failed: {_detail(e)}") from e
        return [{"symbol": row.get("s"), **dict(zip(columns, row.get("d", [])))} for row in data.get("data", [])]

    # ---- many symbols, arbitrary columns (RV peers, earnings calendar) ------
    async def scan_symbols(self, symbols: list[str], columns: list[str],
                           fallback: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """{symbol: {column: value}} — grouped per scanner market. Retries with ``fallback`` columns
        when the scanner rejects an unknown column."""
        by_market: dict[str, list[str]] = {}
        for s in symbols:
            by_market.setdefault(market_for(s), []).append(s)
        out: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for market, syms in by_market.items():
            for cols in [columns] + ([fallback] if fallback else []):
                body = {"symbols": {"tickers": syms, "query": {"types": []}}, "columns": cols}
                try:
                    r = await self.http.post(SCAN_URL.format(market=market), content=json.dumps(body),
                                             headers={"Content-Type": "application/json"})
                    r.raise_for_status()
                    for row in r.json().get("data") or []:
                        out[row.get("s")] = dict(zip(cols, row.get("d", [])))
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{market}: {_detail(e)}")
        if not out and errors:
            raise ProviderError("; ".join(errors[:3]))
        return out

    # ---- fundamentals -----------------------------------------------------
    async def fundamentals(self, symbol: str) -> dict[str, Any]:
        market = market_for(symbol)
        last_err: Exception | None = None
        for cols in (FUNDAMENTAL_COLUMNS, MINIMAL_COLUMNS):
            body = {"symbols": {"tickers": [symbol], "query": {"types": []}}, "columns": cols}
            try:
                r = await self.http.post(SCAN_URL.format(market=market), content=json.dumps(body),
                                         headers={"Content-Type": "application/json"})
                r.raise_for_status()
                data = r.json().get("data") or []
                if not data:
                    raise ProviderError(f"symbol {symbol} not found in scanner market '{market}'")
                return {"symbol": data[0].get("s", symbol), "market": market,
                        "fields": dict(zip(cols, data[0].get("d", [])))}
            except Exception as e:  # noqa: BLE001 - retry with fewer columns
                last_err = e
        raise ProviderError(f"fundamentals failed: {_detail(last_err) if last_err else 'unknown'}")


def parse_rss(root: ET.Element, limit: int = 50) -> list[dict[str, Any]]:
    out = []
    for item in root.iter("item"):
        pub = item.findtext("pubDate")
        try:
            ts = int(parsedate_to_datetime(pub).timestamp()) if pub else None
        except (TypeError, ValueError):
            ts = None
        out.append({"id": item.findtext("guid"), "title": item.findtext("title"), "source": "Yahoo Finance",
                    "published": ts, "urgency": None, "symbols": [], "url": item.findtext("link"),
                    "summary": item.findtext("description")})
        if len(out) >= limit:
            break
    return out
