"""Subscription hub: fan-out between browser websockets and the provider.

* Each browser connection is a ``Client`` with its own quote symbols and bar subscriptions.
* The hub keeps the union of all clients' interests and pushes it to the provider
  (``set_quote_symbols`` / ``set_bar_subscriptions``).
* Updates are coalesced per client and flushed every ``push_interval`` seconds,
  so a fast feed cannot flood a slow browser.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from .alerts import AlertEngine
from .models import Bar, Quote
from .providers.base import BarKey, Provider

log = logging.getLogger(__name__)


class Client:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.symbols: set[str] = set()
        self.bars: set[BarKey] = set()
        self.pending_quotes: dict[str, Quote] = {}
        self.pending_bars: dict[BarKey, Bar] = {}
        self.alive = True


class Hub:
    def __init__(self, provider: Provider, push_interval: float = 0.25,
                 alerts: AlertEngine | None = None) -> None:
        self.provider = provider
        self.alerts = alerts
        self.push_interval = push_interval
        self.clients: set[Client] = set()
        self.last_quotes: dict[str, Quote] = {}
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        provider.on_quote = self._on_quote
        provider.on_bar = self._on_bar

    async def set_provider(self, provider: Provider) -> None:
        """Switch the streaming source at runtime (manual TradingView / Yahoo / SIM toggle)."""
        old = self.provider
        if old is provider:
            return
        old.on_quote = None
        old.on_bar = None
        await old.set_quote_symbols(set())
        await old.set_bar_subscriptions(set())
        self.provider = provider
        provider.on_quote = self._on_quote
        provider.on_bar = self._on_bar
        self.last_quotes.clear()
        await self.resync()
        await self.broadcast({"type": "provider", **provider.health()})

    async def start(self) -> None:
        self._flush_task = asyncio.create_task(self._flush_loop(), name="hub-flush")

    async def stop(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()

    # ---- provider callbacks ---------------------------------------------
    async def _on_quote(self, q: Quote) -> None:
        sym = q["symbol"]
        self.last_quotes[sym] = q
        for c in self.clients:
            if sym in c.symbols:
                c.pending_quotes[sym] = q
        if self.alerts is not None:
            fired = self.alerts.evaluate(q)
            for a in fired:
                await self.broadcast({"type": "alert", "alert": a})
            if fired:
                await self.resync()

    async def broadcast(self, msg: dict[str, Any]) -> None:
        for c in list(self.clients):
            try:
                await c.ws.send_json(msg)
            except Exception:  # noqa: BLE001
                c.alive = False

    def _on_bar(self, symbol: str, interval: str, bar: Bar) -> None:
        key = (symbol, interval)
        for c in self.clients:
            if key in c.bars:
                c.pending_bars[key] = bar

    # ---- client management ----------------------------------------------
    async def add(self, client: Client) -> None:
        self.clients.add(client)

    async def remove(self, client: Client) -> None:
        client.alive = False
        self.clients.discard(client)
        await self.resync()

    async def handle(self, client: Client, msg: dict[str, Any]) -> None:
        """Process one JSON command from a browser. See docs/API.md (WebSocket)."""
        op = msg.get("op")
        if op == "subscribe":
            syms = {s for s in msg.get("symbols", []) if isinstance(s, str) and s}
            client.symbols |= syms
            # send cached values immediately so panels fill without waiting for the next tick
            for s in syms:
                if s in self.last_quotes:
                    client.pending_quotes[s] = self.last_quotes[s]
        elif op == "unsubscribe":
            client.symbols -= set(msg.get("symbols", []))
        elif op == "set_symbols":
            client.symbols = {s for s in msg.get("symbols", []) if isinstance(s, str) and s}
            for s in client.symbols:
                if s in self.last_quotes:
                    client.pending_quotes[s] = self.last_quotes[s]
        elif op == "subscribe_bars":
            client.bars.add((msg["symbol"], msg["interval"]))
        elif op == "unsubscribe_bars":
            client.bars.discard((msg["symbol"], msg["interval"]))
        elif op == "ping":
            await client.ws.send_json({"type": "pong", "t": msg.get("t")})
            return
        else:
            await client.ws.send_json({"type": "error", "message": f"unknown op {op!r}"})
            return
        await self.resync()

    async def resync(self) -> None:
        async with self._lock:
            syms: set[str] = set(self.alerts.symbols()) if self.alerts else set()
            bars: set[BarKey] = set()
            for c in self.clients:
                syms |= c.symbols
                bars |= c.bars
            await self.provider.set_quote_symbols(syms)
            await self.provider.set_bar_subscriptions(bars)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.push_interval)
            for c in list(self.clients):
                if not (c.pending_quotes or c.pending_bars):
                    continue
                quotes, bars = list(c.pending_quotes.values()), c.pending_bars
                c.pending_quotes, c.pending_bars = {}, {}
                try:
                    if quotes:
                        await c.ws.send_json({"type": "quotes", "data": quotes})
                    for (sym, iv), bar in bars.items():
                        await c.ws.send_json({"type": "bar", "symbol": sym, "interval": iv, "bar": bar})
                except Exception:  # noqa: BLE001 - client went away; reader loop cleans up
                    c.alive = False
