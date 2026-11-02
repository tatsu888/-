"""Analysis time windows: lookback length + "as of" (end offset) — used by the window sliders.

end_offset = number of trading days (of the reference series) to step back from the latest bar.
Every series is cut at the same calendar date (not the same bar count), so markets with different
holidays stay aligned and nothing after the as-of date can leak into the analysis.
"""
from __future__ import annotations

import datetime as dt
from typing import Any


def bar_date(b: dict[str, Any]) -> str:
    return dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).strftime("%Y-%m-%d")


def cutoff_date(bars: list[dict[str, Any]], end_offset: int) -> str | None:
    if not bars:
        return None
    i = len(bars) - 1 - max(0, end_offset)
    return bar_date(bars[max(i, 0)])


def cut_series(series: dict[str, list[dict[str, Any]]], end_offset: int, ref: str | None = None
               ) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    """Drop every bar after the as-of date. ref = symbol whose calendar defines the offset
    (default: the longest series)."""
    if not series:
        return series, None
    if ref not in series or not series.get(ref):
        ref = max(series, key=lambda s: len(series[s] or []))
    cut = cutoff_date(series[ref], end_offset)
    if not end_offset or cut is None:
        return series, cut
    return {s: [b for b in (bars or []) if bar_date(b) <= cut] for s, bars in series.items()}, cut


def cut_closes(data: dict[str, dict[str, float]], cut: str | None) -> dict[str, dict[str, float]]:
    if not cut:
        return data
    return {s: {d: v for d, v in m.items() if d <= cut} for s, m in data.items()}


def info(series: dict[str, list[dict[str, Any]]], ref: str | None, lookback: int, end_offset: int,
         cut: str | None) -> dict[str, Any]:
    """{from, to, lookback, end_offset} for the UI label."""
    bars = series.get(ref) if ref else None
    if not bars:
        bars = max(series.values(), key=len) if series else []
    start = bar_date(bars[-lookback]) if len(bars) >= lookback else (bar_date(bars[0]) if bars else None)
    return {"from": start, "to": cut or (bar_date(bars[-1]) if bars else None), "lookback": lookback, "end_offset": end_offset}
