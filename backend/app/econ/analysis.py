"""ECON analysis (pure, deterministic). Observations are [(YYYY-MM-DD, value)] ascending.

Per series
    transform   the signal: yoy (% vs a year ago) | lvl | d1 (vs previous period) | d12 (vs a year ago, units)
    metrics     last / change / signal / z (≈5 years) / percentile (≈10 years) / trend (3 vs 12 periods, sign-adjusted
                by ``good``) / streak / surprise vs a mechanical AR(1) forecast (NOT a market consensus) / stale flag
Across series (point-in-time: every month uses only data up to that month)
    composites  per country × {成長, インフレ, 流動性}: mean of good × rolling z (10 years) of the monthly signal,
                forward-filled for publication lags (M 2, Q 5, A 14 months); diffusion = share improving over 3 months
    quadrant    statistical Growth × Liquidity quadrant (Trinity Part 3) from the composites
    surprise    country surprise index = mean good × AR(1) surprise z of the observations of the last 3 months
    regime      forward returns of an asset by indicator state (high/low vs 5-year median × rising/falling over 3
                months), shifted by the publication lag, and the cross-correlation of the 3-month change with
                forward 1-month returns at leads 0–12 months
"""
from __future__ import annotations

import datetime as dt
import math
from bisect import bisect_right
from statistics import mean, median, pstdev
from typing import Any, Callable

