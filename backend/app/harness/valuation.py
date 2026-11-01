"""Valuation methods: WACC/CAPM, DCF (FCFF), multiples, DDM, residual income."""
from __future__ import annotations

from typing import Any


def wacc(w: Any) -> tuple[float, dict[str, Any]]:
    if isinstance(w, (int, float)):
        return float(w), {"wacc": float(w), "formula": "given"}
    ke = w.get("cost_of_equity")
    if ke is None:
        ke = w["rf"] + w["beta"] * w["erp"] + w.get("size_premium", 0.0)
    kd = w.get("cost_of_debt", 0.0) * (1 - w.get("tax_rate", 0.3))
    wd = w.get("debt_weight", 0.0)
    val = (1 - wd) * ke + wd * kd
    return val, {"wacc": val, "cost_of_equity": ke, "after_tax_cost_of_debt": kd, "debt_weight": wd,
                 "formula": "WACC = (1−wd)·(rf + β·ERP + size) + wd·kd·(1−t)"}


def cost_of_equity(v: dict[str, Any]) -> float:
    w = v.get("wacc")
    if isinstance(v.get("cost_of_equity"), (int, float)):
        return float(v["cost_of_equity"])
    if isinstance(w, dict):
        return w.get("cost_of_equity") or (w["rf"] + w["beta"] * w["erp"] + w.get("size_premium", 0.0))
    raise ValueError("valuation.cost_of_equity (or CAPM inputs in valuation.wacc) required")


def dcf(fcff: list[float], ebitda: list[float], v: dict[str, Any], shares: float | None,
        per_share_factor: float = 1.0) -> dict[str, Any]:
    r, wdetail = wacc(v["wacc"])
    g = float(v.get("terminal_growth", 0.0))
    mid = bool(v.get("mid_year", False))
    n = len(fcff)
    dfs = [1 / (1 + r) ** (t + (0.5 if mid else 1.0)) for t in range(n)]
    pv = [f * d for f, d in zip(fcff, dfs)]
    out: dict[str, Any] = {"wacc": wdetail, "discount_factors": dfs, "pv_fcff": pv, "sum_pv_fcff": sum(pv)}
    tvs = {}
    if "terminal_growth" in v:
        if g >= r:
            raise ValueError(f"terminal growth {g:.2%} must be below WACC {r:.2%}")
        tvs["gordon"] = fcff[-1] * (1 + g) / (r - g)
    if v.get("exit_ev_ebitda"):
        tvs["exit_multiple"] = ebitda[-1] * float(v["exit_ev_ebitda"])
    if not tvs:
        raise ValueError("set valuation.terminal_growth and/or valuation.exit_ev_ebitda")
    disc_n = 1 / (1 + r) ** n
    net_debt = float(v.get("net_debt", 0.0))
    other = float(v.get("non_operating_assets", 0.0))
    results = {}
    for k, tv in tvs.items():
        ev = sum(pv) + tv * disc_n
        eq = ev - net_debt + other
        results[k] = {"terminal_value": tv, "pv_terminal": tv * disc_n, "enterprise_value": ev,
                      "equity_value": eq, "tv_share_of_ev": tv * disc_n / ev if ev else None,
                      "price_per_share": eq * per_share_factor / shares if shares else None}
    out["methods"] = results
    primary = results.get("gordon") or results.get("exit_multiple")
    out.update(primary)
    return out


def multiples(derived: dict[str, list], v: dict[str, Any], shares: float | None, per_share_factor: float,
              book_equity: float | None) -> dict[str, Any]:
    m = v.get("multiples") or {}
    idx = int(m.get("year_index", 0))
    nd = float(v.get("net_debt", 0.0))
    res: dict[str, Any] = {"year_index": idx}
    eps = derived["eps"][idx]
    if m.get("per") and eps is not None:
        res["per"] = {"multiple": m["per"], "eps": eps, "price": m["per"] * eps}
    if m.get("ev_ebitda") and shares:
        eq = m["ev_ebitda"] * derived["ebitda"][idx] - nd
        res["ev_ebitda"] = {"multiple": m["ev_ebitda"], "ebitda": derived["ebitda"][idx],
                            "price": eq * per_share_factor / shares}
    if m.get("pbr") and book_equity is not None and shares:
        bps = book_equity * per_share_factor / shares
        res["pbr"] = {"multiple": m["pbr"], "bps": bps, "price": m["pbr"] * bps}
    return res


def ddm(dividends: list[float], v: dict[str, Any], shares: float | None, per_share_factor: float) -> dict[str, Any]:
    ke = cost_of_equity(v)
    g = float(v.get("dividend_terminal_growth", v.get("terminal_growth", 0.0)))
    if g >= ke:
        raise ValueError("dividend growth must be below cost of equity")
    n = len(dividends)
    pv = sum(d / (1 + ke) ** (t + 1) for t, d in enumerate(dividends))
    tv = dividends[-1] * (1 + g) / (ke - g) / (1 + ke) ** n
    eq = pv + tv
    return {"cost_of_equity": ke, "pv_dividends": pv, "pv_terminal": tv, "equity_value": eq,
            "price_per_share": eq * per_share_factor / shares if shares else None}


def residual_income(net_income: list[float], dividends: list[float], v: dict[str, Any], shares: float | None,
                    per_share_factor: float) -> dict[str, Any]:
    ke = cost_of_equity(v)
    bv = float(v["book_equity"])
    g = float(v.get("ri_terminal_growth", 0.0))
    bv0, pv, ri_list, bvs = bv, 0.0, [], []
    for t, (ni, d) in enumerate(zip(net_income, dividends)):
        ri = ni - ke * bv
        pv += ri / (1 + ke) ** (t + 1)
        ri_list.append(ri)
        bv = bv + ni - d
        bvs.append(bv)
    n = len(net_income)
    tv = ri_list[-1] * (1 + g) / (ke - g) / (1 + ke) ** n if ke > g else 0.0
    eq = bv0 + pv + tv
    return {"cost_of_equity": ke, "residual_income": ri_list, "book_value_path": bvs, "pv_ri": pv,
            "pv_terminal": tv, "equity_value": eq,
            "price_per_share": eq * per_share_factor / shares if shares else None}


def run_all(proj: dict[str, Any], v: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    d = proj["derived"]
    shares_series = d["shares_used"]
    shares = shares_series[-1] if shares_series and shares_series[-1] else None
    f = float(a.get("per_share_factor", 1.0))
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    try:
        out["dcf"] = dcf(d["fcff"], d["ebitda"], v, shares, f)
    except (ValueError, KeyError) as e:
        errors["dcf"] = str(e)
    if v.get("multiples"):
        try:
            out["multiples"] = multiples(d, v, shares_series[0] if shares_series else None, f, v.get("book_equity"))
        except (ValueError, KeyError, TypeError) as e:
            errors["multiples"] = str(e)
    if any(x for x in d["dividends"]):
        try:
            out["ddm"] = ddm(d["dividends"], v, shares, f)
        except (ValueError, KeyError) as e:
            errors["ddm"] = str(e)
    if "book_equity" in v:
        try:
            out["residual_income"] = residual_income(d["net_income"], d["dividends"], v, shares, f)
        except (ValueError, KeyError) as e:
            errors["residual_income"] = str(e)
    price = v.get("current_price")
    if price:
        out["upside"] = {k: (m["price_per_share"] / price - 1) for k, m in out.items()
                         if isinstance(m, dict) and m.get("price_per_share")}
    out["errors"] = errors
    return out
