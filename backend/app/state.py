"""Process-wide singletons shared by the routers."""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import HTTPException

from .alerts import AlertEngine
from .config import settings
from .excel import ExcelLibrary
from .hub import Hub
from .intervals import INTERVAL_SECONDS, normalize_interval
from .models import Bar
from .providers import Provider, ProviderError, ProviderRegistry
from .providers.tv_web import TVWeb
from .store import Store

DATA_DIR = Path(os.environ.get("TERMINAL_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
STARTED = time.time()


class _State:
    def __init__(self) -> None:
        self.registry = ProviderRegistry(settings)
        self.store = Store(DATA_DIR / "store.json")
        self.alerts = AlertEngine(self.store)
        self.web = TVWeb()
        self.excel = ExcelLibrary()
        self.hub: Hub | None = None
        self.hist_cache: dict[tuple[str, str, str, int], tuple[float, list[Bar]]] = {}

    async def provider(self, source: str | None = None) -> Provider:
        try:
            return await self.registry.get(source)
        except ProviderError as e:
            raise HTTPException(400, str(e)) from e

    async def history(self, symbol: str, interval: str, bars: int, source: str | None = None) -> list[Bar]:
        prov = await self.provider(source)
        key = (prov.name, symbol, interval, bars)
        ttl = 15 if INTERVAL_SECONDS[interval] < 86400 else 120
        hit = self.hist_cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        try:
            data = await prov.get_history(symbol, interval, bars)
        except ProviderError as e:
            raise HTTPException(502, f"[{prov.name}] {e}") from e
        self.hist_cache[key] = (time.time(), data)
        if len(self.hist_cache) > 800:
            self.hist_cache.pop(next(iter(self.hist_cache)))
        return data


S = _State()


def interval_or_400(v: str) -> str:
    try:
        return normalize_interval(v)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def symbols_or_400(v: str, cap: int = 200) -> list[str]:
    syms = [s.strip() for s in v.split(",") if s.strip()]
    if not syms:
        raise HTTPException(400, "symbols required")
    if len(syms) > cap:
        raise HTTPException(400, f"too many symbols (max {cap})")
    return syms
