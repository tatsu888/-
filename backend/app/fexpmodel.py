"""FEXP — factor analysis of one security, a basket or the book: market, sector, style, FX, rates, commodities, overseas.

Pure functions on daily changes keyed by "YYYY-MM-DD" (log returns; yields as bp changes). No look-ahead: everything is
estimated on data up to the as-of date, and the attribution of a window uses betas estimated BEFORE the window.

THE MODEL (estimation window ``est`` sessions, default 504 ≈ 2 years)

    r_t = α + β_M·M_t + β_S·S_t + Σ β_s·STYLE_s,t + Σ_k Σ_l β_k,l·X⊥_k,t−l + ε_t

  M      the market: TOPIX for a Japanese security, the S&P 500 otherwise
  S      the security's sector ETF minus the market (TOPIX-17 NEXT FUNDS 1617–1633 / SPDR)
  STYLE  market-relative style returns: the coverage style library (long-short terciles, Japan) and style ETFs minus
         the market (or a spread of two ETFs)
  X⊥     FX, rates, commodities and overseas equities, each made orthogonal to the market (the residual of an OLS on
         M_t over the estimation window). β_M therefore stays the TOTAL market beta and β_k is the sensitivity BEYOND
         the market. The "total β" of the maps is the plain regression on the factor alone (the market channel included).
  lags   a factor that closes after the Tokyo close (the New York FX close, US and European markets, US yields,
         commodities) moves a Japanese security on the same day AND the next one, so it enters as X_t and X_t−1
         (Dimson). Its exposure is β_k = β_k,0 + β_k,1 with the standard error from the full covariance. A non-Japanese
         security uses same-day changes only.

OUTPUTS
  exposures   β per 1 % (or per 10 bp for yields), se, t, 1σ impact (β × the factor's daily σ, % per day), VIF
  risk        Euler decomposition of the variance: share_k = β_k·cov(x_k, fitted) / var(r); Σ shares = R²; 1 − R² is specific
  attribution the log return of a recent window = Σ factor contributions + 個社要因 (α + residual)
  rolling     exposures of a few factors re-estimated on a moving window (a small model: fast and stable)
  maps        each candidate of a group (17 sectors, FX pairs, styles …) with the market only: partial β and t, and the
              total β without the market
  scenario    the expected move for shocks to several factors (% or bp) ± 1 se, from the coefficients and their covariance
"""
from __future__ import annotations

import math
from typing import Any

from .harness.regression import ols_report

GROUPS = ["マーケット", "セクター", "スタイル", "為替", "金利", "商品", "海外株"]
TOPIX17 = {
    "TSE:1617": "食品", "TSE:1618": "エネルギー資源", "TSE:1619": "建設・資材", "TSE:1620": "素材・化学", "TSE:1621": "医薬品",
    "TSE:1622": "自動車・輸送機", "TSE:1623": "鉄鋼・非鉄", "TSE:1624": "機械", "TSE:1625": "電機・精密",
    "TSE:1626": "情報通信・サービスその他", "TSE:1627": "電力・ガス", "TSE:1628": "運輸・物流", "TSE:1629": "商社・卸売",
    "TSE:1630": "小売", "TSE:1631": "銀行", "TSE:1632": "金融（除く銀行）", "TSE:1633": "不動産",
}
US_SECTORS = {
    "AMEX:XLK": "テクノロジー", "AMEX:XLF": "金融", "AMEX:XLE": "エネルギー", "AMEX:XLV": "ヘルスケア", "AMEX:XLI": "資本財",
    "AMEX:XLY": "一般消費財", "AMEX:XLP": "生活必需品", "AMEX:XLU": "公益", "AMEX:XLB": "素材", "AMEX:XLRE": "不動産",
    "AMEX:XLC": "通信サービス", "NASDAQ:SMH": "半導体",
}
# the coverage style library (factorlib.STYLES keys) — long-short terciles of the coverage universe
LIB_STYLES = [("size", "サイズ（大型 − 小型）"), ("value", "バリュー（PB/PE/DY）"), ("mom_1m", "モメンタム 1m（リバーサル）"),
              ("mom_6m", "モメンタム 6m"), ("mom_1y", "モメンタム 1y"), ("volatility", "ボラティリティ（高 − 低）"),
              ("quality", "クオリティ（ROE）"), ("beta", "ベータ（高 − 低）")]


