"""XRAY — return decomposition and unintended factor bets (Notion 01.2 リターン分解 / 04.4 ファクターモデル).

Rule-based, deterministic (pure Python OLS on daily data):

Single stock — hierarchical variance decomposition in the order of the Notion pyramid
    market → style & macro → sector → idiosyncratic
    share_market = R²(market) ; share_style = R²(market+style) − R²(market) ;
    share_sector = R²(all) − R²(market+style) ; share_idio = 1 − R²(all)
    (Notion reference for a typical Japanese single stock: 40–50 / 25–30 / 15–20 / ≈10 %.)
    Full-model betas, t-stats and the "1σ impact" (β × daily σ of the factor, in % per day) make
    factors with different units comparable.

Book — positions {symbol, weight % NAV}: exposure_k = Σ w_i β_ik; factor variance e'Σe with Euler
    contributions e_k (Σe)_k; idiosyncratic variance Σ w_i² σ²_ε,i. Flags (rules):
    • one factor > 20% of book variance  → 意図しないファクター・ベット
    • |market exposure| > 5% NAV           → ベータ調整後ネットが規律（≤5%）を超過
    • idiosyncratic share < 50%            → ブックのリスクの大半がファクター由来

Factor proxies are market data series (no proprietary risk model): see FACTORS_JP / FACTORS_US.
Yields enter as daily changes in bp; everything else as daily log returns.
"""
from __future__ import annotations

import math
from typing import Any

from .harness.regression import ols_report

# kind: "ret" = log return, "bp" = daily change ×100 (yields quoted in %)
FACTORS_JP: dict[str, tuple[str, str]] = {
    "USDJPY": ("FX:USDJPY", "ret"), "JP 10Y": ("TVC:JP10Y", "bp"), "US 10Y": ("TVC:US10Y", "bp"),
    "Oil": ("TVC:USOIL", "ret"), "Copper": ("COMEX:HG1!", "ret"), "Semis (SOXX)": ("NASDAQ:SOXX", "ret"),
    "China (FXI)": ("AMEX:FXI", "ret"), "Small/Growth (2516)": ("TSE:2516", "ret"), "High Div (1489)": ("TSE:1489", "ret"),
}
FACTORS_US: dict[str, tuple[str, str]] = {
    "US 10Y": ("TVC:US10Y", "bp"), "DXY": ("TVC:DXY", "ret"), "Oil": ("TVC:USOIL", "ret"),
    "Size (IWM)": ("AMEX:IWM", "ret"), "Value (IWD)": ("AMEX:IWD", "ret"), "Growth (IWF)": ("AMEX:IWF", "ret"),
    "Momentum (MTUM)": ("BATS:MTUM", "ret"), "Min Vol (USMV)": ("BATS:USMV", "ret"),
}
MARKET = {"JP": "TVC:TOPIX", "US": "SP:SPX"}

# TOPIX-17 sector ETFs (NEXT FUNDS 1617–1633) and SPDR sector ETFs, keyed by TradingView scanner sector
TOPIX17 = {
    "TSE:1617": "食品", "TSE:1618": "エネルギー資源", "TSE:1619": "建設・資材", "TSE:1620": "素材・化学", "TSE:1621": "医薬品",
    "TSE:1622": "自動車・輸送機", "TSE:1623": "鉄鋼・非鉄", "TSE:1624": "機械", "TSE:1625": "電機・精密",
    "TSE:1626": "情報通信・サービスその他", "TSE:1627": "電力・ガス", "TSE:1628": "運輸・物流", "TSE:1629": "商社・卸売",
    "TSE:1630": "小売", "TSE:1631": "銀行", "TSE:1632": "金融（除く銀行）", "TSE:1633": "不動産",
}
US_SECTORS = {
    "AMEX:XLK": "Technology", "AMEX:XLF": "Financials", "AMEX:XLE": "Energy", "AMEX:XLV": "Health Care",
    "AMEX:XLI": "Industrials", "AMEX:XLY": "Cons. Disc.", "AMEX:XLP": "Cons. Staples", "AMEX:XLU": "Utilities",
    "AMEX:XLB": "Materials", "AMEX:XLRE": "Real Estate", "AMEX:XLC": "Comm. Services",
}
_JP_BY_SECTOR = {
    "Technology Services": "TSE:1626", "Electronic Technology": "TSE:1625", "Communications": "TSE:1626",
    "Producer Manufacturing": "TSE:1624", "Consumer Durables": "TSE:1622", "Process Industries": "TSE:1620",
    "Non-Energy Minerals": "TSE:1623", "Energy Minerals": "TSE:1618", "Utilities": "TSE:1627",
    "Health Technology": "TSE:1621", "Consumer Non-Durables": "TSE:1617", "Retail Trade": "TSE:1630",
    "Transportation": "TSE:1628", "Industrial Services": "TSE:1619", "Distribution Services": "TSE:1629",
    "Commercial Services": "TSE:1626", "Consumer Services": "TSE:1626", "Health Services": "TSE:1621",
    "Miscellaneous": "TSE:1626", "Finance": "TSE:1632",
}
_US_BY_SECTOR = {
    "Technology Services": "AMEX:XLK", "Electronic Technology": "AMEX:XLK", "Communications": "AMEX:XLC",
    "Producer Manufacturing": "AMEX:XLI", "Consumer Durables": "AMEX:XLY", "Process Industries": "AMEX:XLB",
    "Non-Energy Minerals": "AMEX:XLB", "Energy Minerals": "AMEX:XLE", "Utilities": "AMEX:XLU",
    "Health Technology": "AMEX:XLV", "Consumer Non-Durables": "AMEX:XLP", "Retail Trade": "AMEX:XLY",
    "Transportation": "AMEX:XLI", "Industrial Services": "AMEX:XLI", "Distribution Services": "AMEX:XLI",
    "Commercial Services": "AMEX:XLI", "Consumer Services": "AMEX:XLY", "Health Services": "AMEX:XLV",
    "Miscellaneous": "AMEX:XLI", "Finance": "AMEX:XLF",
}
NOTION_PYRAMID = {"market": (40, 50), "style": (25, 30), "sector": (15, 20), "idio": (10, 10)}


