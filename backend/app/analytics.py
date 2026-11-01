"""Pure-python analytics used by the /api/analytics endpoints.

No numpy dependency on purpose (easy install, easy to read). All functions take
lists of Bar dicts (see models.py) or float lists and are unit-tested in
tests/test_analytics.py.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from .models import Bar

# ---------------------------------------------------------------------------
# indicators (return lists aligned with input; None where undefined)
# ---------------------------------------------------------------------------


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    ef, es = ema(values, fast), ema(values, slow)
    line = [a - b if a is not None and b is not None else None for a, b in zip(ef, es)]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    sig_part = ema([v for v in line[start:] if v is not None], signal)
    sig: list[float | None] = [None] * start + sig_part
    hist = [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]
    return line, sig, hist


def stochastic(bars: list[Bar], k: int = 14, d: int = 3):
    kv: list[float | None] = [None] * len(bars)
    for i in range(k - 1, len(bars)):
        win = bars[i - k + 1: i + 1]
        hi, lo = max(b["high"] for b in win), min(b["low"] for b in win)
        kv[i] = 50.0 if hi == lo else (bars[i]["close"] - lo) / (hi - lo) * 100
    start = k - 1
    dv: list[float | None] = [None] * len(bars)
    if len(bars) > start:
        s = sma([v for v in kv[start:] if v is not None], d)
        dv = [None] * start + s
    return kv, dv


# ---------------------------------------------------------------------------
# technical rating (similar in spirit to TradingView's "Technicals" gauge)
# ---------------------------------------------------------------------------


def _label(score: float) -> str:
    if score > 0.5:
        return "STRONG BUY"
    if score > 0.1:
        return "BUY"
    if score >= -0.1:
        return "NEUTRAL"
    if score >= -0.5:
        return "SELL"
    return "STRONG SELL"


def technical_rating(bars: list[Bar]) -> dict[str, Any]:
    closes = [b["close"] for b in bars]
    if len(closes) < 30:
        return {"error": "not enough bars", "bars": len(closes)}
    price = closes[-1]
    ma_votes: list[dict] = []
    for n in (10, 20, 30, 50, 100, 200):
        for kind, fn in (("SMA", sma), ("EMA", ema)):
            if len(closes) < n:
                continue
            v = fn(closes, n)[-1]
            if v is None:
                continue
            vote = 1 if price > v else -1 if price < v else 0
            ma_votes.append({"name": f"{kind}{n}", "value": v, "vote": vote})
    osc: list[dict] = []
    r = rsi(closes)[-1]
    if r is not None:
        osc.append({"name": "RSI14", "value": r, "vote": 1 if r < 30 else -1 if r > 70 else 0})
    line, sig, _ = macd(closes)
    if line[-1] is not None and sig[-1] is not None:
        osc.append({"name": "MACD(12,26,9)", "value": line[-1], "vote": 1 if line[-1] > sig[-1] else -1})
    kv, dv = stochastic(bars)
    if kv[-1] is not None and dv[-1] is not None:
        vote = 1 if kv[-1] < 20 and kv[-1] > dv[-1] else -1 if kv[-1] > 80 and kv[-1] < dv[-1] else 0
        osc.append({"name": "Stoch%K(14,3)", "value": kv[-1], "vote": vote})
    if len(closes) > 10:
        mom = closes[-1] - closes[-11]
        osc.append({"name": "Momentum10", "value": mom, "vote": 1 if mom > 0 else -1 if mom < 0 else 0})
    ma_score = sum(v["vote"] for v in ma_votes) / max(len(ma_votes), 1)
    osc_score = sum(v["vote"] for v in osc) / max(len(osc), 1)
    total = (ma_score + osc_score) / 2
    return {
        "summary": {"score": total, "label": _label(total)},
        "moving_averages": {"score": ma_score, "label": _label(ma_score), "items": ma_votes},
        "oscillators": {"score": osc_score, "label": _label(osc_score), "items": osc},
        "price": price,
    }


# ---------------------------------------------------------------------------
# returns / correlation / performance
# ---------------------------------------------------------------------------


def log_returns(closes: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]


def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3 or n != len(y):
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def correlation_matrix(series: dict[str, list[Bar]]) -> dict[str, Any]:
    """Pearson correlation of log returns on the common timestamps of all series."""
    syms = [s for s, b in series.items() if b]
    if not syms:
        return {"symbols": [], "matrix": [], "observations": 0}
    common = set.intersection(*(set(b["time"] for b in series[s]) for s in syms))
    times = sorted(common)
    closes = {s: {b["time"]: b["close"] for b in series[s]} for s in syms}
    rets = {s: log_returns([closes[s][t] for t in times]) for s in syms}
    matrix = [[1.0 if a == b else pearson(rets[a], rets[b]) for b in syms] for a in syms]
    vols = {s: (_stdev(rets[s]) if len(rets[s]) > 2 else None) for s in syms}
    return {"symbols": syms, "matrix": matrix, "observations": max(len(times) - 1, 0), "volatility": vols}


def _stdev(xs: list[float]) -> float:
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


PERF_WINDOWS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}


def performance(daily: list[Bar]) -> dict[str, float | None]:
    """Total return (%) over trailing windows + YTD, from daily bars."""
    import datetime as dt

    closes = [b["close"] for b in daily]
    out: dict[str, float | None] = {}
    if not closes:
        return out
    last = closes[-1]
    out["1D"] = (last / closes[-2] - 1) * 100 if len(closes) > 1 else None
    for k, n in PERF_WINDOWS.items():
        out[k] = (last / closes[-1 - n] - 1) * 100 if len(closes) > n else None
    year = dt.datetime.fromtimestamp(daily[-1]["time"], tz=dt.timezone.utc).year
    prior = [b for b in daily if dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).year < year]
    out["YTD"] = (last / prior[-1]["close"] - 1) * 100 if prior else None
    rets = log_returns(closes[-253:])
    out["VOL_1Y"] = _stdev(rets) * math.sqrt(252) * 100 if len(rets) > 20 else None
    win = daily[-252:]
    out["HIGH_52W"] = max(b["high"] for b in win)
    out["LOW_52W"] = min(b["low"] for b in win)
    return out


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------

STRATEGIES = {
    "sma_cross": {"fast": 20, "slow": 50},
    "ema_cross": {"fast": 12, "slow": 26},
    "rsi_reversion": {"period": 14, "lower": 30, "upper": 70},
    "breakout": {"lookback": 20},
    "buy_hold": {},
}


def _signals(bars: list[Bar], strategy: str, p: dict[str, Any]) -> list[int]:
    """Target position per bar (1 long, 0 flat, -1 short) decided at bar close."""
    closes = [b["close"] for b in bars]
    n = len(closes)
    pos = [0] * n
    if strategy in ("sma_cross", "ema_cross"):
        fn = sma if strategy == "sma_cross" else ema
        f, s = fn(closes, int(p["fast"])), fn(closes, int(p["slow"]))
        for i in range(n):
            if f[i] is not None and s[i] is not None:
                pos[i] = 1 if f[i] > s[i] else -1
    elif strategy == "rsi_reversion":
        r = rsi(closes, int(p["period"]))
        cur = 0
        for i in range(n):
            if r[i] is not None:
                if r[i] < float(p["lower"]):
                    cur = 1
                elif r[i] > float(p["upper"]):
                    cur = -1
                elif (cur == 1 and r[i] > 50) or (cur == -1 and r[i] < 50):
                    cur = 0
            pos[i] = cur
    elif strategy == "breakout":
        lb = int(p["lookback"])
        cur = 0
        for i in range(lb, n):
            hi = max(b["high"] for b in bars[i - lb:i])
            lo = min(b["low"] for b in bars[i - lb:i])
            if closes[i] > hi:
                cur = 1
            elif closes[i] < lo:
                cur = -1
            pos[i] = cur
    elif strategy == "buy_hold":
        pos = [1] * n
    else:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {list(STRATEGIES)}")
    return pos


def backtest(bars: list[Bar], strategy: str, params: dict[str, Any] | None = None, *,
             allow_short: bool = False, fee_bps: float = 5.0, periods_per_year: float = 252.0) -> dict[str, Any]:
    """Vectorised close-to-close backtest.

    The signal computed on bar i's close is applied to the return from bar i to
    i+1 (no look-ahead). ``fee_bps`` is charged on each unit of position change.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; choose from {list(STRATEGIES)}")
    p = {**STRATEGIES[strategy], **(params or {})}
    if len(bars) < 3:
        raise ValueError("not enough bars")
    sig = _signals(bars, strategy, p)
    if not allow_short:
        sig = [max(s, 0) for s in sig]
    equity, bh = [1.0], [1.0]
    trades: list[dict[str, Any]] = []
    prev = 0
    open_trade: dict[str, Any] | None = None
    fee = fee_bps / 10000
    period_rets: list[float] = []
    for i in range(len(bars) - 1):
        target = sig[i]
        cost = abs(target - prev) * fee
        if target != prev:
            if open_trade is not None:
                open_trade.update(exit_time=bars[i]["time"], exit=bars[i]["close"])
                open_trade["return_pct"] = (open_trade["exit"] / open_trade["entry"] - 1) * 100 * open_trade["side"]
                trades.append(open_trade)
                open_trade = None
            if target != 0:
                open_trade = {"side": target, "entry_time": bars[i]["time"], "entry": bars[i]["close"]}
        r = bars[i + 1]["close"] / bars[i]["close"] - 1
        pr = target * r - cost
        period_rets.append(pr)
        equity.append(equity[-1] * (1 + pr))
        bh.append(bh[-1] * (1 + r))
        prev = target
    if open_trade is not None:
        open_trade.update(exit_time=bars[-1]["time"], exit=bars[-1]["close"], open=True)
        open_trade["return_pct"] = (open_trade["exit"] / open_trade["entry"] - 1) * 100 * open_trade["side"]
        trades.append(open_trade)

    peak, mdd = 1.0, 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    years = len(period_rets) / periods_per_year
    mean = sum(period_rets) / len(period_rets)
    sd = _stdev(period_rets) if len(period_rets) > 2 else 0.0
    wins = [t for t in trades if t["return_pct"] > 0]
    return {
        "strategy": strategy,
        "params": p,
        "stats": {
            "total_return_pct": (equity[-1] - 1) * 100,
            "buy_hold_return_pct": (bh[-1] - 1) * 100,
            "cagr_pct": ((equity[-1] ** (1 / years) - 1) * 100) if years > 0 and equity[-1] > 0 else None,
            "max_drawdown_pct": mdd * 100,
            "sharpe": (mean / sd * math.sqrt(periods_per_year)) if sd > 0 else None,
            "trades": len(trades),
            "win_rate_pct": (len(wins) / len(trades) * 100) if trades else None,
            "exposure_pct": sum(1 for s in sig[:-1] if s != 0) / max(len(sig) - 1, 1) * 100,
        },
        "equity": [{"time": b["time"], "value": e} for b, e in zip(bars, equity)],
        "buy_hold": [{"time": b["time"], "value": e} for b, e in zip(bars, bh)],
        "trades": trades[-200:],
    }


def periods_per_year(interval: str) -> float:
    return {"1": 252 * 390, "5": 252 * 78, "15": 252 * 26, "30": 252 * 13, "60": 252 * 7,
            "240": 252 * 2, "1D": 252, "1W": 52, "1M": 12}.get(interval, 252)


def bars_to_csv(symbol: str, bars: Iterable[Bar]) -> str:
    import datetime as dt

    lines = ["symbol,time_utc,epoch,open,high,low,close,volume"]
    for b in bars:
        ts = dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{symbol},{ts},{b['time']},{b['open']},{b['high']},{b['low']},{b['close']},{b['volume']}")
    return "\n".join(lines) + "\n"
