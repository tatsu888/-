"""Notion 04.4 「ファクターモデルによる定量リスク管理」— the minimum factor list, rule-based.

    スタイル : ベータ、サイズ、バリュー(PB/PE/DY)、モメンタム(1d/1m/3m/6m/1y/3y/3y-1y)、
              FY1/FY2 売上修正、クオリティ(EAR)、ボラティリティ
    マクロ   : 原油、米国、欧州、中国、金利、FX、外国人フロー   → time-series betas (xray.py)
    セクター : 24 業種それぞれ                                   → sector ETF / sector nets (xray.py, RULE)
    （Notion: 「コンセンサス強度」は一覧に入っていない）→ 混雑（代理）を追加で表示

Style factors here are Barra-style *exposures*: each stock's characteristic, winsorised and
z-scored across the universe (the AUTO coverage universe). Book exposure = Σ w·z / Σ|w|
(gross-normalised); |exposure| ≥ 0.5 → 「意図しないスタイル・ベット」.

Characteristics (point-in-time from daily bars unless noted):
    beta        252-day OLS beta vs the region's market
    size        ln(market cap, USD)                      (scanner)
    value_pb    book-to-price = 1 / PB                   (scanner)
    value_pe    earnings yield = 1 / PE (loss → negative) (scanner)
    value_dy    dividend yield %                         (scanner)
    mom_1d … mom_1y   log return over 1 / 21 / 63 / 126 / 252 sessions
    mom_3y      log return over 756 sessions; mom_3y_1y = return from t−756 to t−252 (long-term reversal)
    revision    % change of the next-quarter revenue forecast over ~1 month, from the terminal's own daily
                scanner snapshots (FY1/FY2 are not exposed by the data source → next-quarter used; empty until
                snapshots accumulate)
    quality_ear EAR = 3-day market-adjusted return around the most recent earnings release (≤ 180 days ago)
                (Brandt et al. 2008); the Notion label 「クオリティ(EAR)」
    quality_roe ROE (scanner) — supplementary quality
    volatility  60-day annualised realised volatility
    crowding    混雑（コンセンサス強度の代理）= mean of z(activity percentile) and z(mom_1y)
"""
from __future__ import annotations

import math
from typing import Any

STYLE_FACTORS: list[tuple[str, str]] = [
    ("beta", "ベータ"), ("size", "サイズ"), ("value_pb", "バリュー PB"), ("value_pe", "バリュー PE"),
    ("value_dy", "バリュー DY"), ("mom_1d", "モメンタム 1d"), ("mom_1m", "モメンタム 1m"), ("mom_3m", "モメンタム 3m"),
    ("mom_6m", "モメンタム 6m"), ("mom_1y", "モメンタム 1y"), ("mom_3y", "モメンタム 3y"), ("mom_3y_1y", "モメンタム 3y-1y"),
    ("revision", "売上予想修正（FY1/FY2 代替）"), ("quality_ear", "クオリティ (EAR)"), ("quality_roe", "クオリティ (ROE)"),
    ("volatility", "ボラティリティ"), ("crowding", "混雑（コンセンサス強度の代理）"),
]
LABEL = dict(STYLE_FACTORS)
MOM = {"mom_1d": 1, "mom_1m": 21, "mom_3m": 63, "mom_6m": 126, "mom_1y": 252, "mom_3y": 756}


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _logret(closes: list[float], n: int, end: int = 0) -> float | None:
    i1 = len(closes) - 1 - end
    i0 = i1 - n
    if i0 < 0 or closes[i0] <= 0 or closes[i1] <= 0:
        return None
    return math.log(closes[i1] / closes[i0])


def characteristics(bars: list[dict[str, Any]], market: dict[str, float] | None, scan: dict[str, Any] | None,
                    mcap_usd: float | None = None, revision: float | None = None, activity_pctl: float | None = None,
                    today_ts: float | None = None) -> dict[str, float | None]:
    """Raw characteristics of one stock. market = {date: daily log return} of its region's market."""
    import datetime as dt

    sc = scan or {}
    closes = [b["close"] for b in bars]
    dates = [dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).strftime("%Y-%m-%d") for b in bars]
    rets = {dates[i]: math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0}
    out: dict[str, float | None] = {k: _logret(closes, n) for k, n in MOM.items()}
    out["mom_3y_1y"] = _logret(closes, 756 - 252, end=252) if len(closes) > 757 else None
    # beta (252d) vs market
    beta = None
    if market:
        ds = [d for d in sorted(rets) if d in market][-252:]
        if len(ds) >= 60:
            x = [market[d] for d in ds]
            y = [rets[d] for d in ds]
            mx, my = sum(x) / len(x), sum(y) / len(y)
            vx = sum((a - mx) ** 2 for a in x)
            beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx if vx > 0 else None
    out["beta"] = beta
    r60 = [rets[d] for d in sorted(rets)[-60:]]
    if len(r60) >= 20:
        m = sum(r60) / len(r60)
        out["volatility"] = math.sqrt(sum((r - m) ** 2 for r in r60) / (len(r60) - 1)) * math.sqrt(252) * 100
    else:
        out["volatility"] = None
    out["size"] = math.log(mcap_usd) if mcap_usd and mcap_usd > 0 else None
    pb, pe = _num(sc.get("price_book_ratio")), _num(sc.get("price_earnings_ttm"))
    out["value_pb"] = (1 / pb) if pb and pb > 0 else None
    out["value_pe"] = (1 / pe) if pe not in (None, 0) else None
    out["value_dy"] = _num(sc.get("dividend_yield_recent"))
    out["quality_roe"] = _num(sc.get("return_on_equity"))
    out["revision"] = revision
    # EAR: 3 sessions around the last earnings release, market-adjusted
    ear = None
    er = _num(sc.get("earnings_release_date"))
    if er and market and rets:
        er = er / 1000 if er > 1e12 else er
        ed = dt.datetime.fromtimestamp(er, tz=dt.timezone.utc).strftime("%Y-%m-%d")
        now = today_ts or (bars[-1]["time"] if bars else 0)
        if 0 <= (now - er) <= 180 * 86400:
            rd = sorted(rets)
            idx = next((i for i, d in enumerate(rd) if d >= ed), None)
            if idx is not None:
                win = rd[max(0, idx - 1): idx + 2]
                b = beta if beta is not None else 1.0
                ear = sum(rets[d] - b * market.get(d, 0.0) for d in win)
    out["quality_ear"] = ear
    out["activity_pctl"] = activity_pctl
    return out


