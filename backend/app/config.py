"""Runtime configuration (環境変数で上書き可能).

All settings are read once at import time. See docs/CONFIG.md for the full list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # tradingview | yahoo | sim
    provider: str = field(default_factory=lambda: _env("TERMINAL_PROVIDER", "tradingview").lower())
    # TradingView auth token. "unauthorized_user_token" = 未ログイン（多くの取引所で遅延データ）
    tv_auth_token: str = field(default_factory=lambda: _env("TV_AUTH_TOKEN", "unauthorized_user_token"))
    # Yahoo provider quote polling interval (seconds)
    yahoo_poll_sec: float = field(default_factory=lambda: _env_float("YAHOO_POLL_SEC", 5.0))
    # Sim provider tick interval (seconds)
    sim_tick_sec: float = field(default_factory=lambda: _env_float("SIM_TICK_SEC", 1.0))
    # How often the hub flushes coalesced updates to each browser (seconds)
    push_interval_sec: float = field(default_factory=lambda: _env_float("PUSH_INTERVAL_SEC", 0.25))
    # Built frontend to serve at "/" (optional)
    static_dir: Path = field(
        default_factory=lambda: Path(
            _env("TERMINAL_STATIC_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist"))
        )
    )
    # CORS origins for the Vite dev server
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in _env("TERMINAL_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if o.strip()
        )
    )


settings = Settings()
