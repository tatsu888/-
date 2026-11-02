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
    "excel_links": {},    # symbol -> [excel file ids] (manual links; auto-links come from filenames)
    "harness_models": {}, # name -> forecast harness spec (JSON)
    "workspaces": {},     # name -> {panels, layout, security} (saved terminal layouts)
    "harness_versions": {},  # model name -> [{version, saved_at, note, spec_hash, summary, spec}]
    "macro_map": None,    # user-edited propagation map (None -> macro.DEFAULT_MAP)
    "screens": {},        # saved SCRN screens
    "trades": [],         # trade blotter [{id, time, symbol, side, qty, price, fee, note}]
    "scorecards": {},     # symbol -> [{version, saved_at, sheet, result}] (Trinity 評点表 history)
    "fw_book": {"positions": [], "level": "book", "nav": None, "drawdown_pct": None},  # Trinity exposure book
    "fw_ideas": [],       # [{id, title, theme, long, short, answers, month, created}] (05.6 gates)
    "fw_ideas_archive": {},  # month -> ideas snapshot (毎月ゼロから作り直す)
    "transcripts": {},
    "trinity_config": {"enabled": True, "interval_min": 60, "extra": [], "exclude": [], "max_symbols": 150,
                       "sources": ["watchlists", "scorecards", "portfolio"]},  # AUTO Trinity    # symbol -> [{id, period, date, title, text}] (TXT tone/diff)
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
