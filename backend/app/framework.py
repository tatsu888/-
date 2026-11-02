"""Trinity framework (投資の三位一体 — Fundamental × Macro × Quant) as deterministic tools.

Source: the user's Notion STRATEGY / 投資の三位一体 (parts 1–5). Every rule below quotes a number
from those pages; where Notion gives no number (e.g. the individual factor weights of the scoring
sheet) the default here is a PLACEHOLDER and is labelled as such — edit it in the UI.
See docs/FRAMEWORK.md for the page → function map.

Pure functions only (no I/O) so the same inputs always give the same output.

    score_sheet       評点表 (Weight / Score / AI Score / Previous Score → Total, direction 3.4 / 2.7)
    moat_score        3.5句 (monopoly·NW 1 / cost·cospa 1 / brand 1 / tech 0.5) + 物理/化学 filter
    score_gap_size    評点差 → ポジションサイズ (スズキ例: 差0.5→0.5%, 差1.2→2%)
    kelly             E = PW·XW − PL·XL, F = E/(XW·XL), G, six principles
    exposure_check    六層のエクスポージャー規律 L1–L6 + DD rule
    pair_metrics      Pair Sigma / Pair Correlation / Beta-adj Net÷Gross / 20d spread percentile
    pair_suitability  4判別基準 (相関<0.5, 固有分散≥30%, 決算非同期, 貸株) + sector table
    short_models      空売り8モデル (conditions evaluated from inputs; unknown stays unknown)
    top_bottom        天井・底シグナル (回転率, 信用残, 配当利回り, 資金流出)
    gates             05.6 チェックリスト ①–⑤ + 四半期 Ⅰ–Ⅳ, 衝突時の裁定ルール
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# 評点表 (02.4)
# ---------------------------------------------------------------------------
# Notion lists the factors and says each is 配点あり with Σ = 100, but gives no per-factor numbers.
# These defaults are placeholders (PLACEHOLDER=True in the API) — the user sets the real weights.
SCORE_FACTORS: list[dict[str, Any]] = [
    {"id": "gov_incentive", "group": "Long-term", "block": "Corporate Governance", "factor": "Incentives（インセンティブ設計）", "weight": 5},
    {"id": "gov_holders", "group": "Long-term", "block": "Corporate Governance", "factor": "Shareholder structure（株主構成）", "weight": 5},
    {"id": "gov_punish", "group": "Long-term", "block": "Corporate Governance", "factor": "Punishment（懲罰制度）", "weight": 5},
    {"id": "gov_outside", "group": "Long-term", "block": "Corporate Governance", "factor": "Outside ownership（大株主の体外資産）", "weight": 5},
    {"id": "cmp_share", "group": "Long-term", "block": "Competitiveness", "factor": "Market share change（シェアの変化）", "weight": 10},
    {"id": "cmp_intensity", "group": "Long-term", "block": "Competitiveness", "factor": "Intensity of competition（競争の激しさ）", "weight": 10},
    {"id": "st_volume", "group": "Short-term", "block": "Short-term", "factor": "Volume（数量）", "weight": 10},
    {"id": "st_asp", "group": "Short-term", "block": "Short-term", "factor": "ASP（平均販売価格）", "weight": 10},
    {"id": "st_margin", "group": "Short-term", "block": "Short-term", "factor": "Margin（マージン）", "weight": 10},
    {"id": "st_wc", "group": "Short-term", "block": "Short-term", "factor": "W.C. / Revenue（運転資本÷売上）", "weight": 5},
    {"id": "val_evebitda", "group": "Valuation", "block": "Valuation", "factor": "EV/EBITDA", "weight": 7},
    {"id": "val_pe", "group": "Valuation", "block": "Valuation", "factor": "PE", "weight": 5},
    {"id": "val_vs_cons", "group": "Valuation", "block": "Valuation", "factor": "My forecasts vs. consensus（自分の予想 vs コンセンサス）", "weight": 8},
    {"id": "oth_fin", "group": "Other", "block": "Other financial", "factor": "Other financial metrics", "weight": 5},
]
# described (unscored) blocks of the sheet
SCORE_TEXT_BLOCKS = [
    {"id": "catalysts", "label": "Catalysts（まだ起きていないこと）"}, {"id": "risk", "label": "Risk（崩れる経路と下落幅）"},
    {"id": "follow", "label": "Key things to follow（先行指標）"},
    {"id": "mf_view", "label": "Mutual funds' view"}, {"id": "hf_view", "label": "Hedge funds' view"},
    {"id": "retail_view", "label": "Individual investors' view"}, {"id": "depth", "label": "Research depth"},
    {"id": "dividends", "label": "Dividends"}, {"id": "buybacks", "label": "Share buybacks"},
    {"id": "holders_action", "label": "Key shareholders action"},
    {"id": "proposition", "label": "取引可能な命題（誤価格の内容・大きさ・収束の日付）"},
]
LONG_THRESHOLD = 3.4    # 3.4〜3.5点以上ならロング
SHORT_THRESHOLD = 2.7   # 2.6〜2.7点以下ならショート


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _weighted(rows: list[dict[str, Any]], key: str) -> tuple[float | None, float]:
    num = den = 0.0
    for r in rows:
        w, s = _num(r.get("weight")), _num(r.get(key))
        if w and s is not None:
            num += w * s
            den += w
    return (num / den if den else None), den


def direction(total: float | None, long_th: float = LONG_THRESHOLD, short_th: float = SHORT_THRESHOLD) -> str:
    if total is None:
        return "N/A"
    if total >= long_th:
        return "LONG"
    if total <= short_th:
        return "SHORT"
    return "NEUTRAL"


def moat_score(moat: dict[str, Any] | None) -> dict[str, Any]:
    """3.5句: monopoly/network 1, cost/cospa 1, brand 1, technology 0.5. Each input 0..1 (or bool).

    ``physical`` (list of element ids judged 物理的優位 = bought equipment) halves that element's credit —
    「会社が主張する競争優位は、必ず『買ったものか、作ったものか』で切り分ける」.
    """
    moat = moat or {}
    weights = {"monopoly_network": 1.0, "cost_cospa": 1.0, "brand": 1.0, "technology": 0.5}
    labels = {"monopoly_network": "独占・ネットワーク効果", "cost_cospa": "コスト／コスパ", "brand": "ブランド", "technology": "技術リーダーシップ"}
    physical = set(moat.get("physical") or [])
    rows, total = [], 0.0
    for k, w in weights.items():
        v = moat.get(k)
        v = 1.0 if v is True else 0.0 if v in (False, None, "") else max(0.0, min(1.0, float(v)))
        credit = v * w * (0.5 if k in physical else 1.0)
        total += credit
        rows.append({"id": k, "label": labels[k], "weight": w, "value": v, "physical": k in physical, "credit": credit})
    matched = [r["label"] for r in rows if r["value"] >= 0.5]
    return {"rows": rows, "score": total, "max": 3.5, "matched": matched, "qualifies": bool(matched),
            "rule": "3.5句は1つでも当てはまればよい（空売りモデル①が4条件すべて必要なのとは対照的）"}


def score_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a Pinpoint scoring sheet. Scores are 1–5. Returns totals, direction, checks."""
    rows = sheet.get("rows") or SCORE_FACTORS
    issues: list[dict[str, str]] = []
    wsum = sum(_num(r.get("weight")) or 0 for r in rows)
    if abs(wsum - 100) > 1e-6:
        issues.append({"level": "error", "msg": f"Weight の合計が {wsum:g}（100 である必要）"})
    for r in rows:
        for k in ("score", "ai_score", "prev_score"):
            v = _num(r.get(k))
            if v is not None and not 1 <= v <= 5:
                issues.append({"level": "error", "msg": f"{r.get('factor')}: {k}={v:g} は 1〜5 の範囲外"})
    total, covered = _weighted(rows, "score")
    ai_total, _ = _weighted(rows, "ai_score")
    prev_total, _ = _weighted(rows, "prev_score")
    missing = [r.get("factor") for r in rows if _num(r.get("score")) is None]
    if missing:
        issues.append({"level": "warn", "msg": f"未採点 {len(missing)} 項目（Weight {wsum - covered:g} 分）: " + ", ".join(map(str, missing[:5]))})
    groups: dict[str, Any] = {}
    for g in dict.fromkeys(r.get("group") for r in rows):
        sub = [r for r in rows if r.get("group") == g]
        groups[str(g)] = {"score": _weighted(sub, "score")[0], "weight": sum(_num(r.get("weight")) or 0 for r in sub)}
    divergence = [{"factor": r.get("factor"), "score": _num(r.get("score")), "ai_score": _num(r.get("ai_score"))}
                  for r in rows if _num(r.get("score")) is not None and _num(r.get("ai_score")) is not None
                  and abs(_num(r.get("score")) - _num(r.get("ai_score"))) >= 1]
    changes = [{"factor": r.get("factor"), "prev": _num(r.get("prev_score")), "now": _num(r.get("score"))}
               for r in rows if _num(r.get("score")) is not None and _num(r.get("prev_score")) is not None
               and _num(r.get("score")) != _num(r.get("prev_score"))]
    long_th = _num(sheet.get("long_threshold")) or LONG_THRESHOLD
    short_th = _num(sheet.get("short_threshold")) or SHORT_THRESHOLD
    d = direction(total, long_th, short_th)
    moat = moat_score(sheet.get("moat"))
    if d != "N/A" and not (sheet.get("reason") or "").strip():
        issues.append({"level": "warn", "msg": "Reason（3.5 Sentences）が空 — なぜこの点数かを前提まで遡って書く"})
    if d == "SHORT" and moat["qualifies"]:
        issues.append({"level": "warn", "msg": "3.5句に合致する企業のショート → 裁定ルール: 個別ショートではなく TOPIX 先物／大型低ボラ銘柄でヘッジ（05.2）"})
    text = sheet.get("text") or {}
    if d in ("LONG", "SHORT") and not (text.get("proposition") or "").strip():
        issues.append({"level": "warn", "msg": "取引可能な命題（誤価格の内容・大きさ・収束の日付）が未記入 —『A社はB社より良い』はアルファにならない（05.4）"})
    if d == "SHORT" and not (text.get("catalysts") or "").strip():
        issues.append({"level": "error", "msg": "ショートはカタリスト必須（ロングは待てる）"})
    lt, st = groups.get("Long-term", {}).get("score"), groups.get("Short-term", {}).get("score")
    profile = None
    if lt is not None and st is not None:
        profile = ("長期◎・短期◎" if lt >= long_th and st >= long_th else "長期◎・短期✕（スズキ型: 競争力は高いが量・価格が伸びない → 小さく）"
                   if lt >= long_th and st <= short_th else "長期✕・短期◎（短期カタリスト型 — 3.5句外なら長期保有しない）"
                   if lt <= short_th and st >= long_th else "混在")
    return {
        "total": total, "ai_total": ai_total, "prev_total": prev_total,
        "delta": (total - prev_total) if total is not None and prev_total is not None else None,
        "direction": d, "ai_direction": direction(ai_total, long_th, short_th),
        "thresholds": {"long": long_th, "short": short_th}, "weight_sum": wsum, "weight_scored": covered,
        "groups": groups, "profile": profile, "moat": moat, "divergence": divergence, "changes": changes,
        "issues": issues,
        "rule": "全社を1〜5点で採点。予測不能（約60%）は3点前後、明確な乖離（約20%）だけが高／低得点。"
                f"{long_th:g}以上→ロング、{short_th:g}以下→ショート。",
    }


