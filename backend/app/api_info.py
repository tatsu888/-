"""INFO API — the information hub (TOP): feeds from central banks / governments / regulators / news, filings
(EDINET for Japan, SEC EDGAR for the US), company news (Google News RSS), tagging to the coverage, keyword alerts.

Data: <data>/info/items.json (feed items, last 5000), feed_status.json, edinet.json (documents by date),
edinet_codes.json (EDINET code → security code), edgar.json, news_cache.json, state.json.
Store: info_feeds_custom, info_feeds_disabled, info_keywords, info_config {auto, every_min}.
Automatic: feeds every ``every_min`` minutes (default 20); EDINET (needs EDINET_API_KEY) and EDGAR (needs
SEC_USER_AGENT) once a day. Alerts (coverage hit or keyword) → websocket ``info_alert`` (not on a feed's first load).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from .info import feeds as FD
from .info import filings as FL
from .state import DATA_DIR, S

log = logging.getLogger("info")
router = APIRouter(prefix="/api/info")
UA = {"User-Agent": "Mozilla/5.0 (analyst-terminal; information hub)"}
_job: dict[str, Any] = {"running": False, "started": None, "finished": None, "last": None}


def idir() -> Path:
    d = DATA_DIR / "info"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(name: str, default: Any) -> Any:
    try:
        return json.loads((idir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, obj: Any) -> None:
    p = idir() / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _utc() -> str:
    """UTC like the feeds' published (…Z), so the two sort and compare together."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, follow_redirects=True, headers=UA)


def config() -> dict[str, Any]:
    return {"auto": True, "every_min": 20, **(S.store.get("info_config") or {})}


def feeds() -> list[dict[str, Any]]:
    dis = set(S.store.get("info_feeds_disabled") or [])
    out = []
    for f in FD.DEFAULT_FEEDS + [{**c, "custom": True} for c in (S.store.get("info_feeds_custom") or [])]:
        out.append({**f, "enabled": f["id"] not in dis})
    return out


def keywords() -> list[str]:
    kw = S.store.get("info_keywords")
    return list(FD.DEFAULT_KEYWORDS if kw is None else kw)


def coverage_list() -> list[dict[str, Any]]:
    from .api_coverage import state as cov_state
    out = [{"ticker": x["ticker"], "name": x.get("name"), "symbol": x.get("symbol")} for x in cov_state()["items"]]
    have = {x["ticker"] for x in out}
    for p in S.store.get("portfolio") or []:
        t = FL.ticker_of_symbol(p.get("symbol") or "")
        if t and t not in have and len(t) >= 2:
            out.append({"ticker": t, "name": None, "symbol": p["symbol"]})
            have.add(t)
    return out


