"""Factor library (macro side) and per-stock attribution: 個社要因 vs ファクター・スタイル.

MACRO SIDE — daily factor returns, Notion 04.4 list:
  マクロ   : 日本株(TOPIX)・米国・欧州・中国・原油・金利(日本10Y, 米国10Y; bp 変化)・FX(ドル円)  — market data
  セクター : TOPIX-17 業種 ETF − TOPIX（超過リターン）                                         — market data
  スタイル : the coverage universe split into terciles by a point-in-time exposure, rebalanced every
             21 sessions; factor return = mean(top third) − mean(bottom third), equal weight.
             ベータ(252d) / サイズ / バリュー(PB・PE・DY 合成) / モメンタム 1m・3m・6m(t−126→t−21)・1y(t−252→t−21) /
             ボラティリティ(60d) / クオリティ(ROE).  Price-based exposures are point-in-time; size / value /
             quality use the CURRENT scanner values (slow-moving, but this is look-ahead — documented).

STOCK SIDE — attribution of a window (e.g. the last 21 sessions):
  betas are estimated by OLS on the ``est`` sessions BEFORE the window (no look-ahead):
      r_t = a + β_mkt·MKT + β_sec·SECTOR + Σ β_style·STYLE + Σ β_macro·MACRO + e_t
  contribution_k = Σ_{t∈window} β_k f_k,t ;  個社要因 = window return − Σ contributions (alpha + residual).
  factor share = Σ fitted_t² / (Σ fitted_t² + Σ specific_t²) over the window
      ≥ 0.6 → ファクター・スタイル主導 / ≤ 0.35 → 個社要因主導 / otherwise 混在.
"""
from __future__ import annotations

import math
from typing import Any

from .harness.regression import ols_report

MACRO = {
    "日本株 TOPIX": ("TVC:TOPIX", "ret"), "米国 S&P500": ("SP:SPX", "ret"), "欧州 STOXX50": ("TVC:SX5E", "ret"),
    "中国 FXI": ("AMEX:FXI", "ret"), "原油": ("TVC:USOIL", "ret"), "金利 日本10Y": ("TVC:JP10Y", "bp"),
    "金利 米国10Y": ("TVC:US10Y", "bp"), "FX ドル円": ("FX:USDJPY", "ret"),
}
MARKET = "日本株 TOPIX"
STYLES = [("beta", "ベータ"), ("size", "サイズ"), ("value", "バリュー（PB/PE/DY）"), ("mom_1m", "モメンタム 1m（リバーサル）"),
          ("mom_3m", "モメンタム 3m"), ("mom_6m", "モメンタム 6m"), ("mom_1y", "モメンタム 1y"),
          ("volatility", "ボラティリティ"), ("quality", "クオリティ（ROE）")]
ATTR_STYLES = ["size", "value", "mom_6m", "mom_1m", "volatility", "beta"]
ATTR_MACRO = ["FX ドル円", "金利 日本10Y", "金利 米国10Y", "原油", "米国 S&P500", "中国 FXI"]


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


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _z(vals: dict[str, float]) -> dict[str, float]:
    xs = list(vals.values())
    if len(xs) < 3:
        return {}
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((v - m) ** 2 for v in xs) / (len(xs) - 1))
    return {k: (v - m) / sd for k, v in vals.items()} if sd > 0 else {k: 0.0 for k in vals}


