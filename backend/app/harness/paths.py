"""Dotted-path access into nested spec/result dicts: "lines.revenue.params.rates[0]"."""
from __future__ import annotations

import copy
import re
from typing import Any

_TOK = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _parts(path: str) -> list[str | int]:
    return [m.group(1) if m.group(1) is not None else int(m.group(2)) for m in _TOK.finditer(path)]


def get_path(obj: Any, path: str) -> Any:
    cur = obj
    for p in _parts(path):
        cur = cur[p]
    return cur


def set_path(obj: Any, path: str, value: Any) -> Any:
    """Returns a deep copy of obj with path set. A scalar at a list path index is broadcast."""
    out = copy.deepcopy(obj)
    parts = _parts(path)
    cur = out
    for i, p in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        if isinstance(p, str) and isinstance(cur, dict) and p not in cur:
            cur[p] = [] if isinstance(nxt, int) else {}
        if isinstance(nxt, int) and not isinstance(cur[p], list):
            raise ValueError(f"{path}: '{p}' is a scalar; set the whole value or use a list")
        cur = cur[p]
    cur[parts[-1]] = value
    return out
