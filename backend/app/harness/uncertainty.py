"""Scenarios, 2-D sensitivity tables, seeded Monte Carlo — all re-run the full model."""
from __future__ import annotations

import math
import random
from typing import Any, Callable

from .paths import get_path, set_path

Runner = Callable[[dict[str, Any]], dict[str, Any]]


def scenarios(spec: dict[str, Any], defs: dict[str, dict[str, Any]], run: Runner, outputs: list[str]
              ) -> dict[str, Any]:
    res = {}
    for name, overrides in defs.items():
        s = spec
        for path, val in overrides.items():
            if path in ("probability", "description"):
                continue
            s = set_path(s, path, val)
        try:
            r = run(s)
            res[name] = {"outputs": {o: _safe_get(r, o) for o in outputs}, "overrides": overrides,
                         "probability": overrides.get("probability"), "description": overrides.get("description")}
        except (ValueError, KeyError) as e:
            res[name] = {"error": str(e), "overrides": overrides}
    probs = [v.get("probability") for v in res.values()]
    if all(isinstance(p, (int, float)) for p in probs) and probs and abs(sum(probs) - 1) < 1e-6:
        res["_probability_weighted"] = {
            o: sum(v["probability"] * v["outputs"][o] for v in res.values()
                   if isinstance(v.get("outputs", {}).get(o), (int, float)))
            for o in outputs}
    return res


def sensitivity(spec: dict[str, Any], x: dict[str, Any], y: dict[str, Any], output: str, run: Runner
                ) -> dict[str, Any]:
    grid = []
    for yv in y["values"]:
        row = []
        for xv in x["values"]:
            s = set_path(set_path(spec, x["path"], xv), y["path"], yv)
            try:
                row.append(_safe_get(run(s), output))
            except (ValueError, KeyError):
                row.append(None)
        grid.append(row)
    return {"x": x, "y": y, "output": output, "grid": grid}


def _draw(rng: random.Random, d: dict[str, Any]) -> float:
    kind = d.get("dist", "normal")
    if kind == "normal":
        return rng.gauss(d["mean"], d["sd"])
    if kind == "uniform":
        return rng.uniform(d["low"], d["high"])
    if kind == "triangular":
        return rng.triangular(d["low"], d["high"], d["mode"])
    if kind == "lognormal":
        return rng.lognormvariate(d["mu"], d["sigma"])
    raise ValueError(f"unknown distribution {kind!r}")


def monte_carlo(spec: dict[str, Any], cfg: dict[str, Any], run: Runner) -> dict[str, Any]:
    n = min(int(cfg.get("n", 1000)), 20000)
    seed = int(cfg.get("seed", 42))
    rng = random.Random(seed)
    output = cfg["output"]
    vals, failures = [], 0
    for _ in range(n):
        s = spec
        for path, d in cfg["drivers"].items():
            s = set_path(s, path, _draw(rng, d))
        try:
            v = _safe_get(run(s), output)
            if isinstance(v, (int, float)) and math.isfinite(v):
                vals.append(v)
            else:
                failures += 1
        except (ValueError, KeyError, ZeroDivisionError):
            failures += 1
    vals.sort()
    if not vals:
        return {"error": "all simulations failed", "n": n, "seed": seed}

    def pct(q: float) -> float:
        i = min(len(vals) - 1, max(0, int(round(q * (len(vals) - 1)))))
        return vals[i]

    mean = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1))
    lo, hi = vals[0], vals[-1]
    bins = 30
    width = (hi - lo) / bins or 1.0
    hist = [0] * bins
    for v in vals:
        hist[min(bins - 1, int((v - lo) / width))] += 1
    out = {"n": n, "seed": seed, "output": output, "valid": len(vals), "failures": failures, "mean": mean,
           "sd": sd, "percentiles": {f"p{int(q * 100)}": pct(q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
           "histogram": {"start": lo, "width": width, "counts": hist}}
    if cfg.get("current_price"):
        cp = float(cfg["current_price"])
        out["prob_above_current"] = sum(1 for v in vals if v > cp) / len(vals)
    return out


def _safe_get(r: dict[str, Any], path: str) -> Any:
    try:
        return get_path(r, path)
    except (KeyError, IndexError, TypeError):
        return None
