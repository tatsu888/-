"""ALIGN / CHECK / EVAL — the Trinity as an analysis tool (Notion 01.6・05.1 一致点, 05.2 裁定ルール・関門, 04.1 ベイズ推理).

Pure functions on AUTO snapshots (trinity_auto.evaluate rows) and prices. No AI, deterministic.

ALIGN  where every AUTO name stands relative to the core rule 「三方向から同じ結論に着いたときだけ確信度を上げてよい」:
       F (the base) gives the direction; M and 需給 (L) are read RELATIVE to it (順風 / 中立 / 逆風). The state of a name:
         三位一致         M and L both with F                       (conviction 3)
         二位一致         one of M / L with F, the other neutral    (conviction 2)
         F のみ           M and L neutral                           (conviction 1)
         マクロと衝突     M against F, L not against
         需給と衝突       L against F, M not against
         両方と衝突       M and L against F                         (conviction 0)
         F なし・M と需給が一致  no fundamental direction but M = L ≠ 0 → a research candidate (score it in SCORE);
                          macro never creates a position on its own
       and the arbitration rules (05.2) that apply to it.

CHECK  a proposed order (symbol, side, size, pair, short type, Kelly inputs) through gates ①–④ and the six-layer
       discipline, using the AUTO row, the saved score sheet, pair metrics and the book with the order added (the checks
       that get worse because of the order are listed).

EVAL   (a) grades past AUTO verdicts: the market-relative log return h sessions after each snapshot, signed by the
       direction, by conviction / state / source; snapshots are sampled at least h sessions apart (no overlap) and the
       win rate gets a Beta(1+wins, 1+losses) posterior (TRAK).
       (b) backtests the layers that prices alone reproduce point-in-time: M (the growth × liquidity quadrant from market
       data → favoured − disfavoured sector ETFs) and 需給 (天井寄り / 底寄り from volume, drawdown and crowding).
       F is not reproducible (the scanner fundamentals are today's) — graded only through (a).
"""
from __future__ import annotations

import math
from typing import Any

from . import framework as F
from . import trinity_auto as T

STATES = [
    ("ALIGN3", "三位一致", "確信度を上げてよい（F・マクロ・需給が同じ方向）"),
    ("ALIGN2", "二位一致", "F と片方が一致、もう片方は中立"),
    ("F_ONLY", "F のみ", "マクロ・需給は中立 — 確信度 1 のまま"),
    ("CONF_M", "マクロと衝突", "裁定: ネットをフラットに保ったままペアで持つ"),
    ("CONF_L", "需給と衝突", "需給が逆向き → エントリーを待つ（③関門）"),
    ("CONF_ML", "両方と衝突", "確信度 0 — 持たない／ペアで小さく"),
    ("NO_F_ML", "F なし・M と需給が一致", "研究候補：評点表（SCORE）をつける。マクロだけでポジションは作らない"),
    ("NONE", "判断材料なし", "F の方向がなく、M・需給もそろっていない"),
]
STATE_LABEL = {k: lbl for k, lbl, _ in STATES}
STATE_HINT = {k: h for k, _, h in STATES}
REL = {1: "順風", 0: "中立", -1: "逆風"}
# TOPIX-17 NEXT FUNDS → the style bucket AUTO uses (trinity_auto.SECTOR_BUCKET via the scanner sector of the constituents)
TOPIX17_BUCKET = {
    "TSE:1617": "defensive", "TSE:1618": "commodity", "TSE:1619": "cyclical", "TSE:1620": "cyclical", "TSE:1621": "defensive",
    "TSE:1622": "cyclical", "TSE:1623": "commodity", "TSE:1624": "cyclical", "TSE:1625": "tech", "TSE:1626": "tech",
    "TSE:1627": "defensive", "TSE:1628": "cyclical", "TSE:1629": "other", "TSE:1630": "other", "TSE:1631": "value",
    "TSE:1632": "value", "TSE:1633": "value",
}


