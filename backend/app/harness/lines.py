"""Line-item projection methods — every way a forecast line can be built.

Each method is a pure function ``(ctx, params) -> (forecast_values, formula_text, depends_on)``
where ``ctx`` gives access to history and already-projected lines. Methods are
grouped MECE in harness/__init__.py CATALOG.

Common params:
    rates/values may be a list (one per forecast year) or a scalar (broadcast).
    "source": free text — where the assumption comes from (checked by guardrails).
"""
from __future__ import annotations

from typing import Any, Callable

from . import regression as R
from . import timeseries as T


class Ctx:
    def __init__(self, history: dict[str, list[float]], years_hist: list[str], years_fc: list[str]) -> None:
        self.history = history
        self.years_hist = years_hist
        self.years_fc = years_fc
        self.forecast: dict[str, list[float]] = {}
        self.extras: dict[str, dict[str, Any]] = {}  # per-line diagnostics (regression stats etc.)

    @property
    def h(self) -> int:
        return len(self.years_fc)

    def hist(self, name: str) -> list[float]:
        v = self.history.get(name)
        if v is None:
            raise KeyError(f"history for '{name}' is required")
        return [float(x) for x in v]

    def fc(self, name: str) -> list[float]:
        if name not in self.forecast:
            raise KeyError(f"line '{name}' must be projected before it is referenced")
        return self.forecast[name]

    def last(self, name: str) -> float:
        return self.hist(name)[-1]

    def vec(self, v: Any, name: str = "value") -> list[float]:
        if isinstance(v, (int, float)):
            return [float(v)] * self.h
        if isinstance(v, list) and len(v) == self.h:
            return [float(x) for x in v]
        raise ValueError(f"{name} must be a number or a list of {self.h} values")

    def path(self, p: dict[str, Any], label: str) -> list[float]:
        """A driver path given as {"values": [...]} or {"start": x, "growth": g|[...]} or {"line": name}."""
        if "line" in p:
            return self.fc(p["line"])
        if "values" in p:
            return self.vec(p["values"], label)
        start = float(p.get("start", 0.0))
        g = self.vec(p.get("growth", 0.0), f"{label}.growth")
        out, x = [], start
        for gi in g:
            x *= 1 + gi
            out.append(x)
        return out


Method = Callable[[Ctx, str, dict[str, Any]], tuple[list[float], str, list[str]]]


def m_values(ctx, name, p):
    return ctx.vec(p["values"], "values"), "analyst input values", []


def m_growth(ctx, name, p):
    rates = ctx.vec(p["rates"], "rates")
    base = float(p["base"]) if "base" in p else ctx.last(name)
    out, x = [], base
    for g in rates:
        x *= 1 + g
        out.append(x)
    return out, f"{name}[t] = {name}[t-1] × (1 + g[t]); g = {rates}", []


def m_cagr_trend(ctx, name, p):
    hist = ctx.hist(name)
    n = int(p.get("years", len(hist) - 1))
    g = T.cagr(hist[-1 - n], hist[-1], n)
    if g is None:
        raise ValueError("CAGR undefined (non-positive values)")
    out, x = [], hist[-1]
    for _ in range(ctx.h):
        x *= 1 + g
        out.append(x)
    return out, f"continue historical {n}y CAGR = {g:.4%}", []


def m_trend(ctx, name, p):
    kind = p.get("kind", "loglinear")
    res = R.trend(ctx.hist(name), ctx.h, kind)
    ctx.extras[name] = {"trend": res}
    return res["forecast"], f"{kind} time-trend regression on history (R²={res['r2']:.3f})", []


def m_holt(ctx, name, p):
    a, b = float(p.get("alpha", 0.5)), float(p.get("beta", 0.3))
    return T.holt(ctx.hist(name), ctx.h, a, b), f"Holt linear smoothing α={a}, β={b}", []


def m_ar1(ctx, name, p):
    res = T.ar1(ctx.hist(name), ctx.h)
    ctx.extras[name] = res
    return res["forecast"], f"AR(1): x[t] = {res['const']:.4g} + {res['phi']:.4f}·x[t-1]", []


