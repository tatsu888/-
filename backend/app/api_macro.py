"""Macro & propagation-map endpoints (MACRO / PROP)."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from . import macro
from .state import S

router = APIRouter(prefix="/api/macro")
_cache: dict[tuple, tuple[float, Any]] = {}


def current_map() -> list[dict[str, Any]]:
    return S.store.get("macro_map") or macro.DEFAULT_MAP


async def _load(symbols: list[str], bars: int, source: str | None) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    sem = asyncio.Semaphore(8)
    errors: dict[str, str] = {}

    async def one(s: str):
        async with sem:
            try:
                return s, await S.history(s, "1D", bars, source)
            except HTTPException as e:
                errors[s] = str(e.detail)
                return s, []
    res = await asyncio.gather(*(one(s) for s in symbols))
    return macro.closes_from_bars(dict(res)), errors


def _validate_map(items: list[dict[str, Any]]) -> None:
    ids = set()
    for i, it in enumerate(items):
        for k in ("id", "label", "cls", "tier", "series"):
            if k not in it:
                raise HTTPException(400, f"item #{i}: missing {k}")
        if it["id"] in ids:
            raise HTTPException(400, f"duplicate id {it['id']}")
        ids.add(it["id"])
        if it["tier"] not in (1, 2, 3) or it["cls"] not in macro.CLASSES:
            raise HTTPException(400, f"item {it['id']}: tier must be 1-3 and cls one of {macro.CLASSES}")
        if not macro.symbols_in(it["series"]):
            raise HTTPException(400, f"item {it['id']}: series has no symbols")


@router.get("/map")
async def get_map():
    return {"items": current_map(), "custom": S.store.get("macro_map") is not None, "tiers": macro.TIERS,
            "classes": macro.CLASSES}


@router.put("/map")
async def put_map(body: dict[str, Any]):
    items = body.get("items")
    if not isinstance(items, list):
        raise HTTPException(400, "body must be {items: [...]}")
    _validate_map(items)
    S.store.set("macro_map", items)
    _cache.clear()
    return {"ok": True, "count": len(items)}


@router.delete("/map")
async def reset_map():
    S.store.set("macro_map", None)
    _cache.clear()
    return {"ok": True}


@router.get("/propagation")
async def propagation(bars: int = Query(800, ge=200, le=3000), z_window: int = Query(20, ge=5, le=120),
                      gap: float = Query(1.0, ge=0.1, le=5), max_lag: int = Query(30, ge=5, le=90),
                      source: str | None = None):
    key = ("prop", bars, z_window, gap, max_lag, source or S.registry.active_name, id(current_map()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    items = current_map()
    syms = list(dict.fromkeys(s for it in items for s in macro.symbols_in(it["series"])))
    data, errors = await _load(syms, bars, source)
    res = {**macro.analyze(items, data, z_window, gap, max_lag), "errors": errors,
           "source": source or S.registry.active_name}
    _cache[key] = (time.time(), res)
    return res


@router.get("/dashboard")
async def dashboard(bars: int = Query(1500, ge=200, le=5000), source: str | None = None):
    syms = list(dict.fromkeys(macro.all_macro_symbols([]) ))
    data, errors = await _load(syms, bars, source)
    return {"dashboard": macro.dashboard(data), "regime": macro.regimes(data), "errors": errors,
            "source": source or S.registry.active_name}
