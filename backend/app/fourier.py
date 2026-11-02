"""Fourier / spectral analysis and harmonic-regression forecasting (pure python, deterministic).

* periodogram       : dominant cycles (in bars) of a detrended series (Hann window, radix-2 FFT)
* harmonic_forecast : y_t = trend + Σ_k [a_k cos(2πt/P_k) + b_k sin(2πt/P_k)], fitted by OLS on the
                      top-k periods, then extrapolated ``horizon`` bars
* backtest          : rolling-origin evaluation vs naive (last value) and drift → skill score

Honest note (shown in the UI): prices are close to a random walk; cycle extrapolation rarely beats
the naive forecast out of sample. Use the backtest skill score, not the in-sample fit, to judge it.
Seasonal KPIs (monthly sales, quarterly revenue) are where this tends to work.
"""
from __future__ import annotations

import cmath
import math
from typing import Any

from .stats import ols


def _fft(a: list[complex]) -> list[complex]:
    """Iterative radix-2 Cooley-Tukey; len(a) must be a power of two."""
    n = len(a)
    a = list(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        w = cmath.exp(-2j * math.pi / length)
        for i in range(0, n, length):
            wk = 1 + 0j
            for k in range(length // 2):
                u, v = a[i + k], a[i + k + length // 2] * wk
                a[i + k], a[i + k + length // 2] = u + v, u - v
                wk *= w
        length <<= 1
    return a


def detrend(values: list[float], how: str = "loglinear") -> tuple[list[float], dict[str, Any]]:
    """Remove a trend. Returns (residual, trend info used to rebuild levels)."""
    n = len(values)
    if how == "diff":
        return [values[i] - values[i - 1] for i in range(1, n)], {"how": how}
    ys = [math.log(v) for v in values] if how == "loglinear" else list(values)
    if how == "loglinear" and min(values) <= 0:
        raise ValueError("loglinear detrend needs positive values")
    (a, b), _ = ols([[1.0, float(t)] for t in range(n)], ys)
    return [y - (a + b * t) for t, y in enumerate(ys)], {"how": how, "a": a, "b": b}


def periodogram(values: list[float], how: str = "loglinear", top: int = 8, min_period: float = 2.0,
                max_period: float | None = None) -> dict[str, Any]:
    resid, _ = detrend(values, how)
    n = len(resid)
    if n < 16:
        raise ValueError("need at least 16 observations")
    mean = sum(resid) / n
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]  # Hann
    x = [(r - mean) * w for r, w in zip(resid, win)]
    m = 1 << (n - 1).bit_length()
    spec = _fft([complex(v) for v in x] + [0j] * (m - n))
    max_period = max_period or n / 2
    rows = []
    for k in range(1, m // 2):
        period = m / k
        if min_period <= period <= max_period:
            rows.append({"k": k, "period": period, "power": abs(spec[k]) ** 2})
    total = sum(r["power"] for r in rows) or 1.0
    for r in rows:
        r["share"] = r["power"] / total
    # local maxima only (a broad peak shows up once)
    peaks = [r for i, r in enumerate(rows)
             if (i == 0 or r["power"] >= rows[i - 1]["power"]) and (i == len(rows) - 1 or r["power"] >= rows[i + 1]["power"])]
    peaks.sort(key=lambda r: -r["power"])
    return {"n": n, "padded": m, "detrend": how, "peaks": peaks[:top],
            "spectrum": [{"period": r["period"], "power": r["power"]} for r in rows]}


def harmonic_forecast(values: list[float], horizon: int, k: int = 3, how: str = "loglinear",
                      periods: list[float] | None = None) -> dict[str, Any]:
    n = len(values)
    if how == "diff":
        how = "linear"
    if periods:
        ps = [float(p) for p in periods]
    else:
        ps = [p["period"] for p in periodogram(values, how, top=max(k, 1))["peaks"][:k]]
    use_log = how == "loglinear"
    if use_log and min(values) <= 0:
        raise ValueError("loglinear needs positive values")
    ys = [math.log(v) for v in values] if use_log else list(values)
    nyq = [abs(p - 2.0) < 1e-9 for p in ps]  # period 2: sin term is identically 0 on integer t

    def row(t: float) -> list[float]:
        r = [1.0, t]
        for p, ny in zip(ps, nyq):
            r.append(math.cos(2 * math.pi * t / p))
            if not ny:
                r.append(math.sin(2 * math.pi * t / p))
        return r

    X = [row(float(t)) for t in range(n)]
    beta, rss = ols(X, ys)
    fit = [sum(b * v for b, v in zip(beta, r)) for r in X]
    fut = [sum(b * v for b, v in zip(beta, row(float(t)))) for t in range(n, n + horizon)]
    ybar = sum(ys) / n
    tss = sum((y - ybar) ** 2 for y in ys)
    sigma = math.sqrt(rss / max(n - len(beta), 1))
    tr = (lambda v: math.exp(v)) if use_log else (lambda v: v)
    comps, j = [], 2
    for p, ny in zip(ps, nyq):
        amp = abs(beta[j]) if ny else math.hypot(beta[j], beta[j + 1])
        comps.append({"period": p, "amplitude": amp})
        j += 1 if ny else 2
    return {
        "periods": ps, "components": comps, "r2": 1 - rss / tss if tss else None, "detrend": how,
        "fitted": [tr(v) for v in fit], "forecast": [tr(v) for v in fut],
        "lower": [tr(v - 2 * sigma) for v in fut], "upper": [tr(v + 2 * sigma) for v in fut],
    }


def backtest(values: list[float], horizon: int = 20, k: int = 3, how: str = "loglinear", folds: int = 8,
             min_train: int = 120) -> dict[str, Any]:
    """Rolling-origin: at each origin fit on the past only, forecast ``horizon`` ahead, compare with naive & drift."""
    n = len(values)
    origins = [o for o in range(min_train, n - horizon + 1, max(1, (n - horizon - min_train) // max(folds, 1)))][-folds:]
    res: dict[str, list[float]] = {"fourier": [], "naive": [], "drift": []}
    hits: dict[str, list[int]] = {"fourier": [], "drift": []}
    for o in origins:
        train, actual = values[:o], values[o: o + horizon]
        try:
            fc = harmonic_forecast(train, horizon, k, how)["forecast"]
        except (ValueError, ZeroDivisionError):
            continue
        last = train[-1]
        drift_step = (train[-1] - train[0]) / (len(train) - 1)
        preds = {"fourier": fc, "naive": [last] * horizon, "drift": [last + drift_step * (h + 1) for h in range(horizon)]}
        for name, p in preds.items():
            res[name].append(sum(abs(a - f) / abs(a) for a, f in zip(actual, p) if a) / horizon * 100)
        for name in ("fourier", "drift"):
            hits[name].append(int((preds[name][-1] - last) * (actual[-1] - last) > 0))
    mape = {k2: (sum(v) / len(v) if v else None) for k2, v in res.items()}
    skill = (1 - mape["fourier"] / mape["naive"]) if mape["fourier"] is not None and mape["naive"] else None
    return {"origins": len(res["fourier"]), "horizon": horizon, "mape": mape,
            "directional_hit_rate": {k2: (sum(v) / len(v) * 100 if v else None) for k2, v in hits.items()},
            "skill_vs_naive": skill,
            "verdict": None if skill is None else ("beats naive" if skill > 0.05 else "no better than naive"
                                                   if skill > -0.05 else "worse than naive")}
