"""/api/fexp — FEXP: factor analysis of a security, a basket or the book (the maths is in fexpmodel.py).

Target: a symbol (TSE:6857, NASDAQ:AAPL, an ETF or an index), a basket "TSE:6857,TSE:8035" (equal weight) or PORT (the
current holdings, value-weighted in yen). Factor data are market series from the active provider (TradingView / Yahoo /
SIM, labelled DEMO) and the coverage style library (AUTO).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import fexpmodel as FM
from . import quant
from .api_analysis import _fx_series, _fx_to_base, _many
from .state import S

router = APIRouter(prefix="/api/fexp")
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
TTL = 900.0
COMP_KEYS = {
    "JP": [("mkt", "市場β"), ("sector", "セクター"), ("fx.usdjpy", "ドル円"), ("rate.jp10", "日10年"), ("rate.us10", "米10年"),
           ("cmd.oil", "原油"), ("cmd.copper", "銅"), ("os.sox", "SOX"), ("os.china", "中国"), ("sty.size", "サイズ"),
           ("sty.value", "バリュー"), ("sty.mom_6m", "モメンタム"), ("sty.volatility", "ボラ")],
    "US": [("mkt", "市場β"), ("sector", "セクター"), ("fx.dxy", "ドル指数"), ("rate.us10", "米10年"), ("cmd.oil", "原油"),
           ("cmd.copper", "銅"), ("sty.mtum", "モメンタム"), ("sty.vlue", "バリュー"), ("sty.qual", "クオリティ"),
           ("sty.usmv", "低ボラ"), ("sty.iwm", "小型")],
}


def comp_keys(region: str, available: set[str]) -> list[tuple[str, str]]:
    ks = [k for k in COMP_KEYS[region] if not k[0].startswith("sty.") or k[0] in available]
    if region == "JP" and sum(1 for k in ks if k[0].startswith("sty.")) < 2:      # no style library yet → the style ETFs
        ks += [("sty.etf.2516", "小型G"), ("sty.etf.1489", "高配当")]
    return ks


def _put(key: str, value: dict[str, Any]) -> None:
    now = time.time()
    for k in [k for k, (t, _) in _cache.items() if now - t > TTL]:
        _cache.pop(k, None)
    while len(_cache) >= 40:
        _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
    _cache[key] = (now, value)


def _get(key: str) -> dict[str, Any] | None:
    hit = _cache.get(key)
    return hit[1] if hit and time.time() - hit[0] <= TTL else None


def region_of(symbol: str) -> str:
    from .xray import region
    return region(symbol)


def parse_target(target: str) -> tuple[str, list[str]]:
    """("single" | "basket" | "port", symbols)."""
    t = (target or "").strip()
    if not t:
        raise HTTPException(400, "銘柄を指定する（例: TSE:6857、PORT、TSE:6857,TSE:8035）")
    if t.upper() == "PORT":
        return "port", []
    toks = [x.strip().upper() for x in t.replace(" ", ",").split(",") if x.strip()]
    out = []
    for x in toks:
        if ":" in x:
            out.append(x)
        elif len(x) == 4 and x[0].isdigit():
            out.append(f"TSE:{x}")
        else:
            raise HTTPException(400, f"{x}: 取引所つきで指定する（例: TSE:6857、NASDAQ:AAPL）")
    return ("basket" if len(out) > 1 else "single"), list(dict.fromkeys(out))


async def _sector_id(symbol: str, region: str) -> str | None:
    from .api_coverage import coverage_meta
    from .coverage import TOPIX17_ETF
    from .xray import sector_etf

    etf = TOPIX17_ETF.get((coverage_meta().get(symbol) or {}).get("topix17") or "") if region == "JP" else None
    if not etf:
        try:
            sc = (await S.web.scan_symbols([symbol], ["sector", "industry"], ["sector"])).get(symbol) or {}
        except Exception:  # noqa: BLE001 - the model runs without a sector
            sc = {}
        etf = sector_etf(symbol, sc.get("sector"), sc.get("industry"))
    if not etf or etf == symbol:
        return None
    return f"sec.{etf.split(':')[1]}"


def _library() -> dict[str, dict[str, float]]:
    from .api_factors import read_lib
    return (read_lib() or {}).get("style") or {}


async def _target_returns(kind: str, syms: list[str], bars: int, source: str | None
                          ) -> tuple[dict[str, float], dict[str, float], str, dict[str, str]]:
    """(daily returns, weights, region, errors). A basket is equal weight; PORT is value-weighted in yen (returns in yen)."""
    errors: dict[str, str] = {}
    if kind == "port":
        pos = [p for p in (S.store.get("portfolio") or []) if p.get("symbol") and float(p.get("qty") or 0)]
        if not pos:
            raise HTTPException(400, "PORT に保有がない")
        syms = list(dict.fromkeys(p["symbol"] for p in pos))
    series, err = await _many(syms, "1D", bars, source)
    errors.update(err)
    if kind == "single":
        if syms[0] not in series:
            raise HTTPException(502, f"価格が取れない: {errors.get(syms[0])}")
        return FM.changes(quant.closes_by_date(series[syms[0]])), {syms[0]: 1.0}, region_of(syms[0]), errors
    have = [s for s in syms if series.get(s)]
    if not have:
        raise HTTPException(502, f"価格が取れない: {errors}")
    if kind == "basket":
        w = {s: 1 / len(have) for s in have}
        jp = sum(1 for s in have if region_of(s) == "JP")
        ccy = {quant.currency_of(s) for s in have}
        if len(ccy) == 1:
            rets = {s: FM.changes(quant.closes_by_date(series[s])) for s in have}
            return FM.weighted_returns(rets, w), w, "JP" if jp * 2 >= len(have) else "US", errors
    else:
        last = {s: series[s][-1]["close"] for s in have}
        fx, fx_err = await _fx_to_base(have, "JPY", source)
        errors.update(fx_err)
        val = {s: float(next(p["qty"] for p in pos if p["symbol"] == s)) * last[s] * fx.get(s, 1.0) for s in have}
        gross = sum(abs(v) for v in val.values()) or 1.0
        w = {s: v / gross for s, v in val.items()}
    fxs = await _fx_series(have, "JPY", bars, source)
    rets = {}
    for s in have:
        c = quant.closes_by_date(series[s])
        if s in fxs:
            c = {d: v * fxs[s][d] for d, v in c.items() if d in fxs[s]}
        rets[s] = FM.changes(c)
    jp_w = sum(abs(v) for s, v in w.items() if region_of(s) == "JP")
    return FM.weighted_returns(rets, w), w, "JP" if jp_w >= 0.5 * sum(abs(v) for v in w.values()) else "US", errors


async def _factor_series(cat: list[dict[str, Any]], bars: int, source: str | None
                         ) -> tuple[dict[str, dict[str, float]], dict[str, str], bool]:
    series, errors = await _many(FM.symbols_of(cat), "1D", bars, source)
    closes = {s: quant.closes_by_date(b) for s, b in series.items() if b}
    mkt_f = next(f for f in cat if f["id"] == "mkt")
    mkt = FM.factor_series(mkt_f, closes, {}, {})
    lib = _library() if any(f["kind"] == "lib" for f in cat) else {}
    out = {f["id"]: FM.factor_series(f, closes, mkt, lib) for f in cat}
    return {k: v for k, v in out.items() if v}, errors, bool(lib)


@router.get("")
async def fexp(target: str, est: int = Query(504, ge=120, le=750), window: int = Query(21, ge=5, le=252),
               roll: int = Query(126, ge=60, le=504), end_offset: int = Query(0, ge=0, le=750),
               factors: str | None = None, roll_factors: str | None = None, source: str | None = None):
    kind, syms = parse_target(target)
    bars = max(est + window, 760) + end_offset + 40
    y, weights, region, errors = await _target_returns(kind, syms, bars, source)
    cat = FM.catalog(region)
    sers, err2, has_lib = await _factor_series(cat, bars, source)
    errors.update(err2)
    sector_id = await _sector_id(syms[0], region) if kind == "single" else None
    defaults = FM.default_ids(region, sector_id if sector_id in sers else None, set(sers))
    ids = [i for i in (factors or "").split(",") if i] or defaults
    unknown = [i for i in ids if i not in {f["id"] for f in cat}]
    if unknown:
        raise HTTPException(400, f"知らない要因: {', '.join(unknown)}")
    rids = [i for i in (roll_factors or "").split(",") if i] or None
    try:
        res = await asyncio.to_thread(FM.analyze, y, cat, sers, ids, region, est, window, roll, rids, end_offset)
    except (ValueError, ZeroDivisionError) as e:
        raise HTTPException(400, str(e)) from e
    key = hashlib.sha1(json.dumps([target, est, end_offset, ids, source], ensure_ascii=False).encode()).hexdigest()[:16]
    _put(key, res["model"])
    out = {k: v for k, v in res.items() if k != "model"}
    return {"target": target, "kind": kind, "symbols": syms or list(weights), "weights": weights, "region": region,
            "sector_id": sector_id, "ids": ids, "default_ids": defaults, "has_library": has_lib, "key": key,
            "catalog": [{"id": f["id"], "label": f["label"], "group": f["group"], "kind": f["kind"], "late": f["late"] and region == "JP",
                         "available": f["id"] in sers, "in_model": f["id"] in ids} for f in cat],
            "source": source or S.registry.active_name, **out, "errors": errors}


class ScenarioReq(BaseModel):
    key: str
    shocks: dict[str, float]


@router.post("/scenario")
async def scenario_ep(req: ScenarioReq):
    model = _get(req.key)
    if not model:
        raise HTTPException(409, "モデルの保存期限が切れた — FEXP を表示し直す")
    return FM.scenario(model, req.shocks)


@router.get("/coverage")
async def coverage_ep(est: int = Query(504, ge=120, le=750), end_offset: int = Query(0, ge=0, le=750),
                      source: str | None = None, limit: int = Query(60, ge=1, le=120)):
    """Exposures of every coverage stock side by side (the main model with the default factors of its region)."""
    from .api_coverage import state as cov_state
    from .coverage import TOPIX17_ETF

    items = [x for x in cov_state()["items"] if x.get("symbol")][:limit]
    if not items:
        raise HTTPException(400, "カバレッジが空 — COV で Notion の銘柄マスタを同期")
    ck = json.dumps(["cov", est, end_offset, source, [x["symbol"] for x in items]])
    hit = _get(ck)
    if hit:
        return hit
    bars = max(est + 21, 560) + end_offset + 40
    syms = [x["symbol"] for x in items]
    series, errors = await _many(syms, "1D", bars, source)
    regions = sorted({region_of(s) for s in syms})
    fac: dict[str, tuple[list[dict[str, Any]], dict[str, dict[str, float]], bool]] = {}
    for r in regions:
        cat = FM.catalog(r)
        sers, err, has_lib = await _factor_series(cat, bars, source)
        errors.update(err)
        fac[r] = (cat, sers, has_lib)
    try:
        scan = await S.web.scan_symbols([s for s in syms if not TOPIX17_ETF.get(next((x.get("topix17") for x in items if x["symbol"] == s), "") or "")],
                                        ["sector", "industry"], ["sector"])
    except Exception:  # noqa: BLE001
        scan = {}
    from .xray import sector_etf

    def one(it: dict[str, Any]) -> dict[str, Any]:
        s = it["symbol"]
        base = {"symbol": s, "ticker": it.get("ticker"), "name": it.get("name"), "region": region_of(s)}
        if s not in series:
            return {**base, "error": errors.get(s) or "価格が取れない"}
        r = base["region"]
        cat, sers, has_lib = fac[r]
        etf = TOPIX17_ETF.get(it.get("topix17") or "") or sector_etf(s, (scan.get(s) or {}).get("sector"), (scan.get(s) or {}).get("industry"))
        sid = f"sec.{etf.split(':')[1]}" if etf and etf != s and f"sec.{etf.split(':')[1]}" in sers else None
        ids = FM.default_ids(r, sid, set(sers))
        try:
            res = FM.analyze(FM.changes(quant.closes_by_date(series[s])), cat, sers, ids, r, est, 21, 126, None, end_offset,
                             maps=False, rolling=False)
        except (ValueError, ZeroDivisionError) as e:
            return {**base, "error": str(e)}
        keys = [k for k, _ in comp_keys(r, set(sers))]
        a = res.get("attribution") or {}
        return {**base, **FM.summary_row(res, keys), "sector_id": sid,
                "att_1m": {"total_pct": a.get("total_pct"), "specific_pct": a.get("specific_pct")} if "total_pct" in a else None}

    rows = await asyncio.to_thread(lambda: [one(it) for it in items])
    out = {"rows": rows, "columns": {r: [{"key": k, "label": lbl} for k, lbl in comp_keys(r, set(fac[r][1]))] for r in regions},
           "est": est, "has_library": {r: fac[r][2] for r in regions}, "source": source or S.registry.active_name,
           "errors": {k: v for k, v in errors.items() if k not in syms}}
    _put(ck, out)
    return out
