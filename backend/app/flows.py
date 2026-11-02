"""FLOW — global money-flow monitor across asset classes, countries, sectors and style factors (ETF-based).

True fund-flow data (EPFR etc.) is proprietary. These are the observable, rule-based footprints:
    ret        return over the window (window = slider, default 21 sessions)
    rs         return minus the lens benchmark (relative strength)
    value_ratio  average traded value (close × volume) over the window ÷ its 250-session average
    cmf        Chaikin money flow over the window: Σ((C−L)−(H−C))/(H−L)·V / ΣV   (−1 … +1, buying pressure)
    obv        Σ sign(daily return)·traded value / Σ traded value over the window   (−1 … +1)
    flow_score mean of cmf, obv and clip(value_ratio − 1, −1, 1)·sign(rs)  → ≥ 0.25 流入 / ≤ −0.25 流出 / 中立
    creations  REAL creations/redemptions: change in ETF shares outstanding × price, from the terminal's own
               daily snapshots of the scanner's share count (data/flows/shares.json; empty until recorded)
Summary rules turn spreads between groups into statements (株式→債券, EM vs 先進国, シクリカル vs ディフェンシブ …).
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

LENSES: dict[str, dict[str, Any]] = {
    "ASSET": {"label": "アセットクラス", "bench": "NASDAQ:ACWI", "items": {
        "NASDAQ:ACWI": "世界株", "AMEX:SPY": "米国株", "AMEX:EFA": "先進国株（除く米国）", "AMEX:EEM": "新興国株", "AMEX:EWJ": "日本株",
        "NASDAQ:TLT": "米国債 20年+", "NASDAQ:IEF": "米国債 7-10年", "AMEX:BIL": "T-bill（現金）", "AMEX:LQD": "投資適格社債",
        "AMEX:HYG": "ハイイールド", "AMEX:TIP": "TIPS（インフレ連動）", "NASDAQ:EMB": "新興国債", "AMEX:GLD": "金",
        "AMEX:DBC": "コモディティ", "AMEX:USO": "原油", "AMEX:VNQ": "REIT", "AMEX:UUP": "ドル", "NASDAQ:IBIT": "ビットコイン"}},
    "COUNTRY": {"label": "カントリー", "bench": "NASDAQ:ACWI", "items": {
        "AMEX:SPY": "米国", "AMEX:EWJ": "日本", "AMEX:FXI": "中国（大型）", "AMEX:ASHR": "中国 A株", "AMEX:EWH": "香港", "AMEX:EWT": "台湾",
        "AMEX:EWY": "韓国", "BATS:INDA": "インド", "AMEX:EWA": "豪州", "AMEX:EWU": "英国", "AMEX:EWG": "ドイツ", "AMEX:EWQ": "フランス",
        "AMEX:VGK": "欧州", "AMEX:EWC": "カナダ", "AMEX:EWZ": "ブラジル", "AMEX:EWW": "メキシコ", "AMEX:VNM": "ベトナム"}},
    "SECTOR_US": {"label": "セクター（米国）", "bench": "AMEX:SPY", "items": {
        "AMEX:XLK": "テクノロジー", "AMEX:XLF": "金融", "AMEX:XLE": "エネルギー", "AMEX:XLV": "ヘルスケア", "AMEX:XLI": "資本財",
        "AMEX:XLY": "一般消費財", "AMEX:XLP": "生活必需品", "AMEX:XLU": "公益", "AMEX:XLB": "素材", "AMEX:XLRE": "不動産",
        "AMEX:XLC": "通信", "NASDAQ:SMH": "半導体"}},
    "SECTOR_JP": {"label": "セクター（日本 TOPIX-17）", "bench": "TVC:TOPIX", "items": {}},  # filled from xray.TOPIX17
    "STYLE_US": {"label": "スタイル（米国 ETF）", "bench": "AMEX:SPY", "items": {
        "BATS:MTUM": "モメンタム", "BATS:VLUE": "バリュー", "BATS:QUAL": "クオリティ", "BATS:USMV": "最小分散", "AMEX:IWM": "小型",
        "AMEX:IWF": "グロース", "AMEX:IWD": "バリュー（R1000）", "AMEX:SPHB": "高ベータ", "AMEX:SPLV": "低ボラ", "AMEX:VYM": "高配当",
        "AMEX:RSP": "均等加重"}},
    "STYLE_JP": {"label": "スタイル（日本 ETF）", "bench": "TSE:1306", "items": {
        "TSE:1321": "日経225（値嵩）", "TSE:1489": "高配当50", "TSE:1591": "JPX400（クオリティ）", "TSE:2516": "グロース250（小型成長）"}},
}
RISK_ON = ["NASDAQ:ACWI", "AMEX:SPY", "AMEX:EFA", "AMEX:EEM", "AMEX:HYG"]
RISK_OFF = ["NASDAQ:TLT", "NASDAQ:IEF", "AMEX:BIL", "AMEX:GLD"]
CYCLICAL_US = ["AMEX:XLI", "AMEX:XLB", "AMEX:XLE", "AMEX:XLF", "AMEX:XLY"]
DEFENSIVE_US = ["AMEX:XLP", "AMEX:XLU", "AMEX:XLV"]


def lens_items(lens: str) -> dict[str, str]:
    if lens == "SECTOR_JP":
        from .xray import TOPIX17
        return dict(TOPIX17)
    return dict(LENSES[lens]["items"])


def _date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def metrics(bars: list[dict[str, Any]], bench: list[dict[str, Any]] | None, window: int = 21) -> dict[str, Any] | None:
    if len(bars) < window + 30:
        return None
    w = bars[-window:]
    ret = (w[-1]["close"] / bars[-window - 1]["close"] - 1) * 100 if bars[-window - 1]["close"] else None
    rs = None
    if bench and len(bench) > window:
        bm = {_date(b["time"]): b["close"] for b in bench}
        d0, d1 = _date(bars[-window - 1]["time"]), _date(w[-1]["time"])
        b0 = next((bm[d] for d in sorted(bm, reverse=True) if d <= d0), None)
        b1 = next((bm[d] for d in sorted(bm, reverse=True) if d <= d1), None)
        if b0 and b1 and ret is not None:
            rs = ret - (b1 / b0 - 1) * 100
    tv = [b["close"] * float(b.get("volume") or 0) for b in bars]
    hist = tv[-250:]
    avg_all = sum(hist) / len(hist) if hist else 0
    avg_w = sum(tv[-window:]) / window
    value_ratio = avg_w / avg_all if avg_all else None
    num = den = 0.0
    on = 0.0
    for i in range(len(bars) - window, len(bars)):
        b, p = bars[i], bars[i - 1]
        v = float(b.get("volume") or 0)
        rng = (b.get("high") or b["close"]) - (b.get("low") or b["close"])
        if rng > 0:
            num += (((b["close"] - b["low"]) - (b["high"] - b["close"])) / rng) * v
        den += v
        on += (1 if b["close"] > p["close"] else -1 if b["close"] < p["close"] else 0) * b["close"] * v
    cmf = num / den if den else None
    tw = sum(tv[-window:])
    obv = on / tw if tw else None
    parts = [x for x in (cmf, obv) if x is not None]
    if value_ratio is not None and rs is not None:
        parts.append(max(-1.0, min(1.0, value_ratio - 1)) * (1 if rs > 0 else -1 if rs < 0 else 0))
    score = sum(parts) / len(parts) if parts else None
    return {"ret": ret, "rs": rs, "value_ratio": value_ratio, "cmf": cmf, "obv": obv, "flow_score": score,
            "flow": None if score is None else "流入" if score >= 0.25 else "流出" if score <= -0.25 else "中立",
            "last": w[-1]["close"], "date": _date(w[-1]["time"])}


def creations(shares_hist: dict[str, dict[str, float]], symbol: str, price: float | None, asof: str | None = None) -> dict[str, Any]:
    """{date: {symbol: shares}} → flows over ~1W and ~1M (calendar days) in price units."""
    pts = sorted((d, v[symbol]) for d, v in shares_hist.items() if symbol in v and v[symbol] and (not asof or d <= asof))
    if len(pts) < 2 or not price:
        return {"w1": None, "m1": None, "days_recorded": len(pts)}
    last_d, last_s = pts[-1]
    ld = dt.date.fromisoformat(last_d)

    def back(days: int) -> float | None:
        cand = [s for d, s in pts if (ld - dt.date.fromisoformat(d)).days >= days]
        return (last_s - cand[-1]) * price if cand else None

    return {"w1": back(7), "m1": back(28), "shares": last_s, "days_recorded": len(pts),
            "pct_1m": ((last_s / next(s for d, s in reversed(pts) if (ld - dt.date.fromisoformat(d)).days >= 28) - 1) * 100)
            if any((ld - dt.date.fromisoformat(d)).days >= 28 for d, _ in pts) else None}


def summarize(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rule-based statements from group spreads of flow_score (only when both sides are available)."""
    def avg(syms: list[str]) -> float | None:
        v = [rows[s]["flow_score"] for s in syms if s in rows and rows[s].get("flow_score") is not None]
        return sum(v) / len(v) if v else None

    out = []

    def rule(label: str, a: float | None, b: float | None, pos: str, neg: str, th: float = 0.15) -> None:
        if a is None or b is None:
            return
        d = a - b
        out.append({"rule": label, "spread": d, "reading": pos if d >= th else neg if d <= -th else "拮抗"})

    rule("リスク資産 vs 安全資産", avg(RISK_ON), avg(RISK_OFF), "リスクオン（株式・HY へ流入）", "リスクオフ（国債・現金・金へ）")
    rule("新興国 vs 先進国", avg(["AMEX:EEM", "NASDAQ:EMB"]), avg(["AMEX:EFA", "AMEX:SPY"]), "新興国へ", "先進国へ")
    rule("クレジット（HY vs 国債）", avg(["AMEX:HYG"]), avg(["NASDAQ:IEF"]), "クレジットへ（景気楽観）", "国債へ（景気警戒）")
    rule("インフレ（TIPS・コモディティ vs 名目債）", avg(["AMEX:TIP", "AMEX:DBC"]), avg(["NASDAQ:IEF"]), "インフレ・ヘッジへ", "名目債へ（ディスインフレ）")
    rule("シクリカル vs ディフェンシブ（米国）", avg(CYCLICAL_US), avg(DEFENSIVE_US), "シクリカルへ", "ディフェンシブへ")
    rule("グロース vs バリュー（米国）", avg(["AMEX:IWF"]), avg(["AMEX:IWD"]), "グロースへ", "バリューへ")
    rule("高ベータ vs 低ボラ（米国）", avg(["AMEX:SPHB"]), avg(["AMEX:SPLV"]), "高ベータへ（リスク選好）", "低ボラへ（守り）")
    rule("日本 vs 世界", avg(["AMEX:EWJ"]), avg(["NASDAQ:ACWI"]), "日本へ（海外勢の日本株買いの代理）", "日本から流出")
    return out
