"""TradingView websocket wire protocol helpers (pure functions, unit-tested).

The public chart page (www.tradingview.com/chart) talks to
``wss://data.tradingview.com/socket.io/websocket`` with a simple framing:

    ~m~<length>~m~<payload>

* payload is either JSON ``{"m": <method>, "p": [<params>...]}``
* or a heartbeat ``~h~<n>`` which the client must echo back (framed).

This protocol is undocumented and may change without notice. See
docs/DATA_SOURCES.md for the message flow and terms-of-use notes.
"""
from __future__ import annotations

import json
import random
import re
import string
from typing import Any

WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F&type=chart"
ORIGIN = "https://www.tradingview.com"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

_SPLIT = re.compile(r"~m~\d+~m~")

# Fields requested on the quote session -> our normalized Quote keys
QUOTE_FIELD_MAP: dict[str, str] = {
    "lp": "last",
    "ch": "change",
    "chp": "change_pct",
    "open_price": "open",
    "high_price": "high",
    "low_price": "low",
    "prev_close_price": "prev_close",
    "volume": "volume",
    "bid": "bid",
    "ask": "ask",
    "description": "name",
    "exchange": "exchange",
    "currency_code": "currency",
    "type": "type",
    "market_cap_basic": "market_cap",
    "price_earnings_ttm": "pe",
    "earnings_per_share_basic_ttm": "eps",
    "dividends_yield": "div_yield",
    "lp_time": "time",
}
QUOTE_FIELDS: list[str] = list(QUOTE_FIELD_MAP) + ["update_mode", "short_name", "pro_name"]


def frame(payload: str) -> str:
    return f"~m~{len(payload)}~m~{payload}"


def encode(method: str, params: list[Any]) -> str:
    return frame(json.dumps({"m": method, "p": params}, separators=(",", ":")))


def split_frames(raw: str) -> list[str]:
    """Split one websocket text message into its payloads."""
    return [p for p in _SPLIT.split(raw) if p]


def is_heartbeat(payload: str) -> bool:
    return payload.startswith("~h~")


def parse_payload(payload: str) -> dict | None:
    """Return the decoded JSON message, or None for heartbeats / non-JSON (e.g. server hello)."""
    if is_heartbeat(payload):
        return None
    try:
        msg = json.loads(payload)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None


def session_id(prefix: str) -> str:
    return prefix + "_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def resolve_symbol_param(symbol: str, adjustment: str = "splits", session: str = "regular") -> str:
    """resolve_symbol takes a '=' + JSON string describing the symbol."""
    return "=" + json.dumps({"symbol": symbol, "adjustment": adjustment, "session": session},
                            separators=(",", ":"))


def delay_from_update_mode(mode: str | None) -> int | None:
    """'streaming' -> 0, 'delayed_streaming_900' -> 900, unknown -> None."""
    if not mode:
        return None
    if mode == "streaming":
        return 0
    m = re.search(r"(\d+)$", mode)
    return int(m.group(1)) if m else None


def map_quote_values(values: dict[str, Any]) -> dict[str, Any]:
    """Convert a partial TradingView ``qsd`` value dict into normalized Quote keys."""
    out: dict[str, Any] = {}
    for k, v in values.items():
        if k in QUOTE_FIELD_MAP:
            out[QUOTE_FIELD_MAP[k]] = v
        elif k == "update_mode":
            out["delay_sec"] = delay_from_update_mode(v)
    return out


def series_bars(payload: dict, series_id: str) -> list[list[float]]:
    """Extract ``[t,o,h,l,c,v]`` rows for ``series_id`` from a timescale_update/du param dict."""
    node = payload.get(series_id)
    if not isinstance(node, dict):
        return []
    rows = []
    for item in node.get("s", []) or []:
        v = item.get("v") if isinstance(item, dict) else None
        if isinstance(v, list) and len(v) >= 5:
            rows.append(v)
    return rows
