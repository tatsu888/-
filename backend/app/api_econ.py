"""ECON API — macro statistics: ~400 series (Japan + overseas), automatic updates, releases, analysis, flows.

Data: <data>/econ/series/<id>.json (observations, status, metrics), <data>/econ/state.json (releases, sweeps),
<data>/econ/dashboard.json / flows.json (recomputed after each update). The catalog is code (econ/catalog.py) plus
the user's own series (store: econ_custom), code fixes / pinned e-Stat tables (econ_overrides) and econ_disabled.

Automatic update: TERMINAL_ECON_AUTO (default on) — a sweep every 30 minutes fetches the series that are due
(daily data every 6 h, others every 12–72 h; failures back off). Market series are never taken from SIM.
"""
from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from .econ import analysis as A
from .econ import catalog as CAT
from .econ import sources as SRC
from .state import DATA_DIR, S

log = logging.getLogger("econ")
router = APIRouter(prefix="/api/econ")
CONC = {"fred": 2, "estat": 2, "ecb": 2, "eurostat": 2, "wb": 2, "dbnomics": 2, "nbs": 1, "ons": 2, "boe": 1, "statcan": 2, "bcb": 2,
        "market": 3}
DUE_H = {"D": 6, "W": 6, "M": 6, "Q": 12, "A": 48}     # hours between checks (new releases appear within ≈ 6 h)
KEEP_FROM = {"D": "1990-01-01", "W": "1970-01-01"}
_job: dict[str, Any] = {"running": False, "started": None, "finished": None, "total": 0, "done": 0, "ok": 0, "errors": 0,
                        "current": None, "last_summary": None}


def edir() -> Path:
    d = DATA_DIR / "econ" / "series"
    d.mkdir(parents=True, exist_ok=True)
    return d.parent


