"""PFND — automatic pair candidates inside each subsector (Notion 04.3 ペア管理 / 05.4 ペアの適性).

For every pair inside a group (subsector), rule-based:
  direction  long = higher Trinity score (SCORE sheet or AUTO rule score); no scores → direction 未定
  Pair Sigma 21-day annualised vol of the equal-notional pair (25–30% limit, ideal ≈10%)
  Pair Corr  60-day return correlation (both treated as long) — high = the legs share shocks (L2)
  corr<0.5   share of rolling 60-day windows (stride 5, last year) with corr < 0.5 (05.4 適性)
  Beta-adj Net÷Gross  |β_L − β_S| / 2 vs the market (< 30%)
  idio       min over legs of 1 − R² vs the market (≥ 30%)
  entry      20-day percentile of log(L/S); ≥ 80% → wait (拡大局面ではエントリーしない)
  size       評点差 → サイズ (framework.score_gap_size)
Verdict PASS = sigma < 25% and Net÷Gross < 30%; WARN = sigma < 30%; else FAIL.
"""
from __future__ import annotations

import math
from typing import Any

from . import framework as F


def _corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 10:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    saa = sum((x - ma) ** 2 for x in a)
    sbb = sum((y - mb) ** 2 for y in b)
    return sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else None


def _beta(y: list[float], x: list[float]) -> float | None:
    n = len(x)
    if n < 30:
        return None
    mx, my = sum(x) / n, sum(y) / n
    vx = sum((a - mx) ** 2 for a in x)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx if vx > 0 else None


def _sd(x: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    m = sum(x) / n
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))


def evaluate_pair(a: str, b: str, rets: dict[str, dict[str, float]], closes: dict[str, dict[str, float]],
                  bench: dict[str, float] | None, scores: dict[str, float]) -> dict[str, Any] | None:
    sa, sb = scores.get(a), scores.get(b)
    if sa is not None and sb is not None and sb > sa:
        a, b, sa, sb = b, a, sb, sa
    elif sa is None and sb is not None:
        a, b, sa, sb = b, a, sb, sa
    dates = sorted(rets[a].keys() & rets[b].keys() & (bench.keys() if bench else rets[a].keys()))[-252:]
    if len(dates) < 80:
        return None
    ra, rb = [rets[a][d] for d in dates], [rets[b][d] for d in dates]
    pr = [(x - y) / 2 for x, y in zip(ra, rb)]
    sigma = _sd(pr[-21:]) * math.sqrt(252) * 100
    corr = _corr(ra[-60:], rb[-60:])
    roll = [c for e in range(len(dates), 59, -5) if (c := _corr(ra[e - 60:e], rb[e - 60:e])) is not None]
    out: dict[str, Any] = {"long": a, "short": b, "pair_sigma_pct": sigma, "pair_corr": corr,
                           "share_corr_below_0_5": (sum(1 for c in roll if c < 0.5) / len(roll)) if roll else None}
    if bench:
        bm = [bench[d] for d in dates]
        bl, bs = _beta(ra, bm), _beta(rb, bm)
        out["beta_long"], out["beta_short"] = bl, bs
        out["beta_net_gross"] = abs(bl - bs) / 2 if bl is not None and bs is not None else None
        ca, cb = _corr(ra, bm), _corr(rb, bm)
        out["idio_min"] = min(1 - ca * ca, 1 - cb * cb) if ca is not None and cb is not None else None
    ca_, cb_ = closes[a], closes[b]
    common = sorted(ca_.keys() & cb_.keys())[-20:]
    spread = [math.log(ca_[d] / cb_[d]) for d in common if ca_[d] > 0 and cb_[d] > 0]
    out["spread_pctl_20d"] = (sum(1 for v in spread if v <= spread[-1]) / len(spread) * 100) if spread else None
    out["entry_blocked"] = out["spread_pctl_20d"] is not None and out["spread_pctl_20d"] >= 80
    if sa is not None and sb is not None:
        out["score_long"], out["score_short"] = sa, sb
        g = F.score_gap_size(sa, sb)
        out["score_gap"], out["size_pct"] = g["gap"], g["size_pct"]
        out["direction"] = "評点" if g["gap"] > 0 else "評点差なし"
    else:
        out["direction"] = "未定（評点なし）"
    bng = out.get("beta_net_gross")
    out["verdict"] = ("PASS" if sigma < 25 and (bng is None or bng < 0.3) else "WARN" if sigma < 30 else "FAIL")
    return out


def screen(groups: dict[str, list[str]], rets: dict[str, dict[str, float]], closes: dict[str, dict[str, float]],
           bench_of: dict[str, dict[str, float] | None], scores: dict[str, float], max_per_group: int = 25,
           top: int = 200) -> dict[str, Any]:
    rows = []
    for g, syms in groups.items():
        syms = [s for s in dict.fromkeys(syms) if s in rets][:max_per_group]
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                r = evaluate_pair(syms[i], syms[j], rets, closes, bench_of.get(syms[i]), scores)
                if r:
                    rows.append({"group": g, **r})
    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    rows.sort(key=lambda r: (rank[r["verdict"]], r["entry_blocked"], -(r.get("score_gap") or -9), r["pair_sigma_pct"]))
    return {"pairs": rows[:top], "groups": {g: len(v) for g, v in groups.items()}, "evaluated": len(rows)}
