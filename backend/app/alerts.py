"""Server-side price alerts.

Alert dict:
    {id, symbol, condition, value, note, active, once, created, triggered_at, trigger_price}

conditions:
    above / below            last >= value / last <= value
    cross_up / cross_down    last crosses value since the previous tick
    change_pct_above / change_pct_below   daily change % >= value / <= value

Indicator conditions (evaluated every minute on bars of ``interval``, default 1D):
    rsi_above / rsi_below          RSI(14) >= value / <= value
    price_cross_sma_up / _down     close crosses SMA(value) on the latest bar
    golden_cross / dead_cross      SMA50 crosses above / below SMA200
    macd_cross_up / macd_cross_down  MACD line crosses its signal line
    volume_spike                   volume >= value × 20-bar average volume
    breakout_high / breakout_low   close above the prior value-bar high / below the low

Price alerts are evaluated on every quote the hub receives; their symbols are kept
subscribed even when no browser is watching them.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from .models import Quote
from .store import Store

PRICE_CONDITIONS = ("above", "below", "cross_up", "cross_down", "change_pct_above", "change_pct_below")
INDICATOR_CONDITIONS = ("rsi_above", "rsi_below", "price_cross_sma_up", "price_cross_sma_down", "golden_cross",
                        "dead_cross", "macd_cross_up", "macd_cross_down", "volume_spike", "breakout_high", "breakout_low")
CONDITIONS = PRICE_CONDITIONS + INDICATOR_CONDITIONS


def check_indicator(cond: str, value: float, bars: list[dict]) -> tuple[bool, float | None]:
    """(triggered, observed value) on the LAST bar of ``bars`` (pure, tested)."""
    from .analytics import macd, rsi, sma

    closes = [b["close"] for b in bars]
    n = len(closes)
    if n < 3:
        return False, None
    if cond in ("rsi_above", "rsi_below"):
        r = rsi(closes)[-1]
        if r is None:
            return False, None
        return (r >= value if cond == "rsi_above" else r <= value), r
    if cond in ("price_cross_sma_up", "price_cross_sma_down"):
        m = sma(closes, int(value))
        if m[-1] is None or m[-2] is None:
            return False, None
        up = closes[-2] < m[-2] and closes[-1] >= m[-1]
        down = closes[-2] > m[-2] and closes[-1] <= m[-1]
        return (up if cond.endswith("up") else down), m[-1]
    if cond in ("golden_cross", "dead_cross"):
        f, sl = sma(closes, 50), sma(closes, 200)
        if None in (f[-1], f[-2], sl[-1], sl[-2]):
            return False, None
        up = f[-2] <= sl[-2] and f[-1] > sl[-1]
        down = f[-2] >= sl[-2] and f[-1] < sl[-1]
        return (up if cond == "golden_cross" else down), f[-1] - sl[-1]
    if cond in ("macd_cross_up", "macd_cross_down"):
        line, sig, _ = macd(closes)
        if None in (line[-1], line[-2], sig[-1], sig[-2]):
            return False, None
        up = line[-2] <= sig[-2] and line[-1] > sig[-1]
        down = line[-2] >= sig[-2] and line[-1] < sig[-1]
        return (up if cond.endswith("up") else down), line[-1] - sig[-1]
    if cond == "volume_spike":
        if n < 22:
            return False, None
        avg = sum(b["volume"] for b in bars[-21:-1]) / 20
        ratio = bars[-1]["volume"] / avg if avg else None
        return (ratio is not None and ratio >= value), ratio
    if cond in ("breakout_high", "breakout_low"):
        k = int(value)
        if n <= k:
            return False, None
        window = bars[-1 - k:-1]
        if cond == "breakout_high":
            hi = max(b["high"] for b in window)
            return closes[-1] > hi, hi
        lo = min(b["low"] for b in window)
        return closes[-1] < lo, lo
    return False, None


def check(cond: str, value: float, last: float | None, prev: float | None, change_pct: float | None) -> bool:
    if cond == "above":
        return last is not None and last >= value
    if cond == "below":
        return last is not None and last <= value
    if cond == "cross_up":
        return last is not None and prev is not None and prev < value <= last
    if cond == "cross_down":
        return last is not None and prev is not None and prev > value >= last
    if cond == "change_pct_above":
        return change_pct is not None and change_pct >= value
    if cond == "change_pct_below":
        return change_pct is not None and change_pct <= value
    return False


class AlertEngine:
    def __init__(self, store: Store, on_trigger: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self.store = store
        self.on_trigger = on_trigger
        self._prev: dict[str, float] = {}

    def list(self) -> list[dict[str, Any]]:
        return list(self.store.get("alerts") or [])

    def symbols(self) -> set[str]:
        """Symbols that need a live quote stream (price alerts only)."""
        return {a["symbol"] for a in self.list() if a.get("active") and a["condition"] in PRICE_CONDITIONS}

    async def evaluate_indicators(self, history) -> list[dict]:
        """Check active indicator alerts. ``history(symbol, interval, bars)`` is an async callable.
        Fires at most once per bar (remembers the bar time it fired on)."""
        items = self.list()
        fired = []
        for a in items:
            if not a.get("active") or a["condition"] not in INDICATOR_CONDITIONS:
                continue
            try:
                bars = await history(a["symbol"], a.get("interval", "1D"), 300)
            except Exception:  # noqa: BLE001 - provider errors: try again next round
                continue
            if not bars or a.get("last_bar") == bars[-1]["time"]:
                continue
            hit, observed = check_indicator(a["condition"], a["value"], bars)
            if hit:
                a["triggered_at"] = int(time.time())
                a["trigger_price"] = bars[-1]["close"]
                a["observed"] = observed
                a["last_bar"] = bars[-1]["time"]
                if a.get("once", True):
                    a["active"] = False
                fired.append(dict(a))
        if fired:
            self.store.set("alerts", items)
        return fired

    def create(self, symbol: str, condition: str, value: float, note: str = "", once: bool = True,
               interval: str = "1D") -> dict:
        if condition not in CONDITIONS:
            raise ValueError(f"condition must be one of {CONDITIONS}")
        a = {"id": uuid.uuid4().hex[:10], "symbol": symbol, "condition": condition, "value": float(value),
             "note": note, "active": True, "once": once, "created": int(time.time()),
             "triggered_at": None, "trigger_price": None,
             "interval": interval, "kind": "indicator" if condition in INDICATOR_CONDITIONS else "price"}
        self.store.set("alerts", self.list() + [a])
        return a

    def update(self, alert_id: str, **changes: Any) -> dict | None:
        items = self.list()
        for a in items:
            if a["id"] == alert_id:
                a.update({k: v for k, v in changes.items() if k in ("active", "value", "note", "condition", "once")})
                self.store.set("alerts", items)
                return a
        return None

    def delete(self, alert_id: str) -> bool:
        items = self.list()
        keep = [a for a in items if a["id"] != alert_id]
        self.store.set("alerts", keep)
        return len(keep) != len(items)

    def evaluate(self, q: Quote) -> list[dict]:
        sym, last = q.get("symbol"), q.get("last")
        if last is None:
            return []
        prev = self._prev.get(sym)
        self._prev[sym] = last
        items = self.list()
        fired = []
        for a in items:
            if not a.get("active") or a["symbol"] != sym or a["condition"] not in PRICE_CONDITIONS:
                continue
            if check(a["condition"], a["value"], last, prev, q.get("change_pct")):
                a["triggered_at"] = int(time.time())
                a["trigger_price"] = last
                if a.get("once", True):
                    a["active"] = False
                fired.append(dict(a))
        if fired:
            self.store.set("alerts", items)
        return fired
