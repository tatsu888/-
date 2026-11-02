"""Macro & cross-asset "recognition propagation" analytics (pure python, deterministic).

PROPAGATION MAP (the user's market-timing framework, docs/PROPAGATION.md)
    Within an asset class, recognition spreads from niche markets to major markets:
        tier 1  macro specialists (first movers)
        tier 2  macro investors (days → weeks)
        tier 3  Japanese single-stock investors (weeks → months)
    Each map item is a proxy series (a symbol, a spread, a ratio or an equal-weight basket) with a
    "risk-on" direction so that +z always means "risk-on / reflationary" for that item.

Signals per item (daily, UTC-date aligned)
    chg_N   N-day change: % for prices/ratios/baskets, basis points for yields/spreads
    z       standardized 20-day change: (chg_20 − mean) / sd over the trailing ``z_lookback`` days
    sz      signed z = z × direction (risk-on positive)
Tier composites = mean signed z of the tier's items (optionally per asset class); lead-lag between
tier composites estimates how many days recognition takes to propagate; a "gap" flags asset
classes where tier 1/2 moved strongly but tier 3 has not (yet) followed.
"""
from __future__ import annotations

import copy
import datetime as dt
import math
from typing import Any

from .leadlag import cross_correlation
from .models import Bar
from .stats import pearson

TIERS = {1: "マクロ専門家 (初動)", 2: "マクロ投資家 (数日〜数週間)", 3: "日本の個別株投資家 (数週間〜数カ月)"}
CLASSES = ["株式", "金利・クレジット", "通貨", "コモディティ", "オルタナ・その他"]