def m_pct_of(ctx, name, p):
    of = p["of"]
    pct = ctx.vec(p["pct"], "pct")
    base = ctx.fc(of)
    return [b * r for b, r in zip(base, pct)], f"{name} = {of} × pct; pct = {pct}", [of]


def m_hist_avg_pct_of(ctx, name, p):
    of, n = p["of"], int(p.get("years", 3))
    hn, ho = ctx.hist(name)[-n:], ctx.hist(of)[-n:]
    ratio = sum(a / b for a, b in zip(hn, ho)) / len(hn)
    return [b * ratio for b in ctx.fc(of)], f"{name} = {of} × {n}y avg ratio ({ratio:.4%})", [of]


def m_fixed_variable(ctx, name, p):
    """Operating leverage: cost = fixed + variable_ratio × base. Estimated by regression if not given."""
    of = p.get("of", "revenue")
    if "fixed" in p and "variable_ratio" in p:
        fixed, vr = ctx.vec(p["fixed"], "fixed"), ctx.vec(p["variable_ratio"], "variable_ratio")
        how = "given"
    else:
        rep = R.ols_report(ctx.hist(name), [[v] for v in ctx.hist(of)], [of])
        f0, v0 = rep["_beta"]
        infl = ctx.vec(p.get("fixed_growth", 0.0), "fixed_growth")
        fixed, x = [], f0
        for g in infl:
            x *= 1 + g
            fixed.append(x)
        vr = [v0] * ctx.h
        ctx.extras[name] = {"regression": R.public(rep)}
        how = f"estimated by OLS on history (fixed={f0:.4g}, variable={v0:.4%}, R²={rep['r2']:.3f})"
    base = ctx.fc(of)
    return [f + v * b for f, v, b in zip(fixed, vr, base)], f"{name} = fixed + variable_ratio × {of}; {how}", [of]


def m_price_volume(ctx, name, p):
    vol, price = ctx.path(p["volume"], "volume"), ctx.path(p["price"], "price")
    k = float(p.get("unit_factor", 1.0))
    deps = [x["line"] for x in (p["volume"], p["price"]) if "line" in x]
    return [v * pr * k for v, pr in zip(vol, price)], f"{name} = volume × price × {k}", deps


def m_sum(ctx, name, p):
    items = p["items"]
    vals = [ctx.fc(i) for i in items]
    signs = p.get("signs", [1] * len(items))
    return [sum(s * v[t] for s, v in zip(signs, vals)) for t in range(ctx.h)], f"{name} = Σ {items}", list(items)


def m_market_share(ctx, name, p):
    size, share = ctx.path(p["market_size"], "market_size"), ctx.path(p["share"], "share")
    return [a * b for a, b in zip(size, share)], f"{name} = market size × share", []


def m_customers_arpu(ctx, name, p):
    cust, arpu = ctx.path(p["customers"], "customers"), ctx.path(p["arpu"], "arpu")
    k = float(p.get("periods_per_year", 1))
    return [c * a * k for c, a in zip(cust, arpu)], f"{name} = customers × ARPU × {k}", []


def m_backlog(ctx, name, p):
    """Order-backlog conversion (受注残): rev = backlog[t-1]×burn + orders[t]×in_period."""
    orders = ctx.path(p["orders"], "orders")
    burn, inp = ctx.vec(p["burn_rate"], "burn_rate"), ctx.vec(p["in_period_rate"], "in_period_rate")
    bl = float(p["backlog_start"])
    out, backlog = [], []
    for o, b, i in zip(orders, burn, inp):
        rev = bl * b + o * i
        bl = bl + o - rev
        out.append(rev)
        backlog.append(bl)
    ctx.extras[name] = {"backlog_end": backlog}
    return out, f"{name} = backlog[t-1]×burn + orders[t]×in_period; backlog rolls forward", []