def _f(fid: str, label: str, group: str, kind: str, symbol: str | None = None, late: bool = False, orth: bool = False,
       **kw: Any) -> dict[str, Any]:
    return {"id": fid, "label": label, "group": group, "kind": kind, "symbol": symbol, "late": late, "orth": orth, **kw}


def catalog(region: str) -> list[dict[str, Any]]:
    """Every factor that can be used for a security of ``region`` ("JP" or "US").
    kind: ret = log return, bp = yield change in bp, xs = ETF minus the market, spread = ETF A minus ETF B, lib = style library."""
    if region == "JP":
        out = [_f("mkt", "TOPIX", "マーケット", "ret", "TVC:TOPIX")]
        out += [_f(f"sec.{s.split(':')[1]}", f"{n}（{s.split(':')[1]}）", "セクター", "xs", s) for s, n in TOPIX17.items()]
        out += [_f(f"sty.{k}", lbl, "スタイル", "lib", lib=k) for k, lbl in LIB_STYLES]
        out += [_f("sty.etf.2516", "小型・グロース（2516 − TOPIX）", "スタイル", "xs", "TSE:2516"),
                _f("sty.etf.1489", "高配当（1489 − TOPIX）", "スタイル", "xs", "TSE:1489"),
                _f("sty.etf.1321", "大型・値がさ（日経225 1321 − TOPIX）", "スタイル", "xs", "TSE:1321"),
                _f("sty.etf.1591", "クオリティ（JPX400 1591 − TOPIX）", "スタイル", "xs", "TSE:1591")]
        out += [_f("fx.usdjpy", "ドル円（＋＝円安）", "為替", "ret", "FX:USDJPY", True, True),
                _f("fx.eurjpy", "ユーロ円（＋＝円安）", "為替", "ret", "FX:EURJPY", True, True),
                _f("fx.audjpy", "豪ドル円（＋＝円安・リスクオン）", "為替", "ret", "FX:AUDJPY", True, True),
                _f("fx.usdcnh", "ドル人民元（＋＝元安）", "為替", "ret", "FX_IDC:USDCNH", True, True),
                _f("fx.dxy", "ドル指数 DXY", "為替", "ret", "TVC:DXY", True, True)]
        out += [_f("rate.jp10", "日本 10 年金利", "金利", "bp", "TVC:JP10Y", False, True),
                _f("rate.us10", "米国 10 年金利", "金利", "bp", "TVC:US10Y", True, True),
                _f("rate.us02", "米国 2 年金利", "金利", "bp", "TVC:US02Y", True, True)]
        out += [_f("cmd.oil", "原油 WTI", "商品", "ret", "TVC:USOIL", True, True),
                _f("cmd.copper", "銅", "商品", "ret", "COMEX:HG1!", True, True),
                _f("cmd.gold", "金", "商品", "ret", "TVC:GOLD", True, True)]
        out += [_f("os.spx", "米国株 S&P 500", "海外株", "ret", "SP:SPX", True, True),
                _f("os.sox", "米国 半導体 SOX", "海外株", "ret", "NASDAQ:SOX", True, True),
                _f("os.china", "中国株 FXI", "海外株", "ret", "AMEX:FXI", True, True),
                _f("os.europe", "欧州株 STOXX 50", "海外株", "ret", "TVC:SX5E", True, True)]
        return out
    out = [_f("mkt", "S&P 500", "マーケット", "ret", "SP:SPX")]
    out += [_f(f"sec.{s.split(':')[1]}", f"{n}（{s.split(':')[1]}）", "セクター", "xs", s) for s, n in US_SECTORS.items()]
    out += [_f("sty.mtum", "モメンタム（MTUM − 市場）", "スタイル", "xs", "BATS:MTUM"),
            _f("sty.vlue", "バリュー（VLUE − 市場）", "スタイル", "xs", "BATS:VLUE"),
            _f("sty.qual", "クオリティ（QUAL − 市場）", "スタイル", "xs", "BATS:QUAL"),
            _f("sty.usmv", "低ボラ（USMV − 市場）", "スタイル", "xs", "BATS:USMV"),
            _f("sty.iwm", "小型（IWM − 市場）", "スタイル", "xs", "AMEX:IWM"),
            _f("sty.gv", "グロース − バリュー（IWF − IWD）", "スタイル", "spread", "AMEX:IWF", other="AMEX:IWD"),
            _f("sty.hbl", "高ベータ − 低ボラ（SPHB − SPLV）", "スタイル", "spread", "AMEX:SPHB", other="AMEX:SPLV")]
    out += [_f("fx.dxy", "ドル指数 DXY", "為替", "ret", "TVC:DXY", False, True),
            _f("fx.usdjpy", "ドル円", "為替", "ret", "FX:USDJPY", False, True),
            _f("fx.eurusd", "ユーロドル", "為替", "ret", "FX:EURUSD", False, True),
            _f("fx.usdcnh", "ドル人民元", "為替", "ret", "FX_IDC:USDCNH", False, True)]
    out += [_f("rate.us10", "米国 10 年金利", "金利", "bp", "TVC:US10Y", False, True),
            _f("rate.us02", "米国 2 年金利", "金利", "bp", "TVC:US02Y", False, True)]
    out += [_f("cmd.oil", "原油 WTI", "商品", "ret", "TVC:USOIL", False, True),
            _f("cmd.copper", "銅", "商品", "ret", "COMEX:HG1!", False, True),
            _f("cmd.gold", "金", "商品", "ret", "TVC:GOLD", False, True)]
    out += [_f("os.topix", "日本株 TOPIX", "海外株", "ret", "TVC:TOPIX", False, True),
            _f("os.europe", "欧州株 STOXX 50", "海外株", "ret", "TVC:SX5E", False, True),
            _f("os.china", "中国株 FXI", "海外株", "ret", "AMEX:FXI", False, True)]
    return out


