"""Trinity framework endpoints (TRIN / SCORE / KELLY / RULE / PAIR / SHRT / GATE). Logic lives in framework.py."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import framework as F
from . import quant
from .api_analysis import _fx_to_base, _many
from .state import S

router = APIRouter(prefix="/api/framework")

SCAN_COLS = ["description", "currency", "close", "market_cap_basic", "sector", "industry", "beta_1_year",
             "price_earnings_ttm", "enterprise_value_ebitda_ttm", "dividend_yield_recent",
             "float_shares_outstanding", "total_shares_outstanding", "total_revenue_yoy_growth_ttm",
             "operating_margin", "free_cash_flow", "average_volume_30d_calc"]
SCAN_FALLBACK = ["description", "currency", "close", "market_cap_basic", "sector", "industry"]


def bench_for(symbol: str) -> str:
    ex = symbol.split(":")[0].upper() if ":" in symbol else ""
    return {"TSE": "TVC:TOPIX", "OSE": "TVC:TOPIX", "NAG": "TVC:TOPIX", "HKEX": "TVC:HSI", "KRX": "TVC:KOSPI",
            "TWSE": "TVC:TAIEX", "SSE": "SSE:000300", "SZSE": "SSE:000300"}.get(ex, "SP:SPX")


async def _scan(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], str | None]:
    try:
        return await S.web.scan_symbols(symbols, SCAN_COLS, SCAN_FALLBACK), None
    except Exception as e:  # noqa: BLE001 - fundamentals are optional enrichment
        return {}, str(e)


@router.get("/meta")
async def meta():
    return {"score_factors": F.SCORE_FACTORS, "score_text_blocks": F.SCORE_TEXT_BLOCKS,
            "weights_placeholder": True,
            "weights_note": "Notionには『配点あり・合計100』とあるが各Weightの数値は未記載 → 初期値はプレースホルダー。自分の配点に書き換えて保存",
            "thresholds": {"long": F.LONG_THRESHOLD, "short": F.SHORT_THRESHOLD}, "limits": F.LIMITS,
            "short_types": F.SHORT_TYPES, "gates": F.GATES, "quarterly": F.QUARTERLY, "arbitration": F.ARBITRATION,
            "sector_suitability": F.SECTOR_SUITABILITY, "spread_classes": F.SPREAD_CLASSES}


# ---- 評点表 ----------------------------------------------------------------
@router.post("/score/evaluate")
async def score_evaluate(sheet: dict[str, Any]):
    return F.score_sheet(sheet)


def _cards() -> dict[str, list[dict[str, Any]]]:
    return S.store.get("scorecards") or {}


@router.get("/scorecards")
async def scorecards():
    rows = []
    for sym, hist in _cards().items():
        if not hist:
            continue
        last = hist[-1]
        r = last.get("result") or {}
        prev = hist[-2]["result"].get("total") if len(hist) > 1 else None
        rows.append({"symbol": sym, "version": last["version"], "saved_at": last["saved_at"], "total": r.get("total"),
                     "ai_total": r.get("ai_total"), "previous_total": prev, "direction": r.get("direction"),
                     "moat": (r.get("moat") or {}).get("score"), "subsector": last["sheet"].get("subsector"),
                     "sector": last["sheet"].get("sector"), "issues": len(r.get("issues") or [])})
    rows.sort(key=lambda x: -(x["total"] or 0))
    return {"rows": rows, "thresholds": {"long": F.LONG_THRESHOLD, "short": F.SHORT_THRESHOLD}}


@router.get("/scorecards/{symbol}")
async def scorecard(symbol: str):
    hist = _cards().get(symbol) or []
    return {"symbol": symbol, "versions": [{k: v for k, v in h.items() if k != "sheet"} | {"total": h["result"].get("total")}
                                           for h in hist],
            "latest": hist[-1] if hist else None}


@router.post("/scorecards/{symbol}")
async def save_scorecard(symbol: str, sheet: dict[str, Any]):
    cards = _cards()
    hist = cards.get(symbol) or []
    rows = sheet.get("rows") or [dict(r) for r in F.SCORE_FACTORS]
    if hist:  # Previous Score = the score saved last time (unless the user typed one)
        prev = {r.get("id"): r.get("score") for r in hist[-1]["sheet"].get("rows", [])}
        for r in rows:
            if r.get("prev_score") in (None, "") and prev.get(r.get("id")) not in (None, ""):
                r["prev_score"] = prev[r.get("id")]
    sheet = {**sheet, "rows": rows, "symbol": symbol}
    result = F.score_sheet(sheet)
    hist.append({"version": len(hist) + 1, "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
                 "note": sheet.get("note", ""), "sheet": sheet, "result": result})
    cards[symbol] = hist[-50:]
    S.store.set("scorecards", cards)
    return {"version": len(hist), "result": result}


@router.delete("/scorecards/{symbol}")
async def delete_scorecard(symbol: str):
    cards = _cards()
    cards.pop(symbol, None)
    S.store.set("scorecards", cards)
    return {"ok": True}


class GapReq(BaseModel):
    long_score: float
    short_score: float
    cap: float = 2.0


@router.post("/score_gap")
async def score_gap(req: GapReq):
    return F.score_gap_size(req.long_score, req.short_score, req.cap)


@router.get("/pairs_from_scores")
async def pairs_from_scores():
    """Within each subsector: best LONG × worst SHORT by Total Score → 評点差 → size (02.4)."""
    by_sub: dict[str, list[dict[str, Any]]] = {}
    for sym, hist in _cards().items():
        if hist and hist[-1]["result"].get("total") is not None:
            sub = hist[-1]["sheet"].get("subsector") or "(未分類)"
            by_sub.setdefault(sub, []).append({"symbol": sym, "total": hist[-1]["result"]["total"],
                                               "direction": hist[-1]["result"]["direction"]})
    out = []
    for sub, rows in sorted(by_sub.items()):
        rows.sort(key=lambda r: -r["total"])
        if len(rows) >= 2:
            lo, hi = rows[-1], rows[0]
            out.append({"subsector": sub, "long": hi, "short": lo, **F.score_gap_size(hi["total"], lo["total"])})
    return {"pairs": out}


# ---- Kelly ------------------------------------------------------------------
class KellyReq(BaseModel):
    pw: float = Field(..., ge=0, le=1)
    xw: float = Field(..., gt=0)
    xl: float = Field(..., gt=0)
    side: str = "long"
    ruin_prob: float = Field(0.0, ge=0, le=1)
    fraction: float = Field(0.5, gt=0, le=1)
    cap_pct: float | None = None


@router.post("/kelly")
async def kelly(req: KellyReq):
    try:
        return F.kelly(req.pw, req.xw, req.xl, req.side, req.ruin_prob, req.fraction, req.cap_pct)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ---- exposure book (六層) ----------------------------------------------------
@router.get("/book")
async def get_book():
    return S.store.get("fw_book")


@router.put("/book")
async def put_book(body: dict[str, Any]):
    book = {"positions": body.get("positions") or [], "level": body.get("level") or "book",
            "nav": body.get("nav"), "drawdown_pct": body.get("drawdown_pct")}
    S.store.set("fw_book", book)
    return book


class FromPortReq(BaseModel):
    nav: float = Field(..., gt=0)
    base_currency: str = "JPY"
    source: str | None = None


@router.post("/book/from_portfolio")
async def book_from_portfolio(req: FromPortReq):
    """Weights (% of NAV) from PORT positions × latest close × FX; metadata (sector/mcap/beta) from the scanner.
    Existing per-symbol metadata in the book (pair, subsector, short_type …) is kept."""
    port = [p for p in (S.store.get("portfolio") or []) if p.get("symbol") and p.get("qty")]
    if not port:
        raise HTTPException(400, "PORT has no positions")
    syms = sorted({p["symbol"] for p in port})
    series, errors = await _many(syms, "1D", 5, req.source)
    base = req.base_currency.upper()
    fx, fx_err = await _fx_to_base(syms, base, req.source)
    errors.update(fx_err)
    usd, _ = await _fx_to_base(syms, "USD", req.source)
    scan, scan_err = await _scan(syms)
    old = {p.get("symbol"): p for p in (S.store.get("fw_book") or {}).get("positions", [])}
    qty: dict[str, float] = {}
    for p in port:
        qty[p["symbol"]] = qty.get(p["symbol"], 0.0) + float(p["qty"])
    positions = []
    for s in syms:
        if s not in series or not series[s]:
            continue
        px = series[s][-1]["close"]
        rate = fx.get(quant.currency_of(s), 1.0 if quant.currency_of(s) == base else None)
        if rate is None:
            errors[s] = "FX unavailable"
            continue
        w = qty[s] * px * rate / req.nav * 100
        sc = scan.get(s) or {}
        mcap_local = sc.get("market_cap_basic")
        ur = usd.get(quant.currency_of(s), 1.0 if quant.currency_of(s) == "USD" else None)
        keep = old.get(s, {})
        positions.append({
            "symbol": s, "weight": round(w, 4), "sector": keep.get("sector") or sc.get("sector"),
            "subsector": keep.get("subsector") or sc.get("industry"), "pair": keep.get("pair"),
            "short_type": keep.get("short_type"), "expected_downside_pct": keep.get("expected_downside_pct"),
            "mcap_usd": (mcap_local * ur) if mcap_local and ur else keep.get("mcap_usd"),
            "beta": keep.get("beta") if keep.get("beta") is not None else sc.get("beta_1_year")})
    book = {**(S.store.get("fw_book") or {}), "positions": positions, "nav": req.nav}
    S.store.set("fw_book", book)
    return {"book": book, "errors": errors, "scan_error": scan_err}


class ExposureReq(BaseModel):
    positions: list[dict[str, Any]]
    level: str = "book"
    drawdown_pct: float | None = None
    compute_pairs: bool = True
    lookback: int = Field(260, ge=60, le=1500)
    source: str | None = None


@router.post("/exposure")
async def exposure(req: ExposureReq):
    pairs: dict[str, list[dict[str, Any]]] = {}
    for p in req.positions:
        if p.get("pair") and p.get("symbol") and p.get("weight"):
            pairs.setdefault(str(p["pair"]), []).append(p)
    stats: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    if req.compute_pairs and pairs:
        syms = sorted({p["symbol"] for legs in pairs.values() for p in legs})
        benches = sorted({bench_for(s) for s in syms})
        series, errors = await _many(syms + benches, "1D", req.lookback, req.source)
        closes = {s: quant.closes_by_date(b) for s, b in series.items()}
        for pid, legs in pairs.items():
            lg = [x for x in legs if float(x["weight"]) > 0]
            sh = [x for x in legs if float(x["weight"]) < 0]
            if not lg or not sh or lg[0]["symbol"] not in closes or sh[0]["symbol"] not in closes:
                continue
            b = bench_for(lg[0]["symbol"])
            try:
                m = F.pair_metrics(closes, lg[0]["symbol"], sh[0]["symbol"], float(lg[0]["weight"]), float(sh[0]["weight"]),
                                   b if b in closes else None)
            except ValueError as e:
                errors[f"pair {pid}"] = str(e)
                continue
            stats[pid] = {k: m.get(k) for k in ("pair_sigma_pct", "pair_correlation", "beta_net_gross",
                                                "spread_percentile_20d", "entry_blocked", "beta_long", "beta_short")}
            for x, bk in ((lg[0], "beta_long"), (sh[0], "beta_short")):
                if x.get("beta") in (None, "") and m.get(bk) is not None:
                    x["beta"] = m[bk]
    res = F.exposure_check(req.positions, req.level, req.drawdown_pct, stats)
    return {**res, "pair_stats": stats, "errors": errors}


# ---- pair ---------------------------------------------------------------------
class PairReq(BaseModel):
    long: str
    short: str
    w_long: float = 1.0
    w_short: float = -1.0
    bench: str | None = None
    earnings_dirs: list[list[int]] | None = None
    borrow_ok: bool | None = None
    spread_class: str | None = None
    lookback: int = Field(500, ge=80, le=3000)
    source: str | None = None


@router.post("/pair")
async def pair(req: PairReq):
    bench = req.bench or bench_for(req.long)
    series, errors = await _many([req.long, req.short, bench], "1D", req.lookback, req.source)
    if req.long not in series or req.short not in series:
        raise HTTPException(502, f"history unavailable: {errors}")
    closes = {s: quant.closes_by_date(b) for s, b in series.items()}
    try:
        m = F.pair_metrics(closes, req.long, req.short, req.w_long, -abs(req.w_short), bench if bench in closes else None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    suit = F.pair_suitability(m, req.earnings_dirs, req.borrow_ok, req.spread_class)
    return {"long": req.long, "short": req.short, "bench": bench, **m, **suit, "errors": errors}


# ---- short models -------------------------------------------------------------
class ShortReq(BaseModel):
    symbol: str | None = None
    inputs: dict[str, Any] = {}
    source: str | None = None


@router.post("/short_models")
async def short_models(req: ShortReq):
    """Evaluate the 8 short models. With ``symbol`` the price/volume/size fields are auto-filled
    (drawdown_from_high_pct, volume_trend, market_cap_usd, revenue_growth_pct, op_margin_pct, fcf_negative)
    unless the user already supplied them."""
    x = dict(req.inputs)
    auto: dict[str, Any] = {}
    if req.symbol:
        series, _ = await _many([req.symbol], "1D", 300, req.source)
        bars = series.get(req.symbol) or []
        if len(bars) >= 80:
            hi = max(b["high"] for b in bars[-252:])
            auto["drawdown_from_high_pct"] = (1 - bars[-1]["close"] / hi) * 100 if hi else None
            v20 = [b.get("volume") or 0 for b in bars[-20:]]
            v60 = [b.get("volume") or 0 for b in bars[-80:-20]]
            auto["volume_trend"] = (sum(v20) / 20) / (sum(v60) / 60) if sum(v60) else None
        scan, _ = await _scan([req.symbol])
        sc = scan.get(req.symbol) or {}
        if sc.get("market_cap_basic"):
            usd, _ = await _fx_to_base([req.symbol], "USD", req.source)
            r = usd.get(quant.currency_of(req.symbol), 1.0 if quant.currency_of(req.symbol) == "USD" else None)
            auto["market_cap_usd"] = sc["market_cap_basic"] * r if r else None
        if sc.get("total_revenue_yoy_growth_ttm") is not None:
            auto["revenue_growth_pct"] = sc["total_revenue_yoy_growth_ttm"]
        if sc.get("operating_margin") is not None:
            auto["op_margin_pct"] = sc["operating_margin"]
        if sc.get("free_cash_flow") is not None:
            auto["fcf_negative"] = sc["free_cash_flow"] < 0
        hist = _cards().get(req.symbol) or []
        if hist:
            auto["moat_qualifies"] = (hist[-1]["result"].get("moat") or {}).get("qualifies")
        for k, v in auto.items():
            if x.get(k) in (None, "") and v is not None:
                x[k] = v
    return {**F.short_models(x), "inputs": x, "auto": auto}


# ---- top / bottom & crowding ----------------------------------------------------
@router.get("/top_bottom/{symbol}")
async def top_bottom(symbol: str, scope: str = "stock", shares: float | None = None, source: str | None = None,
                     holding_value: float | None = None, inst_ownership_pct: float | None = None,
                     hot_daily_pct: float | None = None, hot_month_pct: float | None = None):
    """天井・底シグナル + 混雑度. Shares default to the scanner's float (else total) shares."""
    series, errors = await _many([symbol], "1D", 800, source)
    bars = series.get(symbol) or []
    scan, scan_err = await _scan([symbol])
    sc = scan.get(symbol) or {}
    sh = shares or sc.get("float_shares_outstanding") or sc.get("total_shares_outstanding")
    vols = [float(b.get("volume") or 0) for b in bars]
    margin = None
    code = symbol.split(":")[-1]
    if symbol.upper().startswith("TSE:"):
        from .api_research import mstore
        from .margin import stock_analysis
        ms = mstore().series(code)
        if ms:
            ma = stock_analysis(ms, bars)
            margin = {"ratio_percentile": ma.get("ratio_percentile"), "buy_days": ma.get("buy_days"),
                      "ratio": (ma.get("latest") or {}).get("ratio"), "date": (ma.get("latest") or {}).get("date")}
    rf_sym = "TVC:JP10Y" if symbol.upper().startswith(("TSE:", "OSE:")) else "TVC:US10Y"
    rf = None
    try:
        rb = await S.history(rf_sym, "1D", 5, source)
        rf = rb[-1]["close"] if rb else None
    except HTTPException as e:
        errors[rf_sym] = str(e.detail)
    res = F.top_bottom(F.turnover_series(vols, sh) if sh else None, margin, sc.get("dividend_yield_recent"), rf,
                       None, None, scope, hot_daily_pct, hot_month_pct)
    px = bars[-1]["close"] if bars else None
    adv_val = (sum(vols[-20:]) / 20 * px) if bars and px else None
    crowd = F.crowding(holding_value, adv_val, inst_ownership_pct)
    turnover = [{"time": b["time"], "v": v / sh * 100} for b, v in zip(bars[-260:], vols[-260:])] if sh else []
    return {"symbol": symbol, **res, "crowding": crowd, "shares": sh, "risk_free": {"symbol": rf_sym, "value": rf},
            "dividend_yield_pct": sc.get("dividend_yield_recent"), "margin": margin, "turnover": turnover,
            "adv_value": adv_val, "errors": errors, "scan_error": scan_err if not sc else None}