def _fv(direction: str | None) -> int:
    return 1 if direction == "LONG" else -1 if direction == "SHORT" else 0


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---- ALIGN ---------------------------------------------------------------------------------------------------------
def align_row(r: dict[str, Any]) -> dict[str, Any]:
    f_dir = (r.get("f") or {}).get("direction")
    fv = _fv(f_dir)
    m = int((r.get("m") or {}).get("view") or 0)
    lv = int((r.get("l") or {}).get("view") or 0)
    rules: list[str] = []
    if not fv:
        if m and m == lv:
            state, rel_m, rel_l = "NO_F_ML", m, lv
        else:
            state, rel_m, rel_l = "NONE", m, lv
    else:
        rel_m, rel_l = m * fv, lv * fv
        if rel_m == -1 and rel_l == -1:
            state = "CONF_ML"
        elif rel_m == -1:
            state = "CONF_M"
        elif rel_l == -1:
            state = "CONF_L"
        elif rel_m == 1 and rel_l == 1:
            state = "ALIGN3"
        elif rel_m == 1 or rel_l == 1:
            state = "ALIGN2"
        else:
            state = "F_ONLY"
        flags = " ".join(r.get("flags") or [])
        if fv < 0 and "3.5句合致" in flags:
            rules.append(F.ARBITRATION[0]["ruling"])
        if fv > 0 and (r.get("l") or {}).get("crowded"):
            rules.append(F.ARBITRATION[1]["ruling"])
        if rel_m == -1:
            rules.append(F.ARBITRATION[2]["ruling"])
        vol = _num((r.get("l") or {}).get("vol_pct"))
        if (r.get("conviction") or 0) >= 2 and vol is not None and vol > T.VOL_TARGET:
            rules.append(F.ARBITRATION[3]["ruling"] + f"（年率ボラ {vol:.0f}% → サイズは {T.VOL_TARGET:.0f}%÷ボラで縮小）")
        if rel_l == -1:
            rules.append("需給が逆向き → エントリーを待つ（③関門）")
        srrg = r.get("sector_rrg") or {}
        if T.sector_against(fv, srrg.get("quadrant")):
            rules.append(f"セクター・フローが逆行（RRG {srrg.get('quadrant')}）→ ①関門で止まる")
        idio = (r.get("xray") or {}).get("idio")
        if idio is not None and idio < 0.3:
            rules.append(f"個別要因 {idio * 100:.0f}% → ペア／ヘッジで持つ")
    return {"symbol": r["symbol"], "name": r.get("name"), "state": state, "state_label": STATE_LABEL[state],
            "hint": STATE_HINT[state], "f_dir": f_dir, "f_score": (r.get("f") or {}).get("score"), "f_source": (r.get("f") or {}).get("source"),
            "m": m, "l": lv, "rel_m": rel_m if fv else None, "rel_l": rel_l if fv else None,
            "direction": r.get("direction"), "conviction": r.get("conviction"), "size_pct": r.get("size_pct"),
            "m_reason": (r.get("m") or {}).get("reason"), "l_zone": (r.get("l") or {}).get("zone"), "rules": rules}


def align(snapshot: dict[str, Any] | None, prev: dict[str, Any] | None = None) -> dict[str, Any]:
    if not snapshot or not snapshot.get("rows"):
        return {"error": "AUTO の結果がまだない — TRIN の AUTO で「今すぐ更新」"}
    rows = [align_row(r) for r in snapshot["rows"]]
    states = {k: [x for x in rows if x["state"] == k] for k, _, _ in STATES}
    grid: dict[str, list[list[list[dict[str, Any]]]]] = {}
    for side in ("LONG", "SHORT"):
        g = [[[] for _ in range(3)] for _ in range(3)]     # [rel_l: +1, 0, −1][rel_m: −1, 0, +1]
        for x in rows:
            if x["f_dir"] == side:
                g[1 - x["rel_l"]][x["rel_m"] + 1].append({k: x[k] for k in ("symbol", "name", "conviction", "size_pct", "state")})
        grid[side] = g
    sized = [x for x in rows if (x["size_pct"] or 0) > 0]
    gross = sum(x["size_pct"] for x in sized)
    aligned = sum(x["size_pct"] for x in sized if x["state"] in ("ALIGN3", "ALIGN2"))
    changes = []
    if prev and prev.get("rows"):
        old = {r["symbol"]: align_row(r)["state"] for r in prev["rows"]}
        for x in rows:
            o = old.get(x["symbol"])
            if o and o != x["state"]:
                changes.append({"symbol": x["symbol"], "name": x["name"], "from": STATE_LABEL[o], "to": x["state_label"]})
    return {
        "generated_at": snapshot.get("generated_at"), "quadrant": snapshot.get("quadrant"), "next_quadrant": snapshot.get("next_quadrant"),
        "rows": rows, "grid": grid, "rel_labels": REL,
        "states": [{"id": k, "label": lbl, "hint": h, "n": len(states[k]), "size_pct": sum(x["size_pct"] or 0 for x in states[k]),
                    "symbols": [x["symbol"] for x in states[k]]} for k, lbl, h in STATES],
        "book": {"gross_pct": gross, "aligned_pct": aligned, "aligned_share": aligned / gross if gross else None,
                 "conflict_pct": sum(x["size_pct"] for x in sized if x["state"].startswith("CONF"))},
        "candidates": states["NO_F_ML"], "changes": changes, "arbitration": F.ARBITRATION,
    }