def score_gap_size(long_score: float, short_score: float, cap: float = 2.0) -> dict[str, Any]:
    """評点差 → サイズ. Notion (02.4, スズキ例) gives two points: gap 0.5 → 0.5%×0.5%, gap 1.2 → 2%.
    Linear interpolation through those points (and through 0 below 0.5), capped (default 2% = short cap)."""
    gap = long_score - short_score
    if gap <= 0:
        size = 0.0
    elif gap <= 0.5:
        size = gap  # 0 → 0, 0.5 → 0.5
    else:
        size = 0.5 + (gap - 0.5) * (2.0 - 0.5) / (1.2 - 0.5)
    return {"gap": gap, "size_pct": min(size, cap), "uncapped_pct": size, "cap_pct": cap,
            "anchors": [{"gap": 0.5, "size_pct": 0.5}, {"gap": 1.2, "size_pct": 2.0}],
            "note": "Notionの2点（差0.5→0.5%、差1.2→2%）の線形補間。タグ上限3%と合わせて 評点差→サイズ→タグ上限 の3段チェック"}


# ---------------------------------------------------------------------------
# Kelly (04.2)
# ---------------------------------------------------------------------------
def kelly(pw: float, xw: float, xl: float, side: str = "long", ruin_prob: float = 0.0,
          fraction: float = 0.5, cap_pct: float | None = None) -> dict[str, Any]:
    """pw = 勝率 (0..1), xw = 勝ったときの収益率 (0.3 = +30%), xl = 負けたときの損失率 (0.15 = −15%)."""
    if not 0 <= pw <= 1:
        raise ValueError("pw must be in [0, 1]")
    if xw <= 0 or xl <= 0:
        raise ValueError("xw and xl must be positive")
    pl = 1 - pw
    e = pw * xw - pl * xl
    var = pw * xw ** 2 + pl * xl ** 2 - e ** 2
    f = e / (xw * xl)

    def growth(fr: float) -> float | None:
        a, b = 1 + fr * xw, 1 - fr * xl
        return pw * math.log(a) + pl * math.log(b) if a > 0 and b > 0 else None

    fmax = min(1 / xl * 0.999, max(2 * abs(f), 1.0))
    curve = []
    for i in range(41):
        fr = fmax * i / 40
        g = growth(fr)
        curve.append({"f": fr, "g": g, "per_bet": (math.exp(g) - 1) if g is not None else None})
    g_star = growth(max(f, 0.0))
    cap = cap_pct if cap_pct is not None else (3.0 if side == "long" else 2.0)
    rec = max(0.0, min(f * fraction * 100, cap)) if e > 0 else 0.0
    if ruin_prob > 0:
        rec = min(rec, cap)
    principles = [
        {"n": 1, "rule": "期待値の符号と方向を一致させる", "ok": e > 0,
         "detail": f"E = {e:+.4f}（{side}ポジションの勝ち/負けとして入力）" + ("" if e > 0 else " → 参加不可")},
        {"n": 2, "rule": "正しい判断は良い結果を保証しない", "ok": None, "detail": "結果ではなくプロセスで評価する"},
        {"n": 3, "rule": "全損の可能性が0.1%でもあるならフルポジション禁止（レバレッジは論外）",
         "ok": not (ruin_prob > 0 and f >= 1), "detail": f"全損確率 {ruin_prob * 100:.2f}%、Kelly F = {f * 100:.1f}%"},
        {"n": 4, "rule": "予想される分散が大きいほどポジション比率は小さく", "ok": None,
         "detail": f"分散 = {var:.4f}（σ = {math.sqrt(max(var, 0)) * 100:.1f}%）"},
        {"n": 5, "rule": "XW×XL が大きいほど最適投資比率は小さい", "ok": None, "detail": f"XW×XL = {xw * xl:.4f}"},
        {"n": 6, "rule": "E/(XW×XL) が大きいほど資金成長は速い", "ok": None,
         "detail": f"G* = {g_star:.5f}/回（1回あたり {((math.exp(g_star) - 1) * 100) if g_star is not None else float('nan'):.3f}%）"},
    ]
    return {"e": e, "variance": var, "f": f, "f_pct": f * 100, "g_star": g_star,
            "growth_per_bet_pct": (math.exp(g_star) - 1) * 100 if g_star is not None else None,
            "fraction": fraction, "cap_pct": cap, "recommended_pct": rec, "curve": curve, "principles": principles,
            "formula": "E = PW·XW − PL·XL ／ F = E/(XW×XL) ／ G = PW·ln(1+F·XW) + PL·ln(1−F·XL)",
            "note": "F は理論値。ファットテールを考慮して計算値より低め（既定 1/2 Kelly）に張り、L1上限（ロング3%／ショート2%）で頭打ち"}


