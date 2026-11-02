"""THEME — Theme Alpha baskets (Notion 03.3 / 03.6 「事実 → 理由 → バスケット」), rule-based monitoring.

A theme = {name, fact, reason, driver (macro series spec, as in macro.build), driver_dir (+1/−1),
           driver_kind ('price' | 'yield'), longs [{symbol, weight}], shorts [...], hedge (index, when no shorts)}.

Daily analytics (deterministic):
  • long basket / short basket (or hedge) — weighted average of daily log returns (weights re-normalised
    over members that traded that day); spread = L − S, and a beta-neutral spread L − (β_L/β_S)·S
  • spread_z  = z of the 20-day spread return vs its own history (trailing 3 years)
  • driver_z  = z of the 20-day driver change × driver_dir (positive = the theme's fact is playing out)
  • lead      = best positive lag of corr(driver change, spread return) (driver leads the basket)
  • phase (反応ラグ 03.2 → rule):
        driver_z ≥ 1 and spread_z < 0.5   → 「②→③ エントリーゾーン（未波及）」
        driver_z ≥ 1 and spread_z ≥ 1.5   → 「③ 織り込み進行（遅い）」
        driver_z < 1 and spread_z ≥ 1.5   → 「バスケット先行（ドライバーなし）— 要確認」
        driver_z ≤ −1                     → 「事実が逆行（テーマ前提を再確認）」
        otherwise                         → 「① 初動前／様子見」
    (no driver → phase from the spread only)
  • basket flow (限界④ / B-1): average pairwise correlation of the long members over 60 days and its
    percentile vs the last year; ≥ 80th pct and ≥ 0.5 → 「バスケット買いが支配（銘柄間の差が効きにくい）」
  • dispersion = cross-sectional σ of members' 21-day returns (idiosyncratic opportunity)
  • crowding  = mean percentile of members' 20-day traded volume vs their own year
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from .leadlag import cross_correlation

TEMPLATES: list[dict[str, Any]] = [
    {"name": "2% Japan", "engine": "Theme Alpha",
     "fact": "日銀の政策正常化で賃金インフレのダイナミクスが解放された／トランプ政策はグローバルにインフレ的",
     "reason": "最終政策金利の上振れ期待が日本株投資家に十分織り込まれていない",
     "portfolio": "ロング：金利感応金融株・内需不動産（30銘柄）／ショート：TOPIX 先物",
     "driver": "TVC:JP10Y", "driver_kind": "yield", "driver_dir": 1,
     "longs": [{"symbol": "TSE:1631"}, {"symbol": "TSE:1632"}, {"symbol": "TSE:1633"}], "shorts": [], "hedge": "TVC:TOPIX"},
    {"name": "Japan Political Beneficiaries", "engine": "Theme Alpha",
     "fact": "総裁選で国家的課題は防衛・防災・人手不足・エネルギー", "reason": "勝利候補のマニフェスト以外のテーマは関心から外れやすい",
     "portfolio": "ロング：重工業・建設・人材派遣・公益（45銘柄）／ショート：TOPIX 先物",
     "driver": None, "driver_kind": "price", "driver_dir": 1,
     "longs": [{"symbol": "TSE:1624"}, {"symbol": "TSE:1619"}, {"symbol": "TSE:1627"}], "shorts": [], "hedge": "TVC:TOPIX"},
    {"name": "ESG Backlash", "engine": "Theme Alpha",
     "fact": "グリーン・トランスフォーメーションの停滞、化石燃料・エネルギー自立の再評価",
     "reason": "自動車・石油精製・鉄鋼・公益のディスカウント縮小、エコ・プレミアムの剥落",
     "portfolio": "ロング：自動車・石油精製・資源・鉄鋼・空運・原発公益（32銘柄）／ショート：エコ素材・住宅機器・ガス（23銘柄）",
     "driver": "TVC:USOIL", "driver_kind": "price", "driver_dir": 1,
     "longs": [{"symbol": "TSE:1622"}, {"symbol": "TSE:1618"}, {"symbol": "TSE:1623"}, {"symbol": "TSE:1627"}],
     "shorts": [{"symbol": "TSE:1620"}, {"symbol": "TSE:1619"}], "hedge": "TVC:TOPIX"},
    {"name": "Governance in Motion", "engine": "Theme Alpha",
     "fact": "TSE 改革とアクティビストで大企業が株主重視に", "reason": "アクティビスト非対象企業は期待が織り込まれておらずペイオフが大きい",
     "portfolio": "ロング：銀行・金融・商社・建設・不動産のアクティビスト非対象（39銘柄）／ショート：TOPIX 先物",
     "driver": None, "driver_kind": "price", "driver_dir": 1,
     "longs": [{"symbol": "TSE:1631"}, {"symbol": "TSE:1632"}, {"symbol": "TSE:1629"}, {"symbol": "TSE:1619"}, {"symbol": "TSE:1633"}],
     "shorts": [], "hedge": "TVC:TOPIX"},
    {"name": "Global Growth Stall", "engine": "Market Timing",
     "fact": "政策ショック・リスクの高まり（リスクオフ初期）", "reason": "内需安定銘柄へシフト、脆弱なシクリカルを回避",
     "portfolio": "ロング：内需の大型安定（49銘柄）／ショート：景気感応・ファンダ弱のシクリカル（46銘柄）",
     "driver": {"ratio": ["COMEX:HG1!", "TVC:GOLD"]}, "driver_kind": "price", "driver_dir": -1,
     "longs": [{"symbol": "TSE:1617"}, {"symbol": "TSE:1621"}, {"symbol": "TSE:1627"}, {"symbol": "TSE:1630"}],
     "shorts": [{"symbol": "TSE:1624"}, {"symbol": "TSE:1625"}, {"symbol": "TSE:1623"}, {"symbol": "TSE:1620"}], "hedge": "TVC:TOPIX"},
]
TEMPLATE_NOTE = ("テンプレートの構成は Notion のセクター記述を TOPIX-17 業種 ETF で代用したもの（実際のバスケットではない）。"
                 "自分の構成銘柄に置き換えて使う。")


def _date(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def daily_returns(bars: list[dict[str, Any]]) -> dict[str, float]:
    out, prev = {}, None
    for b in bars:
        if prev and prev["close"] > 0 and b["close"] > 0:
            out[_date(b["time"])] = math.log(b["close"] / prev["close"])
        prev = b
    return out


def basket(members: list[dict[str, Any]], rets: dict[str, dict[str, float]], dates: list[str]) -> list[float]:
    ws = [(m["symbol"], float(m.get("weight") or 1.0)) for m in members if m.get("symbol") in rets]
    out = []
    for d in dates:
        num = den = 0.0
        for s, w in ws:
            r = rets[s].get(d)
            if r is not None:
                num += w * r
                den += abs(w)
        out.append(num / den if den else 0.0)
    return out


def _sd(x: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    m = sum(x) / n
    return math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))


def _corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 5:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    saa = sum((x - ma) ** 2 for x in a)
    sbb = sum((y - mb) ** 2 for y in b)
    return sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else None


def _beta(y: list[float], x: list[float]) -> float | None:
    n = len(x)
    if n < 20:
        return None
    mx, my = sum(x) / n, sum(y) / n
    vx = sum((a - mx) ** 2 for a in x)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx if vx > 0 else None


def zlast(series: list[float], window: int, hist: int = 756) -> float | None:
    """z of the latest rolling `window` sum vs the history of rolling sums."""
    if len(series) < window + 30:
        return None
    sums = [sum(series[i - window:i]) for i in range(window, len(series) + 1)][-hist:]
    sd = _sd(sums)
    return (sums[-1] - sum(sums) / len(sums)) / sd if sd > 0 else None


def avg_pairwise_corr(rets: dict[str, dict[str, float]], syms: list[str], dates: list[str]) -> float | None:
    cols = [[rets[s].get(d, 0.0) for d in dates] for s in syms if s in rets]
    cs = [c for i in range(len(cols)) for j in range(i + 1, len(cols)) if (c := _corr(cols[i], cols[j])) is not None]
    return sum(cs) / len(cs) if cs else None


def phase(driver_z: float | None, spread_z: float | None) -> str:
    if spread_z is None:
        return "データ不足"
    if driver_z is None:
        return "③ 織り込み進行（スプレッドのみで判定）" if spread_z >= 1.5 else "① 初動前／様子見（ドライバー未設定）"
    if driver_z <= -1:
        return "事実が逆行（テーマ前提を再確認）"
    if driver_z >= 1 and spread_z < 0.5:
        return "②→③ エントリーゾーン（未波及）"
    if driver_z >= 1 and spread_z >= 1.5:
        return "③ 織り込み進行（遅い）"
    if spread_z >= 1.5:
        return "バスケット先行（ドライバーなし）— 要確認"
    return "① 初動前／様子見"


def analyze(theme: dict[str, Any], bars: dict[str, list[dict[str, Any]]], driver: dict[str, float] | None = None,
            lookback: int = 500) -> dict[str, Any]:
    """bars: daily bars for every member + hedge; driver: {date: level} (already built from the spec)."""
    rets = {s: daily_returns(b) for s, b in bars.items() if b}
    longs = [m for m in theme.get("longs") or [] if m.get("symbol")]
    shorts = [m for m in theme.get("shorts") or [] if m.get("symbol")]
    hedge = theme.get("hedge") or "TVC:TOPIX"
    short_side = shorts if shorts else ([{"symbol": hedge}] if hedge in rets else [])
    present = [m["symbol"] for m in longs + short_side if m["symbol"] in rets]
    missing = [m["symbol"] for m in longs + short_side if m["symbol"] not in rets]
    if not longs or not any(m["symbol"] in rets for m in longs):
        return {"error": "ロング側の価格データがない", "missing": missing}
    dates = sorted({d for s in present for d in rets[s]})[-lookback:]
    L = basket(longs, rets, dates)
    S = basket(short_side, rets, dates) if short_side else [0.0] * len(dates)
    spread = [a - b for a, b in zip(L, S)]
    # beta-neutral spread: L − (β_L / β_S)·S with betas vs the hedge index (if the short side IS the index, β_S = 1)
    hseq = [rets[hedge].get(d, 0.0) for d in dates] if hedge in rets else None
    bl = _beta(L[-252:], hseq[-252:]) if hseq else None
    bs = _beta(S[-252:], hseq[-252:]) if hseq and short_side else None
    hedge_ratio = (bl / bs) if bl is not None and bs not in (None, 0) else 1.0
    spread_bn = [a - hedge_ratio * b for a, b in zip(L, S)]

    def cum(x: list[float]) -> list[float]:
        out, v = [], 100.0
        for r in x:
            v *= math.exp(r)
            out.append(v)
        return out

    nav, nav_bn, navL, navS = cum(spread), cum(spread_bn), cum(L), cum(S)
    peak, mdd = -1e18, 0.0
    for v in nav_bn:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    perf = {k: (math.exp(sum(spread_bn[-n:])) - 1) * 100 for k, n in (("1W", 5), ("1M", 21), ("3M", 63), ("6M", 126)) if len(spread_bn) >= n}
    spread_z = zlast(spread_bn, 20)
    # driver
    drv: dict[str, Any] = {"z": None, "lead": None}
    if driver:
        kind = theme.get("driver_kind") or "price"
        dd = sorted(driver)
        ch: dict[str, float] = {}
        for a, b in zip(dd, dd[1:]):
            va, vb = driver[a], driver[b]
            ch[b] = (vb - va) * 100 if kind == "yield" else (math.log(vb / va) if va > 0 and vb > 0 else 0.0)
        sign = 1 if (theme.get("driver_dir") or 1) >= 0 else -1
        ser = [sign * ch[d] for d in sorted(ch)]
        drv["z"] = zlast(ser, 20)
        common = [d for d in dates if d in ch]
        if len(common) >= 60:
            cc = cross_correlation([sign * ch[d] for d in common], [spread_bn[dates.index(d)] for d in common], 20)
            drv["lead"] = cc.get("best_lead")
            drv["significant"] = cc.get("significant")
        drv["last"] = driver[dd[-1]] if dd else None
    # basket flow: average pairwise correlation of the long members
    lsyms = [m["symbol"] for m in longs if m["symbol"] in rets]
    flow = {"avg_corr": None, "pctl": None, "dominant": False}
    if len(lsyms) >= 2 and len(dates) >= 120:
        hist = []
        for end in range(len(dates), max(60, len(dates) - 252) - 1, -5):
            c = avg_pairwise_corr(rets, lsyms, dates[end - 60:end])
            if c is not None:
                hist.append(c)
        if hist:
            cur = hist[0]
            flow = {"avg_corr": cur, "pctl": sum(1 for v in hist if v <= cur) / len(hist) * 100,
                    "dominant": cur >= 0.5 and sum(1 for v in hist if v <= cur) / len(hist) >= 0.8}
    # members
    members = []
    for side, ms in (("L", longs), ("S", shorts)):
        for mbr in ms:
            s = mbr["symbol"]
            r = rets.get(s)
            if not r:
                members.append({"symbol": s, "side": side, "error": "no data"})
                continue
            seq = [r.get(d, 0.0) for d in dates]
            bvol = [float(b.get("volume") or 0) for b in bars[s]]
            v20 = [sum(bvol[i - 20:i]) / 20 for i in range(20, len(bvol) + 1)][-252:]
            members.append({"symbol": s, "side": side, "weight": mbr.get("weight") or 1.0,
                            "ret_1m": (math.exp(sum(seq[-21:])) - 1) * 100, "ret_3m": (math.exp(sum(seq[-63:])) - 1) * 100,
                            "corr_to_basket": _corr(seq[-120:], (L if side == "L" else S)[-120:]),
                            "activity_pctl": (sum(1 for v in v20 if v <= v20[-1]) / len(v20) * 100) if v20 else None})
    r1m = [m["ret_1m"] for m in members if "ret_1m" in m and m["side"] == "L"]
    act = [m["activity_pctl"] for m in members if m.get("activity_pctl") is not None]
    ph = phase(drv["z"], spread_z)
    flags = []
    if flow["dominant"]:
        flags.append("バスケット買いが支配（銘柄間の相関が高い）→ 個別の L/S は効きにくい（限界④ / B-1）")
    if act and sum(act) / len(act) >= 85:
        flags.append("構成銘柄の売買が過去1年の上位 15%（混雑の可能性）")
    if missing:
        flags.append(f"価格データなし: {', '.join(missing[:6])}")
    return {
        "name": theme.get("name"), "phase": ph, "spread_z": spread_z, "driver": drv, "perf_bn_pct": perf,
        "max_dd_bn_pct": mdd * 100, "hedge_ratio": hedge_ratio, "short_side": [m["symbol"] for m in short_side],
        "flow": flow, "dispersion_1m_pct": _sd(r1m) if len(r1m) >= 2 else None,
        "crowding_pctl": sum(act) / len(act) if act else None, "members": members, "flags": flags,
        "series": {"dates": dates[-260:], "spread": nav[-260:], "spread_bn": nav_bn[-260:], "long": navL[-260:], "short": navS[-260:]},
    }