# series spec:  {"sym": S} | {"spread": [A, B]} (A−B, yields) | {"ratio": [A, B]} | {"basket": [...]}
# kind: "price" (log-return based, % changes) or "yield" (level differences, bp)
# dir:  +1 if "up" = risk-on / reflation, −1 otherwise
DEFAULT_MAP: list[dict[str, Any]] = [
    # ---------------- 株式
    {"id": "frontier_eq", "label": "フロンティア株式", "cls": "株式", "tier": 1, "series": {"sym": "AMEX:FM"}, "kind": "price", "dir": 1},
    {"id": "em_eq", "label": "主要新興国株式", "cls": "株式", "tier": 2, "series": {"sym": "AMEX:EEM"}, "kind": "price", "dir": 1},
    {"id": "eu_eq", "label": "欧州株価指数", "cls": "株式", "tier": 2, "series": {"sym": "TVC:SX5E"}, "kind": "price", "dir": 1},
    {"id": "useu_factor", "label": "米欧株ファクター (モメンタム−低ボラ)", "cls": "株式", "tier": 2,
     "series": {"ratio": ["BATS:MTUM", "BATS:USMV"]}, "kind": "price", "dir": 1},
    {"id": "us_idx", "label": "米国株価指数", "cls": "株式", "tier": 3, "series": {"sym": "SP:SPX"}, "kind": "price", "dir": 1},
    {"id": "jp_idx", "label": "日本株価指数", "cls": "株式", "tier": 3, "series": {"sym": "TVC:TOPIX"}, "kind": "price", "dir": 1},
    {"id": "jp_factor", "label": "日本株ファクター (グロース250/高配当)", "cls": "株式", "tier": 3,
     "series": {"ratio": ["TSE:2516", "TSE:1489"]}, "kind": "price", "dir": 1},
    {"id": "jp_style", "label": "日本株の物色選好 (景気敏感/ディフェンシブ)", "cls": "株式", "tier": 3,
     "series": {"ratio": [{"basket": ["TSE:1622", "TSE:1624", "TSE:1625", "TSE:1631"]},
                          {"basket": ["TSE:1617", "TSE:1621", "TSE:1627"]}]}, "kind": "price", "dir": 1},
    # ---------------- 金利・クレジット
    {"id": "dm_credit", "label": "先進国クレジット (HY/国債)", "cls": "金利・クレジット", "tier": 1,
     "series": {"ratio": ["AMEX:HYG", "NASDAQ:IEF"]}, "kind": "price", "dir": 1},
    {"id": "cb", "label": "転換社債 (CB)", "cls": "金利・クレジット", "tier": 1, "series": {"sym": "AMEX:CWB"}, "kind": "price", "dir": 1},
    {"id": "funding", "label": "短期資金・ベーシス (2Y−3M)", "cls": "金利・クレジット", "tier": 1,
     "series": {"spread": ["TVC:US02Y", "TVC:US03MY"]}, "kind": "yield", "dir": 1},
    {"id": "curve", "label": "米欧イールドカーブ (10Y−2Y)", "cls": "金利・クレジット", "tier": 2,
     "series": {"spread": ["TVC:US10Y", "TVC:US02Y"]}, "kind": "yield", "dir": 1},
    {"id": "periphery", "label": "欧州周縁国スプレッド (伊−独10Y)", "cls": "金利・クレジット", "tier": 2,
     "series": {"spread": ["TVC:IT10Y", "TVC:DE10Y"]}, "kind": "yield", "dir": -1},
    {"id": "embi", "label": "新興国国債 (EMBI: EMB)", "cls": "金利・クレジット", "tier": 2, "series": {"sym": "NASDAQ:EMB"}, "kind": "price", "dir": 1},
    {"id": "bei", "label": "インフレ期待 (BEI: TIP/IEF)", "cls": "金利・クレジット", "tier": 2,
     "series": {"ratio": ["AMEX:TIP", "NASDAQ:IEF"]}, "kind": "price", "dir": 1},
    {"id": "us_long", "label": "米国長期金利 (10Y)", "cls": "金利・クレジット", "tier": 3, "series": {"sym": "TVC:US10Y"}, "kind": "yield", "dir": 1},
    {"id": "jp_long", "label": "円長期金利 (JGB10Y)", "cls": "金利・クレジット", "tier": 3, "series": {"sym": "TVC:JP10Y"}, "kind": "yield", "dir": 1},
    # ---------------- 通貨 (baskets of USDxxx are inverted so up = local currency strength = risk-on)
    {"id": "frontier_fx", "label": "フロンティア通貨", "cls": "通貨", "tier": 1,
     "series": {"basket": ["FX_IDC:USDEGP", "FX_IDC:USDNGN", "FX_IDC:USDPKR", "FX_IDC:USDKES", "FX_IDC:USDVND"]}, "kind": "price", "dir": -1},
    {"id": "em_fx", "label": "主要新興国通貨", "cls": "通貨", "tier": 2,
     "series": {"basket": ["FX_IDC:USDBRL", "FX_IDC:USDMXN", "FX_IDC:USDZAR", "FX_IDC:USDINR", "FX_IDC:USDIDR"]}, "kind": "price", "dir": -1},
    {"id": "g10_comm_fx", "label": "G10資源国通貨 (AUD/NZD/CAD/NOK)", "cls": "通貨", "tier": 2,
     "series": {"basket": ["FX:AUDUSD", "FX:NZDUSD", {"inv": "FX:USDCAD"}, {"inv": "FX:USDNOK"}]}, "kind": "price", "dir": 1},
    {"id": "usdjpy", "label": "ドル/円", "cls": "通貨", "tier": 3, "series": {"sym": "FX:USDJPY"}, "kind": "price", "dir": 1},
    {"id": "dxy", "label": "ドル指数", "cls": "通貨", "tier": 3, "series": {"sym": "TVC:DXY"}, "kind": "price", "dir": -1},
    # ---------------- コモディティ
    {"id": "niche_comm", "label": "ニッチコモディティ (ウラン/リチウム)", "cls": "コモディティ", "tier": 1,
     "series": {"basket": ["AMEX:URA", "AMEX:LIT"]}, "kind": "price", "dir": 1},
    {"id": "copper", "label": "銅・産業金属", "cls": "コモディティ", "tier": 1, "series": {"sym": "COMEX:HG1!"}, "kind": "price", "dir": 1},
    {"id": "oil", "label": "原油・エネルギー", "cls": "コモディティ", "tier": 2, "series": {"sym": "TVC:USOIL"}, "kind": "price", "dir": 1},
    {"id": "gold", "label": "金・貴金属", "cls": "コモディティ", "tier": 2, "series": {"sym": "TVC:GOLD"}, "kind": "price", "dir": -1},
    # ---------------- オルタナ・その他
    {"id": "btc", "label": "クリプト (BTC)", "cls": "オルタナ・その他", "tier": 1, "series": {"sym": "BINANCE:BTCUSDT"}, "kind": "price", "dir": 1},
    {"id": "bdi", "label": "バルチック海運 (BDRY)", "cls": "オルタナ・その他", "tier": 1, "series": {"sym": "AMEX:BDRY"}, "kind": "price", "dir": 1},
    {"id": "vix", "label": "株式ボラ (VIX)", "cls": "オルタナ・その他", "tier": 2, "series": {"sym": "TVC:VIX"}, "kind": "price", "dir": -1},
    {"id": "move", "label": "金利ボラ (MOVE)", "cls": "オルタナ・その他", "tier": 2, "series": {"sym": "TVC:MOVE"}, "kind": "price", "dir": -1},
    {"id": "greit", "label": "グローバルREIT", "cls": "オルタナ・その他", "tier": 2, "series": {"sym": "AMEX:REET"}, "kind": "price", "dir": 1},
    {"id": "jreit", "label": "J-REIT", "cls": "オルタナ・その他", "tier": 3, "series": {"sym": "TSE:1343"}, "kind": "price", "dir": 1},
    {"id": "private", "label": "私募資産 (上場PE: PSP)", "cls": "オルタナ・その他", "tier": 3, "series": {"sym": "AMEX:PSP"}, "kind": "price", "dir": 1},
]