# ---------------------------------------------------------------------------
# 六層のエクスポージャー規律 (04.3)
# ---------------------------------------------------------------------------
LIMITS = {
    "long_pct": 3.0, "long_abs_pct": 4.0, "short_pct": 2.0, "short_abs_pct": 3.0,
    "smallcap_short_usd": 1e9, "alpha_short_min_downside_pct": 30.0,
    "pair_sigma_pct": 25.0, "pair_sigma_hard_pct": 30.0, "pair_sigma_ideal_pct": 10.0,
    "pair_beta_net_gross": 0.30, "pair_beta_exceptions": 3,
    "subsector_net_pct": 3.0, "sector_net_pct": 5.0,
    "book_gross": (60.0, 70.0), "book_net_abs": 5.0, "book_names": (40, 80), "book_pairs": (30, 40),
    "fund_gross": (150.0, 300.0), "fund_net": (-10.0, 10.0), "fund_single_abs_pct": 5.0,
    "dd_cut_pct": -5.0,
}
SHORT_TYPES = {"alpha": "① アルファ・ショート", "catalyst": "② 短期カタリスト・ショート",
               "pair_leg": "③ ペアの相方ショート", "funding": "④ Funding Short"}


def _chk(layer: str, rule: str, value: Any, limit: Any, status: str, msg: str = "", subject: str = "") -> dict[str, Any]:
    return {"layer": layer, "rule": rule, "subject": subject, "value": value, "limit": limit, "status": status, "msg": msg}