def _safe(i: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", i)


def read_series(i: str) -> dict[str, Any] | None:
    try:
        return json.loads((edir() / "series" / f"{_safe(i)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_series(i: str, rec: dict[str, Any]) -> None:
    p = edir() / "series" / f"{_safe(i)}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _read(name: str, default: Any) -> Any:
    try:
        return json.loads((edir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, obj: Any) -> None:
    p = edir() / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def entries() -> list[dict[str, Any]]:
    return CAT.all_entries(S.store.get("econ_custom") or [], S.store.get("econ_overrides") or {}, S.store.get("econ_disabled") or [])


def by_id() -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in entries()}


def obs_of(rec: dict[str, Any] | None) -> list[tuple[str, float]]:
    return [(d, v) for d, v in (rec or {}).get("obs") or []]


# ---- fetching --------------------------------------------------------------------------------------------
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=40, follow_redirects=True, headers=SRC.UA)


async def fetch_entry(c: httpx.AsyncClient, e: dict[str, Any], rec: dict[str, Any] | None) -> tuple[list[tuple[str, float]], dict[str, Any]]:
    src, code = e["source"], e["code"]
    if src == "fred":
        return await SRC.fred(c, code), {}
    if src == "estat":
        app = SRC.estat_app_id()
        if not app:
            raise SRC.SourceError("ESTAT_APP_ID が未設定（.env）— e-Stat で無料のアプリケーション ID を取得")
        bad = SRC.estat_app_id_problem(app)
        if bad:
            raise SRC.SourceError(bad)
        resolved = e.get("resolved")              # pinned by the user (override)
        spec_key = json.dumps(code, ensure_ascii=False, sort_keys=True)
        if not resolved:
            old = (rec or {}).get("resolved")
            resolved = old if old and old.get("spec") == spec_key else None
        if not resolved:
            resolved = {**await SRC.estat_resolve(c, code, app), "spec": spec_key}
        return await SRC.estat_fetch(c, resolved, app), {"resolved": resolved}
    if src == "ecb":
        return await SRC.ecb(c, code), {}
    if src == "eurostat":
        return await SRC.eurostat(c, code), {}
    if src == "wb":
        return await SRC.worldbank(c, code), {}
    if src == "dbnomics":
        return await SRC.dbnomics(c, code), {}
    if src == "nbs":
        spec_key = json.dumps(code, ensure_ascii=False, sort_keys=True)
        resolved = e.get("resolved") or ((rec or {}).get("resolved") if ((rec or {}).get("resolved") or {}).get("spec") == spec_key else None)
        if not resolved:
            resolved = {**await SRC.nbs_resolve(c, code), "spec": spec_key}
        obs = await SRC.nbs_fetch(c, resolved)
        adj = code.get("adj") or 0
        return [(d, v + adj) for d, v in obs], {"resolved": resolved}
    if src == "ons":
        return await SRC.ons(c, code), {}
    if src == "boe":
        return await SRC.boe(c, code), {}
    if src == "statcan":
        return await SRC.statcan(c, code), {}
    if src == "bcb":
        return await SRC.bcb(c, code, daily=e["freq"] == "D"), {}
    if src == "market":
        prov = (await S.provider(None)).name
        if prov == "sim":
            raise SRC.SourceError("SIM（DEMO）では市場系列を保存しない")
        bars = await S.history(code, "1D", 2600)
        return [(dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).strftime("%Y-%m-%d"), float(b["close"]))
                for b in bars if b.get("close")], {"provider": prov}
    raise SRC.SourceError(f"取得しない種類: {src}")


def is_due(e: dict[str, Any], rec: dict[str, Any] | None, now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    if not rec or not rec.get("tried_at"):
        return True
    h = (now - dt.datetime.fromisoformat(rec["tried_at"])).total_seconds() / 3600
    if rec.get("status") == "error":
        return h >= min(48, 2 ** min(int(rec.get("errors") or 1), 5))
    return h >= DUE_H.get(e["freq"], 12)


def detect_releases(e: dict[str, Any], old: list[tuple[str, float]], new: list[tuple[str, float]]) -> list[dict[str, Any]]:
    """New reference periods since the last fetch (the first load is not a release; daily series never are)."""
    if not old or e["freq"] == "D":
        return []
    last = old[-1][0]
    newer = [x for x in new if x[0] > last]
    if not newer:
        return []
    sig = A.transform(new, e["freq"], e["tf"])
    sd = {d: v for d, v in sig}
    vals = [v for _, v in sig]
    pos = {d: i for i, (d, _) in enumerate(sig)}
    out = []
    for d, v in newer:
        i = pos.get(d)
        sz = A.surprise_z(vals[: i + 1]) if i is not None and i >= 13 else None
        prev = next((x[1] for x in reversed(new) if x[0] < d), None)
        out.append({"id": e["id"], "name": e["name"], "country": e["country"], "category": e["category"], "key": e.get("key", False),
                    "ref": d, "value": v, "prev": prev, "signal": sd.get(d), "tf": e["tf"], "unit": e.get("unit"),
                    "surprise": sz, "good": e.get("good", 1), "at": _now()})
    return out


def derive(formula: dict[str, Any], get: Any) -> list[tuple[str, float]]:
    """{"lin": [[id, coef], ...]} or {"ratio": [a, b]} on the dates of the first input (others forward-filled ≤ 10 days)."""
    from bisect import bisect_right
    args = formula.get("lin") or [[formula["ratio"][0], 1], [formula["ratio"][1], 1]]
    series = [get(a) for a, _ in args]
    if not all(series):
        return []
    idx = [([d for d, _ in s], [v for _, v in s]) for s in series]
    out = []
    for d, v0 in series[0]:
        vals = [v0]
        for ds, vs in idx[1:]:
            i = bisect_right(ds, d) - 1
            if i < 0 or (dt.date.fromisoformat(d) - dt.date.fromisoformat(ds[i])).days > 10:
                vals = None
                break
            vals.append(vs[i])
        if not vals:
            continue
        if "ratio" in formula:
            if vals[1]:
                out.append((d, vals[0] / vals[1]))
        else:
            out.append((d, sum(c * x for (_, c), x in zip(args, vals))))
    return out


def _metrics_of(e: dict[str, Any], obs: list[tuple[str, float]]) -> dict[str, Any]:
    m = A.metrics(e, obs)
    m.pop("age_days", None)
    m.pop("stale", None)
    return m


def _store(e: dict[str, Any], rec: dict[str, Any], obs: list[tuple[str, float]]) -> None:
    keep = KEEP_FROM.get(e["freq"])
    if keep:
        obs = [x for x in obs if x[0] >= keep]
    rec["obs"] = [[d, v] for d, v in obs]
    rec["metrics"] = _metrics_of(e, obs)


async def update(ids: list[str] | None = None, force: bool = False, make_client: Any = client) -> dict[str, Any]:
    es = entries()
    todo = [e for e in es if e["source"] not in ("derived", "upload") and (not ids or e["id"] in ids)
            and (force or is_due(e, read_series(e["id"])))]
    sems = {k: asyncio.Semaphore(v) for k, v in CONC.items()}
    releases: list[dict[str, Any]] = []
    _job.update(running=True, started=_now(), finished=None, total=len(todo), done=0, ok=0, errors=0)

    async def one(c: httpx.AsyncClient, e: dict[str, Any]) -> None:
        async with sems.get(e["source"], asyncio.Semaphore(1)):
            _job["current"] = e["id"]
            rec = read_series(e["id"]) or {"id": e["id"]}
            try:
                obs, meta = await fetch_entry(c, e, rec)
                if not obs:
                    raise SRC.SourceError("データが空")
                releases.extend(detect_releases(e, obs_of(rec), obs))
                _store(e, rec, obs)
                rec.update(meta)
                rec.update(status="ok", error=None, errors=0, fetched_at=_now())
                _job["ok"] += 1
            except Exception as ex:  # noqa: BLE001 - one bad series must not stop the sweep
                rec.update(status="error", error=f"{type(ex).__name__}: {ex}"[:400], errors=int(rec.get("errors") or 0) + 1)
                _job["errors"] += 1
            rec["tried_at"] = _now()
            write_series(e["id"], rec)
            _job["done"] += 1
            await asyncio.sleep(0.2)

    try:
        async with make_client() as c:
            await asyncio.gather(*(one(c, e) for e in todo))
        # derived series from the stored inputs
        cache: dict[str, list[tuple[str, float]]] = {}

        def get(i: str) -> list[tuple[str, float]]:
            if i not in cache:
                cache[i] = obs_of(read_series(i))
            return cache[i]

        for e in es:
            if e["source"] == "derived" and (not ids or e["id"] in ids or any(a in (ids or []) for a in _formula_ids(e["code"]))):
                rec = read_series(e["id"]) or {"id": e["id"]}
                obs = derive(e["code"], get)
                if obs:
                    releases.extend(detect_releases(e, obs_of(rec), obs))
                    _store(e, rec, obs)
                    rec.update(status="ok", error=None, fetched_at=_now())
                else:
                    rec.update(status="error", error="入力の系列がそろっていない")
                rec["tried_at"] = _now()
                write_series(e["id"], rec)
        st = _read("state.json", {})
        st["releases"] = (st.get("releases", []) + releases)[-3000:]
        st["last_sweep"] = _now()
        _write("state.json", st)
        rebuild()
        if releases and S.hub:
            keyrel = [r for r in releases if r["key"]]
            if keyrel:
                await S.hub.broadcast({"type": "econ_release", "items": keyrel[:12]})
    finally:
        _job.update(running=False, finished=_now(), current=None,
                    last_summary={"fetched": len(todo), "ok": _job["ok"], "errors": _job["errors"], "releases": len(releases)})
    return {"fetched": len(todo), "ok": _job["ok"], "errors": _job["errors"], "releases": releases[:50]}


def _formula_ids(f: dict[str, Any]) -> list[str]:
    return [a for a, _ in f.get("lin", [])] + list(f.get("ratio", []))


def config() -> dict[str, Any]:
    return {"auto": True, "every_min": 30, **(S.store.get("econ_config") or {})}


async def loop(first_delay: float = 90.0) -> None:
    """Automatic updates: shortly after start-up, then every ``every_min`` minutes (config, changeable on screen)."""
    await asyncio.sleep(first_delay)
    while True:
        cfg = config()
        if cfg.get("auto", True) and not _job["running"]:
            try:
                await update()
            except Exception:  # noqa: BLE001
                log.warning("econ sweep failed", exc_info=True)
        await asyncio.sleep(max(10, int(cfg.get("every_min") or 30)) * 60)


# ---- analysis caches -------------------------------------------------------------------------------------
def _all_obs(es: list[dict[str, Any]]) -> dict[str, list[tuple[str, float]]]:
    return {e["id"]: obs_of(read_series(e["id"])) for e in es}


def build_dashboard(es: list[dict[str, Any]], obs: dict[str, list[tuple[str, float]]], today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    cur = today.isoformat()[:7]
    months = A.month_range(A.add_months(cur, -36), cur)
    prepared = {e["id"]: A.prepare(e, obs[e["id"]]) for e in es if obs.get(e["id"]) and e.get("good")}
    countries: dict[str, Any] = {}
    for cc in CAT.COUNTRIES:
        if cc == "GLOBAL":
            continue
        comp: dict[str, Any] = {}
        for name, axes in CAT.COMPOSITES.items():
            items = [prepared[e["id"]] for e in es if e["country"] == cc and e["axis"] in axes and e["id"] in prepared]
            if len(items) >= 3:
                comp[name] = A.composite(items, months)
        if not comp:
            continue
        sur_items = [(e, A.surprise_series(e, obs[e["id"]])) for e in es
                     if e["country"] == cc and e["axis"] in ("growth", "labor") and e.get("good") and obs.get(e["id"])]
        countries[cc] = {"composites": comp, "surprise": A.surprise_index([x for x in sur_items if x[1]], months),
                         "quadrant": A.gl_path(comp["growth"], comp["liquidity"], months) if "growth" in comp and "liquidity" in comp else {"available": False}}
    world: dict[str, Any] = {}
    for name in CAT.COMPOSITES:
        ser = {}
        for m in months:
            vals = [countries[c]["composites"][name][m]["value"] for c in CAT.WORLD
                    if c in countries and name in countries[c]["composites"] and m in countries[c]["composites"][name]]
            if len(vals) >= 2:
                ser[m] = {"value": sum(vals) / len(vals), "n": len(vals), "diffusion": None}
        if ser:
            world[name] = ser
    if world:
        countries["WORLD"] = {"composites": world, "surprise": {},
                              "quadrant": A.gl_path(world["growth"], world["liquidity"], months) if "growth" in world and "liquidity" in world else {"available": False}}
    # heatmap: country × category → mean of good × z of the latest values (fresh series only)
    heat: dict[str, dict[str, Any]] = {}
    for e in es:
        m = A.metrics(e, obs.get(e["id"]) or [], today) if obs.get(e["id"]) else None
        if not m or m.get("z") is None or m.get("stale") or not e.get("good"):
            continue
        cell = heat.setdefault(e["country"], {}).setdefault(e["category"], {"sum": 0.0, "n": 0, "ids": []})
        cell["sum"] += e["good"] * m["z"]
        cell["n"] += 1
        cell["ids"].append(e["id"])
    for c in heat.values():
        for cell in c.values():
            cell["value"] = cell["sum"] / cell["n"]
    # global diffusion of growth: share of countries whose growth composite rose over 3 months
    g = [(cc, d["composites"]["growth"]) for cc, d in countries.items() if cc != "WORLD" and "growth" in d["composites"]]
    up = [cc for cc, s in g if cur in s and A.add_months(cur, -3) in s and s[cur]["value"] > s[A.add_months(cur, -3)]["value"]]
    return {"generated_at": _now(), "months": months, "countries": countries, "heatmap": heat,
            "global_diffusion": {"up": up, "n": len([1 for cc, s in g if cur in s and A.add_months(cur, -3) in s])}}


def build_flows(es: list[dict[str, Any]], obs: dict[str, list[tuple[str, float]]]) -> dict[str, Any]:
    fx = {ccy: obs.get(i) for ccy, (i, _) in CAT.FX_FOR.items()}
    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in CAT.FLOW_GROUPS}
    for e in es:
        meta = e.get("flow")
        if not meta or not obs.get(e["id"]):
            continue
        fl = A.flows_native(e, obs[e["id"]])
        usd = A.to_usd_bn(e, fl, fx.get(meta.get("ccy")) if meta.get("ccy") != "USD" else None)
        groups.setdefault(meta["group"], []).append({"entry": e, "flows": fl, "usd": usd, "m": A.flow_metrics(e, fl, usd)})
    out = {}
    for g, rows in groups.items():
        out[g] = {"rows": [{"id": r["entry"]["id"], "name": r["entry"]["name"], "country": r["entry"]["country"],
                            "unit": r["entry"].get("unit"), "kind": r["m"].get("kind"), "sign": r["m"].get("sign"),
                            "in_total": (r["entry"].get("flow") or {}).get("total", True) and bool(r["usd"]),
                            **{k: v for k, v in r["m"].items() if k not in ("kind", "sign")}} for r in rows],
                  "total": A.group_total(rows)}
    return {"generated_at": _now(), "groups": out}


def rebuild() -> None:
    es = entries()
    obs = _all_obs(es)
    _write("dashboard.json", build_dashboard(es, obs))
    _write("flows.json", build_flows(es, obs))


# ---- endpoints -------------------------------------------------------------------------------------------
def _row(e: dict[str, Any], rec: dict[str, Any] | None, today: dt.date) -> dict[str, Any]:
    m = dict((rec or {}).get("metrics") or {})
    if m.get("last_date"):
        m["age_days"] = (today - dt.date.fromisoformat(m["last_date"])).days
        m["stale"] = m["age_days"] > A.STALE_DAYS[e["freq"]]
    return {"id": e["id"], "name": e["name"], "country": e["country"], "country_name": CAT.COUNTRIES.get(e["country"]),
            "category": e["category"], "axis": e["axis"], "source": e["source"], "freq": e["freq"], "tf": e["tf"],
            "good": e.get("good"), "unit": e.get("unit"), "key": e.get("key"), "custom": e.get("custom", False),
            "flow": bool(e.get("flow")), "status": (rec or {}).get("status") or "未取得", "error": (rec or {}).get("error"),
            "fetched_at": (rec or {}).get("fetched_at"), "code": e["code"] if not isinstance(e["code"], dict) else None, **m}


@router.get("/catalog")
async def catalog_ep(country: str | None = None, category: str | None = None, source: str | None = None, q: str | None = None,
                     key_only: bool = False):
    today = dt.date.today()
    rows = []
    for e in entries():
        if (country and e["country"] != country) or (category and e["category"] != category) or (source and e["source"] != source):
            continue
        if key_only and not e.get("key"):
            continue
        if q and q.lower() not in (e["name"] + " " + e["id"] + " " + str(e["code"])).lower():
            continue
        rows.append(_row(e, read_series(e["id"]), today))
    return {"rows": rows, "countries": CAT.COUNTRIES, "categories": CAT.CATEGORIES, "axes": CAT.AXES}


@router.get("/series/{sid}")
async def series_ep(sid: str, tf: str | None = None, since: str | None = None):
    e = by_id().get(sid)
    if not e:
        raise HTTPException(404, "unknown series")
    rec = read_series(sid) or {}
    obs = obs_of(rec)
    if since:
        obs_v = [x for x in obs if x[0] >= since]
    else:
        obs_v = obs
    sig = A.transform(obs, e["freq"], tf or e["tf"])
    if since:
        sig = [x for x in sig if x[0] >= since]
    out = {"entry": {k: v for k, v in e.items()}, "row": _row(e, rec, dt.date.today()), "obs": obs_v, "signal": sig,
           "tf": tf or e["tf"], "url": SRC.source_url({**e, "resolved": rec.get("resolved")}), "resolved": rec.get("resolved")}
    if e.get("flow"):
        fl = A.flows_native(e, obs)
        out["flows"] = A.flow_metrics(e, fl)
    return out


@router.get("/dashboard")
async def dashboard_ep():
    d = _read("dashboard.json", None)
    if d is None:
        rebuild()
        d = _read("dashboard.json", {})
    return {**d, "country_names": CAT.COUNTRIES}


@router.get("/matrix")
async def matrix_ep():
    """World matrix (Bloomberg ECST style): country × headline indicator → latest value, previous, change, z, date."""
    today = dt.date.today()
    eb = by_id()
    rows = []
    for cc, cols in CAT.MATRIX_ROWS.items():
        cells: dict[str, Any] = {}
        for col, ids in cols.items():
            for i in ids:
                e = eb.get(i)
                rec = read_series(i) if e else None
                if not e or not rec or rec.get("status") != "ok" or not (rec.get("metrics") or {}).get("last_date"):
                    continue
                r = _row(e, rec, today)
                val = r.get("signal") if r.get("signal") is not None else r.get("last")
                prev = r.get("signal_prev") if r.get("signal") is not None else r.get("prev")
                cells[col] = {"id": i, "name": e["name"], "value": val, "prev": prev, "chg": val - prev if prev is not None else None,
                              "date": r.get("signal_date") or r.get("last_date"), "z": r.get("z"), "good": e.get("good", 1),
                              "axis": e["axis"], "pct": e["tf"] == "yoy" or e.get("unit") == "%", "stale": r.get("stale"), "freq": e["freq"]}
                break
        rows.append({"country": cc, "name": CAT.COUNTRIES.get(cc, cc), "cells": cells})
    return {"columns": [{"key": k, "ja": ja, "en": en} for k, ja, en in CAT.MATRIX_COLS], "rows": rows}


@router.get("/flows")
async def flows_ep():
    d = _read("flows.json", None)
    if d is None:
        rebuild()
        d = _read("flows.json", {})
    return d


@router.get("/releases")
async def releases_ep(days: int = 14, key_only: bool = False):
    lim = (dt.datetime.now() - dt.timedelta(days=days)).isoformat()
    rel = [r for r in _read("state.json", {}).get("releases", []) if r["at"] >= lim and (r.get("key") or not key_only)]
    return {"rows": rel[::-1]}


@router.get("/regime")
async def regime_ep(id: str, asset: str = "TVC:TOPIX", lag: int | None = None):
    e = by_id().get(id)
    if not e:
        raise HTTPException(404, "unknown series")
    obs = obs_of(read_series(id))
    if not obs:
        raise HTTPException(400, "系列のデータがまだない（更新してから）")
    sig = A.signal_monthly(e, obs)
    mk = next((x for x in entries() if x["source"] == "market" and x["code"] == asset), None)
    a_obs = obs_of(read_series(mk["id"])) if mk else []
    if not a_obs:
        try:
            bars = await S.history(asset, "1D", 2600)
        except HTTPException as ex:
            raise HTTPException(502, f"資産の価格を取得できない: {ex.detail}") from ex
        a_obs = [(dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).strftime("%Y-%m-%d"), b["close"]) for b in bars]
        demo = (await S.provider(None)).name == "sim"
    else:
        demo = False
    res = A.regime(sig, A.to_monthly(a_obs), e["lag_m"] if lag is None else lag, e.get("good") or 1)
    return {**res, "id": id, "name": e["name"], "asset": asset, "lag_m": e["lag_m"] if lag is None else lag, "demo": demo}


class UpdateReq(BaseModel):
    ids: list[str] | None = None
    source: str | None = None
    country: str | None = None
    force: bool = False


@router.post("/update")
async def update_ep(req: UpdateReq):
    if _job["running"]:
        return {"started": False, "job": _job}
    ids = req.ids
    if req.source or req.country:
        ids = [e["id"] for e in entries() if (not req.source or e["source"] == req.source) and (not req.country or e["country"] == req.country)]
    asyncio.create_task(update(ids, req.force))
    await asyncio.sleep(0)
    return {"started": True, "job": _job}


@router.get("/status")
async def status_ep():
    today = dt.date.today()
    by_src: dict[str, dict[str, int]] = {}
    errors = []
    for e in entries():
        rec = read_series(e["id"])
        row = _row(e, rec, today)
        st = "stale" if row.get("stale") and row["status"] == "ok" else row["status"]
        by_src.setdefault(e["source"], {}).setdefault(st, 0)
        by_src[e["source"]][st] += 1
        if row["status"] == "error":
            errors.append({"id": e["id"], "name": e["name"], "source": e["source"], "error": row["error"]})
    return {"job": _job, "sources": by_src, "errors": errors[:200], "keys": {"FRED_API_KEY": bool(SRC.fred_key()),
            "ESTAT_APP_ID": bool(SRC.estat_app_id()) and not SRC.estat_app_id_problem()},
            "key_problems": {"ESTAT_APP_ID": SRC.estat_app_id_problem()}, "last_sweep": _read("state.json", {}).get("last_sweep"),
            "auto": os.environ.get("TERMINAL_ECON_AUTO", "1") != "0" and config().get("auto", True), "config": config(),
            "auto_env": os.environ.get("TERMINAL_ECON_AUTO", "1") != "0",
            "due_hours": DUE_H, "total": len(entries())}


class EconConfig(BaseModel):
    auto: bool | None = None
    every_min: int | None = None


@router.put("/config")
async def put_config(req: EconConfig):
    cfg = config()
    if req.auto is not None:
        cfg["auto"] = req.auto
    if req.every_min is not None:
        if not 10 <= req.every_min <= 1440:
            raise HTTPException(400, "10〜1440 分")
        cfg["every_min"] = req.every_min
    S.store.set("econ_config", cfg)
    return cfg


@router.get("/search")
async def search_ep(source: str, q: str, stats_code: str | None = None):
    async with client() as c:
        try:
            if source == "fred":
                return {"rows": await SRC.fred_search(c, q)}
            if source == "estat":
                return {"rows": await SRC.estat_search(c, q, stats_code)}
        except SRC.SourceError as e:
            raise HTTPException(400, str(e)) from e
        except httpx.HTTPError as e:
            raise HTTPException(502, f"{type(e).__name__}: {e}") from e
    raise HTTPException(400, "source は fred か estat")


class TestReq(BaseModel):
    source: str
    code: Any
    freq: str = "M"
    tf: str = "lvl"


@router.post("/test")
async def test_ep(req: TestReq):
    """Fetch a code once without saving (to check a new or corrected series)."""
    e = {"id": "TEST", "name": "test", "country": "GLOBAL", "category": "景気・生産", "axis": "growth", "source": req.source,
         "code": req.code, "freq": req.freq, "tf": req.tf, "good": 1}
    try:
        async with client() as c:
            obs, meta = await fetch_entry(c, e, None)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(400, f"{type(ex).__name__}: {ex}") from ex
    return {"n": len(obs), "first": obs[:3], "last": obs[-3:], "meta": meta}


FIELDS = ("id", "name", "country", "category", "axis", "source", "code", "freq", "tf", "good", "unit", "key")


class CustomReq(BaseModel):
    entry: dict[str, Any]


def _validate(x: dict[str, Any]) -> dict[str, Any]:
    e = {k: x.get(k) for k in FIELDS if x.get(k) is not None}
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{2,60}", str(e.get("id", ""))):
        raise HTTPException(400, "id は英数字・. _ - で 2〜60 文字（例 JP.MY_SERIES）")
    for k, ok in (("freq", A.Z_WINDOW), ("tf", ("yoy", "lvl", "d1", "d12")), ("axis", CAT.AXES)):
        if e.get(k) not in ok:
            raise HTTPException(400, f"{k} が不正")
    if e.get("source") not in ("fred", "estat", "ecb", "eurostat", "wb", "dbnomics", "nbs", "ons", "boe", "statcan", "bcb", "market", "upload"):
        raise HTTPException(400, "source が不正")
    e.setdefault("country", "GLOBAL")
    e.setdefault("category", "景気・生産")
    e.setdefault("good", 1)
    if x.get("flow"):
        e["flow"] = {k: x["flow"].get(k) for k in ("kind", "group", "ccy", "mult", "sign", "total") if k in x["flow"]}
    return e


@router.post("/custom")
async def add_custom(req: CustomReq):
    e = _validate(req.entry)
    if e["id"] in {x["id"] for x in CAT.CATALOG}:
        raise HTTPException(400, "組み込みの系列と同じ id")
    cus = [c for c in (S.store.get("econ_custom") or []) if c["id"] != e["id"]] + [e]
    S.store.set("econ_custom", cus)
    return {"ok": True, "entry": e}


@router.delete("/custom/{sid}")
async def del_custom(sid: str):
    S.store.set("econ_custom", [c for c in (S.store.get("econ_custom") or []) if c["id"] != sid])
    return {"ok": True}


class OverrideReq(BaseModel):
    code: Any | None = None
    resolved: dict[str, Any] | None = None
    disabled: bool | None = None
    clear: bool = False


@router.put("/override/{sid}")
async def override_ep(sid: str, req: OverrideReq):
    """Fix a code, pin an e-Stat table (statsDataId + class codes), or switch a series off. ``clear`` removes the fix."""
    if sid not in {e["id"] for e in CAT.all_entries(S.store.get("econ_custom") or [])}:
        raise HTTPException(404, "unknown series")
    ov = dict(S.store.get("econ_overrides") or {})
    if req.clear:
        ov.pop(sid, None)
    else:
        o = dict(ov.get(sid) or {})
        if req.code is not None:
            o["code"] = req.code
        if req.resolved is not None:
            if not req.resolved.get("statsDataId"):
                raise HTTPException(400, "statsDataId が必要")
            o["resolved"] = {**req.resolved, "pinned": True}
        ov[sid] = o
    S.store.set("econ_overrides", ov)
    dis = [d for d in (S.store.get("econ_disabled") or []) if d != sid]
    if req.disabled:
        dis.append(sid)
    S.store.set("econ_disabled", dis)
    rec = read_series(sid)
    if rec and (req.code is not None or req.resolved is not None or req.clear):
        rec.pop("resolved", None)
        rec["tried_at"] = None                     # fetch again on the next sweep
        write_series(sid, rec)
    return {"ok": True, "override": ov.get(sid), "disabled": bool(req.disabled)}


@router.get("/estat/candidates/{sid}")
async def estat_candidates(sid: str):
    """The tables an e-Stat recipe finds, with the class codes it would choose — to review and pin."""
    e = by_id().get(sid)
    if not e or e["source"] != "estat":
        raise HTTPException(404, "e-Stat の系列ではない")
    app = SRC.estat_app_id()
    if not app:
        raise HTTPException(400, "ESTAT_APP_ID が未設定")
    spec = e["code"]
    async with client() as c:
        params = {"appId": app, "searchWord": spec["search"], "limit": 30, "lang": "J"}
        if spec.get("stats_code"):
            params["statsCode"] = spec["stats_code"]
        tables = SRC.estat_tables((await c.get(f"{SRC.ESTAT}/getStatsList", params=params)).json())[:8]
        out = []
        for t in tables:
            meta = SRC.estat_classes((await c.get(f"{SRC.ESTAT}/getMetaInfo", params={"appId": app, "statsDataId": t["id"], "lang": "J"})).json())
            ch = SRC.estat_choose(meta, spec.get("select") or [], t["title"])
            out.append({**t, **ch, "classes": [{"id": k["id"], "name": k["name"], "n": len(k["classes"]),
                                                 "items": [{"code": x["code"], "name": x["name"]} for x in k["classes"][:60]]}
                                                for k in meta if k["id"] != "time"]})
    return {"id": sid, "spec": spec, "current": (read_series(sid) or {}).get("resolved"), "candidates": out}


# ---- uploads (MOF 対外対内証券投資、JPX 投資部門別、自分の CSV / Excel …) ---------------------------------------
def _rows_from_file(name: str, content: bytes) -> list[list[Any]]:
    if name.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(400, "文字コードを判別できない（UTF-8 か Shift_JIS）")
    return [r for r in csv.reader(io.StringIO(text))]


def parse_date_cell(v: Any) -> str | None:
    """Excel dates, 2024/01/05, 2024-01, 2024年1月5日, 「2024年1月7日～1月13日」(the end of a range), Excel serials."""
    if isinstance(v, (dt.datetime, dt.date)):
        return (v.date() if isinstance(v, dt.datetime) else v).isoformat()
    if isinstance(v, (int, float)) and 20000 < v < 80000:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    t = str(v or "").strip().replace("／", "/")
    if not t:
        return None
    parts = re.split(r"[～~〜]", t)
    first = re.search(r"(\d{4})\s*[/\-.年]\s*(\d{1,2})(?:\s*[/\-.月]\s*(\d{1,2}))?", parts[0])
    if not first:
        return None
    y, m, d = int(first.group(1)), int(first.group(2)), int(first.group(3) or 1)
    if len(parts) > 1:                       # a range → its end (weekly data)
        end = re.search(r"(?:(\d{4})\s*[/\-.年]\s*)?(\d{1,2})\s*[/\-.月]\s*(\d{1,2})", parts[1])
        if end:
            y2 = int(end.group(1)) if end.group(1) else (y + 1 if int(end.group(2)) < m else y)
            y, m, d = y2, int(end.group(2)), int(end.group(3))
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def detect_table(rows: list[list[Any]]) -> dict[str, Any]:
    """Header row + date column: the column whose cells below parse as dates most often."""
    best = None
    for hi in range(min(30, len(rows))):
        head = rows[hi]
        if sum(1 for x in head if str(x or "").strip()) < 2:
            continue
        body = rows[hi + 1: hi + 60]
        for ci in range(len(head)):
            n = sum(1 for r in body if ci < len(r) and parse_date_cell(r[ci]))
            if n >= max(3, len(body) // 3) and (best is None or n > best[2]):
                best = (hi, ci, n)
    if not best:
        raise HTTPException(400, "日付の列が見つからない（1 列目に日付、1 行目に見出しの表にする）")
    hi, ci, _ = best
    head = [str(x or "").strip() or f"列{i + 1}" for i, x in enumerate(rows[hi])]
    cols = []
    for j, h in enumerate(head):
        if j == ci:
            continue
        vals = [SRC.num(r[j]) for r in rows[hi + 1:] if j < len(r)]
        k = sum(1 for v in vals if v is not None)
        if k >= 3:
            cols.append({"index": j, "name": h, "numeric": k})
    return {"header_row": hi, "date_col": ci, "date_name": head[ci], "columns": cols}


def series_from_table(rows: list[list[Any]], t: dict[str, Any], col: int) -> list[tuple[str, float]]:
    out = []
    for r in rows[t["header_row"] + 1:]:
        if t["date_col"] < len(r) and col < len(r):
            d, v = parse_date_cell(r[t["date_col"]]), SRC.num(r[col])
            if d and v is not None:
                out.append((d, v))
    return sorted(dict(out).items())


@router.post("/upload")
async def upload_ep(file: UploadFile = File(...)):
    content = await file.read()
    rows = _rows_from_file(file.filename or "x.csv", content)
    t = detect_table(rows)
    tok = uuid.uuid4().hex[:12]
    (edir() / "uploads").mkdir(exist_ok=True)
    (edir() / "uploads" / f"{tok}.json").write_text(json.dumps({"name": file.filename, "rows": [[str(x) if isinstance(x, (dt.date, dt.datetime)) else x for x in r] for r in rows]},
                                                               ensure_ascii=False, default=str), encoding="utf-8")
    sample = [[str(c) for c in r[:8]] for r in rows[t["header_row"]: t["header_row"] + 6]]
    return {"token": tok, "file": file.filename, **t, "sample": sample}


class ApplyCol(BaseModel):
    index: int
    entry: dict[str, Any]


class ApplyReq(BaseModel):
    token: str
    columns: list[ApplyCol]


@router.post("/upload/apply")
async def upload_apply(req: ApplyReq):
    p = edir() / "uploads" / f"{re.sub(r'[^a-f0-9]', '', req.token)}.json"
    if not p.exists():
        raise HTTPException(404, "アップロードの期限切れ（もう一度アップロード）")
    rows = json.loads(p.read_text(encoding="utf-8"))["rows"]
    t = detect_table(rows)
    done = []
    for c in req.columns:
        e = _validate({**c.entry, "source": "upload", "code": {"column": c.index}})
        obs = series_from_table(rows, t, c.index)
        if not obs:
            raise HTTPException(400, f"列 {c.index + 1} に数値がない")
        cus = [x for x in (S.store.get("econ_custom") or []) if x["id"] != e["id"]] + [e]
        S.store.set("econ_custom", cus)
        full = by_id()[e["id"]]
        rec = read_series(e["id"]) or {"id": e["id"]}
        merged = dict(obs_of(rec))
        merged.update(obs)
        new = sorted(merged.items())
        rel = detect_releases(full, obs_of(rec), new)
        _store(full, rec, new)
        rec.update(status="ok", error=None, fetched_at=_now(), tried_at=_now(), uploaded=req.token)
        write_series(e["id"], rec)
        if rel:
            st = _read("state.json", {})
            st["releases"] = (st.get("releases", []) + rel)[-3000:]
            _write("state.json", st)
        done.append({"id": e["id"], "n": len(new), "last": new[-1]})
    rebuild()
    return {"series": done}