def region(symbol: str) -> str:
    return "JP" if symbol.upper().startswith(("TSE:", "OSE:", "NAG:", "FSE:")) else "US"


def sector_etf(symbol: str, sector: str | None, industry: str | None = None) -> str | None:
    if region(symbol) == "JP":
        if sector == "Finance":
            ind = (industry or "").lower()
            if "bank" in ind:
                return "TSE:1631"
            if "real estate" in ind:
                return "TSE:1633"
        return _JP_BY_SECTOR.get(sector or "")
    if sector == "Finance" and "real estate" in (industry or "").lower():
        return "AMEX:XLRE"
    return _US_BY_SECTOR.get(sector or "")


def changes(closes: dict[str, float], kind: str = "ret") -> dict[str, float]:
    ds = sorted(closes)
    out: dict[str, float] = {}
    for a, b in zip(ds, ds[1:]):
        pa, pb = closes[a], closes[b]
        if kind == "bp":
            out[b] = (pb - pa) * 100
        elif pa > 0 and pb > 0:
            out[b] = math.log(pb / pa)
    return out


def _sd(x: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    m = sum(x) / n
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))


def _fit(y: list[float], cols: list[list[float]], names: list[str]) -> dict[str, Any] | None:
    if not cols:
        n = len(y)
        m = sum(y) / n
        return {"r2": 0.0, "coefficients": [{"name": "const", "coef": m, "t": None}], "residuals": [v - m for v in y],
                "sigma": _sd(y)}
    X = [list(r) for r in zip(*cols)]
    try:
        return ols_report(y, X, names)
    except (ValueError, ZeroDivisionError):
        return None


def decompose(stock: dict[str, float], market: tuple[str, dict[str, float]] | None, styles: dict[str, dict[str, float]],
              sector: tuple[str, dict[str, float]] | None = None, lookback: int = 252, min_obs: int = 120) -> dict[str, Any]:
    """stock / market / styles / sector are DAILY CHANGES keyed by date (see ``changes``);
    market and sector are (symbol, changes) so that factor names stay unique across regions."""
    series = {"__y": stock}
    if market and market[1]:
        series[f"Market {market[0]}"] = market[1]
    for k, v in styles.items():
        if v:
            series[k] = v
    if sector and sector[1]:
        series[f"Sector {sector[0]}"] = sector[1]
    dates = sorted(set.intersection(*(set(s) for s in series.values())))[-lookback:]
    if len(dates) < min_obs:
        # degrade gracefully: drop the factor with the fewest overlapping dates until enough remain
        keys = [k for k in series if k != "__y"]
        while keys and len(dates) < min_obs:
            worst = min(keys, key=lambda k: len(set(series[k]) & set(stock)))
            keys.remove(worst)
            series.pop(worst)
            dates = sorted(set.intersection(*(set(s) for s in series.values())))[-lookback:]
        if len(dates) < min_obs:
            raise ValueError(f"not enough overlapping history ({len(dates)} days, need {min_obs})")
    y = [series["__y"][d] for d in dates]
    fac = {k: [series[k][d] for d in dates] for k in series if k != "__y"}
    fac = {k: v for k, v in fac.items() if _sd(v) > 0}
    mk = [k for k in fac if k.startswith("Market ")]
    st = [k for k in fac if not k.startswith(("Market ", "Sector "))]
    sc = [k for k in fac if k.startswith("Sector ")]
    r = []
    for names in (mk, mk + st, mk + st + sc):
        f = _fit(y, [fac[k] for k in names], names)
        r.append(f["r2"] if f and f.get("r2") is not None else (r[-1] if r else 0.0))
    full = _fit(y, [fac[k] for k in mk + st + sc], mk + st + sc)
    r_m, r_ms, r_all = (max(0.0, min(1.0, v)) for v in r)
    shares = {"market": r_m, "style": max(0.0, r_ms - r_m), "sector": max(0.0, r_all - r_ms), "idio": max(0.0, 1 - r_all)}
    coefs = []
    if full:
        for c in full["coefficients"]:
            if c["name"] == "const":
                continue
            sd = _sd(fac[c["name"]])
            coefs.append({"factor": c["name"], "beta": c["coef"], "t": c["t"], "impact_1sd_pct": c["coef"] * sd * 100,
                          "kind": "bp" if c["name"] in ("JP 10Y", "US 10Y") else "ret"})
        coefs.sort(key=lambda c: -abs(c["impact_1sd_pct"]))
    resid_sd = full["sigma"] if full else _sd(y)
    return {
        "n": len(dates), "from": dates[0], "to": dates[-1], "shares": shares, "r2": r_all, "coefficients": coefs,
        "vol_pct": _sd(y) * math.sqrt(252) * 100, "idio_vol_pct": resid_sd * math.sqrt(252) * 100,
        "idio_sd_daily": resid_sd, "factors_used": mk + st + sc, "notion_reference": NOTION_PYRAMID,
        "verdict": ("個別要因が大きい（ファンダの判断が効きやすい）" if shares["idio"] >= 0.5 else
                    "マクロ・スタイル・セクターが支配的（判断が上書きされやすい → ペア／ヘッジで持つ）" if shares["idio"] < 0.3 else
                    "中間"),
    }


