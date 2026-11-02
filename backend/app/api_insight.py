"""Analysis expansion endpoints: XRAY (return decomposition / factor bets), RRG (sector rotation),
THEME (Theme Alpha baskets), PFND (pair finder), TRAK (track record with Bayesian hit rates)."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import macro, pairscreen, quant, rrg, themes, trackrecord, xray
from .api_analysis import _many
from .state import S

router = APIRouter(prefix="/api/insight")


async def _scan(symbols: list[str]) -> dict[str, dict[str, Any]]:
    try:
        return await S.web.scan_symbols(symbols, ["description", "sector", "industry", "market_cap_basic"],
                                        ["description", "sector", "industry"])
    except Exception:  # noqa: BLE001 - optional enrichment (SIM / offline)
        return {}


def factor_symbols(region: str) -> dict[str, tuple[str, str]]:
    return xray.FACTORS_JP if region == "JP" else xray.FACTORS_US


def xray_from_series(symbols: list[str], sectors: dict[str, str | None], series: dict[str, list[dict[str, Any]]],
                     lookback: int) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, float]], dict[str, str]]:
    """Decompose every symbol from already-loaded daily bars; returns (results, factor changes by name, errors)."""
    closes = {s: quant.closes_by_date(b) for s, b in series.items() if b}
    fchg: dict[str, dict[str, float]] = {}
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for s in symbols:
        if s not in closes:
            continue
        r = xray.region(s)
        mk = xray.MARKET[r]
        styles = {name: xray.changes(closes[sym], kind) for name, (sym, kind) in factor_symbols(r).items() if sym in closes}
        etf = sectors.get(s)
        sec = (etf, xray.changes(closes[etf])) if etf and etf in closes and etf != s else None
        mch = xray.changes(closes[mk]) if mk in closes else None
        try:
            results[s] = {**xray.decompose(xray.changes(closes[s]), (mk, mch) if mch else None, styles, sec, lookback),
                          "sector_etf": etf, "region": r}
        except ValueError as e:
            errors[s] = str(e)
            continue
        if mch:
            fchg[f"Market {mk}"] = mch
        fchg.update(styles)
        if sec:
            fchg[f"Sector {etf}"] = sec[1]
    return results, fchg, errors


def xray_symbols_needed(symbols: list[str], sectors: dict[str, str | None]) -> set[str]:
    need = set(symbols)
    for r in {xray.region(s) for s in symbols}:
        need.add(xray.MARKET[r])
        need |= {sym for sym, _ in factor_symbols(r).values()}
    return need | {e for e in sectors.values() if e}


async def xray_inputs(symbols: list[str], sectors: dict[str, str | None], lookback: int, source: str | None,
                      end_offset: int = 0) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, float]], dict[str, str]]:
    from .window import cut_series

    series, errors = await _many(sorted(xray_symbols_needed(symbols, sectors)), "1D", lookback + 40 + end_offset, source)
    series, _ = cut_series(series, end_offset, symbols[0] if symbols else None)
    res, fchg, err2 = xray_from_series(symbols, sectors, series, lookback)
    return res, fchg, {**errors, **err2}


# ---- XRAY ------------------------------------------------------------------------------------
@router.get("/xray")
async def xray_one(symbol: str, lookback: int = Query(252, ge=120, le=1000), sector_etf: str | None = None,
                   end_offset: int = Query(0, ge=0, le=1000), source: str | None = None):
    sc = (await _scan([symbol])).get(symbol) or {}
    from .api_coverage import coverage_meta
    from .coverage import TOPIX17_ETF
    cm = coverage_meta().get(symbol) or {}
    etf = sector_etf or TOPIX17_ETF.get(cm.get("topix17") or "") or xray.sector_etf(symbol, sc.get("sector"), sc.get("industry"))
    res, _, errors = await xray_inputs([symbol], {symbol: etf}, lookback, source, end_offset)
    if symbol not in res:
        raise HTTPException(502, errors.get(symbol) or f"history unavailable: {errors}")
    label = (xray.TOPIX17 | xray.US_SECTORS).get(etf or "", None)
    return {"symbol": symbol, "sector": sc.get("sector"), "industry": sc.get("industry"), "sector_label": label,
            **res[symbol], "errors": errors}


class BookReq(BaseModel):
    positions: list[dict[str, Any]] | None = None   # default: the RULE book (store.fw_book)
    lookback: int = 252
    end_offset: int = 0
    source: str | None = None


@router.post("/xray/book")
async def xray_book(req: BookReq):
    pos = req.positions if req.positions is not None else (S.store.get("fw_book") or {}).get("positions", [])
    pos = [p for p in pos if p.get("symbol") and p.get("weight")]
    if not pos:
        raise HTTPException(400, "no positions — RULE で IMPORT FROM PORT するか positions を渡す")
    syms = [p["symbol"] for p in pos]
    scan = await _scan(syms)
    sectors = {s: xray.sector_etf(s, (scan.get(s) or {}).get("sector") or next((p.get("sector") for p in pos if p["symbol"] == s), None),
                                  (scan.get(s) or {}).get("industry")) for s in syms}
    res, fchg, errors = await xray_inputs(syms, sectors, req.lookback, req.source, req.end_offset)
    out = xray.book(pos, res, fchg, req.lookback)
    out["by_symbol"] = [{"symbol": s, "weight": next(p["weight"] for p in pos if p["symbol"] == s), **res[s]["shares"],
                         "verdict": res[s]["verdict"]} for s in syms if s in res]
    return {**out, "errors": errors}


# ---- RRG -------------------------------------------------------------------------------------
RRG_SETS = {
    "JP17": {"bench": "TVC:TOPIX", "items": xray.TOPIX17},
    "US11": {"bench": "SP:SPX", "items": xray.US_SECTORS},
}


async def rrg_compute(universe: str, symbols: list[str] | None, bench: str | None, tail: int, source: str | None,
                      end_weeks: int = 0, n: int = 10) -> dict[str, Any]:
    if universe in RRG_SETS:
        cfg = RRG_SETS[universe]
        items, b = dict(cfg["items"]), bench or cfg["bench"]
    else:
        syms = symbols or []
        if universe == "COVER":
            from .api_trinity import config, universe as tuni
            syms = tuni(config())
        if not syms:
            raise HTTPException(400, "symbols required")
        items = {s: s for s in syms[:80]}
        b = bench or ("TVC:TOPIX" if all(xray.region(s) == "JP" for s in items) else "SP:SPX")
    from .window import cut_series

    series, errors = await _many(list(items) + [b], "1D", 800 + end_weeks * 5, source)
    if b not in series:
        raise HTTPException(502, f"benchmark {b} unavailable: {errors.get(b)}")
    series, cut = cut_series(series, end_weeks * 5, b)
    res = rrg.analyze({s: series[s] for s in items if s in series}, series[b], items, tail, n, n)
    res["asof"] = cut
    return {**res, "universe": universe, "bench": b, "errors": errors}


@router.get("/rrg")
async def rrg_endpoint(universe: str = "JP17", symbols: str | None = None, bench: str | None = None,
                       tail: int = Query(8, ge=2, le=26), end_weeks: int = Query(0, ge=0, le=156),
                       n: int = Query(10, ge=4, le=26), source: str | None = None):
    syms = [s.strip().upper() for s in (symbols or "").split(",") if s.strip()]
    return await rrg_compute(universe.upper(), syms, bench, tail, source, end_weeks, n)


# ---- THEME -----------------------------------------------------------------------------------
def _themes() -> list[dict[str, Any]]:
    return S.store.get("themes") or []


@router.get("/themes")
async def themes_list():
    return {"themes": _themes(), "templates": [t["name"] for t in themes.TEMPLATES], "template_note": themes.TEMPLATE_NOTE}


@router.post("/themes")
async def themes_save(theme: dict[str, Any]):
    items = _themes()
    if not (theme.get("name") or "").strip():
        raise HTTPException(400, "name required")
    if theme.get("id") and any(t["id"] == theme["id"] for t in items):
        items = [theme if t["id"] == theme["id"] else t for t in items]
    else:
        theme = {**theme, "id": uuid.uuid4().hex[:10], "created": dt.datetime.now().isoformat(timespec="seconds")}
        items.append(theme)
    S.store.set("themes", items)
    return theme


@router.post("/themes/from_template")
async def themes_from_template(body: dict[str, Any]):
    t = next((x for x in themes.TEMPLATES if x["name"] == body.get("name")), None)
    if not t:
        raise HTTPException(404, "unknown template")
    return await themes_save({**t, "template": True, "note": themes.TEMPLATE_NOTE})


@router.delete("/themes/{tid}")
async def themes_delete(tid: str):
    S.store.set("themes", [t for t in _themes() if t["id"] != tid])
    return {"ok": True}


async def theme_compute(theme: dict[str, Any], source: str | None, lookback: int = 500, end_offset: int = 0) -> dict[str, Any]:
    from .window import cut_series

    syms = [m["symbol"] for m in (theme.get("longs") or []) + (theme.get("shorts") or []) if m.get("symbol")]
    syms.append(theme.get("hedge") or "TVC:TOPIX")
    dsyms = macro.symbols_in(theme["driver"]) if theme.get("driver") else []
    series, errors = await _many(list(dict.fromkeys(syms + dsyms)), "1D", 1100 + end_offset, source)
    series, cut = cut_series(series, end_offset, theme.get("hedge") or "TVC:TOPIX")
    driver = None
    if dsyms:
        data = macro.closes_from_bars({s: series[s] for s in dsyms if s in series})
        driver = macro.build(theme["driver"], data) or None
    res = themes.analyze(theme, {s: series[s] for s in syms if s in series}, driver, lookback)
    return {**res, "id": theme.get("id"), "errors": errors, "asof": cut}


@router.get("/themes/{tid}/analyze")
async def themes_analyze(tid: str, source: str | None = None, lookback: int = Query(500, ge=120, le=1500),
                         end_offset: int = Query(0, ge=0, le=1000)):
    t = next((x for x in _themes() if x["id"] == tid), None)
    if not t:
        raise HTTPException(404, "theme not found")
    return await theme_compute(t, source, lookback, end_offset)


# ---- PFND ------------------------------------------------------------------------------------
class PairScreenReq(BaseModel):
    groups: dict[str, list[str]] | None = None   # default: AUTO universe grouped by subsector / industry
    by: str = "subsector"                         # subsector (SCORE sheet, else scanner industry) | industry | sector
    max_per_group: int = 25
    lookback: int = 252
    end_offset: int = 0
    source: str | None = None


@router.post("/pairs/screen")
async def pairs_screen(req: PairScreenReq):
    from .api_trinity import _scorecard_summary, config, tdir, _read
    from .api_trinity import universe as tuni

    snap = _read(tdir() / "latest.json") or {}
    scores: dict[str, float] = {r["symbol"]: r["f"]["score"] for r in snap.get("rows", []) if r.get("f", {}).get("score") is not None}
    scores.update({s: v["total"] for s, v in _scorecard_summary().items() if v.get("total") is not None})
    groups = req.groups
    if not groups:
        syms = tuni(config())
        scan = await _scan(syms)
        cards = S.store.get("scorecards") or {}
        from .api_coverage import coverage_meta
        cmeta = coverage_meta()
        groups = {}
        for s in syms:
            sub = None
            if req.by == "subsector" and cards.get(s):
                sub = cards[s][-1]["sheet"].get("subsector")
            if req.by == "subsector" and not sub:
                sub = (cmeta.get(s) or {}).get("gics_sub")  # GICS 産業サブグループ from the Notion 銘柄マスタ
            sc = scan.get(s) or {}
            key = sub or (sc.get("sector") if req.by == "sector" else sc.get("industry")) or None
            if key:
                groups.setdefault(f"{xray.region(s)} · {key}", []).append(s)
        if not groups:
            raise HTTPException(400, "グループを作れない（業種が取得できない）— groups を指定するか、SCORE にサブセクターを保存")
    syms = sorted({s for v in groups.values() for s in v})
    benches = sorted({xray.MARKET[xray.region(s)] for s in syms})
    from .window import cut_series

    series, errors = await _many(syms + benches, "1D", req.lookback + 50 + req.end_offset, req.source)
    series, cut = cut_series(series, req.end_offset, benches[0] if benches else None)
    series = {k: v[-(req.lookback + 30):] for k, v in series.items()}
    closes = {s: quant.closes_by_date(b) for s, b in series.items() if b}
    rets = {s: xray.changes(c) for s, c in closes.items()}
    bench_of = {s: rets.get(xray.MARKET[xray.region(s)]) for s in syms}
    res = pairscreen.screen(groups, {s: rets[s] for s in syms if s in rets}, closes, bench_of, scores, req.max_per_group)
    return {**res, "errors": errors, "scored": len(scores), "asof": cut}


# ---- TRAK ------------------------------------------------------------------------------------
@router.get("/track")
async def track(a0: float = Query(1.0, gt=0), b0: float = Query(1.0, gt=0)):
    return trackrecord.analyze(S.store.get("trades") or [], a0, b0)
