"""Forecast harness — company-agnostic, deterministic building blocks for earnings
forecasts and valuation. See docs/FORECAST_HARNESS.md.

CATALOG is the MECE map of everything the harness can do; the frontend MODEL
function and AI agents read it via GET /api/harness/catalog.
"""
from __future__ import annotations

from .lines import METHODS as LINE_METHODS

CATALOG = [
    {"layer": "A. Statistical estimation (データから関係を推定)", "items": [
        {"id": "ols", "name": "OLS regression", "api": "POST /api/harness/regression",
         "use": "Y on drivers with t/p-values, R², Durbin-Watson, prediction intervals"},
        {"id": "elasticity", "name": "Log-log elasticity", "api": "POST /api/harness/regression (transform=log)",
         "use": "% response of KPI to % change in driver (FX, oil, volume)"},
        {"id": "trend", "name": "Time trend (linear / log-linear)", "api": "line method: trend",
         "use": "baseline extrapolation with prediction band"},
        {"id": "ts", "name": "Time-series (CAGR, YoY, seasonality, Holt, AR(1), naive)",
         "api": "POST /api/harness/timeseries", "use": "univariate projections, quarterly seasonality"},
        {"id": "accuracy", "name": "Forecast backtest (rolling origin, MAPE/RMSE/bias)",
         "api": "POST /api/harness/timeseries (backtest)", "use": "choose the method that would have worked"},
    ]},
    {"layer": "B. Revenue build (売上の組み立て方) — choose one per line", "items": [
        {"id": "growth", "name": "Growth rate", "api": "line method: growth"},
        {"id": "price_volume", "name": "Price × Volume", "api": "line method: price_volume"},
        {"id": "sum", "name": "Sum of segments", "api": "line method: sum"},
        {"id": "market_share", "name": "Market size × Share", "api": "line method: market_share"},
        {"id": "customers_arpu", "name": "Customers × ARPU", "api": "line method: customers_arpu"},
        {"id": "backlog", "name": "Order backlog conversion (受注残)", "api": "line method: backlog"},
        {"id": "capacity", "name": "Capacity × Utilization × Price", "api": "line method: capacity"},
        {"id": "stores", "name": "Same-store + New stores", "api": "line method: stores"},
        {"id": "driver_regression", "name": "Macro/industry driver regression", "api": "line method: driver_regression"},
        {"id": "statistical", "name": "Statistical (cagr_trend / trend / holt / ar1)", "api": "line methods"},
    ]},
    {"layer": "C. Cost & profit structure (費用構造)", "items": [
        {"id": "pct_of", "name": "% of another line", "api": "line method: pct_of / hist_avg_pct_of"},
        {"id": "fixed_variable", "name": "Fixed + variable (operating leverage, OLS-estimated)",
         "api": "line method: fixed_variable"},
        {"id": "pct_of_prior", "name": "% of prior-year base (D&A from capex)", "api": "line method: pct_of_prior"},
        {"id": "values", "name": "Explicit analyst values (guidance)", "api": "line method: values"},
    ]},
    {"layer": "D. Statement integration (3表の連動)", "items": [
        {"id": "pl", "name": "P&L chain: GP → OP → EBITDA → pretax → tax → minority → NI → EPS", "api": "automatic"},
        {"id": "wc", "name": "Working capital from DSO/DIO/DPO → ΔNWC", "api": "assumptions.dso/dio/dpo"},
        {"id": "fcf", "name": "FCFF = NOPAT + D&A − Capex − ΔNWC", "api": "automatic"},
        {"id": "dividends", "name": "Dividends = NI × payout; book value roll-forward", "api": "assumptions.payout_ratio"},
    ]},
    {"layer": "E. Valuation (価値評価)", "items": [
        {"id": "wacc", "name": "WACC / CAPM", "api": "valuation.wacc"},
        {"id": "dcf", "name": "DCF (Gordon growth and/or exit EV/EBITDA)", "api": "valuation.terminal_growth / exit_ev_ebitda"},
        {"id": "multiples", "name": "Multiples (PER, EV/EBITDA, PBR)", "api": "valuation.multiples"},
        {"id": "ddm", "name": "Dividend discount model", "api": "automatic when payout_ratio > 0"},
        {"id": "rim", "name": "Residual income model", "api": "valuation.book_equity"},
    ]},
    {"layer": "F. Uncertainty (不確実性)", "items": [
        {"id": "scenarios", "name": "Scenarios (bull/base/bear, probability-weighted)", "api": "spec.scenarios"},
        {"id": "sensitivity", "name": "2-D sensitivity table", "api": "spec.sensitivity"},
        {"id": "monte_carlo", "name": "Monte Carlo (seeded, reproducible)", "api": "spec.monte_carlo"},
    ]},
    {"layer": "G. Governance (ハルシネーション対策)", "items": [
        {"id": "checks", "name": "Guardrails: history bands, growth outliers, identities, TV share, tax bounds",
         "api": "result.checks"},
        {"id": "provenance", "name": "Per-line method / formula / parameters / source", "api": "result.projection.provenance"},
        {"id": "hash", "name": "Input & output SHA-256 + engine version (reproducibility)", "api": "result.meta"},
        {"id": "sources", "name": "Unsourced judgmental assumptions flagged", "api": "check: assumption_sources"},
    ]},
]

__all__ = ["CATALOG", "LINE_METHODS"]
