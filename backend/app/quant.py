"""Quant tools for analysts (pure python, deterministic). See docs/ANALYTICS.md §6-§11.

* beta_regression   : BETA — OLS of security returns on benchmark returns (raw / adjusted beta, alpha, R²)
* pair_spread       : SPRD — hedge ratio, spread z-score, half-life, Engle-Granger ADF cointegration test
* seasonality       : SEAS — monthly return table (year × month) and per-month statistics
* event_study       : EVT  — market-model abnormal returns around event dates, CAR and t-stats
* portfolio_risk    : PORT RISK — vol, historical VaR/ES, beta, risk contributions, stress days
* peer_stats        : RV   — median / percentile rank of a security within its peer group
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from .models import Bar
from .stats import ols, pearson

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def closes_by_date(bars: list[Bar]) -> dict[str, float]:
    return {_date(b["time"]): b["close"] for b in bars if b["close"] > 0}


def returns_by_date(bars: list[Bar], log: bool = False) -> dict[str, float]:
    out: dict[str, float] = {}
    for a, b in zip(bars, bars[1:]):
        if a["close"] > 0 and b["close"] > 0:
            r = b["close"] / a["close"]
            out[_date(b["time"])] = math.log(r) if log else r - 1
    return out


def _mean(x: list[float]) -> float:
    return sum(x) / len(x)


def _sd(x: list[float]) -> float:
    m = _mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1)) if len(x) > 1 else 0.0


def _t_p(t: float, df: int) -> float:
    from .harness.regression import t_sf2

    return t_sf2(t, df) if math.isfinite(t) and df > 0 else float("nan")


def _quantile(sorted_x: list[float], q: float) -> float:
    """Linear interpolation quantile (numpy default)."""
    if not sorted_x:
        return float("nan")
    pos = (len(sorted_x) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_x[lo] + (sorted_x[hi] - sorted_x[lo]) * (pos - lo)


# ---------------------------------------------------------------------------
# BETA
# ---------------------------------------------------------------------------


def beta_regression(sec: list[Bar], bmk: list[Bar], periods_per_year: float = 252) -> dict[str, Any]:
    rs, rb = returns_by_date(sec), returns_by_date(bmk)
    dates = sorted(set(rs) & set(rb))
    if len(dates) < 10:
        return {"error": f"only {len(dates)} common observations"}
    y = [rs[d] for d in dates]
    x = [rb[d] for d in dates]
    (alpha, beta), rss = ols([[1.0, v] for v in x], y)
    n = len(y)
    mx = _mean(x)
    sxx = sum((v - mx) ** 2 for v in x)
    s2 = rss / (n - 2)
    se_b = math.sqrt(s2 / sxx) if sxx > 0 else float("nan")
    se_a = math.sqrt(s2 * (1 / n + mx * mx / sxx)) if sxx > 0 else float("nan")
    corr = pearson(x, y)
    return {
        "observations": n, "start": dates[0], "end": dates[-1],
        "beta": beta, "adjusted_beta": 0.67 * beta + 0.33,  # Blume / Bloomberg adjustment
        "alpha_per_period": alpha, "alpha_annualized": (1 + alpha) ** periods_per_year - 1,
        "beta_se": se_b, "beta_t": beta / se_b if se_b else None, "alpha_t": alpha / se_a if se_a else None,
        "alpha_p": _t_p(alpha / se_a, n - 2) if se_a else None,
        "r2": corr * corr if corr is not None else None, "correlation": corr,
        "vol_security": _sd(y) * math.sqrt(periods_per_year), "vol_benchmark": _sd(x) * math.sqrt(periods_per_year),
        "residual_vol": math.sqrt(s2) * math.sqrt(periods_per_year),
        "points": [{"x": a, "y": b, "date": d} for a, b, d in zip(x, y, dates)][-1000:],
    }


# ---------------------------------------------------------------------------
# SPRD — pair spread / cointegration
# ---------------------------------------------------------------------------

# Engle-Granger (2 variables, constant) residual ADF critical values (MacKinnon 2010, asymptotic)
EG_CRIT = {"1%": -3.90, "5%": -3.34, "10%": -3.04}


def adf_stat(x: list[float], lags: int = 1) -> dict[str, Any]:
    """ADF regression Δx_t = a + b·x_{t-1} + Σγ_i Δx_{t-i}; returns t-stat of b."""
    dx = [x[i] - x[i - 1] for i in range(1, len(x))]
    rows, y = [], []
    for t in range(lags, len(dx)):
        rows.append([1.0, x[t], *[dx[t - i] for i in range(1, lags + 1)]])
        y.append(dx[t])
    if len(y) < 20:
        return {"error": "not enough observations"}
    from .harness.regression import ols_report

    rep = ols_report(y, [r[1:] for r in rows], ["level", *[f"dlag{i}" for i in range(1, lags + 1)]])
    b = rep["coefficients"][1]
    return {"t_stat": b["t"], "b": b["coef"], "lags": lags, "n": rep["n"]}


def half_life(spread: list[float]) -> float | None:
    """Mean-reversion half-life from Δs_t = a + b·s_{t-1}: HL = −ln2 / ln(1+b)."""
    if len(spread) < 20:
        return None
    dy = [spread[i] - spread[i - 1] for i in range(1, len(spread))]
    (_, b), _ = ols([[1.0, s] for s in spread[:-1]], dy)
    if b >= 0 or b <= -1:
        return None
    return -math.log(2) / math.log(1 + b)


def pair_spread(a: list[Bar], b: list[Bar], window: int = 60, entry_z: float = 2.0) -> dict[str, Any]:
    ca, cb = closes_by_date(a), closes_by_date(b)
    dates = sorted(set(ca) & set(cb))
    if len(dates) < max(40, window + 5):
        return {"error": f"only {len(dates)} common observations"}
    la = [math.log(ca[d]) for d in dates]
    lb = [math.log(cb[d]) for d in dates]
    (c, hedge), _ = ols([[1.0, v] for v in lb], la)  # ln A = c + h·ln B + e
    spread = [x - hedge * y - c for x, y in zip(la, lb)]
    ratio = [ca[d] / cb[d] for d in dates]
    adf = adf_stat(spread, lags=1)
    z = []
    for i in range(len(spread)):
        if i + 1 < window:
            z.append(None)
            continue
        w = spread[i + 1 - window: i + 1]
        sd = _sd(w)
        z.append((spread[i] - _mean(w)) / sd if sd > 0 else None)
    t_stat = adf.get("t_stat")
    verdict = None
    if t_stat is not None:
        verdict = next((lvl for lvl in ("1%", "5%", "10%") if t_stat < EG_CRIT[lvl]), None)
    ts = [int(dt.datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()) for d in dates]
    last_z = next((v for v in reversed(z) if v is not None), None)
    signal = None
    if last_z is not None:
        signal = "SHORT A / LONG B" if last_z > entry_z else "LONG A / SHORT B" if last_z < -entry_z else "NO TRADE"
    return {
        "observations": len(dates), "hedge_ratio": hedge, "intercept": c,
        "correlation_returns": pearson([la[i] - la[i - 1] for i in range(1, len(la))],
                                       [lb[i] - lb[i - 1] for i in range(1, len(lb))]),
        "adf": adf, "eg_critical": EG_CRIT, "cointegrated_at": verdict,
        "half_life": half_life(spread), "z_last": last_z, "entry_z": entry_z, "signal": signal,
        "window": window,
        "series": {"spread": [{"time": t, "value": v} for t, v in zip(ts, spread)],
                   "z": [{"time": t, "value": v} for t, v in zip(ts, z) if v is not None],
                   "ratio": [{"time": t, "value": v} for t, v in zip(ts, ratio)]},
    }


# ---------------------------------------------------------------------------
# SEAS — seasonality
# ---------------------------------------------------------------------------


def seasonality(daily: list[Bar]) -> dict[str, Any]:
    """Monthly returns (%) by year × month from daily (or monthly) bars."""
    last: dict[tuple[int, int], float] = {}
    for b in daily:
        d = dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc)
        last[(d.year, d.month)] = b["close"]
    keys = sorted(last)
    table: dict[int, dict[int, float]] = {}
    for prev, cur in zip(keys, keys[1:]):
        if last[prev] > 0:
            table.setdefault(cur[0], {})[cur[1]] = (last[cur] / last[prev] - 1) * 100
    stats = []
    for m in range(1, 13):
        xs = [table[y][m] for y in table if m in table[y]]
        if xs:
            sx = sorted(xs)
            stats.append({"month": m, "mean": _mean(xs), "median": _quantile(sx, 0.5),
                          "pct_positive": sum(1 for v in xs if v > 0) / len(xs) * 100, "n": len(xs),
                          "best": max(xs), "worst": min(xs)})
        else:
            stats.append({"month": m, "n": 0})
    years = sorted(table)
    yearly = {y: (math.prod(1 + v / 100 for v in table[y].values()) - 1) * 100 for y in years}
    return {"years": years, "table": {str(y): table[y] for y in years}, "month_stats": stats,
            "yearly": {str(y): v for y, v in yearly.items()}}


# ---------------------------------------------------------------------------
# EVT — event study
# ---------------------------------------------------------------------------


def event_study(sec: list[Bar], bmk: list[Bar], events: list[str], pre: int = 5, post: int = 10,
                est_window: int = 120, gap: int = 10) -> dict[str, Any]:
    """Market-model abnormal returns AR_t = r_t − (α + β·r_m,t), β estimated on
    [event − gap − est_window, event − gap). Day 0 = first trading day on/after the event date."""
    rs, rb = returns_by_date(sec), returns_by_date(bmk)
    dates = sorted(set(rs) & set(rb))
    idx = {d: i for i, d in enumerate(dates)}
    rel = list(range(-pre, post + 1))
    per_event, cars = [], []
    for ev in events:
        day0 = next((i for i, d in enumerate(dates) if d >= ev), None)
        if day0 is None or day0 - pre < 0 or day0 + post >= len(dates):
            per_event.append({"event": ev, "error": "outside data range"})
            continue
        est_end = day0 - pre - gap
        est_start = est_end - est_window
        if est_start < 0:
            per_event.append({"event": ev, "error": "not enough estimation history"})
            continue
        ed = dates[est_start:est_end]
        (a, b), rss = ols([[1.0, rb[d]] for d in ed], [rs[d] for d in ed])
        sigma = math.sqrt(rss / (len(ed) - 2))
        ar = [rs[dates[day0 + k]] - (a + b * rb[dates[day0 + k]]) for k in rel]
        car, acc = [], 0.0
        for v in ar:
            acc += v
            car.append(acc)
        cars.append(car)
        per_event.append({"event": ev, "day0": dates[day0], "beta": b, "sigma": sigma,
                          "ar_day0": ar[pre], "car_total": car[-1], "car_pre": car[pre - 1] if pre else 0.0,
                          "car_post": car[-1] - (car[pre - 1] if pre else 0.0),
                          "t_car_total": car[-1] / (sigma * math.sqrt(len(rel))) if sigma else None})
    if not cars:
        return {"error": "no usable events", "events": per_event}
    n = len(cars)
    mean_car = [_mean([c[k] for c in cars]) for k in range(len(rel))]
    sd_car = [_sd([c[k] for c in cars]) if n > 1 else 0.0 for k in range(len(rel))]
    t_car = [m / (s / math.sqrt(n)) if s > 0 else None for m, s in zip(mean_car, sd_car)]
    final_t = t_car[-1]
    return {
        "relative_days": rel, "n_events": n, "mean_car": mean_car, "sd_car": sd_car, "t_car": t_car,
        "p_final": _t_p(final_t, n - 1) if final_t is not None and n > 1 else None,
        "pct_positive_final": sum(1 for c in cars if c[-1] > 0) / n * 100, "events": per_event,
        "note": "AR/CAR are in return units (0.01 = 1%). Cross-sectional t-stat; events assumed independent.",
    }


def big_move_days(bars: list[Bar], threshold_sigma: float = 2.5, limit: int = 30) -> list[str]:
    """Dates of unusually large absolute moves (proxy for news/earnings days when no dates are given)."""
    r = returns_by_date(bars)
    vals = list(r.values())
    if len(vals) < 30:
        return []
    m, s = _mean(vals), _sd(vals)
    picked = sorted((d for d, v in r.items() if abs(v - m) > threshold_sigma * s), key=lambda d: -abs(r[d] - m))
    return sorted(picked[:limit])


# ---------------------------------------------------------------------------
# PORT RISK
# ---------------------------------------------------------------------------


CCY_BY_EXCHANGE = {
    "TSE": "JPY", "OSE": "JPY", "NAG": "JPY", "FSE": "JPY", "SSE": "CNY", "SZSE": "CNY", "HKEX": "HKD",
    "LSE": "GBP", "XETR": "EUR", "FWB": "EUR", "EURONEXT": "EUR", "SIX": "CHF", "TSX": "CAD", "ASX": "AUD",
    "KRX": "KRW", "TWSE": "TWD", "NSE": "INR", "BSE": "INR",
}


def currency_of(symbol: str) -> str:
    """Trading currency guessed from the exchange prefix (USD default; crypto *USDT/USD pairs -> USD)."""
    return CCY_BY_EXCHANGE.get(symbol.split(":", 1)[0].upper(), "USD")


# market convention for which currency is quoted first (EURUSD, USDJPY, EURJPY ...)
_CCY_ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "CNY", "CNH", "HKD", "SGD", "KRW", "TWD", "INR", "JPY"]


def fx_pairs(ccy: str, base: str) -> list[tuple[str, bool]]:
    """TradingView FX symbols to try for converting 1 unit of ``ccy`` into ``base``.
    Returns [(symbol, invert)] — a pair XY quotes Y per 1 X, so invert when base is quoted first."""
    def rank(c: str) -> int:
        return _CCY_ORDER.index(c) if c in _CCY_ORDER else len(_CCY_ORDER)
    conventional = (f"FX:{ccy}{base}", False) if rank(ccy) <= rank(base) else (f"FX:{base}{ccy}", True)
    other = (f"FX:{base}{ccy}", True) if not conventional[1] else (f"FX:{ccy}{base}", False)
    return [conventional, other]


def portfolio_risk(positions: list[dict[str, Any]], series: dict[str, list[Bar]], bmk: list[Bar] | None,
                   lookback: int = 252, fx_to_base: dict[str, float] | None = None,
                   base_currency: str = "USD") -> dict[str, Any]:
    """positions: [{symbol, qty}]. Market value = qty × last close × fx_to_base[symbol] (1.0 when missing).
    Weights are signed (shorts negative) relative to gross exposure. Returns are local-currency
    (FX moves of the positions are not included in the risk numbers)."""
    fx_to_base = fx_to_base or {}
    rets = {s: returns_by_date(b) for s, b in series.items() if b}
    pos = [p for p in positions if p["symbol"] in rets and series[p["symbol"]]]
    if not pos:
        return {"error": "no positions with history"}
    mv = {p["symbol"]: p["qty"] * series[p["symbol"]][-1]["close"] * fx_to_base.get(p["symbol"], 1.0) for p in pos}
    gross = sum(abs(v) for v in mv.values())
    net = sum(mv.values())
    w = {s: v / gross for s, v in mv.items()} if gross else {}
    syms = list(w)
    dates = sorted(set.intersection(*(set(rets[s]) for s in syms)))[-lookback:]
    if len(dates) < 30:
        return {"error": f"only {len(dates)} common days"}
    R = {s: [rets[s][d] for d in dates] for s in syms}
    port = [sum(w[s] * R[s][i] for s in syms) for i in range(len(dates))]
    means = {s: _mean(R[s]) for s in syms}
    cov = {a: {b: sum((R[a][i] - means[a]) * (R[b][i] - means[b]) for i in range(len(dates))) / (len(dates) - 1)
               for b in syms} for a in syms}
    var_p = sum(w[a] * w[b] * cov[a][b] for a in syms for b in syms)
    vol_p = math.sqrt(max(var_p, 0.0))
    contrib = {}
    for a in syms:
        mcr = sum(w[b] * cov[a][b] for b in syms) / vol_p if vol_p else 0.0
        contrib[a] = {"weight": w[a], "market_value": mv[a], "vol_ann": _sd(R[a]) * math.sqrt(252),
                      "marginal": mcr * math.sqrt(252), "contribution_pct": (w[a] * mcr / vol_p * 100) if vol_p else 0.0}
    sp = sorted(port)
    var95, var99 = -_quantile(sp, 0.05), -_quantile(sp, 0.01)
    es95 = -_mean(sp[: max(1, int(len(sp) * 0.05))])
    es99 = -_mean(sp[: max(1, int(len(sp) * 0.01))])
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in port:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    out: dict[str, Any] = {
        "observations": len(dates), "start": dates[0], "end": dates[-1],
        "gross_exposure": gross, "net_exposure": net, "net_pct_of_gross": net / gross * 100 if gross else None,
        "vol_daily": vol_p, "vol_annual": vol_p * math.sqrt(252),
        "var_95_1d_pct": var95 * 100, "var_99_1d_pct": var99 * 100, "es_95_1d_pct": es95 * 100, "es_99_1d_pct": es99 * 100,
        "var_95_1d_amount": var95 * gross, "var_99_1d_amount": var99 * gross,
        "max_drawdown_pct": mdd * 100, "positions": contrib,
        "correlation": {a: {b: (cov[a][b] / math.sqrt(cov[a][a] * cov[b][b]) if cov[a][a] and cov[b][b] else None)
                            for b in syms} for a in syms},
        "base_currency": base_currency, "fx_to_base": {s: fx_to_base.get(s, 1.0) for s in syms},
        "note": (f"historical simulation on common trading days; market values in {base_currency}; "
                 "position returns in local currency (FX risk not included)"),
    }
    if bmk:
        rb = returns_by_date(bmk)
        bd = [d for d in dates if d in rb]
        if len(bd) >= 30:
            pr = {d: p for d, p in zip(dates, port)}
            (_, beta), _ = ols([[1.0, rb[d]] for d in bd], [pr[d] for d in bd])
            out["beta"] = beta
            worst = sorted(bd, key=lambda d: rb[d])[:5]
            out["stress_worst_benchmark_days"] = [
                {"date": d, "benchmark_pct": rb[d] * 100, "portfolio_pct": pr[d] * 100,
                 "portfolio_amount": pr[d] * gross} for d in worst]
    return out


# ---------------------------------------------------------------------------
# RV — peer statistics
# ---------------------------------------------------------------------------


def peer_stats(rows: dict[str, dict[str, Any]], target: str, fields: list[str]) -> dict[str, Any]:
    """Median and percentile rank (0 = lowest, 100 = highest) of the target for each numeric field."""
    out = {}
    for f in fields:
        vals = sorted(v for r in rows.values() if isinstance(v := r.get(f), (int, float)) and math.isfinite(v))
        tv = rows.get(target, {}).get(f)
        if not vals:
            continue
        rank = None
        if isinstance(tv, (int, float)) and len(vals) > 1:
            below = sum(1 for v in vals if v < tv)
            equal = sum(1 for v in vals if v == tv)
            rank = (below + 0.5 * (equal - 1)) / (len(vals) - 1) * 100
        out[f] = {"median": _quantile(vals, 0.5), "min": vals[0], "max": vals[-1], "n": len(vals),
                  "target": tv, "percentile": rank,
                  "vs_median_pct": ((tv / _quantile(vals, 0.5) - 1) * 100
                                    if isinstance(tv, (int, float)) and _quantile(vals, 0.5) else None)}
    return out
