"""Server-side price alerts.

Alert dict:
    {id, symbol, condition, value, note, active, once, created, triggered_at, trigger_price}

conditions:
    above / below            last >= value / last <= value
    cross_up / cross_down    last crosses value since the previous tick
    change_pct_above / change_pct_below   daily change % >= value / <= value

Alerts are evaluated on every quote the hub receives; their symbols are kept
subscribed even when no browser is watching them.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from .models import Quote
from .store import Store

CONDITIONS = ("above", "below", "cross_up", "cross_down", "change_pct_above", "change_pct_below")


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
        return {a["symbol"] for a in self.list() if a.get("active")}

    def create(self, symbol: str, condition: str, value: float, note: str = "", once: bool = True) -> dict:
        if condition not in CONDITIONS:
            raise ValueError(f"condition must be one of {CONDITIONS}")
        a = {"id": uuid.uuid4().hex[:10], "symbol": symbol, "condition": condition, "value": float(value),
             "note": note, "active": True, "once": once, "created": int(time.time()),
             "triggered_at": None, "trigger_price": None}
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
            if not a.get("active") or a["symbol"] != sym:
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