def style_returns(closes: dict[str, dict[str, float]], market: dict[str, float], scan: dict[str, dict[str, Any]],
                  mcap_usd: dict[str, float] | None = None, rebalance: int = 21, min_names: int = 15) -> dict[str, dict[str, float]]:
    """Daily long-short tercile returns per style factor. closes = {symbol: {date: close}}; market = {date: log return}."""
    dates = sorted(market)
    rets = {s: changes(c) for s, c in closes.items() if len(c) > 60}
    idx = {d: i for i, d in enumerate(dates)}
    cl_dates = {s: sorted(c) for s, c in closes.items()}
    # static exposures (scanner)
    static: dict[str, dict[str, float]] = {"size": {}, "value": {}, "quality": {}}
    vparts: dict[str, dict[str, float]] = {"pb": {}, "pe": {}, "dy": {}}
    for s in rets:
        sc = scan.get(s) or {}
        mc = (mcap_usd or {}).get(s) or _num(sc.get("market_cap_basic"))
        if mc and mc > 0:
            static["size"][s] = math.log(mc)
        pb, pe, dy = _num(sc.get("price_book_ratio")), _num(sc.get("price_earnings_ttm")), _num(sc.get("dividend_yield_recent"))
        if pb and pb > 0:
            vparts["pb"][s] = 1 / pb
        if pe not in (None, 0):
            vparts["pe"][s] = 1 / pe
        if dy is not None:
            vparts["dy"][s] = dy
        q = _num(sc.get("return_on_equity"))
        if q is not None:
            static["quality"][s] = q
    zs = [_z(v) for v in vparts.values()]
    for s in rets:
        parts = [z[s] for z in zs if s in z]
        if parts:
            static["value"][s] = sum(parts) / len(parts)

    def logret(s: str, d_end: str, back_from: int, back_to: int = 0) -> float | None:
        ds = cl_dates[s]
        # index of last date <= d_end
        lo, hi = 0, len(ds) - 1
        if not ds or ds[0] > d_end:
            return None
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if ds[mid] <= d_end:
                lo = mid
            else:
                hi = mid - 1
        i1, i0 = lo - back_to, lo - back_from
        if i0 < 0 or i1 < 0:
            return None
        a, b = closes[s][ds[i0]], closes[s][ds[i1]]
        return math.log(b / a) if a > 0 and b > 0 else None

    out: dict[str, dict[str, float]] = {k: {} for k, _ in STYLES}
    reb = list(range(252, len(dates), rebalance))
    for j, ri in enumerate(reb):
        d0 = dates[ri - 1]  # exposures known at the close before the holding period
        expo: dict[str, dict[str, float]] = {k: {} for k, _ in STYLES}
        for s, r in rets.items():
            past = [dd for dd in dates[max(0, ri - 252):ri] if dd in r]
            if len(past) >= 120:
                x = [market[dd] for dd in past]
                y = [r[dd] for dd in past]
                mx, my = sum(x) / len(x), sum(y) / len(y)
                vx = sum((a - mx) ** 2 for a in x)
                if vx > 0:
                    expo["beta"][s] = sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx
                r60 = y[-60:]
                m60 = sum(r60) / len(r60)
                expo["volatility"][s] = math.sqrt(sum((v - m60) ** 2 for v in r60) / (len(r60) - 1))
            for k, (bf, bt) in {"mom_1m": (21, 0), "mom_3m": (63, 0), "mom_6m": (126, 21), "mom_1y": (252, 21)}.items():
                v = logret(s, d0, bf, bt)
                if v is not None:
                    expo[k][s] = v
            for k in ("size", "value", "quality"):
                if s in static[k]:
                    expo[k][s] = static[k][s]
        end = reb[j + 1] if j + 1 < len(reb) else len(dates)
        for k, _ in STYLES:
            ex = expo[k]
            if len(ex) < min_names:
                continue
            ranked = sorted(ex, key=lambda s: ex[s])
            n3 = len(ranked) // 3
            bot, top = ranked[:n3], ranked[-n3:]
            for di in range(ri, end):
                d = dates[di]
                t = [rets[s][d] for s in top if d in rets[s]]
                b = [rets[s][d] for s in bot if d in rets[s]]
                if len(t) >= 3 and len(b) >= 3:
                    out[k][d] = sum(t) / len(t) - sum(b) / len(b)
    return {k: v for k, v in out.items() if v}


