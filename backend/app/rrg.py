"""RRG — Relative Rotation Graph (sector rotation) + volume-flow proxy.

Used as the rule-based stand-in for Notion 03.4 「セクター・ファンドフロー・モニター」(foreign flows by
sector are not public; relative strength × traded value is the observable footprint of those flows).

Open approximation of the JdK RS-Ratio / RS-Momentum (the original formulas are proprietary):
    weekly close (last close of each ISO week)
    RS          = 100 × price / benchmark
    RS-Ratio    = 100 + z(RS over the last n weeks)            (n = 10)
    RS-Momentum = 100 + z(RS-Ratio over the last m weeks)      (m = 10)
Quadrants (clockwise rotation is the normal path): Improving (ratio<100, mom>100) → Leading (>100, >100)
→ Weakening (>100, <100) → Lagging (<100, <100) → Improving.
Flow proxy: traded value (close × volume) of the last 4 weeks ÷ its 52-week average, and the share of
traded value on up-weeks over the last 4 weeks ("buying pressure").
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

QUAD = {"Leading": "主導", "Weakening": "減速", "Lagging": "劣後", "Improving": "改善"}
NEXT = {"Improving": "Leading", "Leading": "Weakening", "Weakening": "Lagging", "Lagging": "Improving"}


def weekly(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[{week: 'YYYY-Www', date, close, value}] — last close of each ISO week, traded value summed."""
    out: dict[str, dict[str, Any]] = {}
    for b in bars:
        d = dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).date()
        y, w, _ = d.isocalendar()
        key = f"{y}-W{w:02d}"
        row = out.setdefault(key, {"week": key, "value": 0.0})
        row["date"], row["close"] = d.isoformat(), b["close"]
        row["value"] += float(b.get("volume") or 0) * b["close"]
    return [out[k] for k in sorted(out)]


def _z(win: list[float]) -> float | None:
    n = len(win)
    if n < 3:
        return None
    m = sum(win) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in win) / (n - 1))
    return (win[-1] - m) / sd if sd > 0 else 0.0


def quadrant(ratio: float, mom: float) -> str:
    if ratio >= 100:
        return "Leading" if mom >= 100 else "Weakening"
    return "Improving" if mom >= 100 else "Lagging"


def rrg_series(item: list[dict[str, Any]], bench: list[dict[str, Any]], n: int = 10, m: int = 10) -> list[dict[str, Any]]:
    bw = {w["week"]: w["close"] for w in bench}
    rs = [(w["week"], w["date"], 100 * w["close"] / bw[w["week"]]) for w in item if bw.get(w["week"])]
    ratios = []
    for i in range(len(rs)):
        z = _z([r[2] for r in rs[max(0, i - n + 1):i + 1]]) if i >= n - 1 else None
        if z is not None:
            ratios.append((rs[i][0], rs[i][1], 100 + z))
    out = []
    for i in range(len(ratios)):
        if i < m - 1:
            continue
        z = _z([r[2] for r in ratios[i - m + 1:i + 1]])
        if z is None:
            continue
        ratio, mom = ratios[i][2], 100 + z
        out.append({"week": ratios[i][0], "date": ratios[i][1], "ratio": ratio, "momentum": mom, "quadrant": quadrant(ratio, mom)})
    return out


def flow(item: list[dict[str, Any]], recent: int = 4, base: int = 52) -> dict[str, Any]:
    vals = [w["value"] for w in item]
    if len(vals) < recent + 8:
        return {"value_ratio": None, "up_share": None}
    rec = sum(vals[-recent:]) / recent
    hist = vals[-base:]
    avg = sum(hist) / len(hist)
    up = sum(item[i]["value"] for i in range(len(item) - recent, len(item))
             if i > 0 and item[i]["close"] > item[i - 1]["close"])
    tot = sum(vals[-recent:])
    return {"value_ratio": rec / avg if avg else None, "up_share": up / tot if tot else None}


def analyze(items: dict[str, list[dict[str, Any]]], bench: list[dict[str, Any]], labels: dict[str, str] | None = None,
            tail: int = 8, n: int = 10, m: int = 10) -> dict[str, Any]:
    """items: {symbol: daily bars}; bench: daily bars."""
    bw = weekly(bench)
    rows = []
    for sym, bars in items.items():
        w = weekly(bars)
        s = rrg_series(w, bw, n, m)
        if not s:
            rows.append({"symbol": sym, "label": (labels or {}).get(sym, sym), "error": "履歴不足"})
            continue
        last = s[-1]
        prev = s[-2] if len(s) > 1 else last
        heading = math.degrees(math.atan2(last["momentum"] - prev["momentum"], last["ratio"] - prev["ratio"]))
        # clockwise in (ratio, momentum) space = angle decreasing; average over the tail
        angs = [math.atan2(p["momentum"] - 100, p["ratio"] - 100) for p in s[-tail:]]
        dang = 0.0
        for a, b in zip(angs, angs[1:]):
            dang += (b - a + math.pi) % (2 * math.pi) - math.pi
        bmap = {x["week"]: x["close"] for x in bw}
        rel4 = None
        if len(w) > 4 and bmap.get(w[-1]["week"]) and bmap.get(w[-5]["week"]):
            rel4 = ((w[-1]["close"] / w[-5]["close"]) / (bmap[w[-1]["week"]] / bmap[w[-5]["week"]]) - 1) * 100
        f = flow(w)
        penetr = None
        if f["value_ratio"] is not None:
            # 浸透度 (rule): leading/improving with rising traded value and buying pressure
            score = (1 if last["quadrant"] in ("Leading", "Improving") else -1) + (1 if f["value_ratio"] >= 1.2 else 0) \
                + (1 if (f["up_share"] or 0) >= 0.6 else -1 if (f["up_share"] or 1) <= 0.4 else 0)
            penetr = "資金流入が強い" if score >= 2 else "資金流出" if score <= -1 else "中立"
        rows.append({"symbol": sym, "label": (labels or {}).get(sym, sym), **last, "quadrant_ja": QUAD[last["quadrant"]],
                     "next": NEXT[last["quadrant"]], "heading_deg": heading,
                     "rotation": "時計回り" if dang < -0.05 else "反時計回り" if dang > 0.05 else "停滞",
                     "rel_4w_pct": rel4, **f, "flow_view": penetr, "tail": s[-tail:]})
    order = {"Leading": 0, "Improving": 1, "Weakening": 2, "Lagging": 3}
    rows.sort(key=lambda r: (order.get(r.get("quadrant", ""), 9), -(r.get("ratio") or 0)))
    return {"rows": rows, "weeks": len(bw), "params": {"n": n, "m": m, "tail": tail},
            "note": "JdK RRG の公開近似（z スコア版）。右上=主導、右下=減速、左下=劣後、左上=改善。通常は時計回りに巡る。"}