def book(positions: list[dict[str, Any]], results: dict[str, dict[str, Any]], factor_changes: dict[str, dict[str, float]],
         lookback: int = 252) -> dict[str, Any]:
    """positions [{symbol, weight}] (% NAV, signed); results = decompose() per symbol (needs coefficients,
    idio_sd_daily); factor_changes = {factor name: daily changes} for every factor that appears in results."""
    exp: dict[str, float] = {}
    idio_var = 0.0
    used = []
    for p in positions:
        r = results.get(p.get("symbol"))
        w = (p.get("weight") or 0) / 100
        if not r or not w:
            continue
        used.append(p["symbol"])
        for c in r["coefficients"]:
            exp[c["factor"]] = exp.get(c["factor"], 0.0) + w * c["beta"]
        idio_var += (w * r["idio_sd_daily"]) ** 2
    names = [k for k in exp if k in factor_changes]
    dates = sorted(set.intersection(*(set(factor_changes[k]) for k in names)))[-lookback:] if names else []
    cols = {k: [factor_changes[k][d] for d in dates] for k in names}
    means = {k: sum(v) / len(v) for k, v in cols.items()} if dates else {}
    n = len(dates)
    cov = {a: {b: (sum((x - means[a]) * (y - means[b]) for x, y in zip(cols[a], cols[b])) / (n - 1) if n > 1 else 0.0)
               for b in names} for a in names}
    se = {a: sum(cov[a][b] * exp[b] for b in names) for a in names}
    fvar = sum(exp[a] * se[a] for a in names)
    total = fvar + idio_var
    rows = []
    for k in names:
        sd = math.sqrt(cov[k][k]) if cov[k][k] > 0 else 0.0
        contrib = exp[k] * se[k]
        rows.append({"factor": k, "exposure": exp[k], "impact_1sd_bp": exp[k] * sd * 1e4,
                     "var_share": contrib / total if total > 0 else None})
    rows.sort(key=lambda r: -abs(r["var_share"] or 0))
    flags = []
    for r in rows:
        if r["var_share"] is not None and r["var_share"] > 0.2:
            flags.append(f"意図しないファクター・ベットの疑い: {r['factor']} がブックの分散の {r['var_share'] * 100:.0f}%")
    mk = [k for k in exp if k.startswith("Market ")]
    m = sum(exp[k] for k in mk) if mk else None
    if m is not None and abs(m) > 0.05:
        flags.append(f"ベータ調整後ネット {m * 100:+.1f}%（規律: ブック・ネット 5% 以下）")
    idio_share = idio_var / total if total > 0 else None
    if idio_share is not None and idio_share < 0.5:
        flags.append(f"ブックのリスクの {100 - idio_share * 100:.0f}% がファクター由来 — マーケットニュートラルになっていない")
    return {"positions": len(used), "symbols": used, "factors": rows, "factor_var_share": (fvar / total) if total > 0 else None,
            "idio_var_share": idio_share, "vol_pct": math.sqrt(max(total, 0)) * math.sqrt(252) * 100,
            "market_exposure_pct": (m or 0) * 100, "flags": flags, "days": n}