def performance(series: dict[str, float]) -> dict[str, Any]:
    ds = sorted(series)
    vals = [series[d] for d in ds]

    def cum(n: int) -> float | None:
        return (math.exp(sum(vals[-n:])) - 1) * 100 if len(vals) >= n else None

    z = None
    if len(vals) >= 80:
        s20 = [sum(vals[i - 20:i]) for i in range(20, len(vals) + 1)]
        m = sum(s20) / len(s20)
        sd = math.sqrt(sum((v - m) ** 2 for v in s20) / (len(s20) - 1))
        z = (s20[-1] - m) / sd if sd > 0 else None
    return {"1D": vals[-1] * 100 if vals else None, "1W": cum(5), "1M": cum(21), "3M": cum(63), "6M": cum(126),
            "z_20d": z, "last_date": ds[-1] if ds else None, "n": len(vals)}


def attribute(stock: dict[str, float], factors: dict[str, dict[str, float]], window: int = 21, est: int = 252,
              end_offset: int = 0) -> dict[str, Any]:
    """stock / factors: daily changes by date. Factors whose names start with 'スタイル:' / 'セクター' / macro names."""
    names = [k for k, v in factors.items() if v]
    dates = sorted(set(stock).intersection(*(set(factors[k]) for k in names))) if names else sorted(stock)
    if end_offset:
        dates = dates[:-end_offset] if end_offset < len(dates) else []
    if len(dates) < window + 60:
        raise ValueError(f"not enough common history ({len(dates)} sessions)")
    wdates = dates[-window:]
    edates = dates[-window - est:-window]
    # drop factors with no variance in the estimation window
    names = [k for k in names if len({round(factors[k][d], 12) for d in edates}) > 1]
    X = [[factors[k][d] for k in names] for d in edates]
    y = [stock[d] for d in edates]
    rep = ols_report(y, X, names) if names else None
    beta = {c["name"]: c["coef"] for c in (rep or {}).get("coefficients", []) if c["name"] != "const"}
    tstat = {c["name"]: c["t"] for c in (rep or {}).get("coefficients", []) if c["name"] != "const"}
    alpha = next((c["coef"] for c in (rep or {}).get("coefficients", []) if c["name"] == "const"), 0.0)
    contrib = {k: sum(beta[k] * factors[k][d] for d in wdates) for k in names}
    total = sum(stock[d] for d in wdates)
    fitted = [sum(beta[k] * factors[k][d] for k in names) for d in wdates]
    spec = [stock[d] - f for d, f in zip(wdates, fitted)]
    ssf, sss = sum(v * v for v in fitted), sum(v * v for v in spec)
    share = ssf / (ssf + sss) if ssf + sss > 0 else None

    def group(k: str) -> str:
        if k == MARKET:
            return "マーケット"
        if k.startswith("セクター"):
            return "セクター"
        if k.startswith("スタイル:"):
            return "スタイル"
        return "マクロ"

    groups: dict[str, float] = {}
    for k, v in contrib.items():
        groups[group(k)] = groups.get(group(k), 0.0) + v
    specific = total - sum(contrib.values())
    cum_t = cum_f = cum_s = 0.0
    series = []
    for d, f, s_ in zip(wdates, fitted, spec):
        cum_t += stock[d]
        cum_f += f
        cum_s += s_
        series.append({"date": d, "total": cum_t * 100, "factor": cum_f * 100, "specific": cum_s * 100})
    verdict = (None if share is None else "ファクター・スタイル主導" if share >= 0.6 else "個社要因主導" if share <= 0.35 else "混在")
    rows = sorted(({"factor": k, "group": group(k), "beta": beta[k], "t": tstat.get(k), "contribution_pct": contrib[k] * 100}
                   for k in names), key=lambda r: -abs(r["contribution_pct"]))
    return {"window": window, "from": wdates[0], "to": wdates[-1], "est_from": edates[0], "est_to": edates[-1],
            "total_pct": total * 100, "specific_pct": specific * 100, "alpha_daily_pct": alpha * 100,
            "groups_pct": {k: v * 100 for k, v in groups.items()}, "factors": rows, "factor_share": share,
            "verdict": verdict, "r2_est": (rep or {}).get("r2"), "series": series,
            "note": "β は窓の前の期間で推定（先読みなし）。個社要因 = 窓のリターン − ファクター寄与の合計（α を含む）。"}
