"""AUTO Trinity: scheduled, rule-based 三位一体 run over the coverage universe (trinity_auto.py).

Universe = watchlists + saved SCORE sheets + PORT positions (+ extra − exclude), equities only.
Runs at startup and every ``interval_min`` minutes; snapshots are kept in <data>/trinity/:
    latest.json, history/YYYY-MM-DD.json (last run of each day), changes.json (last 500 changes)
Changes (verdict / conviction / quadrant) are pushed to browsers as {"type": "trinity", ...}.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from . import macro, quant
from . import trinity_auto as T
from .api_analysis import _fx_to_base, _many
from .state import DATA_DIR, S
from .universe import UNIVERSE

log = logging.getLogger("trinity")
router = APIRouter(prefix="/api/trinity")

SCAN_COLS = ["description", "currency", "market_cap_basic", "sector", "industry", "beta_1_year",
             "price_earnings_ttm", "enterprise_value_ebitda_ttm", "dividend_yield_recent", "return_on_equity",
             "gross_margin", "operating_margin", "debt_to_equity", "total_revenue_yoy_growth_ttm", "free_cash_flow",
             "float_shares_outstanding", "total_shares_outstanding"]
SCAN_FALLBACK = ["description", "currency", "market_cap_basic", "sector", "industry", "beta_1_year",
                 "price_earnings_ttm", "dividend_yield_recent", "return_on_equity", "gross_margin", "operating_margin",
                 "debt_to_equity"]
NON_EQUITY = ("FX:", "FX_IDC:", "OANDA:", "TVC:", "SP:", "DJ:", "COMEX:", "NYMEX:", "CME:", "CBOT:", "BINANCE:",
              "COINBASE:", "BITSTAMP:", "KRAKEN:", "BYBIT:", "CME_MINI:")
_lock = asyncio.Lock()
_state: dict[str, Any] = {"running": False, "last_run": None, "next_run": None, "last_error": None}


def tdir() -> Path:
    d = DATA_DIR / "trinity"
    (d / "history").mkdir(parents=True, exist_ok=True)
    return d


def _read(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p: Path, obj: Any) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(p)


def config() -> dict[str, Any]:
    return {**(S.store.get("trinity_config") or {})}


def universe(cfg: dict[str, Any]) -> list[str]:
    syms: list[str] = []
    src = set(cfg.get("sources") or [])
    if "watchlists" in src:
        wl = S.store.get("watchlists") or {}
        if wl:
            for v in wl.values():
                syms += list(v or [])
        else:
            syms += [x["symbol"] for x in UNIVERSE.get("W", [])]
    if "scorecards" in src:
        syms += list((S.store.get("scorecards") or {}).keys())
    if "portfolio" in src:
        syms += [p["symbol"] for p in (S.store.get("portfolio") or []) if p.get("symbol")]
    syms += list(cfg.get("extra") or [])
    ex = set(cfg.get("exclude") or [])
    out = [s for s in dict.fromkeys(x.strip().upper() for x in syms if x) if s not in ex and not s.startswith(NON_EQUITY)]
    return out[: int(cfg.get("max_symbols") or 150)]


def _scorecard_summary() -> dict[str, dict[str, Any]]:
    out = {}
    for sym, hist in (S.store.get("scorecards") or {}).items():
        if hist:
            r = hist[-1]["result"]
            out[sym] = {"total": r.get("total"), "direction": r.get("direction"),
                        "moat_qualifies": (r.get("moat") or {}).get("qualifies")}
    return out


async def run_once(source: str | None = None) -> dict[str, Any]:
    async with _lock:
        _state["running"] = True
        t0 = time.time()
        try:
            cfg = config()
            syms = universe(cfg)
            errors: dict[str, str] = {}
            series, err = await _many(syms, "1D", 800, source)
            errors.update(err)
            try:
                scan = await S.web.scan_symbols(syms, SCAN_COLS, SCAN_FALLBACK) if syms else {}
            except Exception as e:  # noqa: BLE001 - fundamentals optional (SIM / offline)
                scan, errors["scanner"] = {}, str(e)
            usd, _ = await _fx_to_base(syms, "USD", source)
            # macro quadrant
            gsyms: list[str] = []
            for comps in macro.GL_INPUTS.values():
                for _, spec, _, _ in comps:
                    gsyms += macro.symbols_in(spec)
            gser, gerr = await _many(list(dict.fromkeys(gsyms)), "1D", 1500, source)
            gl = macro.growth_liquidity(macro.closes_from_bars(gser))
            if gl.get("error"):
                errors["macro"] = gl["error"]
            # JPX margin + risk-free
            from .api_research import mstore
            from .margin import stock_analysis
            rf: dict[str, float | None] = {}
            for rs in ("TVC:JP10Y", "TVC:US10Y"):
                try:
                    b = await S.history(rs, "1D", 5, source)
                    rf[rs] = b[-1]["close"] if b else None
                except HTTPException:
                    rf[rs] = None
            inputs: dict[str, dict[str, Any]] = {}
            for s in syms:
                bars = series.get(s) or []
                sc = scan.get(s) or {}
                margin = None
                if s.startswith("TSE:"):
                    ms = mstore().series(s.split(":")[1])
                    if ms:
                        ma = stock_analysis(ms, bars)
                        margin = {"ratio_percentile": ma.get("ratio_percentile"), "buy_days": ma.get("buy_days")}
                ccy = quant.currency_of(s)
                r = usd.get(ccy, 1.0 if ccy == "USD" else None)
                mc = sc.get("market_cap_basic")
                inputs[s] = {"bars": bars, "scan": sc, "margin": margin,
                             "risk_free": rf.get("TVC:JP10Y" if s.startswith(("TSE:", "OSE:")) else "TVC:US10Y"),
                             "mcap_usd": mc * r if mc and r else None}
            snap = T.evaluate(inputs, gl if not gl.get("error") else None, _scorecard_summary())
            snap.pop("rules", None)
            snap.update({"generated_at": T.now_iso(), "source": source or S.registry.active_name, "universe": len(syms),
                         "errors": errors, "seconds": round(time.time() - t0, 1)})
            d = tdir()
            prev = _read(d / "latest.json")
            changes = T.diff(prev, snap)
            snap["changes"] = changes
            _write(d / "latest.json", snap)
            _write(d / "history" / f"{snap['generated_at'][:10]}.json", snap)
            log_ = _read(d / "changes.json") or []
            log_ = (log_ + [{**c, "at": snap["generated_at"]} for c in changes])[-500:]
            _write(d / "changes.json", log_)
            _state.update(last_run=snap["generated_at"], last_error=None)
            if changes and S.hub:
                await S.hub.broadcast({"type": "trinity", "changes": changes[:20], "at": snap["generated_at"]})
            return snap
        except Exception as e:
            _state["last_error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            _state["running"] = False


async def loop(first_delay: float = 20.0) -> None:
    await asyncio.sleep(first_delay)
    while True:
        cfg = config()
        interval = max(5, int(cfg.get("interval_min") or 60)) * 60
        if cfg.get("enabled", True):
            try:
                await run_once()
            except Exception as e:  # noqa: BLE001
                log.warning("auto trinity run failed: %s", e)
        _state["next_run"] = T.dt.datetime.fromtimestamp(time.time() + interval).isoformat(timespec="seconds")
        await asyncio.sleep(interval)


@router.get("/latest")
async def latest():
    snap = _read(tdir() / "latest.json")
    return {"snapshot": snap, "status": _state, "config": config()}


@router.post("/run")
async def run(source: str | None = None):
    if _lock.locked():
        raise HTTPException(409, "a run is already in progress")
    return await run_once(source)


@router.get("/config")
async def get_config():
    return {"config": config(), "universe": universe(config())}


@router.put("/config")
async def put_config(body: dict[str, Any]):
    cfg = {**config(), **{k: v for k, v in body.items() if k in ("enabled", "interval_min", "extra", "exclude", "max_symbols", "sources")}}
    S.store.set("trinity_config", cfg)
    return {"config": cfg, "universe": universe(cfg)}


@router.get("/history/{symbol}")
async def history(symbol: str, days: int = 120):
    files = sorted((tdir() / "history").glob("*.json"))[-days:]
    out = []
    for f in files:
        snap = _read(f) or {}
        r = next((x for x in snap.get("rows", []) if x["symbol"] == symbol), None)
        if r:
            out.append({"date": f.stem, "direction": r["direction"], "conviction": r["conviction"],
                        "f_score": r["f"]["score"], "m": r["m"]["view"], "l": r["l"]["view"], "size_pct": r["size_pct"]})
    return {"symbol": symbol, "history": out}


@router.get("/changes")
async def changes(limit: int = 100):
    return {"changes": (_read(tdir() / "changes.json") or [])[-limit:][::-1]}