# ---------------------------------------------------------------------------
# series construction
# ---------------------------------------------------------------------------
def symbols_in(spec: Any) -> list[str]:
    if isinstance(spec, str):
        return [spec]
    if isinstance(spec, dict):
        out: list[str] = []
        for k in ("sym", "inv"):
            if k in spec:
                out += symbols_in(spec[k])
        for k in ("spread", "ratio", "basket"):
            for leg in spec.get(k, []):
                out += symbols_in(leg)
        return out
    return []


def _closes(bars: list[Bar]) -> dict[str, float]:
    return {dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).strftime("%Y-%m-%d"): b["close"] for b in bars}


def build(spec: Any, data: dict[str, dict[str, float]]) -> dict[str, float]:
    """date → value. Baskets are equal-weight indices (rebased to 100) on common dates."""
    if isinstance(spec, str):
        return dict(data.get(spec, {}))
    if "sym" in spec:
        return build(spec["sym"], data)
    if "inv" in spec:
        s = build(spec["inv"], data)
        return {d: 1 / v for d, v in s.items() if v}
    if "spread" in spec:
        a, b = (build(x, data) for x in spec["spread"])
        return {d: a[d] - b[d] for d in a.keys() & b.keys()}
    if "ratio" in spec:
        a, b = (build(x, data) for x in spec["ratio"])
        return {d: a[d] / b[d] for d in a.keys() & b.keys() if b[d]}
    if "basket" in spec:
        legs = [build(x, data) for x in spec["basket"]]
        legs = [x for x in legs if x]
        if not legs:
            return {}
        dates = sorted(set.intersection(*(set(x) for x in legs)))
        if not dates:
            return {}
        base = [x[dates[0]] for x in legs]
        return {d: 100 * sum(x[d] / b0 for x, b0 in zip(legs, base) if b0) / len(legs) for d in dates}
    return {}


def _mean(x: list[float]) -> float:
    return sum(x) / len(x)


def _sd(x: list[float]) -> float:
    m = _mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1)) if len(x) > 1 else 0.0