def exposure_check(positions: list[dict[str, Any]], level: str = "book", drawdown_pct: float | None = None,
                   pair_stats: dict[str, dict[str, Any]] | None = None, limits: dict[str, Any] | None = None) -> dict[str, Any]:
    """positions: [{symbol, weight (signed % of NAV), sector, subsector, pair, short_type, mcap_usd, beta,
    expected_downside_pct}]. level: 'book' (PM 1人分: gross 60–70%, net ≤5%) or 'fund' (gross 150–300%, net ±10%)."""
    L = {**LIMITS, **(limits or {})}
    out: list[dict[str, Any]] = []
    pos = [p for p in positions if _num(p.get("weight"))]
    # L1 single position
    for p in pos:
        w, sym = float(p["weight"]), p.get("symbol", "?")
        if level == "fund":
            st = "FAIL" if abs(w) > L["fund_single_abs_pct"] else "PASS"
            out.append(_chk("L6", "単一銘柄 ±5%（GMV比）", w, L["fund_single_abs_pct"], st, subject=sym))
            continue
        if w > 0:
            st = "PASS" if w <= L["long_pct"] else "WARN" if w <= L["long_abs_pct"] else "FAIL"
            out.append(_chk("L1", "ロング1銘柄 3%（絶対上限3〜4%）", w, L["long_pct"], st, subject=sym))
        else:
            st = "PASS" if -w <= L["short_pct"] else "WARN" if -w <= L["short_abs_pct"] else "FAIL"
            out.append(_chk("L1", "ショート1銘柄 2%（絶対上限3%）", w, -L["short_pct"], st, subject=sym))
            mc = _num(p.get("mcap_usd"))
            if mc is not None:
                out.append(_chk("L1", "小型株ショート禁止（時価総額 約10億ドル未満）", mc, L["smallcap_short_usd"],
                                "FAIL" if mc < L["smallcap_short_usd"] else "PASS", subject=sym))
            stype = p.get("short_type")
            if stype not in SHORT_TYPES:
                out.append(_chk("L1", "ショートの型を宣言（アルファ／カタリスト／ペア相方／Funding）", stype, list(SHORT_TYPES),
                                "WARN", "型を混同すると銘柄選定基準がずれる", subject=sym))
            elif stype == "alpha":
                dn = _num(p.get("expected_downside_pct"))
                out.append(_chk("L1", "アルファ・ショートは30〜40%以上の下落見込み", dn, L["alpha_short_min_downside_pct"],
                                "UNKNOWN" if dn is None else "PASS" if dn >= L["alpha_short_min_downside_pct"] else "FAIL", subject=sym))
            elif stype in ("pair_leg", "funding") and mc is not None and mc < 1e10:
                out.append(_chk("L1", "ペア相方/Funding は大型・低ボラ（サブ業界で時価総額1〜2位）", mc, 1e10, "WARN",
                                "スクイーズ回避のため大型を選ぶ", subject=sym))
    # L2 pairs
    pairs: dict[str, list[dict[str, Any]]] = {}
    for p in pos:
        if p.get("pair"):
            pairs.setdefault(str(p["pair"]), []).append(p)
    over = 0
    for pid, legs in pairs.items():
        gross = sum(abs(float(x["weight"])) for x in legs)
        betas = [_num(x.get("beta")) for x in legs]
        if all(b is not None for b in betas) and gross:
            bnet = sum(float(x["weight"]) * b for x, b in zip(legs, betas))
            ratio = abs(bnet) / gross
            bad = ratio >= L["pair_beta_net_gross"]
            over += bad
            out.append(_chk("L2", "Beta調整後 Net÷Gross 30%未満", ratio, L["pair_beta_net_gross"], "WARN" if bad else "PASS", subject=pid))
        subs = {x.get("subsector") for x in legs if x.get("subsector")}
        secs = {x.get("sector") for x in legs if x.get("sector")}
        if len(subs) > 1:
            out.append(_chk("L2", "同一サブセクター内で組む（真のペア）", sorted(subs), 1,
                            "FAIL" if len(secs) > 1 else "WARN",
                            "セクター越境＝デグロス局面で壊れる『偽のペア』" if len(secs) > 1 else "サブセクター越境", subject=pid))
        if not any(float(x["weight"]) > 0 for x in legs) or not any(float(x["weight"]) < 0 for x in legs):
            out.append(_chk("L2", "ペアはロング×ショート1組", len(legs), 2, "WARN", "片側しかない", subject=pid))
        ps = (pair_stats or {}).get(pid) or {}
        sig = _num(ps.get("pair_sigma_pct"))
        if sig is not None:
            st = "PASS" if sig < L["pair_sigma_pct"] else "WARN" if sig < L["pair_sigma_hard_pct"] else "FAIL"
            out.append(_chk("L2", "Pair Sigma 25〜30%未満（理想10%前後）", sig, L["pair_sigma_pct"], st,
                            "25〜30%を超えるペアは、ペアの形をした方向性ベット" if st != "PASS" else "", subject=pid))
        cor = _num(ps.get("pair_correlation"))
        if cor is not None:
            out.append(_chk("L2", "Pair Correlation は高いほど良い", cor, 0.5, "PASS" if cor >= 0.5 else "WARN", subject=pid))
    if pairs:
        out.append(_chk("L2", "Beta調整後Net÷Gross 30%超過は最大3ペア", over, L["pair_beta_exceptions"],
                        "PASS" if over <= L["pair_beta_exceptions"] else "FAIL"))
    # L3 / L4 nets
    for key, layer, lim, label in (("subsector", "L3", L["subsector_net_pct"], "サブセクター・ネット ±3%"),
                                   ("sector", "L4", L["sector_net_pct"], "セクター・ネット ±5%")):
        agg: dict[str, list[float]] = {}
        for p in pos:
            agg.setdefault(p.get(key) or "(未分類)", []).append(float(p["weight"]))
        for name, ws in sorted(agg.items()):
            net, gross = sum(ws), sum(abs(w) for w in ws)
            out.append(_chk(layer, label, net, lim, "PASS" if abs(net) <= lim else "FAIL",
                            f"gross {gross:.1f}%", subject=name))
    # L5 / L6 totals
    gross = sum(abs(float(p["weight"])) for p in pos)
    net = sum(float(p["weight"]) for p in pos)
    names = len(pos)
    if level == "fund":
        lo, hi = L["fund_gross"]
        out.append(_chk("L6", "ファンド・グロス 150〜300%", gross, [lo, hi], "PASS" if lo <= gross <= hi else "WARN"))
        lo, hi = L["fund_net"]
        out.append(_chk("L6", "ファンド・ネット −10〜+10%", net, [lo, hi], "PASS" if lo <= net <= hi else "FAIL"))
    else:
        lo, hi = L["book_gross"]
        out.append(_chk("L5", "ブック・グロス 60〜70%", gross, [lo, hi], "PASS" if lo <= gross <= hi else "WARN"))
        out.append(_chk("L5", "ブック・ネット 5%以下", net, L["book_net_abs"], "PASS" if abs(net) <= L["book_net_abs"] else "FAIL"))
        lo, hi = L["book_names"]
        out.append(_chk("L5", "銘柄数 40〜80", names, [lo, hi], "PASS" if lo <= names <= hi else "WARN"))
        lo, hi = L["book_pairs"]
        out.append(_chk("L5", "ペア数 30〜40（理論値40）", len(pairs), [lo, hi], "PASS" if len(pairs) >= lo else "WARN",
                        "35〜40ペアを適切に組めばブックのボラは7〜9%"))
    if drawdown_pct is not None:
        cut = drawdown_pct <= L["dd_cut_pct"]
        out.append(_chk("L5", "ドローダウン −5% → グロス半減", drawdown_pct, L["dd_cut_pct"], "FAIL" if cut else "PASS",
                        f"目標グロス {gross / 2:.1f}%（現在 {gross:.1f}%）" if cut else ""))
    summary = {s: sum(1 for c in out if c["status"] == s) for s in ("PASS", "WARN", "FAIL", "UNKNOWN")}
    return {"level": level, "gross": gross, "net": net, "long": sum(float(p["weight"]) for p in pos if float(p["weight"]) > 0),
            "short": sum(float(p["weight"]) for p in pos if float(p["weight"]) < 0), "names": names, "pairs": len(pairs),
            "checks": out, "summary": summary, "limits": L}


