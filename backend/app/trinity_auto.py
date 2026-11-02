"""AUTO Trinity — rule-based, automatically refreshed 三位一体 analysis for a whole coverage universe.

No AI, no manual input required. Every number comes from a written rule (below) applied to price /
volume / scanner / JPX-margin data, so the same data always gives the same verdict.

Per symbol, three views ∈ {+1 long, 0, −1 short}:

  F  ファンダメンタル (土台)
     • a saved SCORE sheet (human) wins if present (source = "SCORE");
     • otherwise a RULE score from scanner fundamentals, cross-sectional within the universe:
         quality  35%  ROE↑, operating margin↑, gross margin↑
         growth   25%  revenue YoY↑
         value    25%  EV/EBITDA↓, PE↓ (PE ≤ 0 = worst)
         safety   15%  debt/equity↓, FCF < 0 → 0
       composite percentile p → 1–5 by the Notion distribution (01.1: ~60% unpredictable ≈ 3,
       ~20% clearly mispriced): p ≤ 10% → 1.0–2.6, 10–90% → 2.75–3.35, ≥ 90% → 3.4–5.0.
       Direction: ≥ 3.4 LONG, ≤ 2.7 SHORT (same thresholds as SCORE).
  M  マクロ (意識する層) — Growth × Liquidity quadrant (03.4) favoured / disfavoured style bucket of
     the stock's sector (+ high-beta names in 2. ピーキング).
  L3 需給・行動 — 天井/底 (03.5): turnover (or volume) percentile in its own history, 信用倍率
     percentile, distance from the 52-week high, 3-month momentum. Top zone → −1, bottom zone → +1.

Verdict (05.2 / 01.6): no fundamental direction → NEUTRAL (fundamentals are the base; macro never
creates a position). Otherwise conviction = 1 + (#views agreeing with F) − (#views opposing F),
clipped to 0–3 ("三方向から同じ結論に着いたときだけ確信度を上げてよい").
Size (rule): cap (long 3% / short 2%) × conviction / 3 × min(1, 30% / annual vol).
Arbitration rules of 05.2 are applied as flags. Short models computable from data are evaluated.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from . import framework as F

LONG_CAP, SHORT_CAP, VOL_TARGET = 3.0, 2.0, 30.0

# TradingView scanner sector → style bucket used by the Growth × Liquidity rotation
SECTOR_BUCKET = {
    "Technology Services": "tech", "Electronic Technology": "tech", "Communications": "tech",
    "Producer Manufacturing": "cyclical", "Consumer Durables": "cyclical", "Process Industries": "cyclical",
    "Transportation": "cyclical", "Industrial Services": "cyclical",
    "Energy Minerals": "commodity", "Non-Energy Minerals": "commodity",
    "Utilities": "defensive", "Health Technology": "defensive", "Consumer Non-Durables": "defensive",
    "Health Services": "defensive",
    "Finance": "value",
}
BUCKET_LABEL = {"tech": "テック／グロース", "cyclical": "シクリカル", "commodity": "コモディティ", "defensive": "ディフェンシブ",
                "value": "バリュー（金融）", "other": "その他"}
# Notion 03.4: 優位アセット per quadrant; disfavoured = the style that the quadrant works against
FAVOURED = {1: {"tech", "cyclical"}, 2: {"commodity", "value"}, 3: {"defensive"}, 4: {"tech"}}
DISFAVOURED = {1: {"defensive"}, 2: {"tech"}, 3: {"tech", "cyclical", "commodity"}, 4: {"commodity", "value"}}


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def percentile_ranks(values: dict[str, float | None], higher_better: bool = True) -> dict[str, float]:
    """Average-rank percentile in [0, 1] among symbols that have a value."""
    items = sorted((v, s) for s, v in values.items() if v is not None)
    n = len(items)
    if n < 2:
        return {s: 0.5 for _, s in items}
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][0] == items[i][0]:
            j += 1
        p = ((i + j) / 2) / (n - 1)
        for k in range(i, j + 1):
            out[items[k][1]] = p if higher_better else 1 - p
        i = j + 1
    return out


def percentile_to_score(p: float) -> float:
    if p <= 0.1:
        return 1.0 + (p / 0.1) * 1.6
    if p < 0.9:
        return 2.75 + (p - 0.1) / 0.8 * 0.6
    return 3.4 + (p - 0.9) / 0.1 * 1.6


def fundamental_rule_scores(scans: dict[str, dict[str, Any]], min_peers: int = 5) -> dict[str, dict[str, Any]]:
    syms = list(scans)
    col = lambda k: {s: _num((scans[s] or {}).get(k)) for s in syms}  # noqa: E731
    pe = {s: (1e9 if v is not None and v <= 0 else v) for s, v in col("price_earnings_ttm").items()}
    ev = {s: (1e9 if v is not None and v <= 0 else v) for s, v in col("enterprise_value_ebitda_ttm").items()}
    ranks = {
        "roe": percentile_ranks(col("return_on_equity")), "op_margin": percentile_ranks(col("operating_margin")),
        "gross_margin": percentile_ranks(col("gross_margin")), "rev_growth": percentile_ranks(col("total_revenue_yoy_growth_ttm")),
        "ev_ebitda": percentile_ranks(ev, False), "pe": percentile_ranks(pe, False),
        "debt": percentile_ranks(col("debt_to_equity"), False),
    }
    fcf = col("free_cash_flow")
    groups = {"quality": (0.35, ["roe", "op_margin", "gross_margin"]), "growth": (0.25, ["rev_growth"]),
              "value": (0.25, ["ev_ebitda", "pe"]), "safety": (0.15, ["debt"])}
    out: dict[str, dict[str, Any]] = {}
    for s in syms:
        comp: dict[str, float] = {}
        for g, (_, keys) in groups.items():
            vals = [ranks[k][s] for k in keys if s in ranks[k]]
            if g == "safety" and fcf.get(s) is not None and fcf[s] < 0:
                vals.append(0.0)
            if vals:
                comp[g] = sum(vals) / len(vals)
        covered = sum(groups[g][0] for g in comp)
        peers = min((len(ranks[k]) for k in ("roe", "op_margin", "pe") if ranks[k]), default=0)
        if covered < 0.5 or peers < min_peers:
            out[s] = {"score": None, "components": comp, "peers": peers,
                      "reason": "スキャナーのファンダメンタルズ不足" if covered < 0.5 else f"比較対象が{peers}銘柄（{min_peers}未満）"}
            continue
        p = sum(groups[g][0] * v for g, v in comp.items()) / covered
        out[s] = {"score": percentile_to_score(p), "percentile": p, "components": comp, "peers": peers}
    return out


def macro_fit(sector: str | None, beta: float | None, q: int | None) -> dict[str, Any]:
    bucket = SECTOR_BUCKET.get(sector or "", "other")
    if not q:
        return {"view": 0, "bucket": bucket, "reason": "象限データなし"}
    fav, dis = FAVOURED[q], DISFAVOURED[q]
    view = 1 if bucket in fav else -1 if bucket in dis else 0
    reason = f"{BUCKET_LABEL[bucket]} は {'優位' if view > 0 else '逆風' if view < 0 else '中立'}"
    if q == 2 and beta is not None and beta >= 1.2 and view == 0:
        view, reason = 1, f"高ベータ（β {beta:.2f}）はピーキングで優位"
    nq = {4: 1, 1: 2, 2: 3, 3: 4}[q]
    nxt = 1 if bucket in FAVOURED[nq] else -1 if bucket in DISFAVOURED[nq] else 0
    return {"view": view, "bucket": bucket, "reason": reason, "next_view": nxt}


def _pctl(hist: list[float], x: float) -> float | None:
    return sum(1 for v in hist if v <= x) / len(hist) * 100 if hist else None


def flow_view(bars: list[dict[str, Any]], shares: float | None = None, margin: dict[str, Any] | None = None,
              dividend_yield: float | None = None, risk_free: float | None = None) -> dict[str, Any]:
    closes = [b["close"] for b in bars]
    vols = [float(b.get("volume") or 0) for b in bars]
    if len(closes) < 130:
        return {"view": 0, "zone": "データ不足", "signals": [], "crowded": False}
    hi52 = max(closes[-252:])
    dd = (1 - closes[-1] / hi52) * 100 if hi52 else None
    mom3 = (closes[-1] / closes[-64] - 1) * 100 if len(closes) > 64 and closes[-64] else None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(max(1, len(closes) - 60), len(closes)) if closes[i - 1] > 0]
    vol = (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * math.sqrt(252) * 100 if len(rets) > 2 else None
    # activity: 20-session average turnover (or volume when float is unknown) vs its own history
    act = [v / shares * 100 for v in vols] if shares else vols
    avg20 = [sum(act[i - 20:i]) / 20 for i in range(20, len(act) + 1)]
    act_pct = _pctl(avg20, avg20[-1]) if avg20 else None
    tb = F.top_bottom(act if shares else None, margin, dividend_yield, risk_free)
    signals: list[str] = [s["signal"] for s in tb["top"] + tb["bottom"] if s["on"]]
    top = sum(1 for s in tb["top"] if s["on"])
    bottom = sum(1 for s in tb["bottom"] if s["on"])
    if not shares and act_pct is not None:  # volume-based fallback for the turnover rule
        if act_pct >= 95:
            top += 1
            signals.append("出来高が自己の過去分布で上位5%（浮動株不明のため出来高で代用）")
        elif act_pct <= 10:
            bottom += 1
            signals.append("出来高が自己の過去分布で下位10%（浮動株不明のため出来高で代用）")
    crowded = act_pct is not None and act_pct >= 90 and dd is not None and dd <= 5
    if crowded:
        signals.append("混雑の疑い：売買活発（上位10%）かつ52週高値から5%以内")
    if crowded:
        top += 1
    zone = "天井寄り" if top >= 2 and top > bottom else "底寄り" if bottom >= 2 and bottom > top else "中間帯"
    view = -1 if zone == "天井寄り" else 1 if zone == "底寄り" else 0
    return {"view": view, "zone": zone, "signals": signals, "crowded": crowded, "activity_pctl": act_pct,
            "drawdown_pct": dd, "mom_3m_pct": mom3, "vol_pct": vol}


def verdict(f_dir: str, m_view: int, l_view: int, vol: float | None, *, moat_qualifies: bool = False,
            crowded: bool = False, mcap_usd: float | None = None) -> dict[str, Any]:
    fv = 1 if f_dir == "LONG" else -1 if f_dir == "SHORT" else 0
    flags: list[str] = []
    if fv == 0:
        return {"direction": "NEUTRAL", "conviction": 0, "size_pct": 0.0, "agree": 0, "oppose": 0, "flags": flags}
    agree = (m_view == fv) + (l_view == fv)
    oppose = (m_view == -fv) + (l_view == -fv)
    conv = max(0, min(3, 1 + agree - oppose))
    cap = LONG_CAP if fv > 0 else SHORT_CAP
    scale = min(1.0, VOL_TARGET / vol) if vol else 1.0
    size = round(cap * conv / 3 * scale, 2)
    if fv < 0:
        flags.append("ショートはカタリスト必須（ロングは待てる）")
        if moat_qualifies:
            flags.append("裁定: 3.5句合致企業 → 個別ショートではなく TOPIX 先物／大型低ボラでヘッジ")
            size = 0.0
        if mcap_usd is not None and mcap_usd < 1e9:
            flags.append("小型株ショート禁止（時価総額 約10億ドル未満）")
            size = 0.0
    if fv > 0 and crowded:
        flags.append("裁定: 良い会社だがクラウデッド → Market Timing スリーブに限定、1〜3ヶ月")
    if m_view == -fv:
        flags.append("裁定: マクロは逆風だが期待値は正 → ネットをフラットに保ったままペアで持つ")
    if l_view == -fv:
        flags.append("需給が逆向き → エントリーを待つ（③関門）")
    return {"direction": "LONG" if fv > 0 else "SHORT", "conviction": conv, "size_pct": size,
            "agree": agree, "oppose": oppose, "flags": flags}


def sector_against(fv: int, sector_q: str | None) -> bool:
    """RRG of the stock's sector ETF works against the position (long in Lagging / short in Leading)."""
    return (fv > 0 and sector_q == "Lagging") or (fv < 0 and sector_q == "Leading")


