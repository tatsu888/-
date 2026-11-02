"""Univariate time-series methods + forecast accuracy evaluation."""
from __future__ import annotations

import math
from typing import Any, Callable

from .regression import ols_report, trend


def cagr(first: float, last: float, periods: int) -> float | None:
    if first <= 0 or last <= 0 or periods <= 0:
        return None
    return (last / first) ** (1 / periods) - 1


def yoy(values: list[float], lag: int = 1) -> list[float | None]:
    return [None] * lag + [(values[i] / values[i - lag] - 1) if values[i - lag] else None
                           for i in range(lag, len(values))]


def seasonal_factors(values: list[float], period: int = 4) -> list[float]:
    """Multiplicative seasonal indices (ratio to centered moving average), normalized to mean 1."""
    n = len(values)
    if n < 2 * period:
        raise ValueError(f"need at least {2 * period} observations")
    half = period // 2
    ratios: list[list[float]] = [[] for _ in range(period)]
    for i in range(half, n - half):
        if period % 2 == 0:
            window = values[i - half: i + half + 1]
            cma = (sum(window[1:-1]) + 0.5 * (window[0] + window[-1])) / period
        else:
            cma = sum(values[i - half: i + half + 1]) / period
        if cma:
            ratios[i % period].append(values[i] / cma)
    raw = [sum(r) / len(r) if r else 1.0 for r in ratios]
    m = sum(raw) / period
    return [r / m for r in raw]


def holt(values: list[float], horizon: int, alpha: float = 0.5, beta: float = 0.3) -> list[float]:
    """Holt's linear exponential smoothing (level + trend)."""
    if len(values) < 2:
        raise ValueError("need >= 2 observations")
    level, tr = values[0], values[1] - values[0]
    for v in values[1:]:
        prev = level
        level = alpha * v + (1 - alpha) * (level + tr)
        tr = beta * (level - prev) + (1 - beta) * tr
    return [level + (h + 1) * tr for h in range(horizon)]


def ar1(values: list[float], horizon: int) -> dict[str, Any]:
    """AR(1) with mean: x_t = c + phi x_{t-1}."""
    rep = ols_report(values[1:], [[v] for v in values[:-1]], ["lag1"])
    c, phi = rep["_beta"]
    out, x = [], values[-1]
    for _ in range(horizon):
        x = c + phi * x
        out.append(x)
    return {"phi": phi, "const": c, "long_run_mean": c / (1 - phi) if phi != 1 else None, "forecast": out}


def _fourier(values: list[float], horizon: int) -> list[float]:
    from ..fourier import harmonic_forecast

    how = "loglinear" if min(values) > 0 else "linear"
    k = 1 if len(values) < 24 else 2
    return harmonic_forecast(values, horizon, k, how)["forecast"]


def naive(values: list[float], horizon: int) -> list[float]:
    return [values[-1]] * horizon


def seasonal_naive(values: list[float], horizon: int, period: int = 4) -> list[float]:
    return [values[-period + (h % period)] for h in range(horizon)]


def accuracy(actual: list[float], forecast: list[float]) -> dict[str, float | None]:
    pairs = [(a, f) for a, f in zip(actual, forecast) if a is not None and f is not None]
    if not pairs:
        return {"mape": None, "rmse": None, "bias": None, "n": 0}
    mape = [abs((a - f) / a) for a, f in pairs if a]
    return {"mape": sum(mape) / len(mape) * 100 if mape else None,
            "rmse": math.sqrt(sum((a - f) ** 2 for a, f in pairs) / len(pairs)),
            "bias": sum(f - a for a, f in pairs) / len(pairs), "n": len(pairs)}


METHODS: dict[str, Callable[[list[float], int], list[float]]] = {
    "naive": naive,
    "holt": holt,
    "ar1": lambda v, h: ar1(v, h)["forecast"],
    "trend_loglinear": lambda v, h: trend(v, h)["forecast"],
    "trend_linear": lambda v, h: trend(v, h, "linear")["forecast"],
    "fourier": lambda v, h: _fourier(v, h),
}


def backtest_methods(values: list[float], min_train: int = 5, horizon: int = 1,
                     methods: list[str] | None = None) -> dict[str, Any]:
    """Rolling-origin evaluation: which method would have forecast this series best?"""
    res = {}
    for name in methods or list(METHODS):
        fn = METHODS[name]
        acts, fcs = [], []
        for end in range(min_train, len(values) - horizon + 1):
            try:
                fc = fn(values[:end], horizon)
            except (ValueError, ZeroDivisionError):
                continue
            acts.append(values[end + horizon - 1])
            fcs.append(fc[horizon - 1])
        res[name] = accuracy(acts, fcs)
    ranked = sorted([k for k in res if res[k]["mape"] is not None], key=lambda k: res[k]["mape"])
    return {"results": res, "best": ranked[0] if ranked else None, "ranking": ranked}
