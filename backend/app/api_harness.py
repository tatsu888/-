"""Forecast harness endpoints (deterministic modelling engine)."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from .harness import CATALOG, LINE_METHODS
from .harness import diff as D
from .harness.brief import make_brief
from .harness.excel_refs import resolve as resolve_refs
from .harness.lines import METHOD_PARAMS
from .harness.schema import spec_schema
from .harness import regression as R
from .harness import timeseries as T
from .harness.runner import ENGINE_VERSION, run
from .state import S

router = APIRouter(prefix="/api/harness")
EXAMPLES = Path(__file__).resolve().parents[2] / "models" / "examples"
TEMPLATES = Path(__file__).resolve().parents[2] / "models" / "templates"


def _excel_reader(file_id: str, sheet: str, rng: str) -> list[list[Any]]:
    """Values Excel calculated (lossless XLS view) for an A1 range."""
    from .excel import ExcelError
    from .formula import col_to_num, num_to_col, split_addr

    try:
        view = S.excel.view(file_id)
    except ExcelError as e:
        raise ValueError(f"excel {file_id}: {e}") from e
    sh = next((x for x in view["sheets"] if x["name"] == sheet), None)
    if sh is None:
        raise ValueError(f"excel {file_id}: sheet {sheet!r} not found")
    a, b = rng.split(":")
    (r1, c1), (r2, c2) = split_addr(a), split_addr(b)
    return [[(sh["cells"].get(f"{num_to_col(c)}{r}") or {}).get("v") for c in range(min(c1, c2), max(c1, c2) + 1)]
            for r in range(min(r1, r2), max(r1, r2) + 1)]


def _resolve(spec: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        return resolve_refs(spec, _excel_reader)
    except ValueError as e:
        raise HTTPException(400, f"excel reference: {e}") from e


def _run(spec: dict[str, Any], uncertainty: bool = True) -> dict[str, Any]:
    resolved, refs = _resolve(spec)
    try:
        return run(resolved, uncertainty=uncertainty, excel_refs=refs)
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}") from e


@router.get("/catalog")
async def catalog():
    return {"engine_version": ENGINE_VERSION, "catalog": CATALOG, "line_methods": sorted(LINE_METHODS),
            "method_params": METHOD_PARAMS}


@router.get("/schema")
async def schema():
    """JSON Schema of a spec — give it to an AI assistant so its specs validate."""
    return spec_schema()


@router.get("/templates")
async def templates():
    out = []
    for p in sorted(TEMPLATES.glob("*.json")) if TEMPLATES.is_dir() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"name": p.stem, "description": d.get("_description", "")})
    return out


@router.get("/templates/{name}")
async def template(name: str):
    p = (TEMPLATES / f"{name}.json").resolve()
    if p.parent != TEMPLATES.resolve() or not p.is_file():
        raise HTTPException(404, "template not found")
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/models")
async def list_models():
    saved = S.store.get("harness_models") or {}
    examples = sorted(p.stem for p in EXAMPLES.glob("*.json")) if EXAMPLES.is_dir() else []
    return {"saved": sorted(saved), "examples": examples}


@router.get("/models/{name}")
async def get_model(name: str, example: bool = False):
    if example:
        p = (EXAMPLES / f"{name}.json").resolve()
        if p.parent != EXAMPLES.resolve() or not p.is_file():
            raise HTTPException(404, "example not found")
        return json.loads(p.read_text(encoding="utf-8"))
    saved = S.store.get("harness_models") or {}
    if name not in saved:
        raise HTTPException(404, "model not found")
    return saved[name]


@router.put("/models/{name}")
async def save_model(name: str, spec: dict[str, Any], note: str = ""):
    """Save the model and append a version (when the inputs changed) with key outputs for revision history."""
    import datetime as dt
    import hashlib

    saved = dict(S.store.get("harness_models") or {})
    saved[name] = spec
    S.store.set("harness_models", saved)
    versions = dict(S.store.get("harness_versions") or {})
    hist = list(versions.get(name, []))
    h = hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if not hist or hist[-1]["spec_hash"] != h:
        summary: dict[str, Any] = {}
        try:
            res = _run(spec, uncertainty=False)
            d = res["projection"]["derived"]
            summary = {"operating_profit": d["operating_profit"], "eps": d["eps"],
                       "dcf_price": ((res.get("valuation") or {}).get("dcf") or {}).get("price_per_share"),
                       "checks": res["check_summary"], "output_hash": res["meta"]["output_hash"]}
        except HTTPException as e:
            summary = {"error": e.detail}
        hist.append({"version": len(hist) + 1, "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                     "note": note, "spec_hash": h, "summary": summary, "spec": spec})
        versions[name] = hist[-100:]
        S.store.set("harness_versions", versions)
    return {"ok": True, "name": name, "version": len(hist)}


@router.get("/models/{name}/versions")
async def model_versions(name: str):
    hist = (S.store.get("harness_versions") or {}).get(name, [])
    return [{k: v for k, v in x.items() if k != "spec"} for x in hist]


@router.get("/models/{name}/versions/{version}")
async def model_version(name: str, version: int):
    hist = (S.store.get("harness_versions") or {}).get(name, [])
    v = next((x for x in hist if x["version"] == version), None)
    if v is None:
        raise HTTPException(404, "version not found")
    return v


@router.get("/models/{name}/diff")
async def model_diff(name: str, a: int, b: int):
    """Assumption changes between two saved versions and the effect on key outputs (forecast revision log)."""
    hist = (S.store.get("harness_versions") or {}).get(name, [])
    by = {x["version"]: x for x in hist}
    if a not in by or b not in by:
        raise HTTPException(404, f"versions available: {sorted(by)}")
    va, vb = by[a], by[b]
    return {"name": name, "a": a, "b": b, "changes": D.diff(va["spec"], vb["spec"]),
            "summary_a": va["summary"], "summary_b": vb["summary"]}


@router.post("/run")
async def run_model(spec: dict[str, Any], uncertainty: bool = True):
    return _run(spec, uncertainty)


class BriefReq(BaseModel):
    spec: dict[str, Any]
    task: str = ""
    include_result: bool = True


@router.post("/brief", response_class=PlainTextResponse)
async def brief(req: BriefReq):
    """Markdown prompt for ChatGPT/Claude: rules + methods + spec + last results; answer = JSON changes."""
    result = None
    if req.include_result:
        try:
            result = _run(req.spec, uncertainty=False)
        except HTTPException:
            result = None
    return make_brief(req.spec, result, req.task)


class ChangesReq(BaseModel):
    spec: dict[str, Any]
    changes: list[dict[str, Any]] | dict[str, Any]
    require_source: bool = True


@router.post("/apply_changes")
async def apply_changes(req: ChangesReq):
    """Validate + apply AI-proposed changes ({"changes":[{path, value, source}]}). Returns the new spec,
    rejected items, the diff, and before/after key outputs — nothing is saved until the user saves."""
    changes = req.changes.get("changes", []) if isinstance(req.changes, dict) else req.changes
    new, problems = D.apply_changes(req.spec, changes, req.require_source)
    out: dict[str, Any] = {"spec": new, "rejected": problems, "diff": D.diff(req.spec, new)}
    try:
        before, after = _run(req.spec, uncertainty=False), _run(new, uncertainty=False)
        pick = lambda r: {"eps": r["projection"]["derived"]["eps"],  # noqa: E731
                          "operating_profit": r["projection"]["derived"]["operating_profit"],
                          "dcf_price": ((r.get("valuation") or {}).get("dcf") or {}).get("price_per_share"),
                          "checks": r["check_summary"]}
        out.update(before=pick(before), after=pick(after))
    except HTTPException as e:
        out["run_error"] = e.detail
    return out


class RegressionReq(BaseModel):
    y: list[float]
    drivers: dict[str, list[float]]
    future: dict[str, list[float]] = {}
    transform: str = "level"


@router.post("/regression")
async def regression(req: RegressionReq):
    try:
        if req.future:
            return R.driver_forecast(req.y, req.drivers, req.future, req.transform)
        names = list(req.drivers)
        X = [[req.drivers[k][i] for k in names] for i in range(len(req.y))]
        return R.public(R.ols_report(req.y, X, names))
    except (ValueError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e)) from e


class TSReq(BaseModel):
    values: list[float]
    horizon: int = 4
    period: int = 4


@router.post("/timeseries")
async def timeseries(req: TSReq):
    v, h = req.values, req.horizon
    out: dict[str, Any] = {"yoy": T.yoy(v), "cagr_full": T.cagr(v[0], v[-1], len(v) - 1) if len(v) > 1 else None}
    for name, fn in T.METHODS.items():
        try:
            out[name] = fn(v, h)
        except (ValueError, ZeroDivisionError) as e:
            out[name] = {"error": str(e)}
    try:
        out["seasonal_factors"] = T.seasonal_factors(v, req.period)
    except ValueError as e:
        out["seasonal_factors"] = {"error": str(e)}
    out["backtest"] = T.backtest_methods(v, min_train=max(4, len(v) // 2))
    return out


@router.post("/export.xlsx")
async def export_xlsx(spec: dict[str, Any]):
    """Run the model and export projection, valuation and checks as an Excel workbook (values + formulas text)."""
    res = _run(spec)
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Projection"
    proj = res["projection"]
    hy, fy = proj["years_hist"], proj["years"]
    hdr = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1F1F1F")
    ws.append(["Line", *hy, *fy, "Method / Formula", "Source"])
    for c in ws[1]:
        c.font, c.fill = hdr, fill
    for name, vals in proj["lines"].items():
        p = proj["provenance"].get(name, {})
        hist = proj["history"].get(name) or [None] * len(hy)
        ws.append([name, *hist, *vals, p.get("formula"), p.get("source")])
    ws.append([])
    for name, vals in proj["derived"].items():
        hd = (proj.get("history_derived") or {}).get(name) or [None] * len(hy)
        ws.append([name, *hd, *vals, proj["derived_formulas"].get(name, "")])
    ws2 = wb.create_sheet("Checks")
    ws2.append(["status", "id", "message"])
    for c in res["checks"]:
        ws2.append([c["status"], c["id"], c["message"]])
    ws3 = wb.create_sheet("Meta")
    for k, v in res["meta"].items():
        ws3.append([k, str(v)])
    ws3.append(["spec", json.dumps(spec, ensure_ascii=False)])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = (spec.get("company", {}).get("symbol") or "model").replace(":", "_")
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}_harness.xlsx"'})


@router.get("/for_symbol")
async def models_for_symbol(symbol: str):
    """Saved models whose spec.company.symbol matches (used by TEAR / DES), with their latest version summary."""
    saved = S.store.get("harness_models") or {}
    versions = S.store.get("harness_versions") or {}
    out = []
    for name, spec in saved.items():
        if (spec.get("company") or {}).get("symbol") == symbol:
            hist = versions.get(name) or []
            last = hist[-1] if hist else {}
            out.append({"name": name, "version": last.get("version"), "saved_at": last.get("saved_at"),
                        "summary": last.get("summary"), "company": spec.get("company"),
                        "forecast_years": spec.get("forecast_years")})
    return out