# ---- CHECK ---------------------------------------------------------------------------------------------------------
def _item(status: str, text: str) -> dict[str, str]:
    return {"status": status, "text": text}


def check_trade(trade: dict[str, Any], row: dict[str, Any] | None, scorecard: dict[str, Any] | None,
                book: list[dict[str, Any]], pair: dict[str, Any] | None = None, kelly: dict[str, Any] | None = None) -> dict[str, Any]:
    """trade: {symbol, side LONG|SHORT, weight (% of NAV, > 0), pair_with, short_type, expected_downside_pct, sector,
    subsector, mcap_usd, beta}. row: the AUTO row of the symbol (None when outside the AUTO universe)."""
    side = (trade.get("side") or "LONG").upper()
    fv = 1 if side == "LONG" else -1
    w = abs(_num(trade.get("weight")) or 0.0)
    sym = trade["symbol"]
    g1: list[dict[str, str]] = []
    g2: list[dict[str, str]] = []
    g3: list[dict[str, str]] = []
    g4: list[dict[str, str]] = []
    g5: list[dict[str, str]] = []
    paired = bool(trade.get("pair_with"))
    # ① マクロ
    if row is None:
        g1.append(_item("OPEN", "AUTO の判定がない（ユニバースの外）— GLQ・PROP で確認するか、TRIN の UNIVERSE に追加"))
    else:
        m = row.get("m") or {}
        rel = int(m.get("view") or 0) * fv
        if rel == -1:
            g1.append(_item("WARN" if paired else "FAIL", f"マクロは逆風（{m.get('reason')}）" +
                            ("→ 裁定: ペアでネットをフラットに保つなら可" if paired else "→ 単独の方向性ベットは不可。ペアで持つ（05.2）")))
        else:
            g1.append(_item("PASS", f"マクロは{REL[rel]}（{m.get('reason')}）"))
        if m.get("next_view") is not None and int(m["next_view"]) * fv == -1:
            g1.append(_item("WARN", "次の象限では逆風になる — 保有期間に注意"))
        srrg = row.get("sector_rrg") or {}
        if T.sector_against(fv, srrg.get("quadrant")):
            g1.append(_item("WARN" if paired else "FAIL", f"セクター・フローが逆行（{srrg.get('label') or srrg.get('etf')}: RRG {srrg.get('quadrant')}）"))
    # ② ファンダメンタル
    if scorecard and scorecard.get("total") is not None:
        d = scorecard.get("direction") or F.direction(scorecard["total"])
        if _fv(d) == fv:
            g2.append(_item("PASS", f"評点表 {scorecard['total']:.2f} → {d}"))
        else:
            g2.append(_item("FAIL", f"評点表 {scorecard['total']:.2f} → {d}（{side} と一致しない）"))
        if fv < 0 and scorecard.get("moat_qualifies"):
            g2.append(_item("FAIL", "3.5句合致企業のショート → 裁定: 哲学側を優先。TOPIX 先物／大型低ボラでヘッジ"))
    else:
        fr = (row or {}).get("f") or {}
        d = fr.get("direction")
        if fr.get("score") is not None and _fv(d) == fv:
            g2.append(_item("WARN", f"評点表がない（ルール採点 {fr['score']:.2f} → {d} だけ）— SCORE で採点して保存"))
        elif fr.get("score") is not None:
            g2.append(_item("FAIL", f"ルール採点 {fr['score']:.2f} → {d}（{side} と一致しない）"))
        else:
            g2.append(_item("FAIL", "ファンダの方向がない — マクロだけでポジションは作らない。SCORE で採点"))
    # ③ 需給・行動
    if row is not None:
        lv = row.get("l") or {}
        rel = int(lv.get("view") or 0) * fv
        if rel == -1:
            g3.append(_item("FAIL", f"需給が逆向き（{lv.get('zone')}）→ エントリーを待つ"))
        else:
            g3.append(_item("PASS", f"需給は{REL[rel]}（{lv.get('zone')}）"))
        if fv > 0 and lv.get("crowded"):
            g3.append(_item("WARN", "クラウデッド → 裁定: Market Timing スリーブ・1〜3 か月・大型低ボラ"))
        dte = row.get("days_to_earnings")
        if fv < 0:
            g3.append(_item("PASS", f"カタリスト：決算まで {dte} 日") if dte is not None and 0 <= dte <= 30
                      else _item("WARN", "30 日以内のカタリストが見当たらない — ショートはカタリスト必須"))
        elif dte is not None and 0 <= dte <= 5:
            g3.append(_item("WARN", f"決算まで {dte} 日 — 発表前に建てるなら反応の大きさ（STK）を確認"))
    else:
        g3.append(_item("OPEN", "需給の判定がない — CHIP・MRGN で確認"))
    # ④ サイジング — on the position after the order (what the book already holds + the order)
    have = sum(float(p.get("weight") or 0) for p in book if p.get("symbol") == sym)
    pos = have + w * fv
    held = f"（既存 {have:+.2f}% ＋ 発注 {w * fv:+.2f}%）" if have else ""
    if pos > 0:
        st = "PASS" if pos <= F.LIMITS["long_pct"] else "WARN" if pos <= F.LIMITS["long_abs_pct"] else "FAIL"
        g4.append(_item(st, f"L1 ロング {pos:.2f}%{held}（上限 3%、絶対 4%）"))
    elif pos < 0:
        st = "PASS" if -pos <= F.LIMITS["short_pct"] else "WARN" if -pos <= F.LIMITS["short_abs_pct"] else "FAIL"
        g4.append(_item(st, f"L1 ショート {-pos:.2f}%{held}（上限 2%、絶対 3%）"))
    else:
        g4.append(_item("PASS", f"発注後のポジションは 0%{held}"))
    if fv < 0:
        mc = _num(trade.get("mcap_usd"))
        if pos < 0 and mc is not None and mc < F.LIMITS["smallcap_short_usd"]:
            g4.append(_item("FAIL", f"小型株ショート禁止（時価総額 {mc / 1e9:.2f} 十億ドル）"))
        stype = trade.get("short_type")
        if stype not in F.SHORT_TYPES:
            g4.append(_item("WARN", "ショートの型を宣言する（アルファ／カタリスト／ペア相方／Funding）"))
        elif stype == "alpha":
            dn = _num(trade.get("expected_downside_pct"))
            g4.append(_item("OPEN" if dn is None else "PASS" if dn >= 30 else "FAIL",
                            f"アルファ・ショートの下落見込み {dn if dn is not None else '—'}%（30〜40% 以上）"))
    if kelly:
        if kelly["e"] <= 0:
            g4.append(_item("FAIL", f"期待値 E = {kelly['e']:+.4f} ≤ 0 → 参加不可（原則 1）"))
        else:
            rec = kelly["recommended_pct"]
            g4.append(_item("PASS" if abs(pos) <= rec + 1e-9 else "WARN", f"ケリー推奨 {rec:.2f}%（½F、上限込み）に対して {abs(pos):.2f}%"))
    if row is not None and (row.get("size_pct") or 0) > 0 and _fv(row.get("direction")) == fv and abs(pos) > 1.5 * row["size_pct"]:
        g4.append(_item("WARN", f"AUTO の目安 {row['size_pct']:.2f}%（確信度 {row.get('conviction')}・ボラ調整）より大きい"))
    idio = ((row or {}).get("xray") or {}).get("idio")
    if idio is not None and idio < 0.3:
        g4.append(_item("WARN" if not paired else "PASS", f"個別要因 {idio * 100:.0f}% — ファクターに上書きされやすい" + ("（ペアで持つので可）" if paired else " → ペア／ヘッジで持つ（FEXP で確認）")))
    if pair:
        if pair.get("error"):
            g4.append(_item("OPEN", f"ペアの指標が計算できない: {pair['error']}"))
        else:
            sig = pair.get("pair_sigma_pct")
            if sig is not None:
                g4.append(_item("PASS" if sig < 25 else "WARN" if sig < 30 else "FAIL", f"Pair Sigma {sig:.1f}%（25〜30% 未満）"))
            bng = pair.get("beta_net_gross")
            if bng is not None:
                g4.append(_item("PASS" if bng < 0.3 else "WARN", f"β調整後 Net÷Gross {bng * 100:.0f}%（30% 未満）"))
            cor = pair.get("pair_correlation")
            if cor is not None:
                g4.append(_item("PASS" if cor >= 0.5 else "WARN", f"ペア相関 {cor:.2f}（高いほど良い）"))
            if pair.get("entry_blocked"):
                g4.append(_item("WARN", "20 日スプレッドが上位 20%（拡大しきった後）→ エントリーしない（05.4）"))
    # the book with the order added (an existing position in the same name grows or shrinks)
    signed = w * fv
    pid = f"CHECK:{sym}" if paired else None

    def merged(s: str, delta: float, meta: dict[str, Any]) -> dict[str, Any]:
        old = next((p for p in book if p.get("symbol") == s), {})
        cur = sum(float(p.get("weight") or 0) for p in book if p.get("symbol") == s)
        return {**{k: v for k, v in meta.items() if v is not None}, **{k: v for k, v in old.items() if v is not None and k != "weight"},
                "symbol": s, "weight": cur + delta, "pair": old.get("pair") or pid}

    add = [merged(sym, signed, {"sector": trade.get("sector"), "subsector": trade.get("subsector"), "short_type": trade.get("short_type"),
                                "mcap_usd": trade.get("mcap_usd"), "beta": trade.get("beta"), "expected_downside_pct": trade.get("expected_downside_pct")})]
    if paired:
        add.append(merged(trade["pair_with"], -signed, {"sector": trade.get("pair_sector") or trade.get("sector"),
                                                         "subsector": trade.get("pair_subsector") or trade.get("subsector"),
                                                         "short_type": "pair_leg" if fv > 0 else None, "beta": trade.get("pair_beta")}))
    before = F.exposure_check(book) if book else None
    after = F.exposure_check([p for p in book if p.get("symbol") not in {a["symbol"] for a in add}] + [a for a in add if a["weight"]])
    rank = {"PASS": 0, "UNKNOWN": 1, "WARN": 2, "FAIL": 3}
    old = {(c["layer"], c["rule"], c["subject"]): c["status"] for c in (before or {}).get("checks", [])}
    worse = []
    layers = ("L3", "L4", "L5") if book else ("L3", "L4")      # an empty book: the book-level totals say nothing yet
    for c in after["checks"]:
        k = (c["layer"], c["rule"], c["subject"])
        if c["layer"] in layers and rank.get(c["status"], 0) > rank.get(old.get(k, "PASS"), 0) and c["status"] in ("WARN", "FAIL"):
            worse.append(c)
    for c in worse:
        g4.append(_item(c["status"], f"{c['layer']} {c['rule']}{'（' + str(c['subject']) + '）' if c['subject'] else ''}: "
                        f"{c['value']:.2f} → 上限 {c['limit']}" if isinstance(c["value"], (int, float)) else f"{c['layer']} {c['rule']}"))
    if not book:
        g4.append(_item("INFO", "ブックが未設定 — RULE の「PORT から取り込む」を使うと、セクター・ネットなどへの影響も点検できる"))
    # ⑤ 継続監視
    g5.append(_item("INFO", "毎日：FEXP / XRAY で要因の感応度を再計算（意図しないファクター・ベット）"))
    g5.append(_item("INFO", "毎月：エントリー価格と含み損益を忘れ、ゼロから作り直す（GATE の MONTHLY RESET）"))
    if fv < 0:
        g5.append(_item("INFO", "ショート：カタリストの日付と撤退ルールを先に決める"))
    gates = [{"id": "macro", "title": "① マクロ関門", "items": g1}, {"id": "fundamental", "title": "② ファンダメンタル関門", "items": g2},
             {"id": "flow", "title": "③ 需給・行動関門", "items": g3}, {"id": "sizing", "title": "④ サイジング関門", "items": g4},
             {"id": "monitor", "title": "⑤ 継続監視", "items": g5}]
    for g in gates:
        sts = [i["status"] for i in g["items"]]
        g["status"] = "FAIL" if "FAIL" in sts else "WARN" if "WARN" in sts else "OPEN" if "OPEN" in sts else "PASS" if "PASS" in sts else "INFO"
    blocked = next((g for g in gates[:4] if g["status"] == "FAIL"), None)
    open_ = any(g["status"] == "OPEN" for g in gates[:4])
    warn = any(g["status"] == "WARN" for g in gates[:4])
    verdict = ("見送り" if blocked else "未確認の項目あり" if open_ else "条件付きで可" if warn else "発注可")
    return {"symbol": sym, "side": side, "weight": w, "position_after": pos, "held_before": have, "verdict": verdict, "blocked_at": blocked["title"] if blocked else None,
            "gates": gates, "book_after": {k: after[k] for k in ("gross", "net", "long", "short", "names", "pairs")},
            "book_before": {k: before[k] for k in ("gross", "net", "names")} if before else None, "auto": bool(row)}


