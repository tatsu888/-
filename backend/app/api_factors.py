"""Factor library (macro side) and per-stock page / attribution endpoints."""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from . import factorlib as FL
from . import quant
from .api_analysis import _many
from .state import DATA_DIR, S

router = APIRouter(prefix="/api")
SCAN_COLS = ["market_cap_basic", "price_book_ratio", "price_earnings_ttm", "dividend_yield_recent", "return_on_equity"]


def lib_path() -> Path:
    p = DATA_DIR / "factors"
    p.mkdir(parents=True, exist_ok=True)
    return p / "library.json"


def read_lib() -> dict[str, Any] | None:
    try:
        return json.loads(lib_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_from(series: dict[str, list[dict[str, Any]]], scan: dict[str, dict[str, Any]], market_bars: list[dict[str, Any]],
               source: str | None) -> dict[str, Any]:
    """Build and persist the style-factor library from already-loaded daily bars (used by the AUTO run)."""
    t0 = time.time()
    closes = {s: quant.closes_by_date(b) for s, b in series.items() if b and s.upper().startswith("TSE:")}
    market = FL.changes(quant.closes_by_date(market_bars)) if market_bars else {}
    style = FL.style_returns(closes, market, scan) if market else {}
    lib = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "source": source or S.registry.active_name,
           "universe": len(closes), "style": style, "seconds": round(time.time() - t0, 1),
           "note": "スタイル・ファクター = カバレッジの三分位ロング・ショート（21日ごとにリバランス）。サイズ・バリュー・クオリティは現在のスキャナー値（先読みを含む）。"}
    lib_path().write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    return lib


async def market_factors(source: str | None, bars: int = 800) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    syms = [sym for sym, _ in FL.MACRO.values()]
    series, errors = await _many(syms, "1D", bars, source)
    out = {}
    for name, (sym, kind) in FL.MACRO.items():
        if series.get(sym):
            out[name] = FL.changes(quant.closes_by_date(series[sym]), kind)
    return out, errors


@router.post("/factors/build")
async def factors_build(source: str | None = None):
    """Build the style-factor library now from the AUTO universe (normally done by every AUTO run)."""
    from .api_trinity import config, universe

    syms = [s for s in universe(config()) if s.upper().startswith("TSE:")]
    if len(syms) < 15:
        raise HTTPException(400, f"ユニバースが小さすぎる（{len(syms)} 銘柄、15 以上必要）— COV で Notion のカバレッジを同期")
    series, errors = await _many(syms + ["TVC:TOPIX"], "1D", 800, source)
    try:
        scan = await S.web.scan_symbols(syms, SCAN_COLS, SCAN_COLS[:1])
    except Exception as e:  # noqa: BLE001
        scan, errors["scanner"] = {}, str(e)
    lib = build_from({s: series[s] for s in syms if s in series}, scan, series.get("TVC:TOPIX") or [], source)
    return {"universe": lib["universe"], "factors": len(lib["style"]), "seconds": lib["seconds"], "errors": errors}


@router.get("/factors/library")
async def factors_library(source: str | None = None, end_offset: int = Query(0, ge=0, le=1000)):
    """Which factors are strong: style (from the library), macro and TOPIX-17 sector factors."""
    from .xray import TOPIX17

    lib = read_lib() or {}
    macro, errors = await market_factors(source)
    sect_series, err2 = await _many(list(TOPIX17), "1D", 800, source)
    errors.update(err2)
    mkt = macro.get(FL.MARKET) or {}
    cut = None
    if end_offset and mkt:
        ds = sorted(mkt)
        cut = ds[-1 - min(end_offset, len(ds) - 1)]

    def clip(s: dict[str, float]) -> dict[str, float]:
        return {d: v for d, v in s.items() if not cut or d <= cut}

    rows = []
    for k, label in FL.STYLES:
        s = (lib.get("style") or {}).get(k)
        if s:
            rows.append({"group": "スタイル", "factor": label, **FL.performance(clip(s))})
    for name, s in macro.items():
        rows.append({"group": "マクロ", "factor": name, **FL.performance(clip(s))})
    for sym, label in TOPIX17.items():
        b = sect_series.get(sym)
        if b and mkt:
            ex = {d: r - mkt[d] for d, r in FL.changes(quant.closes_by_date(b)).items() if d in mkt}
            rows.append({"group": "セクター", "factor": f"{label}（{sym.split(':')[1]}）", **FL.performance(clip(ex))})
    return {"rows": rows, "library": {k: lib.get(k) for k in ("generated_at", "universe", "source", "note")},
            "asof": cut, "errors": errors}


