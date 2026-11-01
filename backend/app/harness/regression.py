"""Regression toolkit (deterministic, pure python).

* ols_report       : full OLS with coefficients, SE, t, p, R², adj-R², F, Durbin-Watson
* predict          : point forecast + prediction interval
* elasticity       : log-log regression (% change in Y per 1% change in X)
* trend            : linear or log-linear (constant growth) time trend
* driver_forecast  : fit Y on drivers over history, forecast with assumed future drivers
"""
from __future__ import annotations

import math
from typing import Any

from ..stats import betainc, f_sf, solve


def _inv(m: list[list[float]]) -> list[list[float]]:
    n = len(m)
    cols = [solve(m, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def t_sf2(t: float, df: int) -> float:
    """Two-sided p-value of Student t."""
    if df <= 0:
        return float("nan")
    return betainc(df / 2, 0.5, df / (df + t * t))


def t_crit(df: int, alpha: float = 0.05) -> float:
    """Two-sided critical t by bisection (deterministic)."""
    lo, hi = 0.0, 100.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if t_sf2(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def ols_report(y: list[float], X: list[list[float]], names: list[str], intercept: bool = True) -> dict[str, Any]:
    if len(y) != len(X):
        raise ValueError("y and X length mismatch")
    rows = [[1.0, *r] for r in X] if intercept else [list(r) for r in X]
    cn = (["const"] if intercept else []) + list(names)
    n, k = len(rows), len(rows[0])
    if n <= k:
        raise ValueError(f"need more observations ({n}) than parameters ({k})")
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * yy for r, yy in zip(rows, y)) for i in range(k)]
    beta = solve(xtx, xty)
    fitted = [sum(b * v for b, v in zip(beta, r)) for r in rows]
    resid = [a - b for a, b in zip(y, fitted)]
    rss = sum(e * e for e in resid)
    ybar = sum(y) / n
    tss = sum((v - ybar) ** 2 for v in y)
    df = n - k
    sigma2 = rss / df
    inv = _inv(xtx)
    coefs = []
    for i, name in enumerate(cn):
        se = math.sqrt(max(sigma2 * inv[i][i], 0.0))
        t = beta[i] / se if se > 0 else float("inf")
        coefs.append({"name": name, "coef": beta[i], "se": se, "t": t,
                      "p": t_sf2(t, df) if math.isfinite(t) else 0.0})
    r2 = 1 - rss / tss if tss > 0 else None
    k_slopes = k - (1 if intercept else 0)
    adj = 1 - (1 - r2) * (n - 1) / df if r2 is not None and df > 0 else None
    f = ((tss - rss) / k_slopes) / (rss / df) if k_slopes > 0 and rss > 0 and intercept else None
    dw = sum((resid[i] - resid[i - 1]) ** 2 for i in range(1, n)) / rss if rss > 0 else None
    return {
        "n": n, "k": k, "df_resid": df, "coefficients": coefs, "r2": r2, "adj_r2": adj,
        "f_stat": f, "f_p": f_sf(f, k_slopes, df) if f is not None else None,
        "sigma": math.sqrt(sigma2), "durbin_watson": dw, "residuals": resid, "fitted": fitted,
        "_beta": beta, "_inv": inv, "_intercept": intercept,
        "warnings": _warnings(n, k, r2, dw),
    }


def _warnings(n: int, k: int, r2: float | None, dw: float | None) -> list[str]:
    w = []
    if n < 10 * max(k - 1, 1):
        w.append(f"small sample: n={n} for {k} parameters (rule of thumb n >= {10 * max(k - 1, 1)})")
    if dw is not None and (dw < 1.0 or dw > 3.0):
        w.append(f"Durbin-Watson={dw:.2f}: residual autocorrelation — t-stats likely overstated")
    if r2 is not None and r2 > 0.98 and n < 30:
        w.append("R² > 0.98 on a short sample: possible spurious (trending) regression; try differences/growth rates")
    return w


def predict(report: dict[str, Any], x_new: list[list[float]], alpha: float = 0.05) -> list[dict[str, float]]:
    beta, inv, ic = report["_beta"], report["_inv"], report["_intercept"]
    tc = t_crit(report["df_resid"], alpha)
    out = []
    for x in x_new:
        r = [1.0, *x] if ic else list(x)
        yhat = sum(b * v for b, v in zip(beta, r))
        lev = sum(r[i] * inv[i][j] * r[j] for i in range(len(r)) for j in range(len(r)))
        se = report["sigma"] * math.sqrt(1 + lev)
        out.append({"forecast": yhat, "lower": yhat - tc * se, "upper": yhat + tc * se})
    return out


def public(report: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if not k.startswith("_")}


def elasticity(y: list[float], x: list[float], name: str = "x") -> dict[str, Any]:
    pairs = [(math.log(a), math.log(b)) for a, b in zip(y, x) if a > 0 and b > 0]
    rep = ols_report([p[0] for p in pairs], [[p[1]] for p in pairs], [f"ln({name})"])
    e = rep["coefficients"][1]
    return {"elasticity": e["coef"], "se": e["se"], "p": e["p"], "r2": rep["r2"], "n": rep["n"],
            "interpretation": f"1% change in {name} -> {e['coef']:.2f}% change in Y", "warnings": rep["warnings"]}


def trend(y: list[float], horizon: int, kind: str = "loglinear") -> dict[str, Any]:
    """Fit Y on time index t=0..n-1 and extrapolate ``horizon`` periods."""
    n = len(y)
    if kind == "loglinear":
        if min(y) <= 0:
            raise ValueError("log-linear trend requires positive values")
        rep = ols_report([math.log(v) for v in y], [[t] for t in range(n)], ["t"])
        preds = predict(rep, [[t] for t in range(n, n + horizon)])
        g = math.exp(rep["_beta"][1]) - 1
        return {"kind": kind, "growth_per_period": g, "r2": rep["r2"],
                "forecast": [math.exp(p["forecast"]) for p in preds],
                "lower": [math.exp(p["lower"]) for p in preds], "upper": [math.exp(p["upper"]) for p in preds],
                "warnings": rep["warnings"]}
    rep = ols_report(list(y), [[t] for t in range(n)], ["t"])
    preds = predict(rep, [[t] for t in range(n, n + horizon)])
    return {"kind": "linear", "slope": rep["_beta"][1], "r2": rep["r2"],
            "forecast": [p["forecast"] for p in preds], "lower": [p["lower"] for p in preds],
            "upper": [p["upper"] for p in preds], "warnings": rep["warnings"]}


def driver_forecast(y: list[float], drivers: dict[str, list[float]], future: dict[str, list[float]],
                    transform: str = "level") -> dict[str, Any]:
    """Regress Y on named drivers (history) and forecast using assumed future driver paths.

    transform: "level" (Y ~ X), "log" (lnY ~ lnX, elasticities), "growth" (ΔY% ~ ΔX%)
    """
    names = list(drivers)
    hist_n = len(y)
    if any(len(drivers[k]) != hist_n for k in names):
        raise ValueError("driver history length must equal y length")
    horizon = len(next(iter(future.values()))) if future else 0
    if transform == "log":
        yy = [math.log(v) for v in y]
        X = [[math.log(drivers[k][i]) for k in names] for i in range(hist_n)]
        Xf = [[math.log(future[k][i]) for k in names] for i in range(horizon)]
    elif transform == "growth":
        yy = [y[i] / y[i - 1] - 1 for i in range(1, hist_n)]
        X = [[drivers[k][i] / drivers[k][i - 1] - 1 for k in names] for i in range(1, hist_n)]
        Xf = []
        for i in range(horizon):
            row = []
            for k in names:
                prev = drivers[k][-1] if i == 0 else future[k][i - 1]
                row.append(future[k][i] / prev - 1)
            Xf.append(row)
    else:
        yy, X = list(y), [[drivers[k][i] for k in names] for i in range(hist_n)]
        Xf = [[future[k][i] for k in names] for i in range(horizon)]
    rep = ols_report(yy, X, names)
    preds = predict(rep, Xf)
    if transform == "log":
        fc = [{k: math.exp(v) for k, v in p.items()} for p in preds]
    elif transform == "growth":
        fc, level = [], y[-1]
        for p in preds:
            level_lo, level_hi = level * (1 + p["lower"]), level * (1 + p["upper"])
            level = level * (1 + p["forecast"])
            fc.append({"forecast": level, "lower": level_lo, "upper": level_hi})
    else:
        fc = preds
    return {"transform": transform, "regression": public(rep), "forecast": fc}
