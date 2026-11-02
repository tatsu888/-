"""A local fake of TradingView's chart websocket, speaking the same framing/message protocol
(as documented in docs/DATA_SOURCES.md). Used to test TradingViewProvider end-to-end offline.

If the real protocol turns out to differ, update BOTH the provider and this fake, and record the
real messages (DevTools → WS) in docs/DATA_SOURCES.md.
"""
from __future__ import annotations

import asyncio
import json
import re

from websockets.asyncio.server import serve

from app.providers import tv_protocol as P

BAD = "BAD:SYM"


class FakeTV:
    def __init__(self) -> None:
        self.log: list[tuple[str, list]] = []   # (method, params) received from clients
        self.heartbeat_echoes = 0
        self.connections = 0
        self.conns: set = set()
        self.server = None
        self.port = 0

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/socket.io/websocket"

    def methods(self, name: str) -> list[list]:
        return [p for m, p in self.log if m == name]

    async def start(self) -> None:
        self.server = await serve(self._handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def drop_all(self) -> None:
        for ws in list(self.conns):
            await ws.close()

    @staticmethod
    def _msg(m: str, p: list) -> str:
        return P.encode(m, p)

    async def _handler(self, ws) -> None:
        self.connections += 1
        self.conns.add(ws)
        # server hello (non-JSON-RPC payload) + a heartbeat, in ONE websocket message (tests frame splitting)
        await ws.send(P.frame(json.dumps({"session_id": "fake", "timestamp": 1})) + P.frame("~h~1"))
        prices: dict[str, float] = {}
        try:
            async for raw in ws:
                for payload in P.split_frames(raw):
                    if P.is_heartbeat(payload):
                        self.heartbeat_echoes += 1
                        continue
                    msg = json.loads(payload)
                    m, p = msg["m"], msg["p"]
                    self.log.append((m, p))
                    if m == "quote_add_symbols":
                        qs, syms = p[0], p[1:]
                        out = ""
                        for s in syms:
                            if s == BAD:
                                out += self._msg("qsd", [qs, {"n": s, "s": "error", "v": {}}])
                                continue
                            prices[s] = 100.0 + len(s)
                            out += self._msg("qsd", [qs, {"n": s, "s": "ok", "v": {
                                "lp": prices[s], "ch": 1.0, "chp": 1.0, "description": f"desc {s}",
                                "exchange": s.split(":")[0], "currency_code": "USD", "volume": 1000,
                                "update_mode": "delayed_streaming_900", "lp_time": 1700000000}}])
                        out += self._msg("quote_completed", [qs, syms[0]])
                        await ws.send(out)
                        # a partial update afterwards (only lp changes) — provider must merge
                        for s in syms:
                            if s != BAD:
                                prices[s] += 0.5
                                await ws.send(self._msg("qsd", [qs, {"n": s, "s": "ok", "v": {"lp": prices[s]}}]))
                    elif m == "resolve_symbol":
                        sym = json.loads(p[2][1:])["symbol"]
                        if sym == BAD:
                            await ws.send(self._msg("symbol_error", [p[0], p[1], "invalid symbol"]))
                    elif m == "create_series":
                        cs, n = p[0], int(p[5])
                        bars = [{"i": i, "v": [1700000000 + 86400 * i, 10 + i, 11 + i, 9 + i, 10.5 + i, 100 + i]}
                                for i in range(n)]
                        await ws.send(self._msg("timescale_update", [cs, {"sds_1": {"s": bars, "ns": {}, "t": "s1"}}])
                                      + self._msg("series_completed", [cs, "sds_1", "streaming", "s1"]))
                        last = bars[-1]["v"]
                        await ws.send(self._msg("du", [cs, {"sds_1": {"s": [{"i": n - 1, "v": [last[0], last[1], last[2] + 1,
                                                                                            last[3], last[4] + 1, last[5] + 5]}]}}]))
        finally:
            self.conns.discard(ws)


def symbols_in_resolve(params: list) -> str:
    return re.sub(r"^=", "", params[2])