@router.get("/factors/attribution/{symbol}")
async def attribution(symbol: str, window: int = Query(21, ge=5, le=252), est: int = Query(252, ge=60, le=750),
                      end_offset: int = Query(0, ge=0, le=750), source: str | None = None):
    from .api_coverage import coverage_meta
    from .coverage import TOPIX17_ETF
    from .xray import sector_etf

    bars_needed = window + est + end_offset + 40
    macro, errors = await market_factors(source, bars_needed)
    meta = coverage_meta().get(symbol) or {}
    etf = TOPIX17_ETF.get(meta.get("topix17") or "")
    if not etf:
        try:
            sc = (await S.web.scan_symbols([symbol], ["sector", "industry"], ["sector"])).get(symbol) or {}
        except Exception:  # noqa: BLE001
            sc = {}
        etf = sector_etf(symbol, sc.get("sector"), sc.get("industry"))
    syms = [symbol] + ([etf] if etf else [])
    series, err2 = await _many(syms, "1D", bars_needed, source)
    errors.update(err2)
    if symbol not in series:
        raise HTTPException(502, f"history unavailable: {errors.get(symbol)}")
    stock = FL.changes(quant.closes_by_date(series[symbol]))
    factors: dict[str, dict[str, float]] = {}
    mkt = macro.get(FL.MARKET)
    if mkt:
        factors[FL.MARKET] = mkt
    if etf and series.get(etf) and mkt:
        factors[f"セクター {etf.split(':')[1]}"] = {d: r - mkt[d] for d, r in FL.changes(quant.closes_by_date(series[etf])).items() if d in mkt}
    lib = read_lib() or {}
    if symbol.upper().startswith("TSE:"):
        labels = dict(FL.STYLES)
        for k in FL.ATTR_STYLES:
            s = (lib.get("style") or {}).get(k)
            if s:
                factors[f"スタイル:{labels[k]}"] = s
    for k in FL.ATTR_MACRO:
        if macro.get(k):
            factors[k] = macro[k]
    try:
        res = FL.attribute(stock, factors, window, est, end_offset)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"symbol": symbol, "sector_etf": etf, **res, "style_library": lib.get("generated_at"), "errors": errors}