def item_signals(series: dict[str, float], kind: str, direction: int, z_window: int = 20,
                 z_lookback: int = 500) -> dict[str, Any]:
    dates = sorted(series)
    vals = [series[d] for d in dates]
    n = len(vals)
    if n < z_window + 30:
        return {"error": f"only {n} observations"}

    def chg(i: int, k: int) -> float | None:
        if i - k < 0:
            return None
        a, b = vals[i - k], vals[i]
        if kind == "yield":
            return (b - a) * 100  # bp
        return (b / a - 1) * 100 if a > 0 and b > 0 else None

    c20 = [chg(i, z_window) for i in range(n)]
    sz_series: dict[str, float] = {}
    for i in range(n):
        lo = max(z_window, i - z_lookback)
        hist = [c for c in c20[lo:i + 1] if c is not None]
        if len(hist) >= 30 and c20[i] is not None:
            sd = _sd(hist)
            if sd > 0:
                sz_series[dates[i]] = (c20[i] - _mean(hist)) / sd * direction
    last = n - 1
    ma100 = _mean(vals[-100:]) if n >= 100 else None
    spark = vals[-120:]
    lo_, hi_ = min(spark), max(spark)
    return {
        "last": vals[-1], "date": dates[-1], "kind": kind, "dir": direction,
        "chg_5": chg(last, 5), "chg_20": chg(last, 20), "chg_60": chg(last, 60),
        "z": sz_series[dates[-1]] * direction if dates[-1] in sz_series else None,  # unsigned (raw move)
        "sz": sz_series.get(dates[-1]),                                               # signed: + = risk-on
        "above_ma100": (vals[-1] > ma100) if ma100 is not None else None,
        "spark": [round((v - lo_) / (hi_ - lo_), 3) if hi_ > lo_ else 0.5 for v in spark],
        "_sz_series": sz_series, "_dates": dates, "_vals": vals,
    }