def default_ids(region: str, sector_id: str | None, available: set[str] | None = None) -> list[str]:
    """The main model when the user has not picked factors: enough to explain a stock, few enough to stay stable.
    Japan: the coverage style library (size, value, momentum 6m, volatility) where it has those series, topped up with
    the style ETFs when fewer than two are there (size / value need the scanner)."""
    ok = (lambda i: True) if available is None else (lambda i: i in available)
    if region == "JP":
        styles = [i for i in ("sty.size", "sty.value", "sty.mom_6m", "sty.volatility") if ok(i)]
        if len(styles) < 2:
            styles += [i for i in ("sty.etf.2516", "sty.etf.1489") if ok(i)]
        return ["mkt", *([sector_id] if sector_id else []), *styles, "fx.usdjpy", "rate.jp10", "rate.us10", "cmd.oil",
                "cmd.copper", "os.sox", "os.china"]
    return ["mkt", *([sector_id] if sector_id else []), "sty.mtum", "sty.vlue", "sty.qual", "sty.usmv", "sty.iwm", "fx.dxy",
            "rate.us10", "cmd.oil", "cmd.copper"]


def per_unit(kind: str) -> float:
    """β → % move of the security per 1 % move of the factor (per 10 bp for yields)."""
    return 1000.0 if kind == "bp" else 1.0


def symbols_of(cat: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for f in cat:
        for s in (f.get("symbol"), f.get("other")):
            if s and s not in out:
                out.append(s)
    return out


# ---- series ------------------------------------------------------------------------------------------------------
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


def factor_series(f: dict[str, Any], closes: dict[str, dict[str, float]], market: dict[str, float],
                  library: dict[str, dict[str, float]]) -> dict[str, float]:
    """Daily changes of one catalog factor (empty when its data is missing)."""
    k = f["kind"]
    if k == "lib":
        return dict(library.get(f["lib"]) or {})
    c = closes.get(f["symbol"] or "")
    if not c:
        return {}
    if k == "bp":
        return changes(c, "bp")
    r = changes(c)
    if k == "xs":
        return {d: v - market[d] for d, v in r.items() if d in market}
    if k == "spread":
        o = closes.get(f.get("other") or "")
        if not o:
            return {}
        ro = changes(o)
        return {d: v - ro[d] for d, v in r.items() if d in ro}
    return r


def lagged(s: dict[str, float]) -> dict[str, float]:
    """The previous observation of a series, keyed at the next date of the same series."""
    ds = sorted(s)
    return {b: s[a] for a, b in zip(ds, ds[1:])}


def weighted_returns(returns: dict[str, dict[str, float]], weights: dict[str, float]) -> dict[str, float]:
    """A basket / book: Σ w·r on the dates where every member has a return."""
    keys = [k for k in weights if returns.get(k)]
    if not keys:
        return {}
    dates = sorted(set.intersection(*(set(returns[k]) for k in keys)))
    return {d: sum(weights[k] * returns[k][d] for k in keys) for d in dates}


# ---- small statistics ------------------------------------------------------------------------------------------------
def _mean(x: list[float]) -> float:
    return sum(x) / len(x) if x else 0.0


def _sd(x: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    m = _mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))


