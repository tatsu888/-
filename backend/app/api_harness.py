"""Forecast harness endpoints (deterministic modelling engine)."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .harness import CATALOG, LINE_METHODS
from .harness import regression as R
from .harness import timeseries as T
from .harness.runner import ENGINE_VERSION, run
from .state import S

router = APIRouter(prefix="/api/harness")
EXAMPLES = Path(__file__).resolve().parents[2] / "models" / "examples"


@router.get("/catalog")
async def catalog():
    return {"engine_version": ENGINE_VERSION, "catalog": CATALOG, "line_methods": sorted(LINE_METHODS)}


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
async def save_model(name: str, spec: dict[str, Any]):
    saved = dict(S.store.get("harness_models") or {})
    saved[name] = spec
    S.store.set("harness_models", saved)
    return {"ok": True, "name": name}


@router.post("/run")
async def run_model(spec: dict[str, Any], uncertainty: bool = True):
    try:
        return run(spec, uncertainty=uncertainty)
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}") from e


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
    try:
        res = run(spec)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e)) from e
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