def _winsor_z(values: dict[str, float | None]) -> tuple[dict[str, float], dict[str, float] | None]:
    xs = sorted(v for v in values.values() if v is not None)
    n = len(xs)
    if n < 5:
        return {}, None
    lo, hi = xs[int(0.02 * (n - 1))], xs[int(0.98 * (n - 1))]
    clipped = {s: min(max(v, lo), hi) for s, v in values.items() if v is not None}
    m = sum(clipped.values()) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in clipped.values()) / (n - 1))
    if sd <= 0:
        return {s: 0.0 for s in clipped}, {"mean": m, "sd": 0.0, "lo": lo, "hi": hi, "n": n}
    return {s: (v - m) / sd for s, v in clipped.items()}, {"mean": m, "sd": sd, "lo": lo, "hi": hi, "n": n}


def exposures(chars: dict[str, dict[str, float | None]]) -> dict[str, Any]:
    """chars: {symbol: characteristics()} → {"z": {symbol: {factor: z}}, "stats": {factor: {...}}}."""
    z: dict[str, dict[str, float]] = {s: {} for s in chars}
    stats: dict[str, Any] = {}
    for f, _ in STYLE_FACTORS:
        if f == "crowding":
            continue
        zz, st = _winsor_z({s: c.get(f) for s, c in chars.items()})
        stats[f] = st
        for s, v in zz.items():
            z[s][f] = v
    # crowding (consensus-strength proxy) = mean of z(activity percentile) and z(mom_1y)
    za, sta = _winsor_z({s: c.get("activity_pctl") for s, c in chars.items()})
    stats["activity_pctl"] = sta
    for s in chars:
        parts = [v for v in (za.get(s), z[s].get("mom_1y")) if v is not None]
        if parts:
            z[s]["crowding"] = sum(parts) / len(parts)
    return {"z": z, "stats": stats}


def z_of(stats: dict[str, Any], char: dict[str, float | None]) -> dict[str, float]:
    """z-score a stock that is not in the universe against stored universe stats."""
    out: dict[str, float] = {}
    for f, st in stats.items():
        v = char.get(f)
        if not st or v is None or f == "activity_pctl":
            continue
        v = min(max(v, st["lo"]), st["hi"])
        out[f] = (v - st["mean"]) / st["sd"] if st["sd"] else 0.0
    a, m = char.get("activity_pctl"), char.get("mom_1y")
    st_a = stats.get("activity_pctl")
    parts = []
    if a is not None and st_a and st_a["sd"]:
        parts.append((min(max(a, st_a["lo"]), st_a["hi"]) - st_a["mean"]) / st_a["sd"])
    if "mom_1y" in out:
        parts.append(out["mom_1y"])
    if parts:
        out["crowding"] = sum(parts) / len(parts)
    return out


def book_exposure(positions: list[dict[str, Any]], z: dict[str, dict[str, float]], threshold: float = 0.5) -> dict[str, Any]:
    """Gross-normalised net style exposure Σ w·z / Σ|w| per factor; flags |x| ≥ threshold."""
    gross = sum(abs(p.get("weight") or 0) for p in positions if p.get("symbol") in z)
    rows, flags = [], []
    for f, label in STYLE_FACTORS:
        num, cov = 0.0, 0.0
        for p in positions:
            zz = z.get(p.get("symbol") or "", {})
            if f in zz:
                num += (p.get("weight") or 0) * zz[f]
                cov += abs(p.get("weight") or 0)
        if cov == 0:
            rows.append({"factor": f, "label": label, "exposure": None, "coverage": 0.0})
            continue
        x = num / gross if gross else None
        rows.append({"factor": f, "label": label, "exposure": x, "coverage": cov / gross if gross else None})
        if x is not None and abs(x) >= threshold:
            side = "プラス" if x > 0 else "マイナス"
            flags.append(f"意図しないスタイル・ベットの疑い: {label} に {side} {x:+.2f}σ（グロス比）")
    return {"rows": rows, "flags": flags, "gross": gross, "threshold": threshold}


def factor_performance(z: dict[str, dict[str, float]], fwd: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    """Top-third minus bottom-third average return per factor and horizon (descriptive: current exposures ×
    past returns — 'what kind of stock did well', not a backtest). fwd = {symbol: {"1W": r, "1M": r, "3M": r}}."""
    out = []
    for f, label in STYLE_FACTORS:
        xs = sorted((zz[f], s) for s, zz in z.items() if f in zz and s in fwd)
        if len(xs) < 6:
            continue
        k = max(1, len(xs) // 3)
        bot, top = [s for _, s in xs[:k]], [s for _, s in xs[-k:]]
        row = {"factor": f, "label": label, "n": len(xs)}
        for h in ("1W", "1M", "3M"):
            t = [fwd[s][h] for s in top if fwd[s].get(h) is not None]
            b = [fwd[s][h] for s in bot if fwd[s].get(h) is not None]
            row[h] = (sum(t) / len(t) - sum(b) / len(b)) * 100 if t and b else None
        out.append(row)
    return out