# ---- per-stock page ------------------------------------------------------------------------------
@router.get("/stock/{symbol}/page")
async def stock_page(symbol: str, source: str | None = None):
    """Everything about one stock in one call (sections fail independently)."""
    from .analytics import performance
    from .api_coverage import _open_path, coverage_meta, markers, root_dir, state  # noqa: F401
    from .api_research import mstore
    from .margin import stock_analysis

    errors: dict[str, str] = {}
    cov = state()
    meta = coverage_meta().get(symbol)
    out: dict[str, Any] = {"symbol": symbol, "coverage": meta, "page": (cov["pages"].get(meta["ticker"]) if meta else None)}
    series, err = await _many([symbol], "1D", 800, source)
    errors.update(err)
    bars = series.get(symbol) or []
    if bars:
        out["perf"] = performance(bars)
        out["chart"] = [{"time": b["time"], "value": b["close"]} for b in bars[-260:]]
    # files: folder, Excel, reports
    folder = markers(root_dir(cov)).get(meta["ticker"]) if meta else None
    out["folder"] = str(folder) if folder else None
    out["excel"] = [{"id": f["id"], "name": f["name"], "link": f["link"]} for f in S.excel.match_symbol(symbol, S.store.get("excel_links") or {})][:20]
    out["reports"] = sorted((p.name for p in (folder / "reports").glob("*.md")), reverse=True)[:20] if folder and (folder / "reports").is_dir() else []
    # 信用残 (JPX weekly) — a per-stock analysis, shown on the stock page
    if symbol.upper().startswith("TSE:"):
        ms = mstore().series(symbol.split(":")[1])
        if ms:
            ma = stock_analysis(ms, bars)
            out["margin"] = {k: ma.get(k) for k in ("latest", "ratio_percentile", "weeks", "buy_days", "sell_days", "adv20", "ratio_change_vs_fwd4w")}
            out["margin"]["rows"] = ma.get("rows", [])[-104:]
        else:
            out["margin"] = None
    # supply/demand, Trinity
    try:
        from .api_framework import top_bottom
        tb = await top_bottom(symbol, source=source)
        out["chip"] = {k: tb.get(k) for k in ("zone", "top", "bottom", "crowding", "turnover_percentile", "dividend_yield_pct")}
    except Exception as e:  # noqa: BLE001
        errors["chip"] = str(e)
    try:
        from .api_trinity import _read, tdir
        snap = _read(tdir() / "latest.json") or {}
        rows = {r["symbol"]: r for r in snap.get("rows", [])}
        out["auto"] = rows.get(symbol)
        out["auto_at"] = snap.get("generated_at")
        if meta and meta.get("gics_sub"):
            out["peers"] = [{"symbol": m["symbol"], "ticker": m["ticker"], "name": m.get("name"),
                             "direction": (rows.get(m["symbol"]) or {}).get("direction"), "conviction": (rows.get(m["symbol"]) or {}).get("conviction"),
                             "f": ((rows.get(m["symbol"]) or {}).get("f") or {}).get("score"),
                             "mom_3m": ((rows.get(m["symbol"]) or {}).get("l") or {}).get("mom_3m_pct")}
                            for m in coverage_meta().values() if m.get("gics_sub") == meta["gics_sub"] and m["symbol"] != symbol][:20]
    except Exception as e:  # noqa: BLE001
        errors["auto"] = str(e)
    cards = (S.store.get("scorecards") or {}).get(symbol) or []
    if cards:
        r = cards[-1]["result"]
        out["score"] = {"total": r.get("total"), "direction": r.get("direction"), "prev_total": r.get("prev_total"),
                        "moat": (r.get("moat") or {}).get("score"), "saved_at": cards[-1].get("saved_at")}
    out["themes"] = [t["name"] for t in (S.store.get("themes") or []) if any(m.get("symbol") == symbol for m in (t.get("longs") or []) + (t.get("shorts") or []))]
    txs = (S.store.get("transcripts") or {}).get(symbol) or []
    if txs:
        from . import transcripts as TX
        cur = txs[-1]
        a = TX.analyze(cur["text"], txs[-2]["text"] if len(txs) > 1 else None)
        out["transcript"] = {"period": cur["period"], "net_tone": a["tone"]["net_tone"],
                             "change_score": (a.get("diff") or {}).get("change_score"), "evasiveness": a.get("evasiveness_avg"),
                             "periods": [t["period"] for t in txs]}
    out["errors"] = errors
    return out


@router.get("/stock/{symbol}/report_file")
async def stock_report_file(symbol: str, name: str):
    from .api_coverage import markers, root_dir, state

    meta = (state()["items"] and next((x for x in state()["items"] if x["symbol"] == symbol), None))
    folder = markers(root_dir()).get(meta["ticker"]) if meta else None
    p = (folder / "reports" / name) if folder else None
    if not p or p.parent.resolve() != (folder / "reports").resolve() or not p.is_file():
        raise HTTPException(404, "report not found")
    return {"name": name, "markdown": p.read_text(encoding="utf-8")}