def m_capacity(ctx, name, p):
    cap, util, price = (ctx.path(p[k], k) for k in ("capacity", "utilization", "price"))
    return [c * u * pr for c, u, pr in zip(cap, util, price)], f"{name} = capacity × utilization × price", []


def m_stores(ctx, name, p):
    """Retail: existing-store sales × (1+SSS) + new stores × sales per new store × ramp."""
    sss = ctx.vec(p["same_store_growth"], "same_store_growth")
    new_stores = ctx.vec(p["new_stores"], "new_stores")
    per_new = ctx.vec(p["sales_per_new_store"], "sales_per_new_store")
    ramp = float(p.get("first_year_ramp", 0.5))
    base = float(p["base"]) if "base" in p else ctx.last(name)
    out, x, prev_new = [], base, 0.0
    for g, n, s in zip(sss, new_stores, per_new):
        x = x * (1 + g) + prev_new * s * (1 - ramp) + n * s * ramp
        prev_new = n
        out.append(x)
    return out, f"{name} = prior × (1+SSS) + new stores × sales/store (ramp {ramp})", []


def m_driver_regression(ctx, name, p):
    drivers = {k: [float(x) for x in v] for k, v in p["drivers_history"].items()}
    future = {k: ctx.path(v, k) if isinstance(v, dict) else ctx.vec(v, k) for k, v in p["drivers_future"].items()}
    res = R.driver_forecast(ctx.hist(name), drivers, future, p.get("transform", "level"))
    ctx.extras[name] = res
    r2 = res["regression"]["r2"]
    return [f["forecast"] for f in res["forecast"]], (
        f"{name} regressed on {list(drivers)} ({res['transform']}, R²={r2:.3f}); future drivers assumed"), []


def m_yoy_pct_of_prior(ctx, name, p):
    """e.g. D&A as % of prior-year capex / PP&E."""
    of, pct = p["of"], ctx.vec(p["pct"], "pct")
    prior = [ctx.hist(of)[-1]] + ctx.fc(of)[:-1]
    return [a * r for a, r in zip(prior, pct)], f"{name} = {of}[t-1] × pct", [of]


METHODS: dict[str, Method] = {
    "values": m_values, "growth": m_growth, "cagr_trend": m_cagr_trend, "trend": m_trend, "holt": m_holt,
    "ar1": m_ar1, "pct_of": m_pct_of, "hist_avg_pct_of": m_hist_avg_pct_of, "fixed_variable": m_fixed_variable,
    "price_volume": m_price_volume, "sum": m_sum, "market_share": m_market_share,
    "customers_arpu": m_customers_arpu, "backlog": m_backlog, "capacity": m_capacity, "stores": m_stores,
    "driver_regression": m_driver_regression, "pct_of_prior": m_yoy_pct_of_prior,
}


