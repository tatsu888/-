"""TRAK — your own track record from the trade blotter, with Bayesian hit rates (Notion 04.1 ベイズ推理,
04.2 ケリー, 05.6 Ⅲ「自分の PnL は保険売り型か凸性購入型か」, 目標: 週次勝率 68% / 月次 76% / 年次 90%).

Round trips: average-cost accounting; every trade that reduces a position closes a round trip
(partial closes are separate round trips). Return % = direction × (exit / avg cost − 1).
Tags: hashtags in the trade notes of the position episode (#2%Japan #alpha_short …) + side (long/short).

Per group (all / long / short / each tag), rules:
  hit rate posterior   Beta(a0 + wins, b0 + losses), default prior Beta(1, 1); mean and 90% credible interval
  XW / XL              mean winning return / mean losing return (as fractions)
  E = p·XW − (1−p)·XL, Kelly F = E / (XW·XL) with p = posterior mean
  skew of returns      < −0.5 保険売り型（コツコツドカン） / > 0.5 凸性購入型（ドカンコツコツ） / else 対称
                       (only labelled with n ≥ 10 round trips)
  recommended weight   min(½·F, 3%) (2% for the SHORT group) — F itself is the theoretical Kelly fraction
Period win rates: share of ISO weeks / months / years with positive realised P&L (by close date).
"""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

from .stats import betainc

TARGETS = {"week": 68.0, "month": 76.0, "year": 90.0}


def _tags(note: str | None) -> list[str]:
    return re.findall(r"#([^\s#,、]+)", note or "")


def _day(t: str | None) -> dt.date | None:
    if not t:
        return None
    try:
        return dt.date.fromisoformat(str(t)[:10])
    except ValueError:
        return None


def round_trips(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pos: dict[str, dict[str, Any]] = {}
    out = []
    for t in sorted(trades, key=lambda x: (x.get("time") or "", x.get("id") or "")):
        sym, qty, px = t["symbol"], float(t["qty"]), float(t["price"])
        fee = float(t.get("fee") or 0)
        signed = qty if t["side"] == "buy" else -qty
        p = pos.setdefault(sym, {"qty": 0.0, "avg": 0.0, "opened": None, "tags": set(), "fees": 0.0})
        if p["qty"] == 0 or (p["qty"] > 0) == (signed > 0):
            if p["qty"] == 0:
                p["opened"], p["tags"], p["fees"] = t.get("time"), set(), 0.0
            new = p["qty"] + signed
            p["avg"] = (p["avg"] * abs(p["qty"]) + px * abs(signed)) / abs(new)
            p["qty"] = new
            p["tags"] |= set(_tags(t.get("note")))
            p["fees"] += fee
            continue
        closing = min(abs(signed), abs(p["qty"]))
        direction = 1 if p["qty"] > 0 else -1
        pnl = closing * (px - p["avg"]) * direction - fee
        o, c = _day(p["opened"]), _day(t.get("time"))
        out.append({"symbol": sym, "side": "long" if direction > 0 else "short", "qty": closing, "entry": p["avg"],
                    "exit": px, "pnl": pnl, "ret_pct": direction * (px / p["avg"] - 1) * 100 if p["avg"] else 0.0,
                    "opened": p["opened"], "closed": t.get("time"), "hold_days": (c - o).days if o and c else None,
                    "tags": sorted(p["tags"] | set(_tags(t.get("note"))))})
        remaining = abs(signed) - closing
        p["qty"] += math.copysign(closing, signed)
        if remaining > 0:  # flipped
            p["qty"], p["avg"], p["opened"], p["tags"] = math.copysign(remaining, signed), px, t.get("time"), set(_tags(t.get("note")))
        elif p["qty"] == 0:
            p["avg"] = 0.0
    return out


def beta_quantile(q: float, a: float, b: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if betainc(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def group_stats(trips: list[dict[str, Any]], a0: float = 1.0, b0: float = 1.0) -> dict[str, Any]:
    n = len(trips)
    rets = [t["ret_pct"] / 100 for t in trips]
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r <= 0]
    a, b = a0 + len(wins), b0 + len(losses)
    p = a / (a + b)
    xw = sum(wins) / len(wins) if wins else None
    xl = sum(losses) / len(losses) if losses else None
    e = (p * xw - (1 - p) * xl) if xw is not None and xl is not None else None
    kelly = (e / (xw * xl)) if e is not None and xw and xl else None
    skew = None
    if n >= 3:
        m = sum(rets) / n
        sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (n - 1))
        skew = (sum((r - m) ** 3 for r in rets) / n) / sd ** 3 if sd > 0 else 0.0
    if skew is None:
        shape = None
    elif n < 10:
        shape = f"標本不足（n={n} < 10）"
    else:
        shape = "保険売り型（コツコツドカン）" if skew < -0.5 else "凸性購入型（ドカンコツコツ）" if skew > 0.5 else "対称"
    return {"n": n, "wins": len(wins), "losses": len(losses), "hit_raw": len(wins) / n * 100 if n else None,
            "posterior": {"a": a, "b": b, "mean": p * 100, "lo90": beta_quantile(0.05, a, b) * 100, "hi90": beta_quantile(0.95, a, b) * 100},
            "xw_pct": xw * 100 if xw is not None else None, "xl_pct": xl * 100 if xl is not None else None,
            "payoff": (xw / xl) if xw and xl else None, "e_pct": e * 100 if e is not None else None,
            "kelly_f_pct": kelly * 100 if kelly is not None else None, "skew": skew, "shape": shape,
            "recommended_pct": max(0.0, min(kelly * 50, 3.0)) if kelly is not None else None,
            "pnl": sum(t["pnl"] for t in trips), "avg_hold_days": (sum(t["hold_days"] for t in trips if t["hold_days"] is not None)
                                                                  / max(1, sum(1 for t in trips if t["hold_days"] is not None))) if trips else None}


def period_win_rates(trips: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for name, key in (("week", lambda d: f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"), ("month", lambda d: d.strftime("%Y-%m")),
                      ("year", lambda d: str(d.year))):
        agg: dict[str, float] = {}
        for t in trips:
            d = _day(t["closed"])
            if d:
                agg[key(d)] = agg.get(key(d), 0.0) + t["pnl"]
        pos = sum(1 for v in agg.values() if v > 0)
        out[name] = {"periods": len(agg), "positive": pos, "win_rate": pos / len(agg) * 100 if agg else None,
                     "target": TARGETS[name], "series": [{"period": k, "pnl": v} for k, v in sorted(agg.items())][-60:]}
    return out


def analyze(trades: list[dict[str, Any]], a0: float = 1.0, b0: float = 1.0) -> dict[str, Any]:
    trips = round_trips(trades)
    groups: dict[str, list[dict[str, Any]]] = {"ALL": trips, "LONG": [t for t in trips if t["side"] == "long"],
                                               "SHORT": [t for t in trips if t["side"] == "short"]}
    for t in trips:
        for tag in t["tags"]:
            groups.setdefault(f"#{tag}", []).append(t)
    stats = {k: group_stats(v, a0, b0) for k, v in groups.items() if v}
    if "SHORT" in stats and stats["SHORT"]["recommended_pct"] is not None:
        stats["SHORT"]["recommended_pct"] = min(stats["SHORT"]["recommended_pct"], 2.0)
    return {"groups": stats,
            "periods": period_win_rates(trips), "trips": trips[-200:][::-1], "prior": {"a0": a0, "b0": b0},
            "note": "勝率はベータ分布で更新（事前 Beta(a0,b0)）。KELLY には事後平均の勝率と平均勝ち／負け率を渡す。"}
