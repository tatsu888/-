"""Custom screener: field catalog + filter validation + local evaluation (SIM fallback / tests).

Filters use TradingView scanner semantics: {"left": field, "operation": op, "right": value}
operations: greater, less, egreater, eless, equal, nequal, in_range ([lo, hi]), not_in_range.
"""
from __future__ import annotations

from typing import Any

# field -> (label, group, unit hint)
FIELDS: dict[str, tuple[str, str, str]] = {
    "close": ("Price", "Price", ""), "change": ("Change %", "Price", "%"), "volume": ("Volume", "Price", ""),
    "relative_volume_10d_calc": ("Rel. volume 10D", "Price", "x"), "Perf.W": ("Perf 1W %", "Performance", "%"),
    "Perf.1M": ("Perf 1M %", "Performance", "%"), "Perf.3M": ("Perf 3M %", "Performance", "%"),
    "Perf.6M": ("Perf 6M %", "Performance", "%"), "Perf.YTD": ("Perf YTD %", "Performance", "%"),
    "Perf.Y": ("Perf 1Y %", "Performance", "%"), "price_52_week_high": ("52W high", "Performance", ""),
    "price_52_week_low": ("52W low", "Performance", ""), "market_cap_basic": ("Market cap", "Valuation", ""),
    "price_earnings_ttm": ("P/E TTM", "Valuation", "x"), "price_book_ratio": ("P/B", "Valuation", "x"),
    "enterprise_value_ebitda_ttm": ("EV/EBITDA", "Valuation", "x"), "dividend_yield_recent": ("Div yield %", "Valuation", "%"),
    "return_on_equity": ("ROE %", "Quality", "%"), "gross_margin": ("Gross margin %", "Quality", "%"),
    "operating_margin": ("Op margin %", "Quality", "%"), "net_margin": ("Net margin %", "Quality", "%"),
    "debt_to_equity": ("Debt/Equity", "Quality", "x"), "beta_1_year": ("Beta 1Y", "Risk", ""),
    "RSI": ("RSI(14)", "Technical", ""), "Recommend.All": ("TV tech rating", "Technical", ""),
    "sector": ("Sector", "Classification", "text"), "industry": ("Industry", "Classification", "text"),
}
OPERATIONS = ("greater", "less", "egreater", "eless", "equal", "nequal", "in_range", "not_in_range")

PRESET_SCREENS: dict[str, dict[str, Any]] = {
    "value_quality": {"label": "Value × Quality (PER<15, ROE>12%, mcap>1B)", "filters": [
        {"left": "price_earnings_ttm", "operation": "in_range", "right": [0, 15]},
        {"left": "return_on_equity", "operation": "greater", "right": 12},
        {"left": "market_cap_basic", "operation": "greater", "right": 1e9}], "sort": "return_on_equity"},
    "momentum": {"label": "Momentum (6M>20%, above 52W-high −10%)", "filters": [
        {"left": "Perf.6M", "operation": "greater", "right": 20},
        {"left": "market_cap_basic", "operation": "greater", "right": 1e9}], "sort": "Perf.6M"},
    "oversold": {"label": "Oversold large caps (RSI<30)", "filters": [
        {"left": "RSI", "operation": "less", "right": 30},
        {"left": "market_cap_basic", "operation": "greater", "right": 5e9}], "sort": "RSI", "order": "asc"},
    "high_dividend": {"label": "High dividend (yield>4%, payout sustainable proxy ROE>8%)", "filters": [
        {"left": "dividend_yield_recent", "operation": "greater", "right": 4},
        {"left": "return_on_equity", "operation": "greater", "right": 8}], "sort": "dividend_yield_recent"},
    "volume_surge": {"label": "Volume surge (rel. volume > 2)", "filters": [
        {"left": "relative_volume_10d_calc", "operation": "greater", "right": 2},
        {"left": "market_cap_basic", "operation": "greater", "right": 5e8}], "sort": "relative_volume_10d_calc"},
}


def validate(filters: list[dict[str, Any]]) -> list[str]:
    errs = []
    for i, f in enumerate(filters):
        if f.get("left") not in FIELDS:
            errs.append(f"filter #{i}: unknown field {f.get('left')!r}")
        if f.get("operation") not in OPERATIONS:
            errs.append(f"filter #{i}: unknown operation {f.get('operation')!r}")
        if f.get("operation") in ("in_range", "not_in_range") and not (isinstance(f.get("right"), list) and len(f["right"]) == 2):
            errs.append(f"filter #{i}: {f.get('operation')} needs [lo, hi]")
    return errs


def passes(row: dict[str, Any], f: dict[str, Any]) -> bool:
    v, op, r = row.get(f["left"]), f["operation"], f.get("right")
    if v is None:
        return False
    try:
        if op == "greater":
            return v > r
        if op == "less":
            return v < r
        if op == "egreater":
            return v >= r
        if op == "eless":
            return v <= r
        if op == "equal":
            return v == r
        if op == "nequal":
            return v != r
        if op == "in_range":
            return r[0] <= v <= r[1]
        if op == "not_in_range":
            return not (r[0] <= v <= r[1])
    except TypeError:
        return False
    return False


def run_local(rows: list[dict[str, Any]], filters: list[dict[str, Any]], sort_by: str, order: str, limit: int
              ) -> list[dict[str, Any]]:
    out = [r for r in rows if all(passes(r, f) for f in filters)]
    out.sort(key=lambda r: (r.get(sort_by) is None, r.get(sort_by) or 0), reverse=False)
    if order == "desc":
        out = [r for r in out if r.get(sort_by) is not None][::-1] + [r for r in out if r.get(sort_by) is None]
    return out[:limit]
