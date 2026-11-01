"""Provider interface.

A provider turns an upstream market-data source into normalized ``Quote`` /
``Bar`` dicts (see app/models.py).

Two kinds of access:

* Pull  — ``get_quotes`` / ``get_history`` / ``search`` / ``screener``
* Push  — the hub calls ``set_quote_symbols`` / ``set_bar_subscriptions`` with
          the *complete* desired set whenever browser subscriptions change.
          The provider then calls ``self.emit_quote`` / ``self.emit_bar`` for
          every update.

To add a source: subclass ``Provider``, implement the abstract methods, and
register it in ``providers/__init__.py``.
"""
from __future__ import annotations

import abc
import logging
from typing import Awaitable, Callable

from ..models import Bar, Quote

log = logging.getLogger(__name__)

QuoteCallback = Callable[[Quote], Awaitable[None] | None]
BarCallback = Callable[[str, str, Bar], Awaitable[None] | None]

BarKey = tuple[str, str]  # (symbol, interval)


class ProviderError(Exception):
    """Upstream failure that should be reported to the client (HTTP 502)."""


class Provider(abc.ABC):
    name: str = "base"
    #: shown in the UI status bar
    description: str = ""

    def __init__(self) -> None:
        self.on_quote: QuoteCallback | None = None
        self.on_bar: BarCallback | None = None
        self.status: str = "init"        # init / connecting / connected / error / stopped
        self.status_detail: str = ""

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:  # pragma: no cover - default no-op
        self.status = "connected"

    async def stop(self) -> None:  # pragma: no cover - default no-op
        self.status = "stopped"

    # ---- pull ------------------------------------------------------------
    @abc.abstractmethod
    async def get_quotes(self, symbols: list[str]) -> list[Quote]: ...

    @abc.abstractmethod
    async def get_history(self, symbol: str, interval: str, bars: int) -> list[Bar]: ...

    @abc.abstractmethod
    async def search(self, query: str, limit: int = 20) -> list[dict]: ...

    async def screener(self, market: str, preset: str, limit: int = 25) -> list[Quote]:
        raise ProviderError(f"screener not supported by provider '{self.name}'")

    # ---- push ------------------------------------------------------------
    @abc.abstractmethod
    async def set_quote_symbols(self, symbols: set[str]) -> None: ...

    @abc.abstractmethod
    async def set_bar_subscriptions(self, subs: set[BarKey]) -> None: ...

    async def emit_quote(self, q: Quote) -> None:
        if self.on_quote is not None:
            r = self.on_quote(q)
            if r is not None:
                await r

    async def emit_bar(self, symbol: str, interval: str, bar: Bar) -> None:
        if self.on_bar is not None:
            r = self.on_bar(symbol, interval, bar)
            if r is not None:
                await r

    def health(self) -> dict:
        return {"provider": self.name, "description": self.description,
                "status": self.status, "detail": self.status_detail}