# ---------------------------------------------------------------------------
# propagation analysis
# ---------------------------------------------------------------------------
def composites(items: list[dict[str, Any]], key: str = "tier", cls: str | None = None) -> dict[Any, dict[str, float]]:
    """{tier: {date: mean signed z}} using items that have signals (optionally one asset class)."""
    by: dict[Any, list[dict[str, float]]] = {}
    for it in items:
        sig = it.get("signals") or {}
        if "_sz_series" not in sig or (cls and it["cls"] != cls):
            continue
        by.setdefault(it[key], []).append(sig["_sz_series"])
    out = {}
    for k, lst in by.items():
        dates = sorted(set().union(*lst))
        comp = {}
        for d in dates:
            vals = [s[d] for s in lst if d in s]
            if len(vals) >= max(1, len(lst) // 2):
                comp[d] = _mean(vals)
        out[k] = comp
    return out


def tier_leadlag(comp: dict[int, dict[str, float]], max_lag: int = 30) -> list[dict[str, Any]]:
    """CCF of daily changes between consecutive tiers' composites (positive lag = earlier tier leads)."""
    out = []
    for a, b in ((1, 2), (2, 3), (1, 3)):
        if a not in comp or b not in comp:
            continue
        dates = sorted(comp[a].keys() & comp[b].keys())
        if len(dates) < max_lag * 3:
            continue
        xa = [comp[a][dates[i]] - comp[a][dates[i - 1]] for i in range(1, len(dates))]
        xb = [comp[b][dates[i]] - comp[b][dates[i - 1]] for i in range(1, len(dates))]
        cc = cross_correlation(xa, xb, max_lag)
        lead = [r for r in cc["lags"] if r["lag"] >= 0 and r["corr"] is not None]
        best = max(lead, key=lambda r: r["corr"]) if lead else None
        # level correlation at the best lag (composites are smooth: easier to read)
        lvl = None
        if best:
            k = best["lag"]
            la = [comp[a][d] for d in dates[: len(dates) - k]]
            lb = [comp[b][d] for d in dates[k:]]
            lvl = pearson(la, lb)
        out.append({"from": a, "to": b, "best_lag_days": best["lag"] if best else None,
                    "corr_changes": best["corr"] if best else None, "corr_levels": lvl,
                    "band": cc["band"], "observations": len(dates), "lags": cc["lags"]})
    return out


def propagation_gaps(items: list[dict[str, Any]], threshold: float = 1.0) -> list[dict[str, Any]]:
    """Per asset class: upstream (tier 1-2) signed z vs downstream (tier 3). Flags 未波及 / 逆行 / 波及済."""
    out = []
    for c in CLASSES:
        ups = [it["signals"]["sz"] for it in items if it["cls"] == c and it["tier"] in (1, 2)
               and (it.get("signals") or {}).get("sz") is not None]
        downs = [it["signals"]["sz"] for it in items if it["cls"] == c and it["tier"] == 3
                 and (it.get("signals") or {}).get("sz") is not None]
        if not ups:
            continue
        up = _mean(ups)
        down = _mean(downs) if downs else None
        if down is None:
            state = "下流なし (株式・通貨・金利に集約)"
        elif abs(up) < threshold:
            state = "上流は静穏"
        elif down * up <= 0:
            state = "未波及 (下流が逆行/未反応)"
        elif abs(down) < 0.5 * abs(up):
            state = "波及途中"
        else:
            state = "波及済"
        out.append({"cls": c, "upstream_sz": up, "downstream_sz": down, "gap": up - (down or 0.0), "state": state,
                    "direction": "リスクオン" if up > 0 else "リスクオフ"})
    out.sort(key=lambda g: -abs(g["gap"]))
    return out


def item_leaders(target: dict[str, Any], candidates: list[dict[str, Any]], max_lag: int = 20, top: int = 3
                 ) -> list[dict[str, Any]]:
    """Which upstream items lead this item? CCF of daily returns (or bp changes), positive lags only."""
    def rets(sig: dict[str, Any]) -> dict[str, float]:
        d, v = sig["_dates"], sig["_vals"]
        if sig["kind"] == "yield":
            return {d[i]: (v[i] - v[i - 1]) * sig["dir"] for i in range(1, len(d))}
        return {d[i]: math.log(v[i] / v[i - 1]) * sig["dir"] for i in range(1, len(d)) if v[i] > 0 and v[i - 1] > 0}

    ts = target.get("signals") or {}
    if "_dates" not in ts:
        return []
    ty = rets(ts)
    rows = []
    for c in candidates:
        cs = c.get("signals") or {}
        if "_dates" not in cs or c["id"] == target["id"]:
            continue
        cx = rets(cs)
        dates = sorted(ty.keys() & cx.keys())
        if len(dates) < 120:
            continue
        x, y = [cx[d] for d in dates], [ty[d] for d in dates]
        cc = cross_correlation(x, y, max_lag)
        lead = [r for r in cc["lags"] if r["lag"] > 0 and r["corr"] is not None]
        if not lead:
            continue
        best = max(lead, key=lambda r: abs(r["corr"]))
        rows.append({"id": c["id"], "label": c["label"], "tier": c["tier"], "lag": best["lag"], "corr": best["corr"],
                     "significant": abs(best["corr"]) > (cc["band"] or 1), "lag0": next(r["corr"] for r in cc["lags"] if r["lag"] == 0)})
    rows.sort(key=lambda r: -abs(r["corr"]))
    return rows[:top]


def public_item(it: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in it.items() if k != "signals"}
    sig = it.get("signals") or {}
    out["signals"] = {k: v for k, v in sig.items() if not k.startswith("_")}
    return out


def analyze(map_items: list[dict[str, Any]], data: dict[str, dict[str, float]], z_window: int = 20,
            gap_threshold: float = 1.0, max_lag: int = 30) -> dict[str, Any]:
    items = copy.deepcopy(map_items)
    for it in items:
        series = build(it["series"], data)
        it["signals"] = item_signals(series, it.get("kind", "price"), int(it.get("dir", 1)), z_window) if series else {
            "error": "no data for " + ", ".join(symbols_in(it["series"]))}
    comp = composites(items)
    ll = tier_leadlag(comp, max_lag)
    gaps = propagation_gaps(items, gap_threshold)
    upstream = [it for it in items if it["tier"] in (1, 2)]
    for it in items:
        if it["tier"] == 3:
            it["leaders"] = item_leaders(it, upstream)
    comp_out = {str(k): [{"date": d, "value": v} for d, v in sorted(s.items())][-500:] for k, s in comp.items()}
    latest = {str(k): (list(s.values())[-1] if s else None) for k, s in ((k, dict(sorted(v.items()))) for k, v in comp.items())}
    by_class = {c: {str(t): (lambda s: s[max(s)] if s else None)(v) for t, v in composites(items, cls=c).items()} for c in CLASSES}
    return {"tiers": TIERS, "classes": CLASSES, "items": [public_item(it) for it in items], "composites": comp_out,
            "composite_latest": latest, "class_tier_latest": by_class, "tier_leadlag": ll, "gaps": gaps,
            "params": {"z_window": z_window, "gap_threshold": gap_threshold, "max_lag": max_lag}}


# ---------------------------------------------------------------------------
# MACRO: regime (growth × inflation) and asset returns by regime
# ---------------------------------------------------------------------------
REGIME_INPUTS = {
    "growth": {"ratio": ["COMEX:HG1!", "TVC:GOLD"]},     # copper/gold rising = growth improving
    "inflation": {"ratio": ["AMEX:TIP", "NASDAQ:IEF"]},  # TIPS outperforming nominals = breakevens rising
}
REGIME_ASSETS = ["SP:SPX", "TVC:TOPIX", "NASDAQ:IEF", "TVC:GOLD", "TVC:USOIL", "FX:USDJPY", "AMEX:EEM", "AMEX:HYG"]
REGIME_NAMES = {(1, 0): "Reflation-lite / Goldilocks (成長↑ インフレ↓)", (1, 1): "Reflation (成長↑ インフレ↑)",
                (0, 1): "Stagflation (成長↓ インフレ↑)", (0, 0): "Deflation / Risk-off (成長↓ インフレ↓)"}


def monthly(series: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for d in sorted(series):
        out[d[:7]] = series[d]
    return out


def regimes(data: dict[str, dict[str, float]], lookback_months: int = 3) -> dict[str, Any]:
    g = monthly(build(REGIME_INPUTS["growth"], data))
    i = monthly(build(REGIME_INPUTS["inflation"], data))
    months = sorted(g.keys() & i.keys())
    hist = []
    for k in range(lookback_months, len(months)):
        m, p = months[k], months[k - lookback_months]
        gs = 1 if g[m] > g[p] else 0
        ins = 1 if i[m] > i[p] else 0
        hist.append({"month": m, "growth_up": gs, "inflation_up": ins, "regime": REGIME_NAMES[(gs, ins)],
                     "growth_chg": (g[m] / g[p] - 1) * 100, "inflation_chg": (i[m] / i[p] - 1) * 100})
    # forward 1-month asset returns by regime (regime known at month end → next month return)
    asset_m = {a: monthly(data.get(a, {})) for a in REGIME_ASSETS}
    table: dict[str, dict[str, list[float]]] = {}
    for k, h in enumerate(hist[:-1]):
        nxt = hist[k + 1]["month"]
        for a, s in asset_m.items():
            if h["month"] in s and nxt in s and s[h["month"]]:
                table.setdefault(h["regime"], {}).setdefault(a, []).append((s[nxt] / s[h["month"]] - 1) * 100)
    stats = {r: {a: {"mean": _mean(v), "hit": sum(1 for x in v if x > 0) / len(v) * 100, "n": len(v)}
                 for a, v in d.items() if v} for r, d in table.items()}
    return {"current": hist[-1] if hist else None, "history": hist[-36:], "returns_by_regime": stats,
            "assets": REGIME_ASSETS, "inputs": REGIME_INPUTS,
            "note": "growth = copper/gold, inflation = TIP/IEF (3-month change); returns are NEXT-month (no look-ahead)"}


# ---------------------------------------------------------------------------
# Growth × Liquidity 4-quadrant rotation (Notion 03.4 マクロ・サイクリカル・モニター)
# ---------------------------------------------------------------------------
# The user's own composite indicator is proprietary; these are MARKET-BASED PROXIES (editable here):
#   growth    : 3M change of copper/gold (log) and of the US 10Y yield (bp)
#   liquidity : −3M change of DXY (log), −3M change of the US 2Y yield (bp), 3M change of HYG/IEF (log)
# Each component's 63-day change is z-scored on its trailing 3-year history; the axis = mean of z.
GL_INPUTS = {
    "growth": [("Copper/Gold", {"ratio": ["COMEX:HG1!", "TVC:GOLD"]}, "log", 1), ("US 10Y", "TVC:US10Y", "level", 1)],
    "liquidity": [("DXY", "TVC:DXY", "log", -1), ("US 2Y", "TVC:US02Y", "level", -1),
                  ("HY/IEF", {"ratio": ["AMEX:HYG", "NASDAQ:IEF"]}, "log", 1)],
}
# Notion: 時計回りに 4 → 1 → 2 → 3 と巡る
GL_QUADRANTS = {
    1: {"name": "1. 回復", "pos": "右上", "liq_label": "緩和", "growth_label": "拡大／回復", "assets": "テック／シクリカル／日本／中国／EM"},
    2: {"name": "2. ピーキング", "pos": "右下", "liq_label": "引き締め", "growth_label": "拡大／回復", "assets": "ベータ／EM／コモディティ／バリュー"},
    3: {"name": "3. スローダウン", "pos": "左下", "liq_label": "引き締め", "growth_label": "減速", "assets": "ディフェンシブ／クオリティ／ゴールド／債券／DXY"},
    4: {"name": "4. ボトミング", "pos": "左上", "liq_label": "緩和", "growth_label": "減速", "assets": "テック／グロース／日本／欧州／中国"},
}
GL_NEXT = {4: 1, 1: 2, 2: 3, 3: 4}
GL_ASSETS = {"Tech QQQ": "NASDAQ:QQQ", "Cyclicals XLI": "AMEX:XLI", "Defensive XLP": "AMEX:XLP", "Japan TOPIX": "TVC:TOPIX",
             "China FXI": "AMEX:FXI", "EM EEM": "AMEX:EEM", "Europe VGK": "AMEX:VGK", "Commodities DBC": "AMEX:DBC",
             "Value IWD": "AMEX:IWD", "Gold": "TVC:GOLD", "Bonds IEF": "NASDAQ:IEF", "DXY": "TVC:DXY"}


def quadrant(g: float, l: float) -> int:
    if g >= 0:
        return 1 if l >= 0 else 2
    return 4 if l >= 0 else 3


def _axis(data: dict[str, dict[str, float]], comps: list[tuple[str, Any, str, int]], horizon: int,
          z_window: int) -> tuple[dict[str, float], list[dict[str, Any]]]:
    zs: list[dict[str, float]] = []
    info = []
    for label, spec, how, sign in comps:
        s = build(spec, data)
        ds = sorted(s)
        chg: dict[str, float] = {}
        for i in range(horizon, len(ds)):
            a, b = s[ds[i - horizon]], s[ds[i]]
            if how == "log":
                if a > 0 and b > 0:
                    chg[ds[i]] = sign * math.log(b / a)
            else:
                chg[ds[i]] = sign * (b - a)
        cd = sorted(chg)
        z: dict[str, float] = {}
        for i in range(60, len(cd)):
            win = [chg[d] for d in cd[max(0, i - z_window):i + 1]]
            sd = _sd(win)
            if sd > 0:
                z[cd[i]] = (chg[cd[i]] - _mean(win)) / sd
        info.append({"label": label, "spec": spec, "sign": sign, "n": len(z), "last_z": z[max(z)] if z else None})
        if z:
            zs.append(z)
    if not zs:
        return {}, info
    common = sorted(set.intersection(*(set(z) for z in zs)))
    return {d: sum(z[d] for z in zs) / len(zs) for d in common}, info


def growth_liquidity(data: dict[str, dict[str, float]], horizon: int = 63, z_window: int = 756,
                     trail: int = 126) -> dict[str, Any]:
    g, gi = _axis(data, GL_INPUTS["growth"], horizon, z_window)
    l, li = _axis(data, GL_INPUTS["liquidity"], horizon, z_window)
    dates = sorted(g.keys() & l.keys())
    if not dates:
        return {"error": "insufficient data for growth/liquidity proxies", "inputs": {"growth": gi, "liquidity": li}}
    path = [{"date": d, "growth": g[d], "liquidity": l[d], "q": quadrant(g[d], l[d])} for d in dates]
    cur = path[-1]
    # rotation: angle change over the last 20 sessions (clockwise = negative in math convention when
    # x = growth, y = liquidity: 4 (左上) → 1 (右上) → 2 (右下) → 3 (左下))
    ang = [math.atan2(p["liquidity"], p["growth"]) for p in path[-21:]]
    dang = 0.0
    for a, b in zip(ang, ang[1:]):
        d = b - a
        d = (d + math.pi) % (2 * math.pi) - math.pi
        dang += d
    rotation = "時計回り（通常の循環）" if dang < -0.05 else "反時計回り（逆行）" if dang > 0.05 else "停滞"
    # forward 1-month (21 sessions) returns by quadrant, sampled every 21 sessions (no overlap, no look-ahead)
    table: dict[int, dict[str, list[float]]] = {}
    for i in range(0, len(path), 21):
        d0 = path[i]["date"]
        q = path[i]["q"]
        for name, sym in GL_ASSETS.items():
            s = data.get(sym) or {}
            sd = sorted(s)
            if d0 not in s:
                continue
            j = sd.index(d0)
            if j + 21 < len(sd) and s[d0]:
                table.setdefault(q, {}).setdefault(name, []).append((s[sd[j + 21]] / s[d0] - 1) * 100)
    stats = {q: {a: {"mean": _mean(v), "hit": sum(1 for x in v if x > 0) / len(v) * 100, "n": len(v)}
                 for a, v in d.items() if v} for q, d in table.items()}
    occupancy = {q: sum(1 for p in path if p["q"] == q) for q in GL_QUADRANTS}
    return {"current": {**cur, **GL_QUADRANTS[cur["q"]]}, "next": {"q": GL_NEXT[cur["q"]], **GL_QUADRANTS[GL_NEXT[cur["q"]]]},
            "rotation": rotation, "rotation_rad_20d": dang, "trail": path[-trail:], "closeup_days": 63,
            "quadrants": GL_QUADRANTS, "fwd_returns": stats, "occupancy": occupancy, "assets": GL_ASSETS,
            "inputs": {"growth": gi, "liquidity": li},
            "note": "市場データによる代理指標（ユーザー独自指標ではない）。各成分の3ヶ月変化を過去3年でz化し平均。"
                    "象限別リターンは翌1ヶ月（重複なし・先読みなし）。"}


MACRO_DASH = [
    {"group": "Policy & curve", "items": [
        ("US 2Y", "TVC:US02Y", "yield"), ("US 10Y", "TVC:US10Y", "yield"), ("US 10Y−2Y", {"spread": ["TVC:US10Y", "TVC:US02Y"]}, "yield"),
        ("DE 10Y", "TVC:DE10Y", "yield"), ("DE 10Y−2Y", {"spread": ["TVC:DE10Y", "TVC:DE02Y"]}, "yield"),
        ("JP 10Y", "TVC:JP10Y", "yield"), ("JP 30Y", "TVC:JP30Y", "yield"), ("US−JP 10Y", {"spread": ["TVC:US10Y", "TVC:JP10Y"]}, "yield")]},
    {"group": "Inflation & credit", "items": [
        ("BEI proxy TIP/IEF", {"ratio": ["AMEX:TIP", "NASDAQ:IEF"]}, "price"), ("HY/IEF", {"ratio": ["AMEX:HYG", "NASDAQ:IEF"]}, "price"),
        ("IG LQD", "AMEX:LQD", "price"), ("EM sovereign EMB", "NASDAQ:EMB", "price")]},
    {"group": "Risk & commodities", "items": [
        ("VIX", "TVC:VIX", "price"), ("MOVE", "TVC:MOVE", "price"), ("DXY", "TVC:DXY", "price"), ("USD/JPY", "FX:USDJPY", "price"),
        ("WTI", "TVC:USOIL", "price"), ("Gold", "TVC:GOLD", "price"), ("Copper/Gold", {"ratio": ["COMEX:HG1!", "TVC:GOLD"]}, "price")]},
]


def dashboard(data: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    out = []
    for grp in MACRO_DASH:
        rows = []
        for label, spec, kind in grp["items"]:
            s = build(spec, data)
            sig = item_signals(s, kind, 1) if s else {"error": "no data"}
            rows.append({"label": label, "spec": spec, **{k: v for k, v in sig.items() if not k.startswith("_")}})
        out.append({"group": grp["group"], "rows": rows})
    return out


def all_macro_symbols(map_items: list[dict[str, Any]]) -> list[str]:
    syms: list[str] = []
    for it in map_items:
        syms += symbols_in(it["series"])
    for spec in REGIME_INPUTS.values():
        syms += symbols_in(spec)
    syms += REGIME_ASSETS
    for comps in GL_INPUTS.values():
        for _, spec, _, _ in comps:
            syms += symbols_in(spec)
    syms += list(GL_ASSETS.values())
    for grp in MACRO_DASH:
        for _, spec, _ in grp["items"]:
            syms += symbols_in(spec)
    return list(dict.fromkeys(syms))


def closes_from_bars(bars_by_symbol: dict[str, list[Bar]]) -> dict[str, dict[str, float]]:
    return {s: _closes(b) for s, b in bars_by_symbol.items() if b}