def _cov(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = _mean(a), _mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (n - 1)


def _line(x: list[float], m: list[float]) -> tuple[float, float]:
    """OLS x = a + b·m."""
    vm = _cov(m, m)
    b = _cov(x, m) / vm if vm > 0 else 0.0
    return _mean(x) - b * _mean(m), b


# ---- the model ---------------------------------------------------------------------------------------------------------
def _columns(f: dict[str, Any], s: dict[str, float], lag: bool) -> list[tuple[str, dict[str, float], int]]:
    cols = [(f"{f['id']}@0", s, 0)]
    if lag and f.get("late"):
        cols.append((f"{f['id']}@1", lagged(s), 1))
    return cols


def common_dates(y: dict[str, float], cols: list[tuple[str, dict[str, float], int]]) -> list[str]:
    ds = set(y)
    for _, s, _ in cols:
        ds &= set(s)
    return sorted(ds)


def fit(y: dict[str, float], factors: list[dict[str, Any]], series: dict[str, dict[str, float]], dates: list[str],
        lag: bool) -> dict[str, Any]:
    """OLS of y on the factors over ``dates`` (factors orthogonal to the market where flagged, lags for late factors).
    Returns the coefficients per column, their covariance, the orthogonalisation lines and per-factor exposures."""
    mkt = series.get("mkt") if any(f["id"] == "mkt" for f in factors) else None
    cols: list[tuple[str, dict[str, float], int, dict[str, Any]]] = []
    for f in factors:
        for name, s, l in _columns(f, series[f["id"]], lag):
            cols.append((name, s, l, f))
    yv = [y[d] for d in dates]
    X: list[list[float]] = []
    lines: dict[str, tuple[float, float]] = {}
    raw_sd: dict[str, float] = {}
    for name, s, _l, f in cols:
        x = [s[d] for d in dates]
        if name.endswith("@0"):
            raw_sd[f["id"]] = _sd(x)
        if f.get("orth") and mkt is not None and f["id"] != "mkt":
            a, b = _line(x, [mkt[d] for d in dates])
            lines[name] = (a, b)
            x = [v - a - b * mkt[d] for v, d in zip(x, dates)]
        X.append(x)
    keep = [i for i, x in enumerate(X) if _sd(x) > 0]
    names = [cols[i][0] for i in keep]
    rows = [list(r) for r in zip(*(X[i] for i in keep))] if keep else [[] for _ in dates]
    if len(dates) <= len(names) + 10:
        raise ValueError(f"観測数が足りない（{len(dates)} 日、要因 {len(names)}）")
    rep = ols_report(yv, rows, names)
    sig2 = rep["sigma"] ** 2
    inv = rep["_inv"]
    beta = {c["name"]: c["coef"] for c in rep["coefficients"]}
    idx = {n: i + 1 for i, n in enumerate(names)}                     # +1: the intercept is column 0
    cov = {a: {b: sig2 * inv[idx[a]][idx[b]] for b in names} for a in names}
    var_x = {n: _sd(X[i]) ** 2 * (len(dates) - 1) for n, i in zip(names, keep)}
    fitted = [sum(beta[n] * X[i][t] for n, i in zip(names, keep)) for t in range(len(dates))]
    var_y = _sd(yv) ** 2
    exposures = []
    for f in factors:
        cn = [n for n in names if n.split("@")[0] == f["id"]]
        if not cn:
            continue
        b = sum(beta[n] for n in cn)
        var = sum(cov[a][c] for a in cn for c in cn)
        se = math.sqrt(max(var, 0.0))
        share = sum(beta[n] * _cov(X[keep[names.index(n)]], fitted) for n in cn) / var_y if var_y > 0 else 0.0
        u = per_unit(f["kind"])
        exposures.append({
            "id": f["id"], "label": f["label"], "group": f["group"], "kind": f["kind"], "lagged": len(cn) > 1,
            "beta": b, "se": se, "t": b / se if se > 0 else None, "per_unit_pct": b * u, "se_unit_pct": se * u,
            "unit": "10bp" if f["kind"] == "bp" else "1%",
            "impact_1sd_pct": b * raw_sd.get(f["id"], 0.0) * 100, "risk_share": share,
            "vif": max(inv[idx[n]][idx[n]] * var_x[n] for n in cn),
            "same_day_pct": beta[f"{f['id']}@0"] * u if f"{f['id']}@0" in beta else None,
            "next_day_pct": beta[f"{f['id']}@1"] * u if f"{f['id']}@1" in beta else None,
        })
    return {"rep": rep, "names": names, "beta": beta, "cov": cov, "lines": lines, "exposures": exposures,
            "alpha": beta.get("const", 0.0), "fitted": fitted, "y": yv}


def _x_window(f: dict[str, Any], col: str, s: dict[str, float], d: str, mkt: dict[str, float] | None,
              lines: dict[str, tuple[float, float]]) -> float:
    v = s[d]
    if col in lines and mkt is not None:
        a, b = lines[col]
        v -= a + b * mkt[d]
    return v


def analyze(y: dict[str, float], cat: list[dict[str, Any]], series: dict[str, dict[str, float]], ids: list[str],
            region: str, est: int = 504, window: int = 21, roll: int = 126, roll_ids: list[str] | None = None,
            end_offset: int = 0, step: int = 5, maps: bool = True, rolling: bool = True) -> dict[str, Any]:
    """The whole FEXP analysis. ``series`` holds the daily changes of every catalog factor that has data (by id)."""
    lag = region == "JP"
    by_id = {f["id"]: f for f in cat}
    warnings: list[str] = []
    missing = [i for i in ids if i in by_id and not series.get(i)]
    if missing:
        warnings.append("データが取れず外した要因: " + "、".join(by_id[i]["label"] for i in missing))
    use = [by_id[i] for i in ids if i in by_id and series.get(i)]
    if not use:
        raise ValueError("使える要因がない（市場データが取れていない）")
    cols = [c for f in use for c in _columns(f, series[f["id"]], lag)]
    dates = common_dates(y, cols)
    if end_offset:
        dates = dates[:-end_offset] if end_offset < len(dates) else []
    if len(dates) < 120:
        raise ValueError(f"共通の履歴が足りない（{len(dates)} 日。120 日以上必要）")
    edates = dates[-est:]
    cur = fit(y, use, series, edates, lag)
    rep = cur["rep"]
    mkt_id = "mkt" if any(f["id"] == "mkt" for f in use) else None
    groups: dict[str, float] = {}
    for e in cur["exposures"]:
        groups[e["group"]] = groups.get(e["group"], 0.0) + e["risk_share"]
    r2 = rep["r2"] or 0.0
    yv = cur["y"]
    resid_sd = rep["sigma"]
    vol = _sd(yv)
    exposures = sorted(cur["exposures"], key=lambda e: (GROUPS.index(e["group"]), -abs(e["t"] or 0)))
    for e in exposures:
        if e["vif"] and e["vif"] > 5:
            e["warn"] = f"他の要因と強く連動（VIF {e['vif']:.1f}）— β は不安定"
    out: dict[str, Any] = {
        "region": region, "n": len(edates), "from": edates[0], "to": edates[-1], "lagged": lag,
        "r2": r2, "adj_r2": rep.get("adj_r2"), "vol_pct": vol * math.sqrt(252) * 100,
        "idio_vol_pct": resid_sd * math.sqrt(252) * 100, "alpha_ann_pct": cur["alpha"] * 252 * 100,
        "exposures": exposures, "risk": {"groups": {g: groups.get(g, 0.0) for g in GROUPS if g in groups}, "specific": max(0.0, 1 - r2)},
        "verdict": ("個社要因が大きい（ファンダの判断が効きやすい）" if 1 - r2 >= 0.5 else
                    "ファクターが支配的（判断が上書きされやすい → ヘッジかペアで持つ）" if 1 - r2 < 0.3 else "中間"),
        "model": {"ids": [f["id"] for f in use], "beta": cur["beta"], "cov": cur["cov"], "lines": cur["lines"],
                  "kinds": {f["id"]: f["kind"] for f in use}, "labels": {f["id"]: f["label"] for f in use}},
        "warnings": warnings,
    }
    # ---- attribution of the last `window` sessions with betas estimated before it ----
    try:
        wd = dates[-window:]
        pre = dates[-window - est:-window]
        if len(pre) < 120:
            raise ValueError(f"窓の前の履歴が足りない（{len(pre)} 日）")
        att = fit(y, use, series, pre, lag)
        mkt = series.get("mkt") if mkt_id else None
        contrib: dict[str, float] = {}
        daily_f: list[float] = []
        for d in wd:
            tot = 0.0
            for f in use:
                for col, s, _l in _columns(f, series[f["id"]], lag):
                    if col not in att["beta"]:
                        continue
                    v = att["beta"][col] * _x_window(f, col, s, d, mkt, att["lines"])
                    contrib[f["id"]] = contrib.get(f["id"], 0.0) + v
                    tot += v
            daily_f.append(tot)
        total = sum(y[d] for d in wd)
        specific = total - sum(contrib.values())
        g: dict[str, float] = {}
        for f in use:
            g[f["group"]] = g.get(f["group"], 0.0) + contrib.get(f["id"], 0.0)
        cum, cf, cs, ser = 0.0, 0.0, 0.0, []
        for d, fv in zip(wd, daily_f):
            cum += y[d]
            cf += fv
            cs += y[d] - fv
            ser.append({"date": d, "total": cum * 100, "factor": cf * 100, "specific": cs * 100})
        out["attribution"] = {
            "window": window, "from": wd[0], "to": wd[-1], "est_from": pre[0], "est_to": pre[-1],
            "total_pct": total * 100, "specific_pct": specific * 100, "alpha_pct": att["alpha"] * len(wd) * 100,
            "groups_pct": {k: v * 100 for k, v in g.items()},
            "factors": sorted(({"id": f["id"], "label": f["label"], "group": f["group"], "contribution_pct": contrib.get(f["id"], 0.0) * 100}
                               for f in use), key=lambda r: -abs(r["contribution_pct"])),
            "series": ser,
        }
    except ValueError as e:
        out["attribution"] = {"error": str(e)}
    # ---- rolling exposures (a small model of the chosen factors) ----
    if not rolling:
        if maps:
            out["maps"] = factor_maps(y, cat, series, region, edates[-1], est, ids)
        return out
    rids = [i for i in (roll_ids or []) if i in by_id and series.get(i)] or default_roll_ids(exposures, region)
    rf = [by_id[i] for i in dict.fromkeys(rids) if i in by_id and series.get(i)][:6]
    rcols = [c for f in rf for c in _columns(f, series[f["id"]], lag)]
    rdates = common_dates(y, rcols)
    if end_offset:
        rdates = rdates[:-end_offset] if end_offset < len(rdates) else []
    rolling: dict[str, Any] = {"window": roll, "ids": [f["id"] for f in rf], "labels": {f["id"]: f["label"] for f in rf},
                               "dates": [], "beta": {f["id"]: [] for f in rf}, "t": {f["id"]: [] for f in rf}}
    for end in range(roll, len(rdates) + 1, step):
        try:
            r = fit(y, rf, series, rdates[end - roll:end], lag)
        except (ValueError, ZeroDivisionError):
            continue
        ex = {e["id"]: e for e in r["exposures"]}
        rolling["dates"].append(rdates[end - 1])
        for f in rf:
            e = ex.get(f["id"])
            rolling["beta"][f["id"]].append(e["per_unit_pct"] if e else None)
            rolling["t"][f["id"]].append(e["t"] if e else None)
    out["rolling"] = rolling
    # ---- maps: each candidate with the market only ----
    if maps:
        out["maps"] = factor_maps(y, cat, series, region, edates[-1], est, ids)
    return out


def default_roll_ids(exposures: list[dict[str, Any]], region: str) -> list[str]:
    """Market, the sector, the home FX factor and the strongest other factor of the main model."""
    have = {e["id"] for e in exposures}
    sec = next((e["id"] for e in exposures if e["group"] == "セクター"), None)
    fx = "fx.usdjpy" if region == "JP" else "fx.dxy"
    out = [i for i in ("mkt", sec, fx) if i and i in have]
    rest = sorted((e for e in exposures if e["id"] not in out), key=lambda e: -abs(e["t"] or 0))
    return out + [e["id"] for e in rest[:1]]


def factor_maps(y: dict[str, float], cat: list[dict[str, Any]], series: dict[str, dict[str, float]], region: str,
                asof: str, est: int, in_model: list[str]) -> dict[str, list[dict[str, Any]]]:
    lag = region == "JP"
    mkt_f = next((f for f in cat if f["id"] == "mkt"), None)
    out: dict[str, list[dict[str, Any]]] = {}
    for f in cat:
        if f["id"] == "mkt" or not series.get(f["id"]):
            continue
        row: dict[str, Any] = {"id": f["id"], "label": f["label"], "kind": f["kind"], "in_model": f["id"] in in_model,
                               "unit": "10bp" if f["kind"] == "bp" else "1%"}
        try:
            both = [mkt_f, f] if mkt_f and series.get("mkt") else [f]
            cols = [c for g in both for c in _columns(g, series[g["id"]], lag)]
            ds = [d for d in common_dates(y, cols) if d <= asof][-est:]
            part = fit(y, both, series, ds, lag)
            e = next(x for x in part["exposures"] if x["id"] == f["id"])
            row.update(beta=e["per_unit_pct"], t=e["t"], n=len(ds))
            alone = fit(y, [{**f, "orth": False}], series, ds, lag)
            a = alone["exposures"][0]
            row.update(total_beta=a["per_unit_pct"], total_t=a["t"], total_r2=alone["rep"]["r2"])
        except (ValueError, ZeroDivisionError, StopIteration, IndexError):
            continue
        out.setdefault(f["group"], []).append(row)
    for g in out.values():
        g.sort(key=lambda r: -abs(r.get("t") or 0))
    return out


def scenario(model: dict[str, Any], shocks: dict[str, float]) -> dict[str, Any]:
    """Expected move (%) for shocks in the factors' own units (% for prices and FX, bp for yields), others held at 0.
    A factor made orthogonal to the market moves by (shock − b·market shock), so a joint scenario is consistent."""
    m = (shocks.get("mkt") or 0.0) / 100
    vec: dict[str, float] = {}
    contrib: dict[str, float] = {}
    for name, b in model["beta"].items():
        if name == "const":
            continue
        fid = name.split("@")[0]
        kind = model["kinds"].get(fid)
        raw = shocks.get(fid)
        if raw is None or not math.isfinite(raw):
            raw = 0.0
        x = raw if kind == "bp" else raw / 100
        if name in model["lines"]:
            x -= model["lines"][name][1] * m
        vec[name] = x
        contrib[fid] = contrib.get(fid, 0.0) + b * x * 100
    exp = sum(contrib.values())
    var = sum(vec[a] * model["cov"][a][c] * vec[c] for a in vec for c in vec)
    return {"expected_pct": exp, "se_pct": math.sqrt(max(var, 0.0)) * 100,
            "contributions": sorted(({"id": k, "label": model["labels"].get(k, k), "pct": v} for k, v in contrib.items() if abs(v) > 1e-12),
                                    key=lambda r: -abs(r["pct"]))}


def summary_row(res: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """One line of the coverage comparison: exposures of the chosen factors (per unit) and t."""
    ex = {e["id"]: e for e in res["exposures"]}
    sec = next((e for e in res["exposures"] if e["group"] == "セクター"), None)
    cells: dict[str, Any] = {}
    for k in keys:
        e = sec if k == "sector" else ex.get(k)
        cells[k] = {"beta": e["per_unit_pct"], "t": e["t"], "label": e["label"]} if e else None
    return {"cells": cells, "r2": res["r2"], "specific": res["risk"]["specific"], "vol_pct": res["vol_pct"],
            "idio_vol_pct": res["idio_vol_pct"], "from": res["from"], "to": res["to"]}