def auto_gates(f_dir: str, m_view: int, l_view: int, size: float, sector_q: str | None = None) -> dict[str, str]:
    fv = 1 if f_dir == "LONG" else -1 if f_dir == "SHORT" else 0
    return {"①マクロ": "PASS" if fv and m_view != -fv and not sector_against(fv, sector_q) else "FAIL" if fv else "—",
            "②ファンダ": "PASS" if fv else "FAIL",
            "③需給": "PASS" if fv and l_view != -fv else "FAIL" if fv else "—",
            "④サイズ": "PASS" if size > 0 else "FAIL" if fv else "—"}


def evaluate(inputs: dict[str, dict[str, Any]], gl: dict[str, Any] | None, scorecards: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """inputs: {symbol: {bars, scan, margin, risk_free, mcap_usd}}; gl = macro.growth_liquidity output."""
    q = (gl or {}).get("current", {}).get("q") if gl and not gl.get("error") else None
    rule = fundamental_rule_scores({s: d.get("scan") or {} for s, d in inputs.items()})
    rows = []
    for s, d in inputs.items():
        sc = d.get("scan") or {}
        card = scorecards.get(s)
        if card and card.get("total") is not None:
            f_score, f_src, f_dir = card["total"], "SCORE", card.get("direction") or F.direction(card["total"])
        else:
            r = rule.get(s, {})
            f_score, f_src = r.get("score"), "RULE"
            f_dir = F.direction(f_score) if f_score is not None else "N/A"
        m = macro_fit(sc.get("sector"), _num(sc.get("beta_1_year")), q)
        shares = _num(sc.get("float_shares_outstanding")) or _num(sc.get("total_shares_outstanding"))
        fl = flow_view(d.get("bars") or [], shares, d.get("margin"), _num(sc.get("dividend_yield_recent")), d.get("risk_free"))
        moat = bool(card and card.get("moat_qualifies"))
        v = verdict(f_dir, m["view"], fl["view"], fl.get("vol_pct"), moat_qualifies=moat, crowded=fl["crowded"],
                    mcap_usd=d.get("mcap_usd"))
        sm_in = {"drawdown_from_high_pct": fl.get("drawdown_pct"), "market_cap_usd": d.get("mcap_usd"),
                 "revenue_growth_pct": _num(sc.get("total_revenue_yoy_growth_ttm")), "op_margin_pct": _num(sc.get("operating_margin")),
                 "fcf_negative": (_num(sc.get("free_cash_flow")) < 0) if _num(sc.get("free_cash_flow")) is not None else None,
                 "moat_qualifies": moat}
        bars = d.get("bars") or []
        if len(bars) >= 80:
            v20 = sum(float(b.get("volume") or 0) for b in bars[-20:]) / 20
            v60 = sum(float(b.get("volume") or 0) for b in bars[-80:-20]) / 60
            sm_in["volume_trend"] = v20 / v60 if v60 else None
        sm = F.short_models(sm_in)
        # extra context (filled by the runner when available): sector rotation, XRAY, catalyst
        srrg = d.get("sector_rrg") or None
        xr = d.get("xray") or None
        dte = d.get("days_to_earnings")
        fv = 1 if v["direction"] == "LONG" else -1 if v["direction"] == "SHORT" else 0
        if fv and srrg and sector_against(fv, srrg.get("quadrant")):
            v["flags"].append(f"セクター・フローが逆行（{srrg.get('label') or srrg.get('etf')}: RRG {srrg.get('quadrant')}）")
        if fv and xr and xr.get("idio") is not None and xr["idio"] < 0.3:
            v["flags"].append(f"個別要因 {xr['idio'] * 100:.0f}%（マクロ・セクターに上書きされやすい）→ ペア／ヘッジで持つ")
        if fv < 0 and dte is not None:
            v["flags"].append(f"カタリスト: 決算まで {dte} 日" if 0 <= dte <= 30 else "30日以内に決算なし — カタリスト要確認")
        rows.append({
            "symbol": s, "name": sc.get("description"), "sector": sc.get("sector"),
            "f": {"score": f_score, "source": f_src, "direction": f_dir, "detail": rule.get(s) if f_src == "RULE" else None},
            "m": m, "l": fl, **v, "gates": auto_gates(f_dir, m["view"], fl["view"], v["size_pct"], (srrg or {}).get("quadrant")),
            "sector_rrg": srrg, "xray": xr, "days_to_earnings": dte,
            "short_models": [x["name"] for x in sm["models"] if x["status"] == "MATCH"],
            "last": bars[-1]["close"] if bars else None,
        })
    rows.sort(key=lambda r: (-r["conviction"], r["direction"] != "LONG", -(r["f"]["score"] or 0)))
    longs = [r for r in rows if r["direction"] == "LONG" and r["size_pct"] > 0]
    shorts = [r for r in rows if r["direction"] == "SHORT" and r["size_pct"] > 0]
    gross = sum(r["size_pct"] for r in longs + shorts)
    net = sum(r["size_pct"] for r in longs) - sum(r["size_pct"] for r in shorts)
    return {"rows": rows, "quadrant": (gl or {}).get("current"), "next_quadrant": (gl or {}).get("next"),
            "rotation": (gl or {}).get("rotation"),
            "book": {"longs": len(longs), "shorts": len(shorts), "gross_pct": gross, "net_pct": net,
                     "net_ok": abs(net) <= 5.0},
            "rules": __doc__}


def diff(prev: dict[str, Any] | None, cur: dict[str, Any]) -> list[dict[str, Any]]:
    """Changes in direction / conviction / macro quadrant since the previous snapshot."""
    if not prev:
        return []
    old = {r["symbol"]: r for r in prev.get("rows", [])}
    out = []
    pq, cq = (prev.get("quadrant") or {}).get("q"), (cur.get("quadrant") or {}).get("q")
    if pq and cq and pq != cq:
        out.append({"symbol": "*MACRO*", "what": "quadrant", "from": (prev.get("quadrant") or {}).get("name"),
                    "to": (cur.get("quadrant") or {}).get("name")})
    oth = {t["id"]: t for t in prev.get("themes", []) or []}
    for t in cur.get("themes", []) or []:
        o = oth.get(t["id"])
        if o and o.get("phase") != t.get("phase"):
            out.append({"symbol": f"THEME {t['name']}", "what": "theme", "from": o.get("phase"), "to": t.get("phase")})
    for r in cur.get("rows", []):
        o = old.get(r["symbol"])
        if not o:
            out.append({"symbol": r["symbol"], "what": "new", "from": None, "to": f"{r['direction']} c{r['conviction']}"})
            continue
        if o["direction"] != r["direction"] or o["conviction"] != r["conviction"]:
            out.append({"symbol": r["symbol"], "what": "verdict", "from": f"{o['direction']} c{o['conviction']}",
                        "to": f"{r['direction']} c{r['conviction']}"})
    return out


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")