# ---- ideas & gates (05.6) -------------------------------------------------------
def _month() -> str:
    return dt.date.today().strftime("%Y-%m")


@router.get("/ideas")
async def ideas():
    items = S.store.get("fw_ideas") or []
    return {"month": _month(), "ideas": [{**i, "progress": F.gates_progress(i.get("answers") or {})} for i in items],
            "archive_months": sorted((S.store.get("fw_ideas_archive") or {}).keys())}


@router.post("/ideas")
async def save_idea(idea: dict[str, Any]):
    items = S.store.get("fw_ideas") or []
    idea = {"answers": {}, **idea}
    if not idea.get("id"):
        idea["id"] = uuid.uuid4().hex[:10]
        idea["created"] = dt.datetime.now().isoformat(timespec="seconds")
        idea["month"] = _month()
        items.append(idea)
    else:
        items = [idea if i.get("id") == idea["id"] else i for i in items]
    S.store.set("fw_ideas", items)
    return {**idea, "progress": F.gates_progress(idea.get("answers") or {})}


@router.delete("/ideas/{idea_id}")
async def delete_idea(idea_id: str):
    S.store.set("fw_ideas", [i for i in (S.store.get("fw_ideas") or []) if i.get("id") != idea_id])
    return {"ok": True}


@router.post("/ideas/monthly_reset")
async def monthly_reset():
    """毎月ゼロから作り直す: archive this month's ideas, keep titles/legs but clear every gate answer."""
    items = S.store.get("fw_ideas") or []
    arch = S.store.get("fw_ideas_archive") or {}
    key = _month()
    arch[key] = items
    S.store.set("fw_ideas_archive", arch)
    fresh = [{**{k: v for k, v in i.items() if k not in ("answers",)}, "answers": {}, "month": key} for i in items]
    S.store.set("fw_ideas", fresh)
    return {"archived": key, "ideas": len(fresh)}