# ---- EVAL ------------------------------------------------------------------------------------------------------------
def _beta_ci(wins: int, losses: int) -> tuple[float, float, float]:
    from .trackrecord import beta_quantile
    a, b = 1 + wins, 1 + losses
    return a / (a + b), beta_quantile(0.05, a, b), beta_quantile(0.95, a, b)


def group_stats(vals: list[float]) -> dict[str, Any]:
    """vals: signed market-relative log returns (fractions)."""
    n = len(vals)
    if not n:
        return {"n": 0}
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    wins = sum(1 for v in vals if v > 0)
    pm, lo, hi = _beta_ci(wins, n - wins)
    return {"n": n, "mean_pct": m * 100, "median_pct": sorted(vals)[n // 2] * 100, "hit": wins / n,
            "hit_post": pm, "hit_lo": lo, "hit_hi": hi, "t": m / (sd / math.sqrt(n)) if sd > 0 and n > 1 else None}


def _index_on_or_before(dates: list[str], d: str) -> int | None:
    lo, hi = 0, len(dates) - 1
    if not dates or dates[0] > d:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if dates[mid] <= d:
            lo = mid
        else:
            hi = mid - 1
    return lo


def fwd_excess(closes: dict[str, float], mkt: dict[str, float], d: str, h: int) -> float | None:
    """log return of the stock over the h sessions after date d minus the market's over the same dates."""
    ds = sorted(closes)
    i = _index_on_or_before(ds, d)
    if i is None or i + h >= len(ds):
        return None
    a, b = ds[i], ds[i + h]
    if a not in mkt or b not in mkt or closes[a] <= 0 or closes[b] <= 0 or mkt[a] <= 0 or mkt[b] <= 0:
        return None
    return math.log(closes[b] / closes[a]) - math.log(mkt[b] / mkt[a])


def sample_dates(dates: list[str], calendar: list[str], h: int) -> list[str]:
    """Snapshot dates at least h sessions apart on ``calendar`` (no overlapping forward windows)."""
    out: list[str] = []
    last = None
    for d in sorted(dates):
        i = _index_on_or_before(calendar, d)
        if i is None:
            continue
        if last is None or i - last >= h:
            out.append(d)
            last = i
    return out


def grade_auto(history: list[tuple[str, dict[str, Any]]], closes: dict[str, dict[str, float]],
               market_of: dict[str, str], markets: dict[str, dict[str, float]], horizons: tuple[int, ...] = (5, 21, 63)) -> dict[str, Any]:
    """history: [(date, snapshot)]; market_of: {symbol: market symbol}; markets: {market symbol: closes}."""
    snaps = dict(history)
    cal = sorted(next(iter(markets.values()))) if markets else []
    out: dict[str, Any] = {"snapshots": len(snaps), "from": min(snaps) if snaps else None, "to": max(snaps) if snaps else None, "horizons": {}}
    for h in horizons:
        used = sample_dates(list(snaps), cal, h)
        groups: dict[str, list[float]] = {}
        pending = 0
        for d in used:
            for r in snaps[d].get("rows", []):
                fv = _fv(r.get("direction"))
                if not fv or not r.get("conviction"):
                    continue
                s = r["symbol"]
                mk = markets.get(market_of.get(s, ""))
                if not closes.get(s) or not mk:
                    continue
                x = fwd_excess(closes[s], mk, d, h)
                if x is None:
                    pending += 1
                    continue
                v = fv * x
                st = align_row(r)["state"]
                for key in ("ALL", f"c{r['conviction']}", f"state:{st}", f"src:{(r.get('f') or {}).get('source')}", f"dir:{r['direction']}"):
                    groups.setdefault(key, []).append(v)
        stats = {k: group_stats(v) for k, v in groups.items()}
        c = [stats.get(f"c{i}", {}) for i in (1, 2, 3)]
        verdict = None
        if all((x.get("n") or 0) >= 20 for x in (c[0], c[2])):
            verdict = ("確信度の高い判定ほど成績が良い（三位一致の原則と整合）" if c[2]["mean_pct"] > c[0]["mean_pct"]
                       else "確信度 3 の成績が確信度 1 を下回る — 判定のルールを見直す材料")
        out["horizons"][str(h)] = {"dates_used": len(used), "pending": pending, "stats": stats, "verdict": verdict}
    return out


def backtest_m(path: list[dict[str, Any]], sector_closes: dict[str, dict[str, float]], market: dict[str, float],
               step: int = 21, horizons: tuple[int, ...] = (21, 63)) -> dict[str, Any]:
    """M layer: on every ``step``-th day of the growth × liquidity path (point-in-time), the AUTO rule calls each TOPIX-17
    sector favoured (+1) / disfavoured (−1); forward market-relative returns of the sector ETFs by call."""
    out: dict[str, Any] = {"horizons": {}, "dates": 0}
    sample = path[::step]
    out["dates"] = len(sample)
    for h in horizons:
        spreads: list[float] = []
        by_view: dict[str, list[float]] = {"+1": [], "0": [], "-1": []}
        by_q: dict[int, list[float]] = {}
        for p in sample:
            q = p["q"]
            fav, dis = T.FAVOURED[q], T.DISFAVOURED[q]
            got: dict[int, list[float]] = {1: [], 0: [], -1: []}
            for etf, b in _sector_buckets(sector_closes):
                v = 1 if b in fav else -1 if b in dis else 0
                x = fwd_excess(sector_closes[etf], market, p["date"], h)
                if x is not None:
                    got[v].append(x)
                    by_view[f"{v:+d}" if v else "0"].append(x)
            if got[1] and got[-1]:
                s = sum(got[1]) / len(got[1]) - sum(got[-1]) / len(got[-1])
                spreads.append(s)
                by_q.setdefault(q, []).append(s)
        out["horizons"][str(h)] = {"spread": group_stats(spreads), "by_view": {k: group_stats(v) for k, v in by_view.items()},
                                   "by_quadrant": {str(k): group_stats(v) for k, v in sorted(by_q.items())}}
    return out


def _sector_buckets(sector_closes: dict[str, dict[str, float]]) -> list[tuple[str, str]]:
    return [(etf, TOPIX17_BUCKET[etf]) for etf in sector_closes if etf in TOPIX17_BUCKET and sector_closes[etf]]


def backtest_l(bars_by_symbol: dict[str, list[dict[str, Any]]], market_of: dict[str, str], markets: dict[str, dict[str, float]],
               step: int = 21, horizons: tuple[int, ...] = (21, 63), lookback: int = 800, warmup: int = 260) -> dict[str, Any]:
    """需給 layer: the AUTO 天井/底 rule recomputed on the bars available at each date (volume-based: no float, no margin,
    no dividend history), forward market-relative returns by zone."""
    from .quant import _date, closes_by_date

    zones: dict[str, dict[str, list[float]]] = {str(h): {"天井寄り": [], "中間帯": [], "底寄り": []} for h in horizons}
    signed: dict[str, list[float]] = {str(h): [] for h in horizons}
    crowded: dict[str, list[float]] = {str(h): [] for h in horizons}
    n_obs = 0
    for s, bars in bars_by_symbol.items():
        mk = markets.get(market_of.get(s, ""))
        if not mk or len(bars) < warmup + 21:
            continue
        cl = closes_by_date(bars)
        for i in range(warmup, len(bars), step):
            fl = T.flow_view(bars[max(0, i - lookback + 1):i + 1])
            if fl["zone"] == "データ不足":
                continue
            d = _date(bars[i]["time"])
            n_obs += 1
            for h in horizons:
                x = fwd_excess(cl, mk, d, h)
                if x is None:
                    continue
                zones[str(h)][fl["zone"]].append(x)
                if fl["view"]:
                    signed[str(h)].append(fl["view"] * x)
                if fl["crowded"]:
                    crowded[str(h)].append(x)
    return {"observations": n_obs, "horizons": {
        h: {"by_zone": {z: group_stats(v) for z, v in zones[h].items()}, "signed": group_stats(signed[h]),
            "crowded": group_stats(crowded[h])} for h in zones}}
