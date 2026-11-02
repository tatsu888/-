"""Resolve {"excel": <file_id>, "range": "Sheet!B4:G4"} references inside a harness spec.

Values come from what Excel itself calculated and saved (the XLS library's lossless view), so a
company's existing Excel model can feed the deterministic harness without copy-paste. Every
resolved reference is recorded (file, range, values) and the *resolved* spec is what gets hashed,
so results stay reproducible and auditable.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

Reader = Callable[[str, str, str], list[list[Any]]]  # (file_id, sheet, a1_range) -> 2-D values

_RANGE = re.compile(r"^(?:'((?:[^']|'')+)'|([^!]+))!([A-Za-z]{1,3}\d+)(?::([A-Za-z]{1,3}\d+))?$")


def parse_range(ref: str) -> tuple[str, str, str]:
    m = _RANGE.match(ref.strip())
    if not m:
        raise ValueError(f"bad excel range {ref!r} (expected Sheet!B4:G4)")
    sheet = (m.group(1) or "").replace("''", "'") or m.group(2)
    start, end = m.group(3).upper(), (m.group(4) or m.group(3)).upper()
    return sheet, start, end


def is_ref(v: Any) -> bool:
    return isinstance(v, dict) and "excel" in v and "range" in v and len(v) <= 4


def _flatten(block: list[list[Any]], ref: str) -> Any:
    vals = [v for row in block for v in row]
    for v in vals:
        if v is not None and not isinstance(v, (int, float)):
            raise ValueError(f"excel range {ref} contains non-numeric value {v!r}")
    if len(vals) == 1:
        return vals[0]
    return vals


def resolve(spec: dict[str, Any], reader: Reader) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (resolved_spec, provenance list). Raises ValueError on bad references."""
    out = copy.deepcopy(spec)
    refs: list[dict[str, Any]] = []

    def walk(node: Any, path: str) -> Any:
        if is_ref(node):
            sheet, a, b = parse_range(node["range"])
            block = reader(node["excel"], sheet, f"{a}:{b}")
            if node.get("transpose"):
                block = [list(r) for r in zip(*block)]
            val = _flatten(block, node["range"])
            if node.get("scale") is not None:
                s = float(node["scale"])
                val = [v * s if v is not None else None for v in val] if isinstance(val, list) else val * s
            refs.append({"path": path, "file": node["excel"], "range": node["range"], "values": val})
            return val
        if isinstance(node, dict):
            return {k: walk(v, f"{path}.{k}" if path else k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
        return node

    out = walk(out, "")
    return out, refs