# ---- feeds ---------------------------------------------------------------------------------------------
async def fetch_feed(c: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    r = await c.get(url)
    r.raise_for_status()
    return FD.parse_feed(r.text)


async def update_feeds(make_client: Any = client) -> dict[str, Any]:
    items = _read("items.json", [])
    status = _read("feed_status.json", {})
    known = {i["guid"] for i in items}
    cov, kws = coverage_list(), keywords()
    new: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(4)

    async def one(c: httpx.AsyncClient, f: dict[str, Any]) -> None:
        async with sem:
            first = f["id"] not in status or not status[f["id"]].get("ok_once")
            try:
                parsed = await fetch_feed(c, f["url"])
                status[f["id"]] = {"ok": True, "ok_once": True, "n": len(parsed), "at": _now(), "error": None}
            except Exception as e:  # noqa: BLE001 - one broken feed must not stop the others
                status[f["id"]] = {**status.get(f["id"], {}), "ok": False, "at": _now(), "error": f"{type(e).__name__}: {e}"[:300]}
                return
            for it in parsed:
                if it["guid"] in known:
                    continue
                known.add(it["guid"])
                t = {**FD.tag_item(it, cov, kws), "feed": f["id"], "feed_name": f["name"], "category": f["category"],
                     "region": f["region"], "fetched": _utc()}
                new.append(t)
                if not first and (t["tickers"] or t["keywords"]):
                    alerts.append(t)

    async with make_client() as c:
        await asyncio.gather(*(one(c, f) for f in feeds() if f["enabled"]))
    items = sorted(items + new, key=lambda x: x.get("published") or x["fetched"])[-5000:]
    _write("items.json", items)
    _write("feed_status.json", status)
    if alerts and S.hub:
        await S.hub.broadcast({"type": "info_alert", "items": [{k: a.get(k) for k in ("title", "link", "feed_name", "tickers", "keywords")}
                                                               for a in alerts[:10]]})
    return {"new": len(new), "alerts": len(alerts), "errors": sum(1 for v in status.values() if not v.get("ok"))}


# ---- EDINET / EDGAR ------------------------------------------------------------------------------------
async def _edinet_codes(c: httpx.AsyncClient) -> dict[str, str]:
    cached = _read("edinet_codes.json", None)
    if cached and cached.get("at", "")[:10] >= (dt.date.today() - dt.timedelta(days=7)).isoformat():
        return cached["map"]
    r = await c.get(FL.EDINET_CODES)
    r.raise_for_status()
    m = FL.parse_edinet_codes(r.content)
    _write("edinet_codes.json", {"at": _now(), "map": m})
    return m


async def update_edinet(make_client: Any = client, days: int = 7) -> dict[str, Any]:
    key = os.environ.get("EDINET_API_KEY")
    if not key:
        return {"skipped": "EDINET_API_KEY が未設定（TOP → 7) KEYS）"}
    data = _read("edinet.json", {"dates": {}, "errors": {}})
    primed = bool(data.get("at"))                     # the very first fetch is history: no alerts
    cov = {x["ticker"] for x in coverage_list()}
    alerts = []
    today = dt.date.today()
    async with make_client() as c:
        try:
            codes = await _edinet_codes(c)
        except Exception as e:  # noqa: BLE001 - filings still work for listed filers without the list
            codes = {}
            data["errors"]["codes"] = f"{type(e).__name__}: {e}"[:200]
        for k in range(days):
            d = (today - dt.timedelta(days=k)).isoformat()
            if d in data["dates"] and k > 1:
                continue
            try:
                r = await c.get(f"{FL.EDINET}/documents.json", params={"date": d, "type": 2, "Subscription-Key": key})
                r.raise_for_status()
                docs = FL.parse_edinet_list(r.json())
            except Exception as e:  # noqa: BLE001
                data["errors"][d] = f"{type(e).__name__}: {e}"[:200]
                continue
            old = {x["doc_id"] for x in data["dates"].get(d, [])}
            for x in docs:
                x["ticker"] = FL.edinet_ticker(x, codes)
                if primed and x["ticker"] in cov and x["doc_id"] not in old:
                    alerts.append(x)
            data["dates"][d] = docs
            data["errors"].pop(d, None)
    keep = (today - dt.timedelta(days=400)).isoformat()
    data["dates"] = {d: v for d, v in data["dates"].items() if d >= keep}
    data["at"] = _now()
    _write("edinet.json", data)
    if alerts and S.hub:
        await S.hub.broadcast({"type": "info_alert", "items": [{"title": f"{a['ticker']} {a['filer']}：{a['desc']}", "link": None,
                                                                "feed_name": "EDINET", "tickers": [a["ticker"]], "keywords": [a["kind"]]}
                                                               for a in alerts[:10]]})
    return {"dates": len(data["dates"]), "alerts": len(alerts)}


def us_symbols() -> list[str]:
    from .api_coverage import state as cov_state
    syms = [x.get("symbol") or "" for x in cov_state()["items"]] + [p.get("symbol") or "" for p in S.store.get("portfolio") or []]
    for v in (S.store.get("watchlists") or {}).values():
        syms += list(v or [])
    return [s for s in dict.fromkeys(syms) if s.upper().startswith(("NASDAQ:", "NYSE:", "AMEX:", "BATS:", "NYSEARCA:"))][:60]


async def update_edgar(make_client: Any = client) -> dict[str, Any]:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        return {"skipped": "SEC_USER_AGENT が未設定（TOP → 7) KEYS）"}
    data = _read("edgar.json", {"tickers": {}, "map_at": None, "map": {}})
    syms = us_symbols()
    if not syms:
        return {"skipped": "米国株がカバレッジ・PORT・ウォッチリストにない"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": ua}) if make_client is client else make_client() as c:
        if not data.get("map") or (data.get("map_at") or "")[:10] < (dt.date.today() - dt.timedelta(days=7)).isoformat():
            r = await c.get(FL.SEC_TICKERS)
            r.raise_for_status()
            data["map"], data["map_at"] = FL.parse_sec_tickers(r.json()), _now()
        for s in syms:
            t = FL.ticker_of_symbol(s)
            cik = data["map"].get(t)
            if not cik or (data["tickers"].get(t) or {}).get("at", "")[:10] == dt.date.today().isoformat():
                continue
            try:
                r = await c.get(FL.SEC_SUBMISSIONS.format(cik=cik))
                r.raise_for_status()
                data["tickers"][t] = {"at": _now(), "cik": cik, "filings": FL.parse_sec_submissions(r.json())}
            except Exception as e:  # noqa: BLE001
                data["tickers"][t] = {**data["tickers"].get(t, {}), "error": f"{type(e).__name__}: {e}"[:200]}
            await asyncio.sleep(0.15)       # SEC: at most 10 requests per second
    _write("edgar.json", data)
    return {"tickers": len(data["tickers"])}


async def update_all(daily: bool = False) -> dict[str, Any]:
    _job.update(running=True, started=_now())
    out: dict[str, Any] = {}
    try:
        out["feeds"] = await update_feeds()
        out["edinet"] = await update_edinet()           # today and yesterday on every sweep: filings arrive all day
        st = _read("state.json", {})
        if daily or (st.get("daily_at") or "")[:10] != dt.date.today().isoformat():
            out["edgar"] = await update_edgar()           # once a day (one request per US stock)
            st["daily_at"] = _now()
        st["last_run"], st["last"] = _now(), out
        _write("state.json", st)
    finally:
        _job.update(running=False, finished=_now(), last=out)
    return out


async def loop(first_delay: float = 120.0) -> None:
    await asyncio.sleep(first_delay)
    while True:
        cfg = config()
        if cfg.get("auto", True) and not _job["running"]:
            try:
                await update_all()
            except Exception:  # noqa: BLE001
                log.warning("info sweep failed", exc_info=True)
        await asyncio.sleep(max(5, int(cfg.get("every_min") or 20)) * 60)


# ---- endpoints -------------------------------------------------------------------------------------------
@router.get("/items")
async def items_ep(category: str | None = None, region: str | None = None, q: str | None = None, hits_only: bool = False,
                   ticker: str | None = None, days: int = 7, limit: int = 300):
    lim = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    out = []
    for it in reversed(_read("items.json", [])):
        ts = it.get("published") or it.get("fetched") or ""
        if ts < lim[:19]:
            continue
        if (category and it.get("category") != category) or (region and it.get("region") != region):
            continue
        if hits_only and not (it.get("tickers") or it.get("keywords")):
            continue
        if ticker and ticker.split(":")[-1].upper() not in (it.get("tickers") or []):
            continue
        if q and q.lower() not in (it.get("title", "") + " " + it.get("summary", "")).lower():
            continue
        out.append(it)
        if len(out) >= limit:
            break
    return {"rows": out, "categories": sorted({f["category"] for f in feeds()}), "regions": sorted({f["region"] for f in feeds()}),
            "symbols": {x["ticker"]: x["symbol"] for x in coverage_list() if x.get("symbol")}}


@router.get("/feeds")
async def feeds_ep():
    st = _read("feed_status.json", {})
    return {"rows": [{**f, **(st.get(f["id"]) or {})} for f in feeds()]}


class FeedReq(BaseModel):
    name: str
    url: str
    category: str = "ニュース"
    region: str = "GLOBAL"


@router.post("/feeds")
async def add_feed(req: FeedReq):
    if not re.match(r"https?://", req.url):
        raise HTTPException(400, "URL は http(s)://")
    if not req.name.strip():
        raise HTTPException(400, "名前を入れる")
    fid = "u_" + hashlib.sha1(req.url.strip().encode()).hexdigest()[:10]       # one id per URL (names may be Japanese)
    cus = [f for f in (S.store.get("info_feeds_custom") or []) if f["id"] != fid] + [{"id": fid, **req.model_dump()}]
    S.store.set("info_feeds_custom", cus)
    return {"ok": True, "id": fid}


@router.delete("/feeds/{fid}")
async def del_feed(fid: str):
    S.store.set("info_feeds_custom", [f for f in (S.store.get("info_feeds_custom") or []) if f["id"] != fid])
    return {"ok": True}


class EnableReq(BaseModel):
    enabled: bool


@router.put("/feeds/{fid}")
async def enable_feed(fid: str, req: EnableReq):
    dis = [d for d in (S.store.get("info_feeds_disabled") or []) if d != fid] + ([] if req.enabled else [fid])
    S.store.set("info_feeds_disabled", dis)
    return {"ok": True}


class TestReq(BaseModel):
    url: str


@router.post("/feeds/test")
async def test_feed(req: TestReq):
    try:
        async with client() as c:
            items = await fetch_feed(c, req.url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"{type(e).__name__}: {e}") from e
    return {"n": len(items), "items": items[:5]}


class WordsReq(BaseModel):
    words: list[str]


@router.get("/keywords")
async def get_words():
    return {"words": keywords(), "default": FD.DEFAULT_KEYWORDS}


@router.put("/keywords")
async def put_words(req: WordsReq):
    S.store.set("info_keywords", [w.strip() for w in req.words if w.strip()][:200])
    return {"words": keywords()}


def _edinet_rows(ticker: str | None = None, kinds: list[str] | None = None, days: int = 30, coverage_only: bool = True) -> list[dict[str, Any]]:
    data = _read("edinet.json", {"dates": {}})
    lim = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    cov = {x["ticker"]: x for x in coverage_list()}
    out = []
    for d, docs in data["dates"].items():
        if d < lim:
            continue
        for x in docs:
            t = x.get("ticker")
            if ticker and t != ticker:
                continue
            if coverage_only and not ticker and t not in cov:
                continue
            if kinds and x["kind"] not in kinds:
                continue
            out.append({**x, "date": d, "name": (cov.get(t) or {}).get("name"), "source": "EDINET",
                        "pdf": f"/api/info/edinet/{x['doc_id']}/pdf"})
    return sorted(out, key=lambda x: x["at"] or x["date"], reverse=True)


@router.get("/filings")
async def filings_ep(ticker: str | None = None, kind: str | None = None, days: int = 30, coverage_only: bool = True):
    t = ticker.split(":")[-1].upper() if ticker else None
    rows = _edinet_rows(t, [kind] if kind else None, days, coverage_only)
    edgar = _read("edgar.json", {"tickers": {}})["tickers"]
    us = sorted(({**f, "ticker": tk, "source": "EDGAR"} for tk, v in edgar.items() if not t or tk == t for f in (v.get("filings") or [])),
                key=lambda f: f.get("date") or "", reverse=True)[:300]
    data = _read("edinet.json", {})
    return {"rows": rows, "edgar": us, "kinds": [k for k, _ in FL.KINDS] + ["その他"], "edinet_at": data.get("at"),
            "edinet_errors": data.get("errors", {}), "keys": {"EDINET_API_KEY": bool(os.environ.get("EDINET_API_KEY")),
                                                              "SEC_USER_AGENT": bool(os.environ.get("SEC_USER_AGENT"))}}


@router.get("/edinet/{doc_id}/pdf")
async def edinet_pdf(doc_id: str):
    """The filing as PDF (the API key stays on the server)."""
    key = os.environ.get("EDINET_API_KEY")
    if not key:
        raise HTTPException(400, "EDINET_API_KEY が未設定")
    if not re.fullmatch(r"[A-Z0-9]{6,12}", doc_id):
        raise HTTPException(400, "docID が不正")
    async with client() as c:
        r = await c.get(f"{FL.EDINET}/documents/{doc_id}", params={"type": 2, "Subscription-Key": key})
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("application/pdf"):
        raise HTTPException(502, f"EDINET: {r.status_code}")
    return Response(r.content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{doc_id}.pdf"'})


async def google_news(q: str, lang: str = "ja", max_age_min: int = 60) -> list[dict[str, Any]]:
    cache = _read("news_cache.json", {})
    k = f"{lang}:{q}"
    hit = cache.get(k)
    if hit and hit["at"] >= (dt.datetime.now() - dt.timedelta(minutes=max_age_min)).isoformat():
        return hit["items"]
    async with client() as c:
        items = await fetch_feed(c, FD.google_news_url(q, lang))
    cache[k] = {"at": _now(), "items": items[:30]}
    if len(cache) > 300:
        cache = dict(sorted(cache.items(), key=lambda kv: kv[1]["at"])[-300:])
    _write("news_cache.json", cache)
    return items[:30]


@router.get("/news")
async def news_ep(q: str, lang: str = "ja"):
    try:
        return {"rows": await google_news(q, lang), "q": q}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {e}") from e


@router.get("/stock/{symbol}")
async def stock_ep(symbol: str, news: bool = True):
    """Everything about one stock: tagged feed items, filings (EDINET / EDGAR), company news (Google News)."""
    t = symbol.split(":")[-1].upper()
    cov = next((x for x in coverage_list() if x["ticker"] == t), None)
    items = (await items_ep(ticker=t, days=60, limit=30))["rows"]
    out: dict[str, Any] = {"ticker": t, "items": items, "filings": _edinet_rows(t, days=365),
                           "edgar": ((_read("edgar.json", {"tickers": {}})["tickers"].get(t) or {}).get("filings") or [])[:20]}
    if news:
        q = (cov or {}).get("name") or t
        out["news_q"] = q
        try:
            out["news"] = await google_news(q, "ja" if FL.is_jp(symbol) else "en")
        except Exception as e:  # noqa: BLE001
            out["news"], out["news_error"] = [], f"{type(e).__name__}: {e}"[:200]
    return out


@router.post("/update")
async def update_ep(daily: bool = False):
    if _job["running"]:
        return {"started": False, "job": _job}
    asyncio.create_task(update_all(daily))
    await asyncio.sleep(0)
    return {"started": True, "job": _job}


@router.get("/status")
async def status_ep():
    st = _read("feed_status.json", {})
    fs = feeds()
    return {"job": _job, "config": config(), "auto_env": os.environ.get("TERMINAL_INFO_AUTO", "1") != "0",
            "feeds": {"total": len(fs), "enabled": sum(f["enabled"] for f in fs), "ok": sum(1 for f in fs if (st.get(f["id"]) or {}).get("ok")),
                      "error": sum(1 for f in fs if st.get(f["id"]) and not st[f["id"]].get("ok"))},
            "items": len(_read("items.json", [])), "state": _read("state.json", {}),
            "keys": {"EDINET_API_KEY": bool(os.environ.get("EDINET_API_KEY")), "SEC_USER_AGENT": bool(os.environ.get("SEC_USER_AGENT"))}}


class InfoConfig(BaseModel):
    auto: bool | None = None
    every_min: int | None = None


@router.put("/config")
async def put_config(req: InfoConfig):
    cfg = config()
    if req.auto is not None:
        cfg["auto"] = req.auto
    if req.every_min is not None:
        if not 5 <= req.every_min <= 1440:
            raise HTTPException(400, "5〜1440 分")
        cfg["every_min"] = req.every_min
    S.store.set("info_config", cfg)
    return cfg
