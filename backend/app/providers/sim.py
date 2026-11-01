"""Simulated provider — オフライン開発・デモ用の疑似データ.

Every quote is tagged ``source="sim"`` and the UI shows a red DEMO badge, so
simulated numbers can never be mistaken for market data. Prices follow a
deterministic (per-symbol seeded) geometric random walk.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import random
import time

from ..intervals import INTERVAL_SECONDS, bucket_start
from ..models import Bar, Quote, make_bar, make_quote
from ..universe import all_symbols, label_for
from .base import BarKey, Provider

# rough anchor levels so the demo looks plausible; unknown symbols get a hashed price
_ANCHORS: dict[str, float] = {
    "SP:SPX": 6000, "NASDAQ:NDX": 21000, "DJ:DJI": 44000, "TVC:RUT": 2300, "TVC:VIX": 16,
    "TVC:NI225": 39000, "TVC:TOPIX": 2750, "TVC:HSI": 20000, "XETR:DAX": 20000,
    "TVC:UKX": 8300, "TVC:SX5E": 5000, "TVC:CAC40": 7500, "SSE:000001": 3300, "TVC:KOSPI": 2600,
    "FX:USDJPY": 150, "FX:EURUSD": 1.08, "FX:GBPUSD": 1.27, "FX:EURJPY": 162, "FX:AUDUSD": 0.66,
    "FX:USDCHF": 0.88, "FX:USDCAD": 1.37, "FX_IDC:USDCNH": 7.2, "TVC:DXY": 104,
    "TVC:US02Y": 4.2, "TVC:US10Y": 4.3, "TVC:US30Y": 4.5, "TVC:DE10Y": 2.3, "TVC:GB10Y": 4.4,
    "TVC:JP10Y": 1.0, "TVC:GOLD": 2600, "TVC:SILVER": 31, "TVC:USOIL": 70, "TVC:UKOIL": 74,
    "COMEX:HG1!": 4.2, "NYMEX:NG1!": 3.0, "BINANCE:BTCUSDT": 95000, "BINANCE:ETHUSDT": 3400,
    "BINANCE:SOLUSDT": 190, "BINANCE:XRPUSDT": 2.2, "BINANCE:BNBUSDT": 650, "BINANCE:DOGEUSDT": 0.35,
    "NASDAQ:AAPL": 230, "NASDAQ:MSFT": 420, "NASDAQ:NVDA": 140, "NASDAQ:AMZN": 210,
    "NASDAQ:GOOGL": 175, "NASDAQ:META": 580, "NASDAQ:TSLA": 340, "NYSE:JPM": 240,
    "TSE:7203": 2800, "TSE:6758": 3200, "TSE:8306": 1800, "TSE:9984": 9000,
}

_DAILY_VOL = 0.015  # 1.5% daily sigma


def _seed(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def _anchor(symbol: str) -> float:
    if symbol in _ANCHORS:
        return _ANCHORS[symbol]
    return 10 + (_seed(symbol) % 50000) / 100.0


def _currency(symbol: str) -> str:
    ex = symbol.split(":")[0]
    if ex in ("TSE", "TVC:NI225"):
        return "JPY"
    if ex == "XETR":
        return "EUR"
    return "USD"


class _State:
    __slots__ = ("price", "prev_close", "open", "high", "low", "volume", "rng")

    def __init__(self, symbol: str) -> None:
        self.rng = random.Random(_seed(symbol, "live"))
        base = _anchor(symbol)
        self.prev_close = base
        self.price = base * (1 + self.rng.gauss(0, _DAILY_VOL / 2))
        self.open = base * (1 + self.rng.gauss(0, _DAILY_VOL / 4))
        self.high = max(self.open, self.price)
        self.low = min(self.open, self.price)
        self.volume = float(self.rng.randint(10_000, 5_000_000))


class SimProvider(Provider):
    name = "sim"
    description = "SIMULATED DEMO DATA — not market data"

    def __init__(self, tick_sec: float = 1.0) -> None:
        super().__init__()
        self.tick_sec = tick_sec
        self._states: dict[str, _State] = {}
        self._quote_syms: set[str] = set()
        self._bar_subs: set[BarKey] = set()
        self._bars: dict[BarKey, Bar] = {}
        self._task: asyncio.Task | None = None

    def _state(self, symbol: str) -> _State:
        st = self._states.get(symbol)
        if st is None:
            st = self._states[symbol] = _State(symbol)
        return st

    def _quote(self, symbol: str) -> Quote:
        st = self._state(symbol)
        spread = st.price * 0.0002
        return make_quote(
            symbol, self.name,
            name=label_for(symbol) or symbol.split(":")[-1],
            exchange=symbol.split(":")[0], currency=_currency(symbol),
            last=st.price, open=st.open, high=st.high, low=st.low, prev_close=st.prev_close,
            volume=st.volume, bid=st.price - spread, ask=st.price + spread,
            time=int(time.time()), delay_sec=0,
        )

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        self.status = "connected"
        self.status_detail = "simulated feed"
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self.status = "stopped"

    async def _loop(self) -> None:
        step_sigma = _DAILY_VOL * math.sqrt(self.tick_sec / 23400)  # 6.5h session
        while True:
            await asyncio.sleep(self.tick_sec)
            now = int(time.time())
            touched = self._quote_syms | {s for s, _ in self._bar_subs}
            for sym in list(touched):
                st = self._state(sym)
                st.price *= math.exp(st.rng.gauss(0, step_sigma * 3))
                st.high = max(st.high, st.price)
                st.low = min(st.low, st.price)
                dv = float(st.rng.randint(0, 2000))
                st.volume += dv
                if sym in self._quote_syms:
                    await self.emit_quote(self._quote(sym))
                for key in [k for k in self._bar_subs if k[0] == sym]:
                    await self.emit_bar(sym, key[1], self._update_bar(key, now, st.price, dv))

    def _update_bar(self, key: BarKey, now: int, price: float, dv: float) -> Bar:
        start = bucket_start(now, key[1])
        bar = self._bars.get(key)
        if bar is None or bar["time"] != start:
            o = bar["close"] if bar else price
            bar = make_bar(start, o, max(o, price), min(o, price), price, dv)
        else:
            bar = make_bar(start, bar["open"], max(bar["high"], price), min(bar["low"], price), price,
                           bar["volume"] + dv)
        self._bars[key] = bar
        return bar

    # ---- pull ------------------------------------------------------------
    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        return [self._quote(s) for s in symbols]

    async def get_history(self, symbol: str, interval: str, bars: int) -> list[Bar]:
        sec = INTERVAL_SECONDS[interval]
        rng = random.Random(_seed(symbol, interval, "hist"))
        sigma = _DAILY_VOL * math.sqrt(sec / 86400) * (1.4 if sec < 86400 else 1.0)
        # walk backwards from the current live price so history joins the live feed
        end_price = self._state(symbol).price
        closes = [end_price]
        for _ in range(bars - 1):
            closes.append(closes[-1] / math.exp(rng.gauss(0.00002, sigma)))
        closes.reverse()
        last_start = bucket_start(int(time.time()), interval)
        out: list[Bar] = []
        prev = closes[0] * math.exp(rng.gauss(0, sigma / 2))
        for i, c in enumerate(closes):
            t = last_start - (bars - 1 - i) * sec
            if interval in ("1W", "1M"):
                t = bucket_start(t, interval)
            o = prev
            h = max(o, c) * (1 + abs(rng.gauss(0, sigma / 2)))
            l = min(o, c) * (1 - abs(rng.gauss(0, sigma / 2)))
            v = rng.randint(50_000, 3_000_000) * (sec / 3600) ** 0.5
            out.append(make_bar(t, o, h, l, c, v))
            prev = c
        # dedupe times (1M nominal spacing can collide)
        dedup: dict[int, Bar] = {b["time"]: b for b in out}
        return [dedup[t] for t in sorted(dedup)]

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        q = query.upper()
        res = []
        for s in all_symbols():
            label = label_for(s) or ""
            if q in s.upper() or q in label.upper():
                ex, tk = s.split(":", 1)
                res.append({"symbol": s, "ticker": tk, "exchange": ex, "description": label, "type": ""})
        return res[:limit]

    async def screener(self, market: str, preset: str, limit: int = 25) -> list[Quote]:
        qs = [self._quote(s) for s in all_symbols()]
        key = {"gainers": lambda q: -(q["change_pct"] or 0), "losers": lambda q: q["change_pct"] or 0,
               "most_active": lambda q: -(q["volume"] or 0)}.get(preset, lambda q: -(q["volume"] or 0))
        return sorted(qs, key=key)[:limit]

    # ---- push ------------------------------------------------------------
    async def set_quote_symbols(self, symbols: set[str]) -> None:
        self._quote_syms = set(symbols)

    async def set_bar_subscriptions(self, subs: set[BarKey]) -> None:
        self._bar_subs = set(subs)
        for k in list(self._bars):
            if k not in self._bar_subs:
                del self._bars[k]
