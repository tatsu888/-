"""決算時の株価反応 (pure functions — no I/O).

For every reported quarter of a company:
    reaction day   the first trading day on which the market trades the news
    r1 / x1        the reaction-day return, raw and in excess of the market (TOPIX for Japan, S&P 500 otherwise)
    r5 / x5        reaction day + 4 trading days, measured from the close before the reaction
    drift          days 2–5 after the reaction (post-earnings drift: continuation > 0 or reversal < 0)
    vol_ratio      volume on the reaction day ÷ median of the previous 20 trading days

Reaction day for a KNOWN announcement date D: D itself (intraday / pre-open announcements) or the next trading day
(after the close — the usual case in Japan), whichever shows the larger volume spike; with no clear spike
(< 1.5×) the next trading day (after-close assumption).

For a quarter whose date is only ESTIMATED, the reaction day is DETECTED: the largest volume spike of at least
2× within ±10 calendar days of the estimate and at least 7 days after the quarter end. The announcement date is
then taken as the trading day before it (after-close assumption) and labelled 検出 — never presented as known.
"""
from __future__ import annotations

import datetime as dt
from bisect import bisect_left, bisect_right
from statistics import mean, median
from typing import Any

SPIKE_MIN = 2.0       # detection threshold (× median volume of the previous 20 trading days)
CLEAR_SPIKE = 1.5     # below this a known date gives no timing evidence → after-close assumption
WINDOW_DAYS = 10      # detection window around the estimate (calendar days)


def _day(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def daily(bars: list[dict[str, Any]]) -> tuple[list[str], list[float], list[float]]:
    """(dates, closes, volumes), ascending, one row per date (the last bar of a date wins)."""
    rows: dict[str, tuple[float, float]] = {}
    for b in bars:
        if b.get("close"):
            rows[_day(b["time"])] = (float(b["close"]), float(b.get("volume") or 0.0))
    ds = sorted(rows)
    return ds, [rows[d][0] for d in ds], [rows[d][1] for d in ds]


def vol_ratio(vols: list[float], i: int, n: int = 20) -> float | None:
    prev = [v for v in vols[max(0, i - n):i] if v > 0]
    if len(prev) < 10 or vols[i] <= 0:
        return None
    m = median(prev)
    return vols[i] / m if m > 0 else None


def reaction_at_known(dates: list[str], vols: list[float], announce: str) -> tuple[int, str] | None:
    """(index of the reaction day, timing) for a known announcement date."""
    i0 = bisect_left(dates, announce)
    if i0 >= len(dates):
        return None
    if dates[i0] != announce:                    # announced on a holiday / weekend
        return i0, "休日の発表"
    same, nxt = (i0, "場中・寄り前"), (i0 + 1, "引け後")
    if nxt[0] >= len(dates):
        return same
    r_same, r_next = vol_ratio(vols, same[0]) or 0.0, vol_ratio(vols, nxt[0]) or 0.0
    if max(r_same, r_next) < CLEAR_SPIKE:
        return nxt[0], "引け後（仮定）"
    return same if r_same > r_next else nxt


def detect(dates: list[str], vols: list[float], around: str, not_before: str,
           window: int = WINDOW_DAYS, min_ratio: float = SPIKE_MIN) -> dict[str, Any] | None:
    """The reaction day of an announcement whose date is unknown: the largest volume spike near the estimate."""
    a = dt.date.fromisoformat(around)
    lo = max(a - dt.timedelta(days=window), dt.date.fromisoformat(not_before)).isoformat()
    hi = (a + dt.timedelta(days=window)).isoformat()
    best: tuple[int, float] | None = None
    for i in range(max(1, bisect_left(dates, lo)), bisect_right(dates, hi)):
        r = vol_ratio(vols, i)
        if r is not None and (best is None or r > best[1]):
            best = (i, r)
    if best and best[1] >= min_ratio:
        return {"index": best[0], "reaction_day": dates[best[0]], "announce": dates[best[0] - 1], "vol_ratio": best[1]}
    return None


def metrics(dates: list[str], closes: list[float], vols: list[float], i: int,
            market: dict[str, float] | None) -> dict[str, Any] | None:
    if i < 1 or i >= len(dates):
        return None
    d0, d1 = dates[i - 1], dates[i]
    r1 = closes[i] / closes[i - 1] - 1
    m1 = market[d1] / market[d0] - 1 if market and d0 in market and d1 in market else None
    j = i + 4
    r5 = closes[j] / closes[i - 1] - 1 if j < len(closes) else None
    drift = closes[j] / closes[i] - 1 if j < len(closes) else None
    m5 = market[dates[j]] / market[d0] - 1 if r5 is not None and market and d0 in market and dates[j] in market else None
    return {"reaction_day": d1, "r1": r1, "m1": m1, "x1": None if m1 is None else r1 - m1,
            "r5": r5, "x5": None if m5 is None or r5 is None else r5 - m5, "drift": drift, "vol_ratio": vol_ratio(vols, i)}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Typical earnings move: mean |reaction| (market-adjusted when the market series is there), direction counts,
    and whether the move tends to continue (drift in the reaction's direction > 0) or reverse."""
    use = [r for r in rows if r.get("r1") is not None]
    if not use:
        return {"n": 0}
    adj = all(r.get("x1") is not None for r in use)
    xs = [r["x1"] if adj else r["r1"] for r in use]
    follow = [r["drift"] * (1 if x > 0 else -1) for r, x in zip(use, xs) if r.get("drift") is not None and x]
    return {"n": len(xs), "basis": "対市場" if adj else "生のリターン", "avg_abs": mean(abs(x) for x in xs),
            "median_abs": median(abs(x) for x in xs), "max_abs": max(abs(x) for x in xs),
            "up": sum(x > 0 for x in xs), "down": sum(x < 0 for x in xs), "avg": mean(xs),
            "drift_follow": mean(follow) if follow else None, "detected": sum(r.get("kind") == "検出" for r in use)}
