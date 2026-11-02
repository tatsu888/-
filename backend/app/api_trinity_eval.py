"""/api/trinity/align · /check · /eval — the Trinity as an analysis tool (trinity_eval.py; docs/FRAMEWORK.md §12)."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import framework as F
from . import macro, quant
from . import trinity_auto as T
from . import trinity_eval as E
from .api_analysis import _fx_to_base, _many
from . import api_trinity as AT
from .state import S

router = APIRouter(prefix="/api/trinity")
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _market_of(symbol: str) -> str:
    return "TVC:TOPIX" if symbol.upper().startswith(("TSE:", "OSE:", "NAG:", "FSE:")) else "SP:SPX"


def _prev_snapshot(latest: dict[str, Any] | None) -> dict[str, Any] | None:
    """The last daily snapshot from before the latest one's day."""
    d0 = ((latest or {}).get("generated_at") or "")[:10]
    prev = [f for f in sorted((AT.tdir() / "history").glob("*.json")) if f.stem < d0]
    return AT._read(prev[-1]) if prev else None


@router.get("/align")
async def align_ep():
    latest = AT._read(AT.tdir() / "latest.json")
    res = E.align(latest, _prev_snapshot(latest))
    if res.get("error"):
        raise HTTPException(404, res["error"])
    return res


class CheckReq(BaseModel):
    symbol: str
    side: str = "LONG"
    weight: float = Field(..., gt=0, le=100)
    pair_with: str | None = None
    short_type: str | None = None
    expected_downside_pct: float | None = None
    pw: float | None = None
    xw: float | None = None
    xl: float | None = None
    source: str | None = None


async def _mini_row(sym: str, latest: dict[str, Any], source: str | None, errors: dict[str, str]) -> dict[str, Any] | None:
    """AUTO's rules for one symbol outside the universe (F from a saved score sheet only: the rule score needs peers)."""
    series, err = await _many([sym], "1D", 800, source)
    errors.update(err)
    bars = series.get(sym) or []
    if not bars:
        return None
    try:
        scan = (await S.web.scan_symbols([sym], AT.SCAN_COLS, AT.SCAN_FALLBACK)).get(sym) or {}
    except Exception as e:  # noqa: BLE001 - fundamentals optional
        scan, errors["scanner"] = {}, str(e)
    gl = {"current": latest.get("quadrant"), "next": latest.get("next_quadrant")} if latest.get("quadrant") else None
    row = T.evaluate({sym: {"bars": bars, "scan": scan, "margin": None, "risk_free": None, "mcap_usd": None}}, gl,
                     AT._scorecard_summary())["rows"][0]
    return {**row, "mini": True}


@router.post("/check")
async def check_ep(req: CheckReq):
    sym = req.symbol.strip().upper()
    side = req.side.upper()
    if side not in ("LONG", "SHORT") or ":" not in sym:
        raise HTTPException(400, "symbol は TSE:6857 の形、side は LONG か SHORT")
    pw = req.pair_with.strip().upper() if req.pair_with else None
    if pw and ":" not in pw:
        raise HTTPException(400, "ペアの相手も TSE:8035 の形で")
    errors: dict[str, str] = {}
    latest = AT._read(AT.tdir() / "latest.json") or {}
    row = next((r for r in latest.get("rows", []) if r["symbol"] == sym), None)
    if row is None:
        row = await _mini_row(sym, latest, req.source, errors)
    book = (S.store.get("fw_book") or {}).get("positions") or []
    known = {p.get("symbol"): p for p in book}
    try:
        scan = await S.web.scan_symbols([sym] + ([pw] if pw else []), ["sector", "industry", "market_cap_basic", "beta_1_year"], ["sector"])
    except Exception as e:  # noqa: BLE001
        scan, errors["scanner"] = {}, str(e)
    usd, _ = await _fx_to_base([sym] + ([pw] if pw else []), "USD", req.source)

    def meta(s: str) -> dict[str, Any]:
        k, sc = known.get(s) or {}, scan.get(s) or {}
        mc = sc.get("market_cap_basic")
        own = (row or {}).get("sector") if s == sym else None
        return {"sector": k.get("sector") or sc.get("sector") or own,
                "subsector": k.get("subsector") or sc.get("industry"),
                "mcap_usd": k.get("mcap_usd") or (mc * usd[s] if mc and usd.get(s) else None),
                "beta": k.get("beta") if k.get("beta") is not None else sc.get("beta_1_year")}

    m = meta(sym)
    trade = {"symbol": sym, "side": side, "weight": req.weight, "pair_with": pw, "short_type": req.short_type,
             "expected_downside_pct": req.expected_downside_pct, **m}
    pair = None
    if pw:
        pm = meta(pw)
        trade.update(pair_sector=pm["sector"], pair_subsector=pm["subsector"], pair_beta=pm["beta"])
        bench = _market_of(sym)
        series, err = await _many([sym, pw, bench], "1D", 300, req.source)
        errors.update(err)
        closes = {s: quant.closes_by_date(b) for s, b in series.items() if b}
        long_s, short_s = (sym, pw) if side == "LONG" else (pw, sym)
        try:
            full = F.pair_metrics(closes, long_s, short_s, 1.0, -1.0, bench if bench in closes else None)
            pair = {k: full.get(k) for k in ("pair_sigma_pct", "pair_correlation", "beta_net_gross", "entry_blocked", "spread_percentile_20d", "days")}
        except (ValueError, KeyError) as e:
            pair = {"error": str(e)}
    kelly = None
    if req.pw is not None and req.xw is not None and req.xl is not None:
        try:
            kelly = F.kelly(req.pw, req.xw, req.xl, side.lower())
        except ValueError as e:
            raise HTTPException(400, f"ケリーの入力: {e}") from e
    res = E.check_trade(trade, row, AT._scorecard_summary().get(sym), book, pair, kelly)
    return {**res, "pair": pair, "kelly": {k: kelly[k] for k in ("e", "f_pct", "recommended_pct")} if kelly else None,
            "auto_row": {k: (row or {}).get(k) for k in ("direction", "conviction", "size_pct", "mini")} if row else None,
            "meta": m, "snapshot_at": latest.get("generated_at"), "errors": errors}


