"""JSON Schema (draft 2020-12) for forecast-harness specs, generated from METHOD_PARAMS.

Give it to an AI assistant so it produces specs that validate (GET /api/harness/schema).
"""
from __future__ import annotations

from typing import Any

from .lines import COMMON_PARAMS, METHOD_PARAMS

NUM = {"type": "number"}
VEC = {"oneOf": [NUM, {"type": "array", "items": NUM}]}
EXCEL_REF = {"type": "object", "required": ["excel", "range"],
             "properties": {"excel": {"type": "string", "description": "file id from GET /api/excel/files"},
                            "range": {"type": "string", "description": "Sheet!B4:G4 (row or column → list; one cell → number)"}}}
PATH = {"oneOf": [
    {"type": "object", "required": ["values"], "properties": {"values": VEC}},
    {"type": "object", "required": ["start", "growth"], "properties": {"start": NUM, "growth": VEC}},
    {"type": "object", "required": ["line"], "properties": {"line": {"type": "string"}}},
]}


def _ptype(t: str) -> dict[str, Any]:
    if t == "vec":
        return {"oneOf": [VEC, EXCEL_REF]}
    if t in ("number", "int"):
        return {"oneOf": [{"type": "integer" if t == "int" else "number"}, EXCEL_REF]}
    if t == "line":
        return {"type": "string", "description": "name of another line"}
    if t == "lines":
        return {"type": "array", "items": {"type": "string"}}
    if t == "path":
        return PATH
    if t.startswith("enum:"):
        return {"enum": t[5:].split("|")}
    if t == "dict":
        return {"type": "object", "additionalProperties": {"oneOf": [{"type": "array", "items": NUM}, PATH, EXCEL_REF]}}
    if t == "list":
        return {"type": "array"}
    return {"type": "string"}


def line_schema(method: str) -> dict[str, Any]:
    meta = METHOD_PARAMS[method]
    props = {k: _ptype(v) for k, v in {**meta["required"], **meta["optional"], **COMMON_PARAMS}.items()}
    return {"type": "object", "title": method, "description": meta["desc"], "required": ["method", "params"],
            "properties": {"method": {"const": method},
                           "params": {"type": "object", "required": list(meta["required"]), "properties": props,
                                      "additionalProperties": False}}}


def spec_schema() -> dict[str, Any]:
    series = {"oneOf": [{"type": "array", "items": {"type": ["number", "null"]}}, EXCEL_REF]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Analyst Terminal forecast-harness spec",
        "type": "object",
        "required": ["forecast_years", "lines"],
        "properties": {
            "company": {"type": "object", "properties": {"symbol": {"type": "string"}, "name": {"type": "string"},
                                                         "currency": {"type": "string"}, "unit": {"type": "string"}}},
            "history": {"type": "object", "required": ["years"],
                        "properties": {"years": {"type": "array", "items": {"type": "string"}}},
                        "additionalProperties": series,
                        "description": "historical values per line/KPI; every list as long as years"},
            "forecast_years": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "lines": {"type": "object", "required": ["revenue"],
                      "additionalProperties": {"oneOf": [line_schema(m) for m in METHOD_PARAMS]}},
            "assumptions": {"type": "object", "properties": {
                k: {"oneOf": [VEC, EXCEL_REF]} for k in
                ("tax_rate", "minority_pct", "payout_ratio", "dso", "dio", "dpo", "shares", "per_share_factor")}},
            "valuation": {"type": "object"},
            "scenarios": {"type": "object"},
            "sensitivity": {"type": "object"},
            "monte_carlo": {"type": "object"},
            "checks": {"type": "object"},
            "report_outputs": {"type": "array", "items": {"type": "string"}},
        },
    }
