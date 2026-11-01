"""Canonical bar intervals shared by every provider.

Canonical names (used by the API and the frontend):
    1, 5, 15, 30, 60, 240  -> minutes
    1D, 1W, 1M             -> day / week / month
"""
from __future__ import annotations

INTERVAL_SECONDS: dict[str, int] = {
    "1": 60,
    "5": 300,
    "15": 900,
    "30": 1800,
    "60": 3600,
    "240": 14400,
    "1D": 86400,
    "1W": 604800,
    "1M": 2592000,  # nominal (30d); only used for simulation / bucketing
}

ALIASES: dict[str, str] = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "60m": "60", "h": "60", "4h": "240",
    "d": "1D", "1d": "1D", "day": "1D",
    "w": "1W", "1w": "1W", "week": "1W",
    "m": "1M", "1mo": "1M", "mo": "1M", "month": "1M",
}

# TradingView resolution strings
TV_RESOLUTION: dict[str, str] = {
    "1": "1", "5": "5", "15": "15", "30": "30", "60": "60", "240": "240",
    "1D": "D", "1W": "W", "1M": "M",
}


def normalize_interval(value: str) -> str:
    v = (value or "").strip()
    if v in INTERVAL_SECONDS:
        return v
    key = v.lower()
    if key in ALIASES:
        return ALIASES[key]
    if v.upper() in INTERVAL_SECONDS:
        return v.upper()
    raise ValueError(f"unsupported interval: {value!r}")


def bucket_start(ts: int, interval: str) -> int:
    """Start (epoch seconds, UTC) of the bar that contains ``ts``."""
    if interval == "1M":
        import datetime as dt

        d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
        return int(dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc).timestamp())
    if interval == "1W":
        # weeks start Monday 00:00 UTC (epoch day 0 was a Thursday)
        day = ts // 86400
        return int((day - (day + 3) % 7) * 86400)
    sec = INTERVAL_SECONDS[interval]
    return ts - ts % sec