# Parameter contract per method (drives validation, the JSON schema and the MODEL form editor).
# "path" = driver path: {"values": [...]} | {"start": x, "growth": g|[...]} | {"line": "<other line>"}
# "vec"  = number or list with one value per forecast year
METHOD_PARAMS: dict[str, dict[str, Any]] = {
    "values": {"required": {"values": "vec"}, "optional": {}, "judgmental": True,
               "desc": "explicit analyst / company-guidance values"},
    "growth": {"required": {"rates": "vec"}, "optional": {"base": "number"}, "judgmental": True,
               "desc": "x[t] = x[t-1] × (1 + g[t])"},
    "cagr_trend": {"required": {}, "optional": {"years": "int"}, "judgmental": False,
                   "desc": "continue the historical CAGR"},
    "trend": {"required": {}, "optional": {"kind": "enum:loglinear|linear"}, "judgmental": False,
              "desc": "time-trend regression on history"},
    "holt": {"required": {}, "optional": {"alpha": "number", "beta": "number"}, "judgmental": False,
             "desc": "Holt linear exponential smoothing"},
    "ar1": {"required": {}, "optional": {}, "judgmental": False, "desc": "AR(1) with mean reversion"},
    "pct_of": {"required": {"of": "line", "pct": "vec"}, "optional": {}, "judgmental": True,
               "desc": "x = other line × pct"},
    "hist_avg_pct_of": {"required": {"of": "line"}, "optional": {"years": "int"}, "judgmental": False,
                        "desc": "x = other line × average historical ratio"},
    "fixed_variable": {"required": {"of": "line"}, "optional": {"fixed": "vec", "variable_ratio": "vec",
                                                                "fixed_growth": "vec"},
                       "judgmental": False, "desc": "fixed + variable × base (OLS-estimated if not given)"},
    "pct_of_prior": {"required": {"of": "line", "pct": "vec"}, "optional": {}, "judgmental": True,
                     "desc": "x = other line[t-1] × pct"},
    "price_volume": {"required": {"volume": "path", "price": "path"}, "optional": {"unit_factor": "number"},
                     "judgmental": True, "desc": "volume × price"},
    "sum": {"required": {"items": "lines"}, "optional": {"signs": "list"}, "judgmental": False,
            "desc": "sum of other lines (segments)"},
    "market_share": {"required": {"market_size": "path", "share": "path"}, "optional": {}, "judgmental": True,
                     "desc": "market size × share"},
    "customers_arpu": {"required": {"customers": "path", "arpu": "path"}, "optional": {"periods_per_year": "number"},
                       "judgmental": True, "desc": "customers × ARPU"},
    "backlog": {"required": {"orders": "path", "burn_rate": "vec", "in_period_rate": "vec", "backlog_start": "number"},
                "optional": {}, "judgmental": True, "desc": "order backlog conversion"},
    "capacity": {"required": {"capacity": "path", "utilization": "path", "price": "path"}, "optional": {},
                 "judgmental": True, "desc": "capacity × utilization × price"},
    "stores": {"required": {"same_store_growth": "vec", "new_stores": "vec", "sales_per_new_store": "vec"},
               "optional": {"first_year_ramp": "number", "base": "number"}, "judgmental": True,
               "desc": "existing stores × (1+SSS) + new stores"},
    "driver_regression": {"required": {"drivers_history": "dict", "drivers_future": "dict"},
                          "optional": {"transform": "enum:level|log|growth"}, "judgmental": True,
                          "desc": "regress on macro / industry drivers"},
}
COMMON_PARAMS = {"source": "string", "note": "string"}


def check_params(name: str, spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one line spec — missing required params / unknown params."""
    method = spec.get("method")
    if method not in METHOD_PARAMS:
        return [f"line '{name}': unknown method {method!r}"], []
    meta = METHOD_PARAMS[method]
    params = spec.get("params") or {}
    errors = [f"line '{name}' ({method}): missing param '{k}'" for k in meta["required"] if k not in params]
    known = set(meta["required"]) | set(meta["optional"]) | set(COMMON_PARAMS)
    warnings = [f"line '{name}' ({method}): unknown param '{k}' (ignored)" for k in params if k not in known]
    return errors, warnings


def dependencies(spec: dict[str, Any]) -> list[str]:
    deps = []
    for k in ("of", "items"):
        v = spec.get("params", {}).get(k)
        if isinstance(v, str):
            deps.append(v)
        elif isinstance(v, list):
            deps.extend(v)
    for k in ("volume", "price", "market_size", "share", "customers", "arpu", "orders", "capacity",
              "utilization"):
        v = spec.get("params", {}).get(k)
        if isinstance(v, dict) and "line" in v:
            deps.append(v["line"])
    for v in (spec.get("params", {}).get("drivers_future") or {}).values():
        if isinstance(v, dict) and "line" in v:
            deps.append(v["line"])
    return deps


def topo_order(lines: dict[str, dict[str, Any]]) -> list[str]:
    order, state = [], {}

    def visit(n: str) -> None:
        if state.get(n) == 1:
            raise ValueError(f"circular dependency at line '{n}'")
        if state.get(n) == 2:
            return
        state[n] = 1
        for d in dependencies(lines[n]):
            if d in lines:
                visit(d)
        state[n] = 2
        order.append(n)

    for n in lines:
        visit(n)
    return order
