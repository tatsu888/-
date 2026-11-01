"""Tiny JSON-file persistence (watchlists, alerts, portfolio, notes, layout).

Single-user, single-process. Writes are atomic (tmp file + rename). Path is
``data/store.json`` at the repo root unless TERMINAL_DATA_DIR is set. Swap for
SQLite/Postgres when multi-user is needed (see docs/ROADMAP.md).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "watchlists": {},     # name -> [symbols]; empty -> frontend uses universe "W"
    "alerts": [],         # see alerts.py
    "portfolio": [],      # [{id, symbol, qty, cost, note}]
    "notes": {},          # symbol -> text
    "layout": None,       # frontend panel layout
    "settings": {},
}

ALLOWED_KEYS = tuple(DEFAULTS)


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = json.loads(json.dumps(DEFAULTS))
        if path.exists():
            try:
                self._data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                backup = path.with_suffix(".corrupt.json")
                path.replace(backup)

    def get(self, key: str) -> Any:
        if key not in ALLOWED_KEYS:
            raise KeyError(key)
        return self._data.get(key)

    def set(self, key: str, value: Any) -> Any:
        if key not in ALLOWED_KEYS:
            raise KeyError(key)
        with self._lock:
            self._data[key] = value
            self._flush()
        return value

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
