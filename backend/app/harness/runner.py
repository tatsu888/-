"""Deterministic model runner: spec (JSON) -> projection + valuation + uncertainty + checks.

Reproducibility contract
  * Same spec  -> same output, bit for bit (no wall-clock, seeded RNG).
  * meta.input_hash  = sha256 of the canonical spec JSON
  * meta.output_hash = sha256 of the canonical numeric output (rounded to 10 significant digits)
  * Every forecast line carries method, formula, parameters and source (provenance).
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from . import checks as C
from . import uncertainty as U
from .model import project
from .valuation import run_all

ENGINE_VERSION = "harness-0.1.0"


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _round(obj: Any) -> Any:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return str(obj)
        return float(f"{obj:.10g}")
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj


def core(spec: dict[str, Any]) -> dict[str, Any]:
    """Projection + valuation only (used inside scenario / sensitivity / Monte Carlo loops)."""
    proj = project(spec)
    val = run_all(proj, spec["valuation"], spec.get("assumptions", {})) if spec.get("valuation") else None
    return {"projection": proj, "valuation": val}


def run(spec: dict[str, Any], *, uncertainty: bool = True, excel_refs: list[dict[str, Any]] | None = None
        ) -> dict[str, Any]:
    """``spec`` must already have excel references resolved (see harness/excel_refs.py);
    ``excel_refs`` is the provenance of those references (recorded in meta)."""
    warnings = validate(spec)
    base = core(spec)
    proj, val = base["projection"], base["valuation"]
    out: dict[str, Any] = {
        "company": spec.get("company", {}),
        "projection": proj,
        "valuation": val,
        "checks": C.run_checks(spec, proj, val),
    }
    if uncertainty:
        outputs = spec.get("report_outputs") or ["valuation.dcf.price_per_share",
                                                 "projection.derived.operating_profit[0]",
                                                 "projection.derived.eps[0]"]
        if spec.get("scenarios"):
            out["scenarios"] = U.scenarios(spec, spec["scenarios"], core, outputs)
        if spec.get("sensitivity"):
            s = spec["sensitivity"]
            out["sensitivity"] = U.sensitivity(spec, s["x"], s["y"], s["output"], core)
        if spec.get("monte_carlo"):
            out["monte_carlo"] = U.monte_carlo(spec, spec["monte_carlo"], core)
    if warnings:
        out["checks"].append({"id": "spec_warnings", "status": "WARN", "message": "; ".join(warnings)})
    out["check_summary"] = C.summary(out["checks"])
    out = _round(out)
    out["meta"] = {
        "engine_version": ENGINE_VERSION,
        "input_hash": hashlib.sha256(_canon(spec).encode()).hexdigest(),
        "output_hash": hashlib.sha256(_canon(out).encode()).hexdigest(),
        "deterministic": True,
        "excel_refs": excel_refs or [],
    }
    return out


def validate(spec: dict[str, Any]) -> list[str]:
    """Raise ValueError on structural errors; return non-fatal warnings (unknown params, …)."""
    from .excel_refs import is_ref
    from .lines import check_params

    errs: list[str] = []
    warns: list[str] = []
    if not isinstance(spec.get("forecast_years"), list) or not spec["forecast_years"]:
        errs.append("forecast_years: non-empty list required")
    if not isinstance(spec.get("lines"), dict) or "revenue" not in spec.get("lines", {}):
        errs.append("lines.revenue required")
    hist = spec.get("history") or {}
    years = hist.get("years")
    if years is not None:
        for k, v in hist.items():
            if k != "years" and isinstance(v, list) and len(v) != len(years):
                errs.append(f"history.{k}: {len(v)} values but {len(years)} years")
    for name, ls in (spec.get("lines") or {}).items():
        if not isinstance(ls, dict):
            errs.append(f"line '{name}': must be an object with method/params")
            continue
        e, w = check_params(name, ls)
        errs += e
        warns += w

    def find_refs(node: Any, path: str) -> None:
        if is_ref(node):
            errs.append(f"{path}: unresolved excel reference (run through /api/harness/run to resolve)")
        elif isinstance(node, dict):
            for k, v in node.items():
                find_refs(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                find_refs(v, f"{path}[{i}]")
    find_refs(spec, "")
    if errs:
        raise ValueError("; ".join(errs))
    return warns
