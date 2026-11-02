"""BRIEF API — the morning brief (brief.py), saved to <coverage root>/_terminal/briefs/YYYY-MM-DD.json and .md
(the .md is for reading in Explorer / OneDrive; the .json feeds the BRIEF screen).

Generated automatically by the AUTO Trinity run once a day, on the first run at or after ``brief_config.time``
(default 07:30), and on demand (POST /api/brief/generate). Reads only — it never writes to the earnings calendar.
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import brief as B
from .state import S

router = APIRouter(prefix="/api/brief")


def bdir() -> Path:
    from .api_coverage import root_dir
    return root_dir() / "_terminal" / "briefs"


def config() -> dict[str, Any]:
    return {"auto": True, "time": "07:30", **(S.store.get("brief_config") or {})}


async def _bars(symbol: str | None, n: int, source: str | None) -> list[dict[str, Any]] | None:
    if not symbol:
        return None
    try:
        return await S.history(symbol, "1D", n, source)
    except HTTPException:
        return None


def _previous_day_snapshot(today: dt.date) -> dict[str, Any] | None:
    from .api_trinity import _read, tdir

    days = sorted(p for p in (tdir() / "history").glob("*.json") if p.stem < today.isoformat())
    return _read(days[-1]) if days else None


async def gather(source: str | None = None, today: dt.date | None = None) -> dict[str, Any]:
    from . import api_earnings as AE
    from . import factorlib as FL
    from . import trinity_auto as T
    from .api_analysis import _fx_to_base
    from .api_coverage import state as cov_state
    from .api_factors import read_lib
    from .api_research import mstore
    from .api_trinity import _read, tdir

    today = today or dt.date.today()
    provider = (await S.provider(source)).name
    cov = cov_state()
    # markets
    mk = await asyncio.gather(*(_bars(sym, 40, source) for _, sym, _ in B.MARKETS))
    markets = [B.market_row(label, sym, kind, bars) for (label, sym, kind), bars in zip(B.MARKETS, mk)]
    # style factors (factor library)
    lib = read_lib() or {}
    frows = []
    for k, label in FL.STYLES:
        s = (lib.get("style") or {}).get(k)
        if s:
            frows.append({"factor": label, **FL.performance(s)})
    factors = B.factor_section(frows)
    # Trinity AUTO: changes since the previous day
    latest = _read(tdir() / "latest.json")
    prev = _previous_day_snapshot(today)
    changes = T.diff(prev, latest) if latest and prev else (latest or {}).get("changes") or []
    auto = B.auto_section(latest, changes)
    auto_by_ticker = {r["symbol"].split(":")[-1]: r for r in (latest or {}).get("rows", [])}
    # earnings (calendar) + the reactions of the last few days (computed on a copy — nothing is written)
    c = AE.load()
    rows = AE.window_rows(c, back=4, ahead=7, today=today)
    typical = {t: comp.get("reaction") or {} for t, comp in c["companies"].items()}
    sym_of = {x["ticker"]: x["symbol"] for x in cov["items"]}
    reactions: dict[str, dict[str, Any]] = {}
    cc, cache = copy.deepcopy(c), {}
    for r in [x for x in rows if x["days"] < 0]:
        bars = await _bars(sym_of.get(r["ticker"]), 120, source)
        if not bars:
            continue
        res = AE.reactions_from_bars(cc, r["ticker"], bars, await AE._market_bars(sym_of[r["ticker"]], source, cache), "brief")
        hit = next((x for x in res["rows"] if x["id"] == r["id"] and x.get("r1") is not None), None)
        if hit:
            reactions[r["ticker"]] = hit
    earnings = B.earnings_section(rows, reactions, typical, auto_by_ticker)
    # portfolio earnings risk (values in JPY)
    positions = [p for p in (S.store.get("portfolio") or []) if p.get("symbol")]
    syms = list(dict.fromkeys(p["symbol"] for p in positions))
    fx = (await _fx_to_base(syms, "JPY", source))[0] if syms else {}
    last = dict(zip(syms, await asyncio.gather(*(_bars(s, 5, source) for s in syms))))
    values: dict[str, float] = {}
    for p in positions:
        b = last.get(p["symbol"])
        if b:
            values[p["symbol"]] = values.get(p["symbol"], 0.0) + float(p.get("qty") or 0) * b[-1]["close"] * fx.get(p["symbol"], 1.0)
    upcoming = {}
    for r in AE.window_rows(c, back=0, ahead=14, today=today):
        upcoming.setdefault(r["ticker"], r)
    portfolio = B.portfolio_section([{"symbol": s} for s in syms], values, upcoming, typical)
    # マクロ統計（ECST の計算済みの結果だけを読む — ネットワークに出ない）
    from . import api_econ as EC
    since = (dt.datetime.now() - dt.timedelta(days=2)).isoformat()
    econ = B.econ_section(EC._read("dashboard.json", None), [r for r in EC._read("state.json", {}).get("releases", []) if r["at"] >= since],
                          EC._read("flows.json", None))
    # 信用残
    margin = B.margin_section(cov["items"], mstore().series)
    errs = sorted((latest or {}).get("errors", {}).keys())
    health = {"provider": provider, "demo": provider == "sim", "items": {
        "データ": provider + ("（SIM — DEMO データ）" if provider == "sim" else ""),
        "三位一体 AUTO": f"{latest.get('generated_at')}（取得できなかったもの: {', '.join(errs) or 'なし'}）" if latest else "未実行",
        "決算カレンダー": f"更新 {c['config'].get('last_refresh') or '—'} · JPX {c['jpx'].get('fetched') or '未取得'}",
        "ファクター・ライブラリ": lib.get("generated_at") or "未作成（AUTO / FCTR）",
        "カバレッジ": f"{len(cov['items'])} 銘柄",
        "信用残": margin.get("last_date") or "未取り込み（MRGN）"}}
    return {"date": today.isoformat(), "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "markets": markets,
            "factors": factors, "auto": auto, "earnings": earnings, "portfolio": portfolio, "margin": margin, "econ": econ,
            "health": health}


def save_brief(b: dict[str, Any]) -> Path:
    d = bdir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{b['date']}.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    md = d / f"{b['date']}.md"
    md.write_text(B.render_md(b), encoding="utf-8")
    return md


async def generate(source: str | None = None) -> dict[str, Any]:
    b = await gather(source)
    b["md_path"] = str(save_brief(b))
    return b


async def maybe_auto(source: str | None = None, now: dt.datetime | None = None) -> dict[str, Any] | None:
    """Called after each AUTO run: the first run at or after the configured time makes the day's brief."""
    cfg = config()
    now = now or dt.datetime.now()
    if not cfg.get("auto"):
        return None
    hh, mm = (int(x) for x in str(cfg.get("time") or "07:30").split(":")[:2])
    if now.time() < dt.time(hh, mm) or (bdir() / f"{now.date().isoformat()}.json").exists():
        return None
    b = await generate(source)
    if S.hub:
        await S.hub.broadcast({"type": "brief", "date": b["date"]})
    return b


