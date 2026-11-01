"""Factor / style analysis — 「今どのファクターが効いているか」.

Two complementary methods (docs/ANALYTICS.md):

1. ETF proxy (works with TradingView *and* Yahoo history)
   Excess return of style ETFs vs a benchmark over trailing windows, plus a
   relative-strength curve (factor / benchmark, normalized to 100).

2. Cross-sectional (TradingView scanner)
   Take the N largest stocks of a market, score each on factor characteristics
   (value, size, momentum, quality, low-vol, dividend ...), then measure over
   1W/1M/3M: (a) top-minus-bottom quintile return spread, (b) rank IC
   (Spearman of score vs return). Also sector average returns (rotation).
   CAVEAT: characteristics are *as of now*, returns are *past* — this is a
   style attribution of recent winners, not a tradable backtest.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from .models import Bar
from .stats import spearman

# ---------------------------------------------------------------------------
# 1. ETF proxies  (TradingView symbols; Yahoo mapping strips the exchange prefix)
#    Exchange prefixes marked unverified in docs/DATA_SOURCES.md — edit here.
# ---------------------------------------------------------------------------
FACTOR_SETS: dict[str, dict[str, Any]] = {
    "US": {
        "benchmark": "AMEX:SPY",
        "factors": {
            "Momentum": "BATS:MTUM",
            "Value": "BATS:VLUE",
            "Quality": "BATS:QUAL",
            "Min Volatility": "BATS:USMV",
            "Small Size": "AMEX:IWM",
            "Growth": "AMEX:IWF",
            "Value (R1000)": "AMEX:IWD",
            "High Dividend": "AMEX:VYM",
            "High Beta": "AMEX:SPHB",
            "Low Vol": "AMEX:SPLV",
            "Equal Weight": "AMEX:RSP",
        },
    },
    "JP": {
        "benchmark": "TSE:1306",
        "factors": {
            "Nikkei225 (large/price-wt)": "TSE:1321",
            "High Dividend": "TSE:1489",
            "JPX400 (quality)": "TSE:1591",
            "Growth Mkt 250 (small/growth)": "TSE:2516",
        },
    },
    "SECTORS_US": {
        "benchmark": "AMEX:SPY",
        "factors": {
            "Tech": "AMEX:XLK", "Financials": "AMEX:XLF", "Energy": "AMEX:XLE", "Health Care": "AMEX:XLV",
            "Industrials": "AMEX:XLI", "Cons. Disc.": "AMEX:XLY", "Cons. Staples": "AMEX:XLP",
            "Utilities": "AMEX:XLU", "Materials": "AMEX:XLB", "Real Estate": "AMEX:XLRE",
            "Comm. Services": "AMEX:XLC", "Semis": "NASDAQ:SMH",
        },
    },
}

WINDOWS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}


def _by_date(bars: list[Bar]) -> dict[str, float]:
    return {dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).strftime("%Y-%m-%d"): b["close"]
            for b in bars}


def etf_factor_report(benchmark: list[Bar], factors: dict[str, list[Bar]]) -> dict[str, Any]:
    """Excess returns (factor − benchmark, %) per window + relative-strength curves."""
    bmk = _by_date(benchmark)
    rows, curves = [], {}
    for name, bars in factors.items():
        fx = _by_date(bars)
        dates = sorted(set(bmk) & set(fx))
        if len(dates) < 6:
            rows.append({"factor": name, "error": "not enough overlapping history"})
            continue
        row: dict[str, Any] = {"factor": name, "observations": len(dates)}
        for w, n in WINDOWS.items():
            if len(dates) > n:
                a, b = dates[-1 - n], dates[-1]
                fr = (fx[b] / fx[a] - 1) * 100
                br = (bmk[b] / bmk[a] - 1) * 100
                row[w] = fr - br
                row[w + "_abs"] = fr
            else:
                row[w] = None
        year = dates[-1][:4]
        prior = [d for d in dates if d[:4] < year]
        if prior:
            a, b = prior[-1], dates[-1]
            row["YTD"] = (fx[b] / fx[a] - 1) * 100 - (bmk[b] / bmk[a] - 1) * 100
        base = fx[dates[0]] / bmk[dates[0]]
        curves[name] = [{"time": int(dt.datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()),
                         "value": fx[d] / bmk[d] / base * 100} for d in dates]
        rows.append(row)
    ranked = sorted([r for r in rows if r.get("1M") is not None], key=lambda r: -r["1M"])
    return {"rows": rows, "curves": curves, "leaders_1M": [r["factor"] for r in ranked[:3]],
            "laggards_1M": [r["factor"] for r in ranked[-3:]][::-1]}


# ---------------------------------------------------------------------------
# 2. Cross-sectional factors from scanner rows
# ---------------------------------------------------------------------------
SCAN_FACTOR_COLUMNS = [
    "name", "description", "sector", "close", "market_cap_basic", "price_earnings_ttm", "price_book_ratio",
    "dividend_yield_recent", "return_on_equity", "gross_margin", "beta_1_year",
    "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.Y",
]


def _inv(v: Any) -> float | None:
    return 1.0 / v if isinstance(v, (int, float)) and v > 0 else None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None


def _mom_12_1(r: dict) -> float | None:
    y, m = _num(r.get("Perf.Y")), _num(r.get("Perf.1M"))
    if y is None or m is None or m <= -100:
        return None
    return ((1 + y / 100) / (1 + m / 100) - 1) * 100


# factor name -> (score function (higher = more exposure), description)
FACTOR_DEFS: dict[str, tuple[Any, str]] = {
    "Value (E/P)": (lambda r: _inv(r.get("price_earnings_ttm")), "earnings yield = 1 / PE"),
    "Value (B/P)": (lambda r: _inv(r.get("price_book_ratio")), "book yield = 1 / PB"),
    "Small Size": (lambda r: -math.log(r["market_cap_basic"]) if (r.get("market_cap_basic") or 0) > 0 else None,
                   "−log(market cap)"),
    "Momentum 12-1": (_mom_12_1, "12M return excluding last month"),
    "Quality (ROE)": (lambda r: _num(r.get("return_on_equity")), "return on equity"),
    "Profitability (GM)": (lambda r: _num(r.get("gross_margin")), "gross margin"),
    "Low Beta": (lambda r: -r["beta_1_year"] if _num(r.get("beta_1_year")) is not None else None, "−beta 1Y"),
    "Dividend Yield": (lambda r: _num(r.get("dividend_yield_recent")), "dividend yield"),
}

RETURN_WINDOWS = {"1W": "Perf.W", "1M": "Perf.1M", "3M": "Perf.3M"}


def cross_sectional_factors(rows: list[dict[str, Any]], quantiles: int = 5) -> dict[str, Any]:
    """rows: dicts keyed by SCAN_FACTOR_COLUMNS (plus 'symbol')."""
    out = []
    for fname, (fn, desc) in FACTOR_DEFS.items():
        res: dict[str, Any] = {"factor": fname, "definition": desc}
        for w, col in RETURN_WINDOWS.items():
            pairs = []
            for r in rows:
                try:
                    s = fn(r)
                except (TypeError, ValueError, KeyError):
                    s = None
                ret = _num(r.get(col))
                if s is not None and ret is not None:
                    pairs.append((s, ret))
            res[f"n_{w}"] = len(pairs)
            if len(pairs) < quantiles * 4:
                res[w] = None
                res[f"ic_{w}"] = None
                continue
            pairs.sort(key=lambda p: p[0])
            q = len(pairs) // quantiles
            bottom = [p[1] for p in pairs[:q]]
            top = [p[1] for p in pairs[-q:]]
            res[w] = sum(top) / len(top) - sum(bottom) / len(bottom)  # long-short spread, % points
            res[f"ic_{w}"] = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        out.append(res)
    # sector rotation
    sectors: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        sec = r.get("sector") or "Unknown"
        for w, col in RETURN_WINDOWS.items():
            v = _num(r.get(col))
            if v is not None:
                sectors.setdefault(sec, {}).setdefault(w, []).append(v)
    sector_rows = [{"sector": s, "count": max(len(v) for v in d.values()),
                    **{w: (sum(d[w]) / len(d[w]) if d.get(w) else None) for w in RETURN_WINDOWS}}
                   for s, d in sectors.items()]
    sector_rows.sort(key=lambda r: -(r.get("1M") or -1e9))
    ranked = sorted([f for f in out if f.get("1M") is not None], key=lambda f: -f["1M"])
    return {"universe_size": len(rows), "factors": out, "sectors": sector_rows,
            "strongest_1M": [f["factor"] for f in ranked[:3]], "weakest_1M": [f["factor"] for f in ranked[-3:]][::-1]}
