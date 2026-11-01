"""Provider registry. Add new data sources here."""
from __future__ import annotations

from ..config import Settings
from .base import Provider, ProviderError
from .sim import SimProvider


def create_provider(settings: Settings) -> Provider:
    name = settings.provider
    if name == "tradingview":
        from .tradingview import TradingViewProvider
        return TradingViewProvider(settings.tv_auth_token)
    if name == "yahoo":
        from .yahoo import YahooProvider
        return YahooProvider(settings.yahoo_poll_sec)
    if name == "sim":
        return SimProvider(settings.sim_tick_sec)
    raise ValueError(f"unknown TERMINAL_PROVIDER={name!r} (tradingview | yahoo | sim)")


__all__ = ["Provider", "ProviderError", "create_provider"]
