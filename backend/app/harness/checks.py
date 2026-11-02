"""Guardrails — deterministic sanity checks on a model run.

Status: PASS / WARN / FAIL. These are the "harness" against plausible-looking
but unfounded numbers: every forecast is compared with the company's own
history, accounting identities, and valuation consistency rules.
"""
from __future__ import annotations

import math
from typing import Any


def _c(cid: str, status: str, msg: str, **detail: Any) -> dict[str, Any]:
    return {"id": cid, "status": status, "message": msg, **({"detail": detail} if detail else {})}


def _stats(xs: list[float]) -> tuple[float, float] | None:
    xs = [x for x in xs if isinstance(x, (int, float)) and math.isfinite(x)]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def run_checks(spec: dict[str, Any], proj: dict[str, Any], val: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    d, hd = proj["derived"], proj.get("history_derived")
    years = proj["years"]
    a = spec.get("assumptions", {})

    # 1. data sufficiency
    nh = len(proj["years_hist"])
    out.append(_c("history_length", "PASS" if nh >= 5 else "WARN" if nh >= 3 else "FAIL",
                  f"{nh} historical periods (≥5 recommended for regression-based methods)"))

    # 2. assumption provenance (anti-hallucination): every non-statistical line must cite a source
    statistical = {"cagr_trend", "trend", "holt", "ar1", "hist_avg_pct_of", "fixed_variable", "driver_regression", "fourier"}
    def derived_only(p: dict[str, Any]) -> bool:  # built purely from other projected lines
        return p["method"] == "sum" or (p["method"] == "price_volume" and len(p["depends_on"]) == 2)

    def has_source(p: dict[str, Any]) -> bool:
        src = str(p.get("source") or "").strip()
        return bool(src) and not src.upper().startswith("TODO")  # template placeholders count as missing

    unsourced = [n for n, p in proj["provenance"].items()
                 if p["method"] not in statistical and not derived_only(p) and not has_source(p)]
    out.append(_c("assumption_sources", "PASS" if not unsourced else "WARN",
                  "all judgmental assumptions cite a source" if not unsourced else
                  f"assumptions without 'source': {unsourced}", lines=unsourced))

    # 3. sign / identity checks
    neg = [y for y, r in zip(years, proj["lines"]["revenue"]) if r < 0]
    out.append(_c("revenue_non_negative", "FAIL" if neg else "PASS",
                  f"negative revenue in {neg}" if neg else "revenue ≥ 0 in all years"))
    seg = spec.get("checks", {}).get("segments_sum_to")
    if seg:
        total, items = seg["total"], seg["items"]
        diffs = [abs(proj["lines"][total][t] - sum(proj["lines"][i][t] for i in items)) for t in range(len(years))]
        ok = max(diffs) <= 1e-6 * max(1.0, max(abs(x) for x in proj["lines"][total]))
        out.append(_c("segments_sum", "PASS" if ok else "FAIL", f"Σ{items} {'=' if ok else '≠'} {total}",
                      max_diff=max(diffs)))

    # 4. margins vs history (±2σ band, widened to ±3pp minimum)
    if hd:
        for m in ("gross_margin", "operating_margin", "net_margin"):
            st = _stats(hd.get(m) or [])
            if not st:
                continue
            mu, sd = st
            band = max(2 * sd, 0.03)
            bad = [(y, v) for y, v in zip(years, d[m]) if v is not None and abs(v - mu) > band]
            out.append(_c(f"{m}_range", "WARN" if bad else "PASS",
                          (f"{m} outside history mean {mu:.1%} ± {band:.1%} in " + ", ".join(f"{y}: {v:.1%}" for y, v in bad))
                          if bad else f"{m} within history mean {mu:.1%} ± {band:.1%}"))

    # 5. growth outliers vs history
    hr = proj["history"].get("revenue")
    if hr and len(hr) >= 3:
        hg = [hr[i] / hr[i - 1] - 1 for i in range(1, len(hr)) if hr[i - 1]]
        lim = max(0.2, 1.5 * max(abs(g) for g in hg))
        bad = [(y, g) for y, g in zip(years, d["revenue_growth"]) if g is not None and abs(g) > lim]
        out.append(_c("revenue_growth_outlier", "WARN" if bad else "PASS",
                      (f"growth beyond ±{lim:.0%} (1.5× max historical) in " + ", ".join(f"{y}: {g:.1%}" for y, g in bad))
                      if bad else f"revenue growth within ±{lim:.0%}"))

    # 6. tax rate
    tr = a.get("tax_rate", 0.30)
    trs = tr if isinstance(tr, list) else [tr]
    out.append(_c("tax_rate_bounds", "PASS" if all(0 <= t <= 0.5 for t in trs) else "FAIL",
                  f"tax rate(s) {trs} within [0, 50%]" if all(0 <= t <= 0.5 for t in trs) else f"tax rate {trs} out of bounds"))

    # 7. statistical diagnostics surfaced from regression-based lines
    for name, p in proj["provenance"].items():
        diag = p.get("diagnostics") or {}
        reg = diag.get("regression") or (diag.get("trend") or {})
        warns = reg.get("warnings") if isinstance(reg, dict) else None
        if warns:
            out.append(_c(f"regression_{name}", "WARN", f"{name}: " + "; ".join(warns)))

    # 8. valuation consistency
    v = spec.get("valuation") or {}
    if val and "dcf" in val:
        dcf = val["dcf"]
        g = v.get("terminal_growth")
        if g is not None:
            out.append(_c("terminal_growth", "WARN" if g > 0.04 else "PASS",
                          f"terminal growth {g:.2%}" + (" > 4% (above long-run nominal GDP?)" if g > 0.04 else "")))
        share = dcf.get("tv_share_of_ev")
        if share is not None:
            out.append(_c("terminal_value_share", "WARN" if share > 0.85 else "PASS",
                          f"terminal value = {share:.0%} of EV" + (" — valuation dominated by TV" if share > 0.85 else "")))
        if dcf.get("enterprise_value", 0) <= 0:
            out.append(_c("ev_positive", "FAIL", "enterprise value ≤ 0"))
    if val and val.get("errors"):
        for k, e in val["errors"].items():
            out.append(_c(f"valuation_{k}", "FAIL" if k == "dcf" and "valuation" in spec else "WARN", f"{k}: {e}"))
    return out


def summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    s = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for c in checks:
        s[c["status"]] += 1
    return s