# ---- FLOW: global money flows (asset class / country / sector / style) -------------------------------------
def shares_path() -> Path:
    p = DATA_DIR / "flows"
    p.mkdir(parents=True, exist_ok=True)
    return p / "shares.json"


def read_shares() -> dict[str, dict[str, float]]:
    try:
        return json.loads(shares_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def all_flow_symbols() -> list[str]:
    from . import flows as FW

    syms: list[str] = []
    for k, cfg in FW.LENSES.items():
        syms += list(FW.lens_items(k)) + [cfg["bench"]]
    return list(dict.fromkeys(syms))


@router.post("/flows/record")
async def flows_record():
    """Record today's ETF shares outstanding (true creations/redemptions accumulate day by day). Also run by AUTO."""
    syms = [s for s in all_flow_symbols() if not s.startswith("TVC:")]
    try:
        scan = await S.web.scan_symbols(syms, ["total_shares_outstanding", "close"], ["close"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"scanner unavailable: {e}") from e
    today = dt.date.today().isoformat()
    hist = read_shares()
    hist[today] = {s: v["total_shares_outstanding"] for s, v in scan.items() if v.get("total_shares_outstanding")}
    hist = {d: hist[d] for d in sorted(hist)[-400:]}
    shares_path().write_text(json.dumps(hist), encoding="utf-8")
    return {"date": today, "recorded": len(hist[today]), "days": len(hist)}


@router.get("/flows")
async def flows(lens: str = "ASSET", window: int = Query(21, ge=5, le=126), end_offset: int = Query(0, ge=0, le=750),
                source: str | None = None):
    from . import flows as FW
    from .window import cut_series

    lens = lens.upper()
    if lens not in FW.LENSES:
        raise HTTPException(400, f"lens must be one of {list(FW.LENSES)}")
    items = FW.lens_items(lens)
    bench = FW.LENSES[lens]["bench"]
    # summary needs the asset / US sector / US style symbols as well
    extra = list(FW.LENSES["ASSET"]["items"]) + FW.CYCLICAL_US + FW.DEFENSIVE_US + ["AMEX:IWF", "AMEX:IWD", "AMEX:SPHB", "AMEX:SPLV"]
    syms = list(dict.fromkeys(list(items) + [bench, "NASDAQ:ACWI", "AMEX:SPY"] + extra))
    series, errors = await _many(syms, "1D", 300 + end_offset, source)
    series, cut = cut_series(series, end_offset, bench)
    shares = read_shares()
    rows = []
    allm: dict[str, dict[str, Any]] = {}
    for s in syms:
        m = FW.metrics(series.get(s) or [], series.get(bench if s in items else ("NASDAQ:ACWI" if s in FW.LENSES["ASSET"]["items"] else "AMEX:SPY")), window)
        if m:
            allm[s] = m
    for s, label in items.items():
        m = allm.get(s)
        if not m:
            rows.append({"symbol": s, "label": label, "error": errors.get(s, "履歴不足")})
            continue
        rows.append({"symbol": s, "label": label, **m, "creations": FW.creations(shares, s, m["last"], cut)})
    rows.sort(key=lambda r: -(r.get("flow_score") if r.get("flow_score") is not None else -9))
    return {"lens": lens, "label": FW.LENSES[lens]["label"], "bench": bench, "window": window, "asof": cut, "rows": rows,
            "summary": FW.summarize(allm), "lenses": {k: v["label"] for k, v in FW.LENSES.items()},
            "shares_days": len(shares), "errors": errors,
            "note": "ETF の価格・出来高による資金フローの代理（EPFR 等の実フローではない）。設定・解約は発行済口数の日次記録から（記録日数が増えると表示）。"}
