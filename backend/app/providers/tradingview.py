"""TradingView provider.

* Real-time-ish quotes : persistent websocket "quote session"
* Live bars            : one "chart session" per (symbol, interval) subscription on that socket
* History              : short-lived websocket chart session per request
* Symbol search        : https://symbol-search.tradingview.com/symbol_search/v3/
* Screener             : https://scanner.tradingview.com/<market>/scan

Without a logged-in auth token (TV_AUTH_TOKEN) many exchanges are delayed
(e.g. 15 min). Each quote carries ``delay_sec`` derived from ``update_mode``.

IMPORTANT: these are TradingView's *internal* endpoints, not a public API.
Review TradingView's Terms of Use before relying on them. See docs/DATA_SOURCES.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx
from websockets.asyncio.client import ClientConnection, connect

from ..intervals import TV_RESOLUTION
from ..models import Bar, Quote, make_bar, make_quote
from . import tv_protocol as P
from .base import BarKey, Provider, ProviderError

log = logging.getLogger(__name__)

SEARCH_URL = "https://symbol-search.tradingview.com/symbol_search/v3/"
SCAN_URL = "https://scanner.tradingview.com/{market}/scan"

SCAN_COLUMNS = ["name", "description", "close", "change", "change_abs", "volume", "open", "high", "low",
                "market_cap_basic", "price_earnings_ttm", "exchange", "currency", "type"]

# preset -> (sort column, order, extra filters)
SCAN_PRESETS: dict[str, tuple[str, str, list[dict]]] = {
    "gainers": ("change", "desc", [{"left": "market_cap_basic", "operation": "greater", "right": 1e9}]),
    "losers": ("change", "asc", [{"left": "market_cap_basic", "operation": "greater", "right": 1e9}]),
    "most_active": ("volume", "desc", []),
    "largest": ("market_cap_basic", "desc", []),
}

_TAG = re.compile(r"</?em>")


class TradingViewProvider(Provider):
    name = "tradingview"
    description = "TradingView (unofficial websocket/scanner endpoints)"

    def __init__(self, auth_token: str = "unauthorized_user_token", ws_url: str | None = None,
                 http: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self.auth_token = auth_token
        self.ws_url = ws_url or P.WS_URL
        self._ws: ClientConnection | None = None
        self._task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._qs = P.session_id("qs")
        self._quote_syms: set[str] = set()      # symbols wanted by the hub
        self._snapshot_syms: dict[str, float] = {}  # symbol -> expiry (one-shot get_quotes)
        self._added: set[str] = set()           # symbols currently on the quote session
        self._quotes: dict[str, dict[str, Any]] = {}
        self._quote_events: dict[str, asyncio.Event] = {}
        self._bar_subs: dict[BarKey, str] = {}  # key -> chart session id
        self._cs_keys: dict[str, BarKey] = {}   # chart session id -> key
        self._http = http or httpx.AsyncClient(timeout=15, headers={"Origin": P.ORIGIN, "Referer": P.ORIGIN + "/",
                                                                    "User-Agent": P.USER_AGENT})

    # ======================================================================
    # lifecycle
    # ======================================================================
    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="tv-ws")

    async def stop(self) -> None:
        self.status = "stopped"
        if self._task:
            self._task.cancel()
        if self._ws:
            await self._ws.close()
        await self._http.aclose()

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            self.status = "connecting"
            try:
                async with self._connect() as ws:
                    self._ws = ws
                    self.status, self.status_detail = "connected", ""
                    backoff = 1.0
                    await self._init_session()
                    async for raw in ws:
                        await self._on_message(raw if isinstance(raw, str) else raw.decode())
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - reconnect on anything
                self.status, self.status_detail = "error", f"{type(e).__name__}: {e}"
                log.warning("TradingView websocket error: %s", self.status_detail)
            self._ws = None
            self._added.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def _connect(self):
        local = any(h in self.ws_url for h in ("://localhost", "://127.0.0.1"))
        return connect(self.ws_url, origin=P.ORIGIN, user_agent_header=P.USER_AGENT, max_size=None,
                       open_timeout=15, **({"proxy": None} if local else {}))

    async def _send(self, method: str, params: list[Any]) -> None:
        ws = self._ws
        if ws is None:
            return
        async with self._send_lock:
            await ws.send(P.encode(method, params))

    async def _init_session(self) -> None:
        await self._send("set_auth_token", [self.auth_token])
        await self._send("quote_create_session", [self._qs])
        await self._send("quote_set_fields", [self._qs, *P.QUOTE_FIELDS])
        await self._sync_quote_symbols()
        # re-create chart sessions after reconnect
        keys = list(self._bar_subs)
        self._bar_subs.clear()
        self._cs_keys.clear()
        for key in keys:
            await self._add_bar_sub(key)

    # ======================================================================
    # incoming
    # ======================================================================
    async def _on_message(self, raw: str) -> None:
        for payload in P.split_frames(raw):
            if P.is_heartbeat(payload):
                async with self._send_lock:
                    if self._ws is not None:
                        await self._ws.send(P.frame(payload))
                continue
            msg = P.parse_payload(payload)
            if msg is None:
                continue
            m, p = msg.get("m"), msg.get("p") or []
            if m == "qsd" and len(p) >= 2:
                await self._on_qsd(p[1])
            elif m in ("timescale_update", "du") and len(p) >= 2:
                await self._on_series(p[0], p[1])
            elif m in ("critical_error", "protocol_error"):
                self.status_detail = f"{m}: {p}"
                log.error("TradingView %s %s", m, p)

    async def _on_qsd(self, data: dict) -> None:
        sym = data.get("n")
        if not sym:
            return
        cur = self._quotes.setdefault(sym, {})
        if data.get("s") == "error":
            cur["error"] = "symbol error"
        cur.update(P.map_quote_values(data.get("v") or {}))
        ev = self._quote_events.get(sym)
        if ev is not None and (cur.get("last") is not None or cur.get("error")):
            ev.set()  # unknown symbols answer with s="error": don't wait for the timeout
        if sym in self._quote_syms:
            await self.emit_quote(self._to_quote(sym))

    async def _on_series(self, cs: str, payload: dict) -> None:
        key = self._cs_keys.get(cs)
        if key is None:
            return
        rows = P.series_bars(payload, "sds_1")
        if rows:
            r = rows[-1]
            await self.emit_bar(key[0], key[1], make_bar(r[0], r[1], r[2], r[3], r[4], r[5] if len(r) > 5 else 0))

    def _to_quote(self, sym: str) -> Quote:
        fields = dict(self._quotes.get(sym, {}))
        if isinstance(fields.get("time"), (int, float)):
            fields["time"] = int(fields["time"])
        return make_quote(sym, self.name, **fields)

    # ======================================================================
    # push subscriptions
    # ======================================================================
    async def set_quote_symbols(self, symbols: set[str]) -> None:
        self._quote_syms = set(symbols)
        await self._sync_quote_symbols()

    async def _sync_quote_symbols(self) -> None:
        now = time.time()
        self._snapshot_syms = {s: t for s, t in self._snapshot_syms.items() if t > now}
        want = self._quote_syms | set(self._snapshot_syms)
        add, remove = sorted(want - self._added), sorted(self._added - want)
        if self._ws is None:
            return
        if remove:
            await self._send("quote_remove_symbols", [self._qs, *remove])
            self._added -= set(remove)
        if add:
            await self._send("quote_add_symbols", [self._qs, *add])
            self._added |= set(add)
        if self._quote_syms:
            await self._send("quote_fast_symbols", [self._qs, *sorted(self._quote_syms)])

    async def set_bar_subscriptions(self, subs: set[BarKey]) -> None:
        for key in list(self._bar_subs):
            if key not in subs:
                cs = self._bar_subs.pop(key)
                self._cs_keys.pop(cs, None)
                await self._send("chart_delete_session", [cs])
        for key in subs:
            if key not in self._bar_subs:
                await self._add_bar_sub(key)

    async def _add_bar_sub(self, key: BarKey) -> None:
        symbol, interval = key
        cs = P.session_id("cs")
        self._bar_subs[key] = cs
        self._cs_keys[cs] = key
        await self._send("chart_create_session", [cs, ""])
        await self._send("resolve_symbol", [cs, "sds_sym_1", P.resolve_symbol_param(symbol)])
        await self._send("create_series", [cs, "sds_1", "s1", "sds_sym_1", TV_RESOLUTION[interval], 2, ""])

    # ======================================================================
    # pull
    # ======================================================================
    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        missing = [s for s in symbols if self._quotes.get(s, {}).get("last") is None]
        if missing:
            if self._ws is None:
                raise ProviderError(f"TradingView not connected ({self.status_detail or self.status})")
            expiry = time.time() + 60
            for s in missing:
                self._snapshot_syms[s] = expiry
                self._quote_events.setdefault(s, asyncio.Event())
            await self._sync_quote_symbols()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(self._quote_events[s].wait() for s in missing)), timeout=8)
            except asyncio.TimeoutError:
                pass
            for s in missing:
                self._quote_events.pop(s, None)
        return [self._to_quote(s) if s in self._quotes else
                make_quote(s, self.name, error="no data (timeout or unknown symbol)") for s in symbols]

    async def get_history(self, symbol: str, interval: str, bars: int) -> list[Bar]:
        try:
            return await asyncio.wait_for(self._fetch_history(symbol, interval, bars), timeout=20)
        except asyncio.TimeoutError as e:
            raise ProviderError(f"history timeout for {symbol}") from e
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"history failed for {symbol}: {type(e).__name__}: {e}") from e

    async def _fetch_history(self, symbol: str, interval: str, bars: int) -> list[Bar]:
        cs = P.session_id("cs")
        rows: dict[int, list] = {}
        async with self._connect() as ws:
            async def send(m: str, p: list) -> None:
                await ws.send(P.encode(m, p))

            await send("set_auth_token", [self.auth_token])
            await send("chart_create_session", [cs, ""])
            await send("resolve_symbol", [cs, "sds_sym_1", P.resolve_symbol_param(symbol)])
            await send("create_series", [cs, "sds_1", "s1", "sds_sym_1", TV_RESOLUTION[interval], bars, ""])
            async for raw in ws:
                raw = raw if isinstance(raw, str) else raw.decode()
                for payload in P.split_frames(raw):
                    if P.is_heartbeat(payload):
                        await ws.send(P.frame(payload))
                        continue
                    msg = P.parse_payload(payload)
                    if not msg:
                        continue
                    m, p = msg.get("m"), msg.get("p") or []
                    if m == "timescale_update" and len(p) >= 2:
                        for r in P.series_bars(p[1], "sds_1"):
                            rows[int(r[0])] = r
                    elif m == "series_completed":
                        return [make_bar(r[0], r[1], r[2], r[3], r[4], r[5] if len(r) > 5 else 0)
                                for _, r in sorted(rows.items())]
                    elif m in ("symbol_error", "series_error", "critical_error", "protocol_error"):
                        raise ProviderError(f"{m}: {p[1:] if len(p) > 1 else p}")
        raise ProviderError("connection closed before series_completed")

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        params = {"text": query, "hl": "0", "exchange": "", "lang": "en", "search_type": "undefined",
                  "domain": "production"}
        try:
            r = await self._http.get(SEARCH_URL, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"symbol search failed: {http_detail(e)}") from e
        items = data.get("symbols", []) if isinstance(data, dict) else data
        out = []
        for it in items[:limit]:
            ticker = _TAG.sub("", it.get("symbol", ""))
            ex = it.get("prefix") or it.get("exchange") or ""
            out.append({"symbol": f"{ex}:{ticker}" if ex else ticker, "ticker": ticker, "exchange": ex,
                        "description": _TAG.sub("", it.get("description", "")), "type": it.get("type", "")})
        return out

    async def screener(self, market: str, preset: str, limit: int = 25) -> list[Quote]:
        sort_by, order, filters = SCAN_PRESETS.get(preset, SCAN_PRESETS["most_active"])
        body = {
            "columns": SCAN_COLUMNS,
            "filter": filters,
            "sort": {"sortBy": sort_by, "sortOrder": order},
            "range": [0, limit],
            "options": {"lang": "en"},
            "markets": [market],
        }
        try:
            r = await self._http.post(SCAN_URL.format(market=market), content=json.dumps(body),
                                      headers={"Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"screener failed: {http_detail(e)}") from e
        return [parse_scan_row(row, self.name) for row in data.get("data", [])]


def http_detail(e: Exception) -> str:
    """Include the response body for HTTP errors — the scanner names the offending column there."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}: {e.response.text[:300]}"
    return f"{type(e).__name__}: {e}"


def parse_scan_row(row: dict, source: str) -> Quote:
    d = dict(zip(SCAN_COLUMNS, row.get("d", [])))
    return make_quote(
        row.get("s", d.get("name", "?")), source,
        name=d.get("description"), exchange=d.get("exchange"), currency=d.get("currency"), type=d.get("type"),
        last=d.get("close"), change=d.get("change_abs"), change_pct=d.get("change"),
        open=d.get("open"), high=d.get("high"), low=d.get("low"), volume=d.get("volume"),
        market_cap=d.get("market_cap_basic"), pe=d.get("price_earnings_ttm"),
    )
