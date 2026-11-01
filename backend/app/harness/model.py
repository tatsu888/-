"""Statement integration: project lines, then derive the standard P&L / cash-flow chain.

Line naming convention (spec["lines"] keys) — only ``revenue`` is mandatory:
    revenue, cogs, sga, other_operating, da, non_operating, capex, minority, shares
Any extra line (segments, KPIs, drivers) is allowed and can be referenced.

Assumptions (spec["assumptions"]):
    tax_rate, minority_pct, payout_ratio, dso, dio, dpo (days), per_share_factor
"""
from __future__ import annotations

from typing import Any

from .lines import METHODS, Ctx, topo_order

DERIVED_FORMULAS = {
    "gross_profit": "revenue − cogs",
    "operating_profit": "gross_profit − sga − other_operating",
    "ebitda": "operating_profit + da",
    "pretax_profit": "operating_profit + non_operating",
    "tax": "pretax_profit × tax_rate",
    "minority_interest": "minority line, else (pretax − tax) × minority_pct",
    "net_income": "pretax_profit − tax − minority_interest",
    "eps": "net_income × per_share_factor / shares",
    "nopat": "operating_profit × (1 − tax_rate)",
    "nwc": "revenue×DSO/365 + cogs×DIO/365 − cogs×DPO/365",
    "delta_nwc": "nwc[t] − nwc[t−1]",
    "fcff": "nopat + da − capex − Δnwc",
    "dividends": "net_income × payout_ratio",
    "gross_margin": "gross_profit / revenue",
    "operating_margin": "operating_profit / revenue",
    "net_margin": "net_income / revenue",
    "revenue_growth": "revenue[t] / revenue[t−1] − 1",
}


def _get(d: dict[str, list[float]], k: str, n: int, default: float = 0.0) -> list[float]:
    v = d.get(k)
    return list(v) if v is not None else [default] * n


def _vec(a: dict[str, Any], key: str, n: int, default: float) -> list[float]:
    v = a.get(key, default)
    if isinstance(v, (int, float)):
        return [float(v)] * n
    if isinstance(v, list) and len(v) == n:
        return [float(x) for x in v]
    raise ValueError(f"assumption '{key}' must be a number or list of {n}")


def derive(lines: dict[str, list[float]], a: dict[str, Any], n: int, prev_rev: float | None,
           prev_cogs: float | None, prev_nwc: float | None = None) -> dict[str, list[float | None]]:
    rev = lines["revenue"]
    cogs, sga = _get(lines, "cogs", n), _get(lines, "sga", n)
    oth, da = _get(lines, "other_operating", n), _get(lines, "da", n)
    nonop, capex = _get(lines, "non_operating", n), _get(lines, "capex", n)
    tax_rate = _vec(a, "tax_rate", n, 0.30)
    payout = _vec(a, "payout_ratio", n, 0.0)
    f = float(a.get("per_share_factor", 1.0))
    gp = [r - c for r, c in zip(rev, cogs)]
    op = [g - s - o for g, s, o in zip(gp, sga, oth)]
    ebitda = [o + d for o, d in zip(op, da)]
    pre = [o + x for o, x in zip(op, nonop)]
    tax = [p * t for p, t in zip(pre, tax_rate)]
    if "minority" in lines:
        mi = lines["minority"]
    else:
        mp = _vec(a, "minority_pct", n, 0.0)
        mi = [(p - t) * m for p, t, m in zip(pre, tax, mp)]
    ni = [p - t - m for p, t, m in zip(pre, tax, mi)]
    shares = lines.get("shares") or ([float(a["shares"])] * n if "shares" in a else None)
    eps = [x * f / s if s else None for x, s in zip(ni, shares)] if shares else [None] * n
    nopat = [o * (1 - t) for o, t in zip(op, tax_rate)]
    dso, dio, dpo = (_vec(a, k, n, 0.0) for k in ("dso", "dio", "dpo"))
    nwc = [r * s / 365 + c * i / 365 - c * p / 365 for r, c, s, i, p in zip(rev, cogs, dso, dio, dpo)]
    if prev_nwc is None:
        prev_nwc = ((prev_rev or 0) * dso[0] / 365 + (prev_cogs or 0) * dio[0] / 365
                    - (prev_cogs or 0) * dpo[0] / 365) if prev_rev is not None else nwc[0]
    dnwc = [nwc[0] - prev_nwc] + [nwc[i] - nwc[i - 1] for i in range(1, n)]
    fcff = [np_ + d - c - w for np_, d, c, w in zip(nopat, da, capex, dnwc)]
    div = [x * p for x, p in zip(ni, payout)]
    growth = [None] * n
    prev = prev_rev
    for i, r in enumerate(rev):
        growth[i] = (r / prev - 1) if prev else None
        prev = r
    return {
        "gross_profit": gp, "operating_profit": op, "ebitda": ebitda, "pretax_profit": pre, "tax": tax,
        "minority_interest": mi, "net_income": ni, "eps": eps, "nopat": nopat, "nwc": nwc, "delta_nwc": dnwc,
        "fcff": fcff, "dividends": div, "shares_used": shares or [None] * n,
        "gross_margin": [g / r if r else None for g, r in zip(gp, rev)],
        "operating_margin": [o / r if r else None for o, r in zip(op, rev)],
        "net_margin": [x / r if r else None for x, r in zip(ni, rev)],
        "revenue_growth": growth,
    }