@router.get("/ideas/archive/{month}")
async def idea_archive(month: str):
    return {"month": month, "ideas": (S.store.get("fw_ideas_archive") or {}).get(month, [])}


@router.post("/gates")
async def gates(answers: dict[str, Any]):
    return F.gates_progress(answers)


# ---- overview: one screen that reads the whole trinity for a symbol ------------------
@router.get("/overview/{symbol}")
async def overview(symbol: str, source: str | None = None):
    """Fundamental (latest score sheet) × Macro (growth/liquidity quadrant) × Quant (sizing hints) for one name."""
    from . import macro
    from .api_macro import _load

    hist = _cards().get(symbol) or []
    score = hist[-1]["result"] if hist else None
    syms = []
    for comps in macro.GL_INPUTS.values():
        for _, spec, _, _ in comps:
            syms += macro.symbols_in(spec)
    data, errs = await _load(list(dict.fromkeys(syms)), 1500, source)
    gl = macro.growth_liquidity(data)
    tb = None
    try:
        tb = await top_bottom(symbol, source=source)
    except HTTPException as e:
        errs[symbol] = str(e.detail)
    agree = []
    if score:
        agree.append({"phase": "ファンダメンタル", "view": score["direction"], "detail": f"Total {score['total']:.2f}" if score.get("total") else "未採点"})
    if gl and not gl.get("error"):
        agree.append({"phase": "マクロ", "view": gl["current"]["name"], "detail": f"優位: {gl['current']['assets']} → 次: {gl['next']['name']}"})
    if tb:
        agree.append({"phase": "需給", "view": tb["zone"], "detail": "; ".join(s["signal"] for s in tb["top"] + tb["bottom"] if s["on"]) or "シグナルなし"})
    return {"symbol": symbol, "score": score, "growth_liquidity": gl if not gl.get("error") else None,
            "top_bottom": tb, "phases": agree, "errors": errs,
            "rule": "三方向から同じ結論に着いたときだけ、確信度を上げてよい（第1部 01.6）"}