def _dates() -> list[str]:
    d = bdir()
    return sorted((p.stem for p in d.glob("????-??-??.json")), reverse=True) if d.is_dir() else []


# ---- endpoints ------------------------------------------------------------------------------------
@router.get("")
async def latest_ep():
    dates = _dates()
    b = json.loads((bdir() / f"{dates[0]}.json").read_text(encoding="utf-8")) if dates else None
    return {"brief": b, "dates": dates, "dir": str(bdir()), "config": config()}


@router.post("/generate")
async def generate_ep(source: str | None = None):
    b = await generate(source)
    return {"brief": b, "dates": _dates(), "dir": str(bdir()), "config": config()}


class BriefConfig(BaseModel):
    auto: bool | None = None
    time: str | None = None


@router.get("/config")
async def get_config():
    return config()


@router.put("/config")
async def put_config(req: BriefConfig):
    cfg = config()
    if req.auto is not None:
        cfg["auto"] = req.auto
    if req.time is not None:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", req.time):
            raise HTTPException(400, "時刻は HH:MM")
        cfg["time"] = req.time
    S.store.set("brief_config", cfg)
    return cfg


@router.get("/{date}")
async def by_date(date: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not (bdir() / f"{date}.json").exists():
        raise HTTPException(404, "no brief for that date")
    return {"brief": json.loads((bdir() / f"{date}.json").read_text(encoding="utf-8")), "dates": _dates(), "dir": str(bdir()),
            "config": config()}
