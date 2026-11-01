"""Provider registry. Add new data sources here.

The registry lazily creates and starts providers. One provider is "active"
(streams quotes/bars to the browser); any provider can also serve pull
requests via the ``source=`` query parameter (e.g. long daily history from
Yahoo while streaming from TradingView).
"""
from __future__ import annotations

from ..config import Settings
from .base import Provider, ProviderError
from .sim import SimProvider

PROVIDERS = {
    "tradingview": "TradingView — websocket quotes/bars, scanner, search (unofficial)",
    "yahoo": "Yahoo Finance — chart/search endpoints, polling (unofficial)",
    "sim": "Simulated demo data (offline, clearly labelled)",
}


def create_provider(name: str, settings: Settings) -> Provider:
    if name == "tradingview":
        from .tradingview import TradingViewProvider
        return TradingViewProvider(settings.tv_auth_token)
    if name == "yahoo":
        from .yahoo import YahooProvider
        return YahooProvider(settings.yahoo_poll_sec)
    if name == "sim":
        return SimProvider(settings.sim_tick_sec)
    raise ValueError(f"unknown provider {name!r} ({' | '.join(PROVIDERS)})")


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._instances: dict[str, Provider] = {}
        if settings.provider not in PROVIDERS:
            raise ValueError(f"unknown TERMINAL_PROVIDER={settings.provider!r}")
        self.active_name = settings.provider

    async def get(self, name: str | None = None) -> Provider:
        name = name or self.active_name
        if name not in PROVIDERS:
            raise ProviderError(f"unknown source {name!r}; choose from {list(PROVIDERS)}")
        p = self._instances.get(name)
        if p is None:
            p = self._instances[name] = create_provider(name, self.settings)
            await p.start()
        return p

    @property
    def active(self) -> Provider:
        return self._instances[self.active_name]

    async def stop_all(self) -> None:
        for p in self._instances.values():
            await p.stop()
        self._instances.clear()  # a later start (e.g. new event loop in tests) recreates them

    def describe(self) -> list[dict]:
        out = []
        for name, desc in PROVIDERS.items():
            inst = self._instances.get(name)
            out.append({"name": name, "description": desc, "active": name == self.active_name,
                        "started": inst is not None, **({"status": inst.status, "detail": inst.status_detail}
                                                        if inst else {})})
        return out


__all__ = ["Provider", "ProviderError", "ProviderRegistry", "PROVIDERS", "create_provider"]