# ---------------------------------------------------------------------------
# Pair metrics / suitability (04.3, 05.4)
# ---------------------------------------------------------------------------
def _sd(x: list[float]) -> float:
    if len(x) < 2:
        return float("nan")
    m = sum(x) / len(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def _corr(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None


def _r2(y: list[float], x: list[float]) -> float | None:
    c = _corr(x, y)
    return c * c if c is not None else None


def aligned_returns(closes: dict[str, dict[str, float]], symbols: list[str]) -> tuple[list[str], dict[str, list[float]]]:
    dates = sorted(set.intersection(*(set(closes[s]) for s in symbols))) if symbols else []
    rets: dict[str, list[float]] = {s: [] for s in symbols}
    for i in range(1, len(dates)):
        for s in symbols:
            a, b = closes[s][dates[i - 1]], closes[s][dates[i]]
            rets[s].append(math.log(b / a) if a > 0 and b > 0 else 0.0)
    return dates[1:], rets


def pair_metrics(closes: dict[str, dict[str, float]], long_sym: str, short_sym: str, w_long: float = 1.0,
                 w_short: float = -1.0, bench: str | None = None, sigma_window: int = 21, corr_window: int = 60,
                 spread_window: int = 20) -> dict[str, Any]:
    """Pair Sigma = annualised vol of the pair (normalised to its gross) over the last month (21d).
    Pair Correlation = corr of the two legs' returns as if both were long. Beta-adj Net÷Gross uses betas vs ``bench``.
    Entry rule (05.4): 20-day percentile of the log spread; ≥80% → 拡大局面、エントリーしない."""
    syms = [long_sym, short_sym] + ([bench] if bench else [])
    dates, r = aligned_returns(closes, syms)
    n = len(dates)
    if n < max(sigma_window, 25):
        raise ValueError(f"not enough overlapping history ({n} days)")
    gross = abs(w_long) + abs(w_short)
    pr = [(w_long * a + w_short * b) / gross for a, b in zip(r[long_sym], r[short_sym])]
    sig = _sd(pr[-sigma_window:]) * math.sqrt(252) * 100
    cor = _corr(r[long_sym][-corr_window:], r[short_sym][-corr_window:])
    # rolling 60d correlation distribution (05.4: 相関 < 0.5 が維持されるか)
    roll = [c for i in range(corr_window, n + 1) if (c := _corr(r[long_sym][i - corr_window:i], r[short_sym][i - corr_window:i])) is not None]
    roll_sorted = sorted(roll)
    q = (lambda p: roll_sorted[min(len(roll_sorted) - 1, int(p * (len(roll_sorted) - 1)))]) if roll_sorted else (lambda p: None)
    out: dict[str, Any] = {
        "days": n, "pair_sigma_pct": sig, "pair_correlation": cor,
        "corr_distribution": {"p10": q(0.1), "p50": q(0.5), "p90": q(0.9), "share_below_0_5": (sum(1 for c in roll if c < 0.5) / len(roll)) if roll else None},
    }
    if bench:
        bl = _beta(r[long_sym][-252:], r[bench][-252:])
        bs = _beta(r[short_sym][-252:], r[bench][-252:])
        out["beta_long"], out["beta_short"] = bl, bs
        if bl is not None and bs is not None:
            out["beta_net_gross"] = abs(w_long * bl + w_short * bs) / gross
        r2l, r2s = _r2(r[long_sym][-252:], r[bench][-252:]), _r2(r[short_sym][-252:], r[bench][-252:])
        out["idio_share_long"] = (1 - r2l) if r2l is not None else None
        out["idio_share_short"] = (1 - r2s) if r2s is not None else None
    # spread percentile within the last 20 days (log price ratio)
    lc, sc = closes[long_sym], closes[short_sym]
    common = sorted(lc.keys() & sc.keys())
    spread = [math.log(lc[d] / sc[d]) for d in common if lc[d] > 0 and sc[d] > 0]
    win = spread[-spread_window:]
    pct = sum(1 for v in win if v <= win[-1]) / len(win) * 100 if win else None
    out["spread_percentile_20d"] = pct
    out["entry_blocked"] = pct is not None and pct >= 80
    out["spread"] = [{"date": d, "v": v} for d, v in zip(common[-250:], spread[-250:])]
    out["sigma_series"] = [{"date": dates[i], "v": _sd(pr[i - sigma_window + 1:i + 1]) * math.sqrt(252) * 100}
                           for i in range(sigma_window - 1, n)][-250:]
    st = "PASS" if sig < 25 else "WARN" if sig < 30 else "FAIL"
    out["verdict"] = {"pair_sigma": st, "entry": "見送り（20日スプレッドが上位20%＝拡大しきった後）" if out["entry_blocked"] else "可"}
    return out


def _beta(y: list[float], x: list[float]) -> float | None:
    n = len(x)
    if n < 20:
        return None
    mx, my = sum(x) / n, sum(y) / n
    vx = sum((a - mx) ** 2 for a in x)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx if vx else None


# 05.4 「ペアの適性は、セクターによって決まっている」— 非同期スコア (Notion の表をそのまま)
SECTOR_SUITABILITY = [
    {"subsector": "半導体製造装置", "score": 88, "grade": "◎", "note": "最有力 — プロセスステップ別にエンドマーケットが全く異なる"},
    {"subsector": "産業用電気・FA", "score": 82, "grade": "◎", "note": "高適性 — 中国エクスポージャーと製品特化度の差が効く"},
    {"subsector": "コネクタ・通信部品", "score": 72, "grade": "○", "note": "適性あり"},
    {"subsector": "エネルギー上流 vs 下流", "score": 58, "grade": "△", "note": "条件付き"},
    {"subsector": "電線（セグメント間）", "score": 55, "grade": "△", "note": "会社間では稀だがセグメント間では構造的に逆行が発生"},
    {"subsector": "自動車部品（HV／EV軸）", "score": 48, "grade": "△", "note": "関税が両脚に波及する共通ショックに注意"},
    {"subsector": "エネルギー精製", "score": 32, "grade": "✕", "note": "不適"},
    {"subsector": "電線（会社間）", "score": 28, "grade": "✕", "note": "AIテーマのバスケット買いがスプレッドを圧殺"},
    {"subsector": "電力（規制電力）", "score": 14, "grade": "✕✕", "note": "最不適"},
]
SPREAD_CLASSES = {
    "A-1": {"label": "ファンダメンタル起因 かつ 事前予測可能", "ok": "◎ アルファの源泉"},
    "A-2": {"label": "ファンダメンタル起因 だが 事後的にしか判別できない", "ok": "△ ノイズに近い"},
    "B-1": {"label": "フロー・需給（バスケット買い、リバランス）", "ok": "✕ 予測困難"},
    "B-2": {"label": "センチメント・テーマ（市場の誤認）", "ok": "△ 崩れるタイミングが不明"},
}


def pair_suitability(m: dict[str, Any], earnings_dirs: list[list[int]] | None = None, borrow_ok: bool | None = None,
                     spread_class: str | None = None) -> dict[str, Any]:
    """Four criteria of 05.4. ``earnings_dirs`` = [[long_leg_sign, short_leg_sign], ...] per quarter (営業利益の前年比方向)."""
    crit = []
    d = m.get("corr_distribution") or {}
    share = d.get("share_below_0_5")
    crit.append({"criterion": "ペア内リターン相関の分布（相関<0.5が維持されるか）", "value": share,
                 "status": "UNKNOWN" if share is None else "PASS" if share >= 0.5 else "WARN",
                 "detail": f"60日ローリング相関 p10/p50/p90 = {d.get('p10')}/{d.get('p50')}/{d.get('p90')}"})
    if earnings_dirs:
        inv = sum(1 for a, b in earnings_dirs if a * b < 0) / len(earnings_dirs)
        crit.append({"criterion": "決算サプライズの非同期性（営業利益方向の逆転頻度）", "value": inv,
                     "status": "PASS" if inv >= 0.3 else "WARN", "detail": f"{len(earnings_dirs)}四半期中 逆転 {inv * 100:.0f}%"})
    else:
        crit.append({"criterion": "決算サプライズの非同期性", "value": None, "status": "UNKNOWN", "detail": "四半期ごとの営業利益方向を入力"})
    idio = [v for v in (m.get("idio_share_long"), m.get("idio_share_short")) if v is not None]
    crit.append({"criterion": "固有分散比率 30%以上（ベンチマークで説明できない割合）", "value": min(idio) if idio else None,
                 "status": "UNKNOWN" if not idio else "PASS" if min(idio) >= 0.3 else "FAIL",
                 "detail": "市場1ファクターでの近似（20+ファクターモデルではない）"})
    crit.append({"criterion": "ショートアベイラビリティ（両脚の貸株が安定して取れるか）", "value": borrow_ok,
                 "status": "UNKNOWN" if borrow_ok is None else "PASS" if borrow_ok else "FAIL", "detail": "手入力"})
    sc = SPREAD_CLASSES.get(spread_class or "")
    crit.append({"criterion": "スプレッドの四分類を宣言（L/Sで勝てるのは A-1 だけ）", "value": spread_class,
                 "status": "UNKNOWN" if not sc else "PASS" if spread_class == "A-1" else "WARN",
                 "detail": f"{spread_class}: {sc['label']} {sc['ok']}" if sc else "A-1 でなければ、それはアルファではなく運"})
    return {"criteria": crit, "sector_table": SECTOR_SUITABILITY, "spread_classes": SPREAD_CLASSES}


# ---------------------------------------------------------------------------
# 空売り8モデル (04.5)
# ---------------------------------------------------------------------------
def _cond(label: str, ok: bool | None, value: Any = None, need: str = "") -> dict[str, Any]:
    return {"label": label, "ok": ok, "value": value, "need": need}


def short_models(x: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the 8 short models from inputs (None = unknown, never guessed).

    Inputs (all optional): valuation_percentile (own history, 0–100), growth_path (list, %, past→future e.g.
    [30, 20, 10]), crowding_pct (0–100 percentile), drawdown_from_high_pct, volume_trend (ratio recent/earlier),
    downgrade_share (0–1 of covering analysts), longonly_selling (bool), revenue_growth_pct, op_margin_pct,
    fcf_negative (bool), industry_growth_pct, market_rank (int), share_change_pp, fraud_confirmed (bool),
    winner_take_all (bool), disruption (bool), cyclical (bool), pe_percentile (own history, low = cheap),
    cycle_stage ('peak'|'other'), market_cap_usd, moat_qualifies (bool from 3.5句)."""
    # growth_path = profit growth RATES (%), i.e. the 1st derivative of profit; its change is the 2nd derivative.
    # Notion: 「過去3年の平均成長率30% → 来年予測20% → 再来年10%」= 一階微分が正、二階微分が負.
    g = [float(v) for v in (x.get("growth_path") or [])]
    d1 = g[-1] if g else None
    d2 = (g[-1] - g[-2]) if len(g) >= 2 else None

    def gte(v, t):
        v = _num(v)
        return None if v is None else v >= t

    def lt(v, t):
        v = _num(v)
        return None if v is None else v < t

    rev, opm = _num(x.get("revenue_growth_pct")), _num(x.get("op_margin_pct"))
    rule40 = (rev + opm) if rev is not None and opm is not None else None
    models = [
        {"id": 1, "name": "①増速放緩（Decelerating Growth）", "all_required": True, "conds": [
            _cond("バリュエーションが自社の歴史で90〜95パーセンタイル以上", gte(x.get("valuation_percentile"), 90), x.get("valuation_percentile")),
            _cond("利益予測は未来1〜2年ベース", bool(g) or None, g, "growth_path に将来予測を含める"),
            _cond("増速鈍化（一階微分は正、二階微分が負）", None if d2 is None else (d1 > 0 and d2 < 0), {"d1": d1, "d2": d2}),
            _cond("取引が過度に混雑", gte(x.get("crowding_pct"), 80), x.get("crowding_pct"))]},
        {"id": 2, "name": "②基金放棄（Mutual Funds Give Up）", "all_required": True, "conds": [
            _cond("高値からしばらく下落", gte(x.get("drawdown_from_high_pct"), 20), x.get("drawdown_from_high_pct")),
            _cond("出来高が縮小し始める", lt(x.get("volume_trend"), 0.8), x.get("volume_trend")),
            _cond("セルサイドの過半数が格下げ", gte(x.get("downgrade_share"), 0.5), x.get("downgrade_share")),
            _cond("主力ロングオンリーの処分売り", x.get("longonly_selling"), x.get("longonly_selling"))]},
        {"id": 3, "name": "③無利潤の成長（Unprofitable Growth）", "all_required": True, "conds": [
            _cond("増速50%未満 または Rule of 40 < 40",
                  None if rev is None else (rev < 50 or (rule40 is not None and rule40 < 40)), {"growth": rev, "rule_of_40": rule40}),
            _cond("キャッシュフローがマイナス", x.get("fcf_negative"), x.get("fcf_negative"))]},
        {"id": 4, "name": "④シェア減少（Market Share Loss・バリュートラップ）", "all_required": True, "conds": [
            _cond("業界が低成長／ゼロ成長", lt(x.get("industry_growth_pct"), 5), x.get("industry_growth_pct")),
            _cond("業界3位以下", gte(x.get("market_rank"), 3), x.get("market_rank")),
            _cond("シェアを失っている", lt(x.get("share_change_pp"), 0), x.get("share_change_pp"))]},
        {"id": 5, "name": "⑤偽会社（粉飾）— 摘発『後』のみ", "all_required": True, "conds": [
            _cond("粉飾が摘発・確定済み（疑いの段階では入らない）", x.get("fraud_confirmed"), x.get("fraud_confirmed"))]},
        {"id": 6, "name": "⑥インターネット企業（n²/2 の2位以下）", "all_required": True, "conds": [
            _cond("勝者総取り（n²/2型ネットワーク効果）", x.get("winner_take_all"), x.get("winner_take_all")),
            _cond("業界2位以下", gte(x.get("market_rank"), 2), x.get("market_rank"))]},
        {"id": 7, "name": "⑦降維打撃（Disruption）", "all_required": True, "conds": [
            _cond("新技術・新産業による旧業界の顛覆", x.get("disruption"), x.get("disruption"))]},
        {"id": 8, "name": "⑧周期株の見頂（PEが最も低く見える時が天井）", "all_required": True, "conds": [
            _cond("シクリカル業種", x.get("cyclical"), x.get("cyclical")),
            _cond("PEが自社の歴史で低位（≤20パーセンタイル）", None if _num(x.get("pe_percentile")) is None else _num(x.get("pe_percentile")) <= 20, x.get("pe_percentile")),
            _cond("景気サイクルの第二段階（ピーク圏）", None if x.get("cycle_stage") is None else x.get("cycle_stage") == "peak", x.get("cycle_stage"))]},
    ]
    for m in models:
        oks = [c["ok"] for c in m["conds"]]
        m["met"] = sum(1 for o in oks if o is True)
        m["unknown"] = sum(1 for o in oks if o is None)
        m["status"] = "MATCH" if all(o is True for o in oks) else "NO" if any(o is False for o in oks) else "INCOMPLETE"
    guards = []
    mc = _num(x.get("market_cap_usd"))
    if mc is not None and mc < 1e9:
        guards.append("小型株（時価総額 約10億ドル未満）は空売り禁止")
    if x.get("moat_qualifies"):
        guards.append("3.5句に合致 → 安易にショートしない（ヘッジはTOPIX先物／大型低ボラで）")
    return {"models": models, "matches": [m["name"] for m in models if m["status"] == "MATCH"], "guards": guards,
            "short_types": SHORT_TYPES,
            "note": "アルファ・ショートは30〜40%以上の下落見込みが最低ライン。実行はカタリストを待ってから。"}


# ---------------------------------------------------------------------------
# 天井・底シグナル (03.5)
# ---------------------------------------------------------------------------
def turnover_series(volumes: list[float], shares: float) -> list[float]:
    return [v / shares * 100 for v in volumes] if shares else []


def top_bottom(daily_turnover_pct: list[float] | None = None, margin: dict[str, Any] | None = None,
               dividend_yield_pct: float | None = None, risk_free_pct: float | None = None,
               valuation_percentile: float | None = None, flows_stopped: bool | None = None,
               scope: str = "stock", hot_daily_pct: float | None = None, hot_month_pct: float | None = None) -> dict[str, Any]:
    """Notion: 天井 = 回転率が持続的に高い（市場全体70%×1か月、個別10%×1か月）／絶対的な過大評価／信用買い残が大きい。
    底 = 回転率が極めて低い／配当利回りが高い／資金流出が止まる。
    Interpretation (documented, editable): stock = average DAILY turnover over the last 20 sessions ≥ 10%;
    market = 20-session (monthly) cumulative turnover ≥ 70%."""
    top, bottom = [], []
    t = daily_turnover_pct or []
    if len(t) >= 20:
        last20 = t[-20:]
        avg, cum = sum(last20) / 20, sum(last20)
        hist20 = [sum(t[i - 20:i]) for i in range(20, len(t) + 1)]
        pct = sum(1 for v in hist20 if v <= cum) / len(hist20) * 100
        if scope == "market":
            th = hot_month_pct if hot_month_pct is not None else 70.0
            top.append({"signal": f"回転率が持続的に高い（市場全体 {th:g}%×1か月）", "value": cum, "on": cum >= th})
        else:
            th = hot_daily_pct if hot_daily_pct is not None else 10.0
            top.append({"signal": f"回転率が持続的に高い（個別 1日平均{th:g}%×1か月）", "value": avg, "on": avg >= th})
        bottom.append({"signal": "回転率が極めて低い（自己の過去分布で下位10%）", "value": pct, "on": pct <= 10})
        falling = len(hist20) > 20 and hist20[-1] < 0.5 * hist20[-21]
        top.append({"signal": "回転率の急低下（売りたい時に買い手がいない）— 要注意", "value": None, "on": falling})
        turnover_pct_rank = pct
    else:
        turnover_pct_rank = None
    if valuation_percentile is not None:
        top.append({"signal": "株価が絶対的に過大評価（自己の歴史で≥95パーセンタイル）", "value": valuation_percentile, "on": valuation_percentile >= 95})
    if margin and margin.get("ratio_percentile") is not None:
        rp = margin["ratio_percentile"]
        top.append({"signal": "信用買い残が大きい（信用倍率が自己の過去分布で上位20%）", "value": rp, "on": rp >= 80})
        if margin.get("buy_days") is not None:
            top.append({"signal": "買残÷20日平均出来高（日数）が大きい", "value": margin["buy_days"], "on": margin["buy_days"] >= 5})
    if dividend_yield_pct is not None:
        spread = dividend_yield_pct - (risk_free_pct or 0)
        bottom.append({"signal": "配当利回りが無リスク金利より有意に高い", "value": spread, "on": spread >= 2.0})
    if flows_stopped is not None:
        bottom.append({"signal": "資金流出が続いた後に流出が止まる", "value": flows_stopped, "on": flows_stopped})
    nt, nb = sum(1 for s in top if s["on"]), sum(1 for s in bottom if s["on"])
    zone = "天井シグナル群に近い" if nt >= 2 and nt > nb else "底シグナル群に近い" if nb >= 2 and nb > nt else "中間帯（ランダムウォーク＝予測不能）"
    return {"top": top, "bottom": bottom, "zone": zone, "turnover_percentile": turnover_pct_rank,
            "note": "予測できるのは天井と底だけ。出来高は意見対立を映すセンチメント指標で、それ自体は何も断定しない。"}


def crowding(holding_value: float | None, adv_value: float | None, inst_ownership_pct: float | None = None,
             leveraged_etf: bool | None = None) -> dict[str, Any]:
    """混雑度 = 機関保有比率 ／ 保有金額 ÷ 1日売買代金 (days to exit)."""
    days = holding_value / adv_value if holding_value and adv_value else None
    flags = []
    if days is not None and days >= 5:
        flags.append(f"保有金額が1日売買代金の {days:.1f} 日分")
    if inst_ownership_pct is not None and inst_ownership_pct >= 70:
        flags.append(f"機関保有比率 {inst_ownership_pct:.0f}%")
    if leveraged_etf:
        flags.append("レバレッジETFが存在（過熱の典型サイン）")
    return {"days_of_volume": days, "inst_ownership_pct": inst_ownership_pct, "flags": flags, "crowded": len(flags) >= 2}


# ---------------------------------------------------------------------------
# 05.6 チェックリスト / 05.2 裁定ルール
# ---------------------------------------------------------------------------
GATES = [
    {"id": "macro", "title": "① マクロ関門 — Theme Alpha の入口", "items": [
        "このテーマのマクロ・インプットは『Well-known but less focused』か？ コンセンサス（Crowded）ではないか？",
        "反応ラグのどのフェーズか？ 第①段（早すぎる）／第②→③段（エントリーゾーン）／第③段（遅い）",
        "Growth×Liquidity の4象限のどこか？ その象限で優位なアセットと整合しているか？",
        "セクター・ファンドフローは、このテーマの浸透度と整合しているか？"]},
    {"id": "fundamental", "title": "② ファンダメンタル関門 — 銘柄への翻訳", "items": [
        "ロング側は3.5句のどれに合致するか？（独占／ネットワーク効果／コスパ・コスト／ブランド／技術優位）",
        "能力の輪の中か？ 可理解・可分析・可予測の3条件を満たすか？",
        "三大原則：全純資産で丸ごと買いたいか／3年売買停止でも持ちたいか／5年後の業界像を描けるか",
        "バリュエーションはEVベースで見たか？（PER・PBRの罠を回避したか）",
        "財務諸表は BS > CF > PL の順で見たか？ 配当は出ているか（粉飾リスクの逆指標）",
        "情報は『事実に対して』『同業に対して』先行しているか？ 両軸遅行になっていないか？"]},
    {"id": "flow", "title": "③ 需給・行動関門 — タイミング", "items": [
        "混雑度：機関保有比率／保有金額÷1日売買代金は？ レバレッジETF等の過熱サインはないか？",
        "浮動株と主要保有者：誰が持っているか／取得コストと目標価格／空売り比率と理由",
        "カタリスト：『まだ起きていないこと』があるか？（ショートは必須、ロングは待てる）",
        "指数採用・除外、ロックアップ解除の日程を把握したか？",
        "市場全体は天井／底のどちらのシグナル群に近いか？（回転率・配当利回り・信用残）",
        "認知バイアスを逆用できる局面か？（決算集中日のPEAD、3日連続暴落後の押し目、指数リバランスの非対称）"]},
    {"id": "sizing", "title": "④ サイジング関門 — 最終ゲート", "items": [
        "期待値 E = PW·XW − PL·XL は正か？ 方向と符号は一致しているか？",
        "ケリー F = E/(XW×XL) で計算したか？ ファットテールを考慮して低めに張ったか？",
        "原則3：全損確率が0.1%でもあるならフルポジション禁止。レバレッジは論外",
        "ロング1銘柄3%／ショート1銘柄2%の上限内か？ 小型株ショートになっていないか？",
        "グロス／ネット規則（全体ネット5%以下、セクター±5%、サブセクター±3%）を満たすか？",
        "20+ファクターモデルで意図しないファクターベットが出ていないか？",
        "40ペア以上に分散されているか？",
        "Pair Sigma 25〜30%未満／Pair Correlation は十分高いか／Beta調整後Net÷Grossは30%未満か",
        "そのペアは同一サブセクター内で組まれているか？（偽のペアになっていないか）",
        "建てようとしているショートは4類型のどれかを宣言したか？"]},
    {"id": "monitor", "title": "⑤ 継続監視 — 毎日・毎月", "items": [
        "毎日：ファクター・エクスポージャーを再計算／反応ラグのフェーズを更新／ベイズ推理で勝率を更新",
        "毎月：エントリー価格と含み損益を忘れ、ポートフォリオをゼロから作り直す",
        "なぜ儲かったか／損したかを書き出し、運と実力を区別する",
        "テーマが機能しないと判明したら buy on dip せず縮小・入替（ゴキブリ理論）"]},
]
QUARTERLY = [
    {"id": "q1", "title": "Ⅰ. アルファ源泉の特定", "items": [
        "自分のエッジは (A) 強制フロー／(B) 保険料徴収／(C) 凸性購入／(D) 情報・分析 のどれか",
        "そのエッジは『なぜ他の参加者が取れないのか』を一文で説明できるか",
        "マクロ伝播経路の個社レベルでの定量化を中核に据えるか"]},
    {"id": "q2", "title": "Ⅱ. 時間リスクの設計", "items": [
        "各ポジションの収束カタリストは特定できているか",
        "カタリストのないポジションの保有期限・撤退ルールはあるか",
        "フローがファンダを凌駕する局面での戦術オーバーレイを型として持っているか"]},
    {"id": "q3", "title": "Ⅲ. 非対称性とドローダウン規律", "items": [
        "自分のPnLは保険売り型か凸性購入型か、自覚した資金管理になっているか",
        "浅いDDリミット（例：−5%でグロス半減）を課しているか",
        "混雑度の計測をプロセスに組み込んでいるか"]},
    {"id": "q4", "title": "Ⅳ. 四半期ごとに見直す指標", "items": [
        "自分のリターンのアルファ／ファクター／フローへの寄与分解",
        "ペアごとの A-1象限の比率の推移",
        "戦略の混雑シグナル（同型戦略のAUM増加、スプレッドの縮小）"]},
]
ARBITRATION = [
    {"conflict": "3.5句合致企業がテーマ的にショート候補になった",
     "ruling": "哲学側を優先。個別ショートではなくTOPIX先物／大型低ボラ銘柄でヘッジ"},
    {"conflict": "ファンダメンタル良好な銘柄がクラウデッド",
     "ruling": "Market Timingスリーブに限定し期間を1〜3ヶ月に区切る。大型・低ボラ銘柄を選ぶ（スクイーズ回避）"},
    {"conflict": "マクロが弱気だが企業の期待値は正",
     "ruling": "ネットをフラットに保ったままペアで持つ。方向性ベットにしない"},
    {"conflict": "確信度は高いが分散も大きい",
     "ruling": "ケリー公式に従う。確信度はグロスを、分散はウェイトを決める — 両者は別の変数"},
]


def gates_progress(answers: dict[str, Any]) -> dict[str, Any]:
    """answers: {"macro:0": "yes"|"no"|"na", ...}. A gate passes only when every item is yes/na (全項目が『買い』)."""
    res = []
    blocked_at = None
    for g in GATES + QUARTERLY:
        st = [answers.get(f"{g['id']}:{i}") for i in range(len(g["items"]))]
        yes = sum(1 for s in st if s in ("yes", "na"))
        no = sum(1 for s in st if s == "no")
        status = "PASS" if yes == len(st) else "FAIL" if no else "OPEN"
        res.append({"id": g["id"], "title": g["title"], "yes": yes, "no": no, "total": len(st), "status": status})
        if blocked_at is None and g in GATES and status != "PASS":
            blocked_at = g["title"]
    return {"gates": res, "position_ok": blocked_at is None or blocked_at.startswith("⑤"),
            "blocked_at": blocked_at,
            "note": "順序に意味がある: ①で何にベットするかを決め、②で銘柄に翻訳、③で時期、④で量。⑤で毎月ゼロに戻す。"}