@router.get("/eval")
async def eval_ep(parts: str = "auto,m,l", horizons: str = "5,21,63", source: str | None = None, refresh: bool = False):
    hs = tuple(sorted({int(x) for x in horizons.split(",") if x.strip().isdigit() and 1 <= int(x) <= 252})) or (21,)
    want = {p.strip() for p in parts.split(",")}
    key = f"{sorted(want)}|{hs}|{source}|{dt.date.today()}"
    hit = _cache.get(key)
    if hit and not refresh and time.time() - hit[0] < 3600:
        return hit[1]
    out: dict[str, Any] = {"source": source or S.registry.active_name, "horizons": list(hs), "errors": {}}
    if "auto" in want:
        files = sorted((AT.tdir() / "history").glob("*.json"))
        history = [(f.stem, snap) for f in files if (snap := AT._read(f))]
        syms = sorted({r["symbol"] for _, s in history for r in s.get("rows", []) if r.get("direction") in ("LONG", "SHORT")})[:200]
        if history and syms:
            days = (dt.date.today() - dt.date.fromisoformat(history[0][0])).days
            bars = min(2000, int(days * 5 / 7) + max(hs) + 60)
            mks = sorted({_market_of(s) for s in syms})
            series, err = await _many(syms + mks, "1D", bars, source)
            out["errors"].update(err)
            closes = {s: quant.closes_by_date(b) for s, b in series.items() if b}
            out["auto"] = await asyncio.to_thread(E.grade_auto, history, {s: closes[s] for s in syms if s in closes},
                                                  {s: _market_of(s) for s in syms}, {m: closes[m] for m in mks if m in closes}, hs)
        else:
            out["auto"] = {"snapshots": len(history), "horizons": {}, "note": "AUTO の履歴（方向のある判定）がまだない"}
    long_h = tuple(h for h in hs if h >= 21) or (21,)
    if "m" in want:
        gsyms: list[str] = []
        for comps in macro.GL_INPUTS.values():
            for _, spec, _, _ in comps:
                gsyms += macro.symbols_in(spec)
        gser, gerr = await _many(list(dict.fromkeys(gsyms)), "1D", 1500, source)
        out["errors"].update(gerr)
        gl = macro.growth_liquidity(macro.closes_from_bars(gser), trail=10 ** 6)
        sser, serr = await _many(list(E.TOPIX17_BUCKET) + ["TVC:TOPIX"], "1D", 1500, source)
        out["errors"].update(serr)
        if gl.get("error") or not sser.get("TVC:TOPIX"):
            out["m"] = {"error": gl.get("error") or "TOPIX が取れない"}
        else:
            sc = {s: quant.closes_by_date(b) for s, b in sser.items() if b and s != "TVC:TOPIX"}
            out["m"] = await asyncio.to_thread(E.backtest_m, gl["trail"], sc, quant.closes_by_date(sser["TVC:TOPIX"]), 21, long_h)
            out["m"]["from"], out["m"]["to"] = gl["trail"][0]["date"], gl["trail"][-1]["date"]
    if "l" in want:
        syms = [s for s in AT.universe(AT.config())][:80]
        if syms:
            mks = sorted({_market_of(s) for s in syms})
            series, err = await _many(syms + mks, "1D", 1500, source)
            out["errors"].update(err)
            markets = {m: quant.closes_by_date(series[m]) for m in mks if series.get(m)}
            out["l"] = await asyncio.to_thread(E.backtest_l, {s: series[s] for s in syms if series.get(s)},
                                               {s: _market_of(s) for s in syms}, markets, 21, long_h)
            out["l"]["universe"] = len(syms)
        else:
            out["l"] = {"error": "AUTO のユニバースが空 — TRIN の UNIVERSE"}
    out["notes"] = [
        "F（ファンダメンタル）は過去の時点で再現できない（スキャナーの値は今日のもの）— AUTO の判定の答え合わせ（auto）でだけ評価する",
        "需給の過去検証は出来高・高値からの距離・混雑だけ（浮動株・信用残・配当利回りの過去の値は使わない）",
        "超過リターン = 銘柄の対数リターン − 市場（日本株は TOPIX、ほかは S&P 500）。方向（ショートは符号を逆）を掛けた値で勝ち負けを数える",
        "SIM のデータでは関係のない乱数なので、数値に意味はない（DEMO）",
    ]
    _cache[key] = (time.time(), out)
    return out