def project(spec: dict[str, Any]) -> dict[str, Any]:
    hist = spec.get("history", {})
    years_hist = list(hist.get("years", []))
    years_fc = list(spec["forecast_years"])
    history = {k: v for k, v in hist.items() if k != "years"}
    ctx = Ctx(history, years_hist, years_fc)
    line_specs: dict[str, dict[str, Any]] = spec["lines"]
    if "revenue" not in line_specs:
        raise ValueError("spec.lines.revenue is required")
    provenance: dict[str, Any] = {}
    for name in topo_order(line_specs):
        ls = line_specs[name]
        method = ls.get("method")
        if method not in METHODS:
            raise ValueError(f"line '{name}': unknown method {method!r}; choose from {sorted(METHODS)}")
        params = ls.get("params", {})
        try:
            values, formula, deps = METHODS[method](ctx, name, params)
        except KeyError as e:
            raise ValueError(f"line '{name}' ({method}): missing {e}") from e
        if len(values) != ctx.h:
            raise ValueError(f"line '{name}' produced {len(values)} values, expected {ctx.h}")
        ctx.forecast[name] = values
        provenance[name] = {"method": method, "formula": formula, "depends_on": deps,
                            "params": params, "source": params.get("source") or ls.get("source"),
                            "diagnostics": ctx.extras.get(name)}
    a = spec.get("assumptions", {})
    n = ctx.h
    prev_rev = history["revenue"][-1] if history.get("revenue") else None
    prev_cogs = history["cogs"][-1] if history.get("cogs") else None
    derived = derive(ctx.forecast, a, n, prev_rev, prev_cogs)

    # historical derived values (for guardrails & display)
    hist_derived = None
    if history.get("revenue"):
        hn = len(history["revenue"])
        hl = {k: [float(x) for x in v] for k, v in history.items() if isinstance(v, list) and len(v) == hn}
        ha = {k: v for k, v in a.items() if not isinstance(v, list)}
        hist_derived = derive(hl, ha, hn, None, None, prev_nwc=0.0)
        hist_derived.pop("delta_nwc")
        hist_derived.pop("fcff")
    return {
        "years_hist": years_hist, "years": years_fc,
        "lines": ctx.forecast, "history": history, "derived": derived, "history_derived": hist_derived,
        "provenance": provenance, "derived_formulas": DERIVED_FORMULAS,
    }
