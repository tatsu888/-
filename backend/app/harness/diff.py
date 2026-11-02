"""Spec diff / patch — used for version history and for applying AI-proposed changes safely."""
from __future__ import annotations

from typing import Any

from .paths import set_path


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """{"lines.revenue.params.rates": [..]} — lists of scalars are leaves; lists of dicts are indexed."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list) and any(isinstance(v, (dict, list)) for v in obj):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def diff(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    fa, fb = flatten(a), flatten(b)
    out = []
    for k in sorted(set(fa) | set(fb)):
        if k.startswith("_"):
            continue
        if fa.get(k, "<absent>") != fb.get(k, "<absent>"):
            out.append({"path": k, "before": fa.get(k), "after": fb.get(k),
                        "kind": "added" if k not in fa else "removed" if k not in fb else "changed"})
    return out


# Paths an AI assistant is allowed to change through apply_changes (assumptions, not structure or history).
ALLOWED_PREFIXES = ("lines.", "assumptions.", "valuation.", "scenarios.", "sensitivity.", "monte_carlo.",
                    "forecast_years", "report_outputs", "checks.")
FORBIDDEN_PREFIXES = ("history.",)  # actuals come from filings / Excel, never from an AI


def apply_changes(spec: dict[str, Any], changes: list[dict[str, Any]], require_source: bool = True
                  ) -> tuple[dict[str, Any], list[str]]:
    """Apply [{path, value, source}] changes. Returns (new_spec, problems). Rejected changes are listed,
    accepted ones applied. Judgmental line params without a 'source' are rejected when require_source."""
    problems: list[str] = []
    new = spec
    for i, ch in enumerate(changes):
        path = ch.get("path", "")
        if not path or not path.startswith(ALLOWED_PREFIXES) or path.startswith(FORBIDDEN_PREFIXES):
            problems.append(f"#{i} {path!r}: path not allowed (allowed: {', '.join(ALLOWED_PREFIXES)})")
            continue
        if "value" not in ch:
            problems.append(f"#{i} {path}: missing 'value'")
            continue
        if require_source and path.startswith("lines.") and ".params." in path and not ch.get("source"):
            problems.append(f"#{i} {path}: judgmental change without 'source' rejected")
            continue
        try:
            new = set_path(new, path, ch["value"])
            if ch.get("source") and path.startswith("lines.") and ".params." in path:
                line_params = path.split(".params.")[0] + ".params.source"
                new = set_path(new, line_params, ch["source"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            problems.append(f"#{i} {path}: {e}")
    return new, problems
