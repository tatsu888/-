"""Lead-lag (タイムラグ) analysis — e.g. oil → equities, US themes → Japan.

Alignment
---------
Daily bars are keyed by their UTC calendar date and the two series are
inner-joined on dates where *both* traded. Returns are log close-to-close.
A lag of +k means "X at day t-k vs Y at day t" → **X leads Y by k sessions**.

Because Tokyo closes before New York opens, a US move on date D is reflected in
Japan on D+1: a US→JP effect therefore shows up at lag +1 (see docs/ANALYTICS.md).

Tools
-----
* cross_correlation  : corr(X_{t-k}, Y_t) for k in [-L, L] with ±2/√N band
* granger            : F-test "past X helps predict Y beyond past Y"
* rolling_correlation: stability of the relationship at a fixed lag
* scan_leader        : one leader vs many followers, ranked
* residualize        : remove market beta from the follower (theme-specific effect)
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from .models import Bar
from .stats import f_sf, ols, pearson

# Preset themes. Symbols are TradingView notation (Yahoo mapping handles TSE:xxxx -> xxxx.T).
THEMES: list[dict[str, Any]] = [
    {"id": "us_semis_jp", "name": "US Semis → JP Semis", "leader": "NASDAQ:SOX", "market": "TVC:TOPIX",
     "followers": ["TSE:8035", "TSE:6857", "TSE:6920", "TSE:6146", "TSE:4063"],
     "note": "Philadelphia semis index vs Tokyo Electron / Advantest / Lasertec / Disco / Shin-Etsu"},
    {"id": "nvda_ai_jp", "name": "NVIDIA → JP AI supply chain", "leader": "NASDAQ:NVDA", "market": "TVC:TOPIX",
     "followers": ["TSE:6857", "TSE:8035", "TSE:9984", "TSE:6526", "TSE:3436"],
     "note": "Advantest / TEL / SoftBank G / Socionext / SUMCO"},
    {"id": "oil_energy", "name": "Crude Oil → Energy & Airlines", "leader": "TVC:USOIL", "market": "TVC:TOPIX",
     "followers": ["TSE:1605", "TSE:5020", "NYSE:XOM", "NYSE:CVX", "TSE:9201", "TSE:9202"],
     "note": "INPEX / ENEOS / Exxon / Chevron; JAL / ANA expected negative"},
    {"id": "us10y_jp_banks", "name": "US 10Y yield → JP Financials", "leader": "TVC:US10Y", "market": "TVC:TOPIX",
     "followers": ["TSE:8306", "TSE:8316", "TSE:8411", "TSE:8766"],
     "note": "MUFG / SMFG / Mizuho / Tokio Marine (leader in yield changes)"},
    {"id": "usdjpy_exporters", "name": "USD/JPY → JP Exporters", "leader": "FX:USDJPY", "market": "TVC:TOPIX",
     "followers": ["TSE:7203", "TSE:7267", "TSE:6758", "TSE:6501", "TSE:6954"],
     "note": "Toyota / Honda / Sony / Hitachi / Fanuc"},
    {"id": "copper_materials", "name": "Copper → Miners & Materials", "leader": "COMEX:HG1!", "market": "TVC:TOPIX",
     "followers": ["TSE:5713", "TSE:5711", "NYSE:FCX"],
     "note": "Sumitomo Metal Mining / Mitsubishi Materials / Freeport"},
    {"id": "spx_japan", "name": "S&P 500 → Japan indices", "leader": "SP:SPX", "market": None,
     "followers": ["TVC:NI225", "TVC:TOPIX"], "note": "overnight US move → next Tokyo session"},
    {"id": "btc_crypto_eq", "name": "Bitcoin → crypto equities", "leader": "BINANCE:BTCUSDT", "market": None,
     "followers": ["NASDAQ:COIN", "NASDAQ:MSTR", "TSE:3350", "TSE:8698"],
     "note": "Coinbase / Strategy / Metaplanet / Monex"},
]


def _date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def daily_returns(bars: list[Bar]) -> dict[str, float]:
    """date -> log return vs previous bar of the same series."""
    out: dict[str, float] = {}
    for a, b in zip(bars, bars[1:]):
        if a["close"] > 0 and b["close"] > 0:
            out[_date(b["time"])] = math.log(b["close"] / a["close"])
    return out


def align(x: dict[str, float], y: dict[str, float]) -> tuple[list[str], list[float], list[float]]:
    dates = sorted(set(x) & set(y))
    return dates, [x[d] for d in dates], [y[d] for d in dates]


def lagged_pairs(x: list[float], y: list[float], k: int) -> tuple[list[float], list[float]]:
    """Pairs (X_{t-k}, Y_t). k>0: X leads; k<0: Y leads."""
    if k >= 0:
        return x[: len(x) - k] if k else x[:], y[k:]
    return x[-k:], y[: len(y) + k]


def cross_correlation(x: list[float], y: list[float], max_lag: int = 5) -> dict[str, Any]:
    rows = []
    for k in range(-max_lag, max_lag + 1):
        a, b = lagged_pairs(x, y, k)
        rows.append({"lag": k, "corr": pearson(a, b), "n": len(a)})
    n = len(x)
    band = 2 / math.sqrt(n) if n else None
    lead = [r for r in rows if r["lag"] > 0 and r["corr"] is not None]
    best = max(lead, key=lambda r: abs(r["corr"])) if lead else None
    return {"lags": rows, "band": band, "best_lead": best,
            "significant": bool(best and band and abs(best["corr"]) > band)}


def granger(x: list[float], y: list[float], p: int = 1) -> dict[str, Any]:
    """Does X Granger-cause Y with p lags? H0: coefficients on X lags are all zero."""
    n = len(y)
    if n < 3 * p + 10:
        return {"p": p, "error": "not enough observations"}
    Xr, Xu, yy = [], [], []
    for t in range(p, n):
        ylags = [y[t - i] for i in range(1, p + 1)]
        xlags = [x[t - i] for i in range(1, p + 1)]
        Xr.append([1.0, *ylags])
        Xu.append([1.0, *ylags, *xlags])
        yy.append(y[t])
    try:
        _, rss_r = ols(Xr, yy)
        beta_u, rss_u = ols(Xu, yy)
    except ValueError:
        return {"p": p, "error": "singular regression"}
    d1, d2 = p, len(yy) - (2 * p + 1)
    if d2 <= 0 or rss_u <= 0:
        return {"p": p, "error": "degenerate regression"}
    f = ((rss_r - rss_u) / d1) / (rss_u / d2)
    return {"p": p, "f_stat": f, "p_value": f_sf(f, d1, d2), "df": [d1, d2], "n": len(yy),
            "x_coefs": beta_u[1 + p:]}


def rolling_correlation(dates: list[str], x: list[float], y: list[float], lag: int, window: int = 60
                        ) -> list[dict[str, Any]]:
    a, b = lagged_pairs(x, y, lag)
    d = dates[lag:] if lag >= 0 else dates[: len(dates) + lag]
    out = []
    for i in range(window, len(a) + 1):
        c = pearson(a[i - window: i], b[i - window: i])
        if c is not None:
            out.append({"time": int(dt.datetime.strptime(d[i - 1], "%Y-%m-%d")
                                    .replace(tzinfo=dt.timezone.utc).timestamp()), "value": c})
    return out


def residualize(y: dict[str, float], market: dict[str, float]) -> tuple[dict[str, float], float | None]:
    """y − beta·market on common dates. Returns (residual returns, beta)."""
    dates, ys, ms = align(y, market)
    if len(dates) < 20:
        return y, None
    (alpha, beta), _ = ols([[1.0, m] for m in ms], ys)
    return {d: yy - alpha - beta * m for d, yy, m in zip(dates, ys, ms)}, beta


def pair_analysis(leader: list[Bar], follower: list[Bar], max_lag: int = 5, window: int = 60,
                  market: list[Bar] | None = None) -> dict[str, Any]:
    xr, yr = daily_returns(leader), daily_returns(follower)
    beta = None
    if market:
        yr, beta = residualize(yr, daily_returns(market))
    dates, x, y = align(xr, yr)
    if len(dates) < 30:
        return {"error": f"only {len(dates)} overlapping days", "observations": len(dates)}
    ccf = cross_correlation(x, y, max_lag)
    best_lag = ccf["best_lead"]["lag"] if ccf["best_lead"] else 1
    g = [granger(x, y, p) for p in sorted({1, 2, best_lag} & set(range(1, max_lag + 1)))]
    g_rev = granger(y, x, 1)
    return {
        "observations": len(dates), "start": dates[0], "end": dates[-1],
        "residualized": market is not None, "market_beta": beta,
        "ccf": ccf, "granger": g, "granger_reverse_lag1": g_rev,
        "rolling": rolling_correlation(dates, x, y, best_lag, window),
        "rolling_lag": best_lag, "window": window,
        "contemporaneous": next((r["corr"] for r in ccf["lags"] if r["lag"] == 0), None),
    }


def scan_leader(leader: list[Bar], followers: dict[str, list[Bar]], max_lag: int = 5,
                market: list[Bar] | None = None) -> list[dict[str, Any]]:
    xr = daily_returns(leader)
    mr = daily_returns(market) if market else None
    rows = []
    for sym, bars in followers.items():
        yr = daily_returns(bars)
        if mr is not None:
            yr, _ = residualize(yr, mr)
        dates, x, y = align(xr, yr)
        if len(dates) < 30:
            rows.append({"symbol": sym, "error": f"only {len(dates)} overlapping days"})
            continue
        ccf = cross_correlation(x, y, max_lag)
        best = ccf["best_lead"]
        g = granger(x, y, best["lag"] if best else 1)
        rows.append({
            "symbol": sym, "observations": len(dates),
            "lag0_corr": next((r["corr"] for r in ccf["lags"] if r["lag"] == 0), None),
            "best_lag": best["lag"] if best else None, "best_corr": best["corr"] if best else None,
            "band": ccf["band"], "significant": ccf["significant"],
            "granger_p": g.get("p_value"),
        })
    rows.sort(key=lambda r: -(abs(r.get("best_corr") or 0)))
    return rows