Obs = list[tuple[str, float]]
Z_WINDOW = {"D": 1260, "W": 260, "M": 60, "Q": 20, "A": 10}       # ≈ 5 years of periods
PCTL_WINDOW = {"D": 2520, "W": 520, "M": 120, "Q": 40, "A": 20}   # ≈ 10 years
STALE_DAYS = {"D": 10, "W": 21, "M": 80, "Q": 200, "A": 640}     # last observation older than this → 更新停止の疑い
FFILL_M = {"D": 1, "W": 1, "M": 2, "Q": 5, "A": 14}              # months a monthly-grid value stays valid
ROLL = {"M": (120, 24), "Q": (40, 12), "A": (20, 8)}             # rolling z window / minimum (in periods)


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def add_months(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + k
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def month_range(a: str, b: str) -> list[str]:
    out, m = [], a
    while m <= b:
        out.append(m)
        m = add_months(m, 1)
    return out


# ---------------------------------------------------------------------------------------------------
# transforms
# ---------------------------------------------------------------------------------------------------
def _year_ago(obs: Obs, freq: str) -> Callable[[str], float | None]:
    if freq in ("M", "Q", "A"):
        m = dict(obs)
        return lambda d: m.get(f"{int(d[:4]) - 1:04d}{d[4:]}")
    ds, vs = [x[0] for x in obs], [x[1] for x in obs]
    tol = 3 if freq == "W" else 4             # 52 weeks = 364 days; daily data skips weekends and holidays

    def f(d: str) -> float | None:
        target = _date(d) - dt.timedelta(days=365)
        i = bisect_right(ds, target.isoformat())
        best = None
        for j in (i - 1, i):                     # nearest observation on either side (52 weeks = 364 days)
            if 0 <= j < len(ds) and ds[j] < d:
                gap = abs((_date(ds[j]) - target).days)
                if gap <= tol and (best is None or gap < best[0]):
                    best = (gap, vs[j])
        return best[1] if best else None
    return f


def transform(obs: Obs, freq: str, tf: str) -> Obs:
    if tf == "lvl":
        return list(obs)
    if tf == "d1":
        return [(obs[i][0], obs[i][1] - obs[i - 1][1]) for i in range(1, len(obs))]
    base = _year_ago(obs, freq)
    out = []
    for d, v in obs:
        b = base(d)
        if b is None:
            continue
        if tf == "yoy":
            if b > 0:
                out.append((d, (v / b - 1) * 100))
        else:  # d12
            out.append((d, v - b))
    return out


def to_monthly(obs: Obs) -> dict[str, float]:
    out: dict[str, float] = {}
    for d, v in obs:
        out[d[:7]] = v            # ascending → the last observation of each month wins
    return out


def signal_monthly(entry: dict[str, Any], obs: Obs) -> dict[str, float]:
    """The signal on a monthly grid (daily/weekly data: month-end value first, then the transform)."""
    f = entry["freq"]
    if f in ("D", "W"):
        mo = sorted(to_monthly(obs).items())
        sig = transform([(k + "-01", v) for k, v in mo], "M", entry["tf"])
    else:
        sig = transform(obs, f, entry["tf"])
    return {d[:7]: v for d, v in sig}


# ---------------------------------------------------------------------------------------------------
# per-series metrics
# ---------------------------------------------------------------------------------------------------
def ar1_forecast(x: list[float], n: int = 60) -> tuple[float, float] | None:
    """Forecast of the last value from the ones before it: x_t = a + b·x_{t-1}, fitted on up to n prior pairs."""
    hist = x[:-1][-(n + 1):]
    if len(hist) < 13:
        return None
    xs, ys = hist[:-1], hist[1:]
    mx, my = mean(xs), mean(ys)
    sxx = sum((a - mx) ** 2 for a in xs)
    b = sum((a - mx) * (c - my) for a, c in zip(xs, ys)) / sxx if sxx > 0 else 0.0
    a = my - b * mx
    sd = pstdev([c - (a + b * p) for p, c in zip(xs, ys)])
    return a + b * x[-2], sd


def surprise_z(x: list[float]) -> float | None:
    f = ar1_forecast(x)
    if not f or f[1] <= 0:
        return None
    return (x[-1] - f[0]) / f[1]


def streak(x: list[float], good: int) -> int:
    """Consecutive periods moving the same way at the end (+ = improving in the ``good`` sense, − = worsening)."""
    if len(x) < 2:
        return 0
    sgn = 1 if good >= 0 else -1
    d0 = (x[-1] - x[-2]) * sgn
    if d0 == 0:
        return 0
    n = 0
    for i in range(len(x) - 1, 0, -1):
        d = (x[i] - x[i - 1]) * sgn
        if d == 0 or (d > 0) != (d0 > 0):
            break
        n += 1
    return n if d0 > 0 else -n


def metrics(entry: dict[str, Any], obs: Obs, today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    if not obs:
        return {"n": 0}
    f, good = entry["freq"], entry.get("good", 1)
    last_d, last_v = obs[-1]
    prev = obs[-2][1] if len(obs) > 1 else None
    out: dict[str, Any] = {"n": len(obs), "first": obs[0][0], "last_date": last_d, "last": last_v, "prev": prev,
                           "chg": last_v - prev if prev is not None else None,
                           "age_days": (today - _date(last_d)).days}
    out["stale"] = out["age_days"] > STALE_DAYS[f]
    if entry["tf"] == "yoy":
        out["yoy"] = None
    sig = transform(obs, f, entry["tf"])
    if not sig:
        return out
    sv = [v for _, v in sig]
    out["signal"], out["signal_date"] = sv[-1], sig[-1][0]
    out["signal_prev"] = sv[-2] if len(sv) > 1 else None
    w = sv[-Z_WINDOW[f]:]
    sd = pstdev(w) if len(w) > 1 else 0.0
    out["z"] = (sv[-1] - mean(w)) / sd if len(w) >= 8 and sd > 0 else None
    p = sv[-PCTL_WINDOW[f]:]
    out["pctl"] = sum(1 for v in p if v <= sv[-1]) / len(p) * 100
    m = sorted(signal_monthly(entry, obs).items()) if f in ("D", "W") else None
    tv = [v for _, v in m] if m else sv
    per = {"Q": (1, 4), "A": (1, 3)}.get(f, (3, 12))
    if len(tv) >= per[1]:
        raw = mean(tv[-per[0]:]) - mean(tv[-per[1]:])
        out["trend_raw"] = raw
        out["trend"] = 0 if abs(raw) < 1e-12 else (1 if raw > 0 else -1) * (1 if good >= 0 else -1) if good else (1 if raw > 0 else -1)
    out["streak"] = streak(sv, good or 1)
    if f in ("W", "M", "Q"):
        out["surprise"] = surprise_z(sv)
    return out


# ---------------------------------------------------------------------------------------------------
# composites, diffusion, statistical quadrant, surprise index
# ---------------------------------------------------------------------------------------------------
def rolling_z(series: dict[str, float], freq: str) -> dict[str, float]:
    window, min_n = ROLL.get(freq, ROLL["M"])
    ks = sorted(series)
    vals = [series[k] for k in ks]
    out = {}
    for i, k in enumerate(ks):
        win = vals[max(0, i - window + 1): i + 1]
        if len(win) < min_n:
            continue
        sd = pstdev(win)
        if sd > 0:
            out[k] = (vals[i] - mean(win)) / sd
    return out


def _ffill(series: dict[str, float], keys: list[str], m: str, max_age: int) -> float | None:
    i = bisect_right(keys, m) - 1
    if i < 0:
        return None
    k = keys[i]
    if add_months(k, max_age) < m:
        return None
    return series[k]


def prepare(entry: dict[str, Any], obs: Obs) -> dict[str, Any]:
    """Monthly signal + its point-in-time rolling z (for composites)."""
    sig = signal_monthly(entry, obs)
    zf = "M" if entry["freq"] in ("D", "W", "M") else entry["freq"]
    z = rolling_z(sig, zf)
    return {"entry": entry, "sig": sig, "sig_keys": sorted(sig), "z": z, "z_keys": sorted(z),
            "max_age": FFILL_M[entry["freq"]]}


def composite(items: list[dict[str, Any]], months: list[str]) -> dict[str, dict[str, Any]]:
    """items: prepare() outputs (one country, one composite). → {month: {value, n, diffusion}}."""
    out = {}
    for m in months:
        vals, up, cnt = [], 0, 0
        for it in items:
            g = it["entry"].get("good", 1)
            z = _ffill(it["z"], it["z_keys"], m, it["max_age"])
            if z is not None:
                vals.append(g * z)
            s1 = _ffill(it["sig"], it["sig_keys"], m, it["max_age"])
            s0 = _ffill(it["sig"], it["sig_keys"], add_months(m, -3), it["max_age"] + 3)
            if s1 is not None and s0 is not None and s1 != s0:
                cnt += 1
                up += (s1 - s0) * g > 0
        if vals:
            out[m] = {"value": mean(vals), "n": len(vals), "diffusion": up / cnt * 100 if cnt else None}
    return out


def quadrant(g: float, l: float) -> int:
    from ..macro import quadrant as q
    return q(g, l)


def gl_path(growth: dict[str, dict[str, Any]], liquidity: dict[str, dict[str, Any]], months: list[str]) -> dict[str, Any]:
    from ..macro import GL_NEXT, GL_QUADRANTS

    path = [{"month": m, "growth": growth[m]["value"], "liquidity": liquidity[m]["value"],
             "q": quadrant(growth[m]["value"], liquidity[m]["value"])} for m in months if m in growth and m in liquidity]
    if not path:
        return {"available": False}
    cur = path[-1]
    ang = [math.atan2(p["liquidity"], p["growth"]) for p in path[-4:]]
    dang = sum(((b - a + math.pi) % (2 * math.pi)) - math.pi for a, b in zip(ang, ang[1:]))
    rot = "時計回り（通常の循環）" if dang < -0.05 else "反時計回り（逆行）" if dang > 0.05 else "停滞"
    return {"available": True, "current": {**cur, **GL_QUADRANTS[cur["q"]]}, "next": {"q": GL_NEXT[cur["q"]], **GL_QUADRANTS[GL_NEXT[cur["q"]]]},
            "rotation": rot, "trail": path[-24:], "quadrants": GL_QUADRANTS, "closeup_days": 4}


def surprise_series(entry: dict[str, Any], obs: Obs) -> dict[str, float]:
    """Point-in-time AR(1) surprise z of every observation of the signal (keyed by reference month)."""
    if entry["freq"] not in ("M", "Q", "W"):
        return {}
    sig = transform(obs, entry["freq"], entry["tf"])
    if entry["freq"] == "W":
        sig = sorted(to_monthly(sig).items())
        sig = [(k + "-01", v) for k, v in sig]
    vals = [v for _, v in sig]
    out = {}
    for i in range(13, len(vals)):
        z = surprise_z(vals[: i + 1])
        if z is not None:
            out[sig[i][0][:7]] = max(-4.0, min(4.0, z))
    return out


def surprise_index(items: list[tuple[dict[str, Any], dict[str, float]]], months: list[str], window: int = 3) -> dict[str, dict[str, Any]]:
    out = {}
    for m in months:
        lo = add_months(m, -(window - 1))
        vals = [e.get("good", 1) * z for e, s in items for k, z in s.items() if lo <= k <= m and e.get("good", 1)]
        if vals:
            out[m] = {"value": mean(vals), "n": len(vals)}
    return out


# ---------------------------------------------------------------------------------------------------
# regime / lead-lag against an asset
# ---------------------------------------------------------------------------------------------------
def _corr(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    mx, my = mean(x), mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx > 0 and sy > 0 else None


def regime(signal: dict[str, float], asset: dict[str, float], lag_m: int, good: int = 1, max_lead: int = 12) -> dict[str, Any]:
    """signal: reference month → value; asset: month → month-end close. Entry at the month-end when the value is
    known (reference month + lag); states use only information known then."""
    ks = sorted(signal)
    rows = []
    for i, m in enumerate(ks):
        t = add_months(m, lag_m)
        if t not in asset:
            continue
        hist = [signal[k] for k in ks[: i + 1]][-60:]
        prev3 = signal.get(add_months(m, -3))
        if len(hist) < 24 or prev3 is None:
            continue
        lvl = "高" if signal[m] >= median(hist) else "低"
        dirn = "上昇" if signal[m] >= prev3 else "低下"
        fwd = {h: asset[add_months(t, h)] / asset[t] - 1 for h in (1, 3, 6) if add_months(t, h) in asset and asset[t]}
        rows.append({"month": m, "known": t, "state": f"{lvl}・{dirn}", "fwd": fwd, "d3": signal[m] - prev3})
    states = {}
    for st in ("高・上昇", "高・低下", "低・上昇", "低・低下"):
        rs = [r for r in rows if r["state"] == st]
        cell: dict[str, Any] = {"n": len(rs)}
        for h in (1, 3, 6):
            v = [r["fwd"][h] * 100 for r in rs if h in r["fwd"]]
            cell[f"m{h}"] = mean(v) if v else None
            cell[f"hit{h}"] = sum(1 for x in v if x > 0) / len(v) * 100 if v else None
        states[st] = cell
    base = [r["fwd"][1] * 100 for r in rows if 1 in r["fwd"]]
    # lead-lag: 3-month change of the indicator (known at t) vs the asset's 1-month return starting k months later
    ccf = []
    for k in range(0, max_lead + 1):
        xs, ys = [], []
        for r in rows:
            a, b = add_months(r["known"], k), add_months(r["known"], k + 1)
            if a in asset and b in asset and asset[a]:
                xs.append(r["d3"] * (good or 1))
                ys.append(asset[b] / asset[a] - 1)
        ccf.append({"lead": k, "corr": _corr(xs, ys), "n": len(xs)})
    usable = [c for c in ccf if c["corr"] is not None and c["n"] >= 24]
    best = max(usable, key=lambda c: abs(c["corr"])) if usable else None
    last = rows[-1] if rows else None
    return {"states": states, "n": len(rows), "base_m1": mean(base) if base else None,
            "base_hit1": sum(1 for x in base if x > 0) / len(base) * 100 if base else None,
            "ccf": ccf, "best": best, "current_state": last["state"] if last else None,
            "note": "状態は当時分かっていた情報だけで判定（発表のずれを考慮）。3・6 か月先は重なりのある観測。相関は因果ではない。"}


# ---------------------------------------------------------------------------------------------------
# flows — 残高の系列は変化（Δ）、フローの系列は合計。ドル換算は単位が分かる系列だけ
# ---------------------------------------------------------------------------------------------------
FLOW_WINDOWS = {"W": (1, 4, 13, 52), "M": (1, 3, 6, 12), "Q": (1, 2, 4, 8), "A": (1, 2, 3, 5)}
FLOW_LABELS = {"W": ("1 週", "4 週", "13 週", "52 週"), "M": ("1 か月", "3 か月", "6 か月", "12 か月"),
               "Q": ("1 四半期", "2 四半期", "4 四半期", "8 四半期"), "A": ("1 年", "2 年", "3 年", "5 年")}


def weekly_last(obs: Obs) -> Obs:
    """Daily → weekly (the last observation of each ISO week)."""
    out: dict[tuple[int, int], tuple[str, float]] = {}
    for d, v in obs:
        y, w, _ = _date(d).isocalendar()
        out[(y, w)] = (d, v)
    return [out[k] for k in sorted(out)]


def flow_freq(entry: dict[str, Any]) -> str:
    return "W" if entry["freq"] == "D" else entry["freq"]


def flows_native(entry: dict[str, Any], obs: Obs) -> Obs:
    """Per-period flows in the series' own unit: Δ of a balance (kind stock) or the published flow (kind flow)."""
    if entry["freq"] == "D":
        obs = weekly_last(obs)
    if (entry.get("flow") or {}).get("kind") == "flow":
        return list(obs)
    return [(obs[i][0], obs[i][1] - obs[i - 1][1]) for i in range(1, len(obs))]


def to_usd_bn(entry: dict[str, Any], flows: Obs, fx: Obs | None) -> Obs | None:
    """Native flows → 10 億ドル (FX of each date, forward-filled). None when the unit or the FX is unknown."""
    meta = entry.get("flow") or {}
    mult, ccy = meta.get("mult"), meta.get("ccy", "USD")
    if not mult:
        return None
    if ccy == "USD":
        return [(d, v * mult / 1e9) for d, v in flows]
    if not fx:
        return None
    from .catalog import FX_FOR
    how = FX_FOR[ccy][1]
    ds = [x[0] for x in fx]
    out = []
    for d, v in flows:
        i = bisect_right(ds, d) - 1
        if i < 0:
            continue
        rate = fx[i][1]
        if rate:
            out.append((d, (v * mult / rate if how == "per_usd" else v * mult * rate) / 1e9))
    return out


def flow_metrics(entry: dict[str, Any], flows: Obs, usd: Obs | None = None, cum_periods: int = 156) -> dict[str, Any]:
    f = flow_freq(entry)
    if not flows:
        return {"n": 0}
    meta = entry.get("flow") or {}
    vals = [v for _, v in flows]
    w = vals[-Z_WINDOW.get(f, 60):]
    sd = pstdev(w) if len(w) > 1 else 0.0
    sums = {lab: sum(vals[-k:]) for k, lab in zip(FLOW_WINDOWS[f], FLOW_LABELS[f]) if len(vals) >= k}
    out: dict[str, Any] = {"n": len(vals), "freq": f, "last_date": flows[-1][0], "last": vals[-1], "sums": sums,
                           "z": (vals[-1] - mean(w)) / sd if len(w) >= 8 and sd > 0 else None,
                           "streak": _sign_streak(vals), "sign": meta.get("sign", 1), "kind": meta.get("kind", "stock")}
    tail = flows[-cum_periods:]
    acc, cum = 0.0, []
    for d, v in tail:
        acc += v
        cum.append((d, acc))
    out["cum"] = cum
    if usd:
        uv = [v for _, v in usd]
        out["usd_last"] = uv[-1]
        out["usd_sums"] = {lab: sum(uv[-k:]) for k, lab in zip(FLOW_WINDOWS[f], FLOW_LABELS[f]) if len(uv) >= k}
        acc, cu = 0.0, []
        for d, v in usd[-cum_periods:]:
            acc += v
            cu.append((d, acc))
        out["usd_cum"] = cu
    return out


def _sign_streak(vals: list[float]) -> int:
    """Consecutive periods of inflow (+n) or outflow (−n) at the end."""
    if not vals or vals[-1] == 0:
        return 0
    s = vals[-1] > 0
    n = 0
    for v in reversed(vals):
        if v == 0 or (v > 0) != s:
            break
        n += 1
    return n if s else -n


def group_total(rows: list[dict[str, Any]], weekly_months: int = 36) -> dict[str, Any] | None:
    """Sum of the effects (sign × USD flow) of a group's rows on a monthly grid (weekly flows summed per month)."""
    use = [r for r in rows if r.get("usd") and (r["entry"].get("flow") or {}).get("total", True)]
    if not use:
        return None
    monthly: dict[str, float] = {}
    for r in use:
        sign = (r["entry"].get("flow") or {}).get("sign", 1)
        for d, v in r["usd"]:
            monthly[d[:7]] = monthly.get(d[:7], 0.0) + sign * v
    ks = sorted(monthly)[-weekly_months:]
    series = [(k, monthly[k]) for k in ks]
    return {"members": [r["entry"]["id"] for r in use], "monthly": series,
            "m1": series[-1][1] if series else None, "m3": sum(v for _, v in series[-3:]) if len(series) >= 3 else None,
            "m12": sum(v for _, v in series[-12:]) if len(series) >= 12 else None}
