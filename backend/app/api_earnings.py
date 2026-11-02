"""Earnings / quarter system API (independent of Notion). Data: <data>/earnings/calendar.json."""
from __future__ import annotations

import datetime as dt
import io
import json
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from . import earnings as E
from .state import DATA_DIR, S

router = APIRouter(prefix="/api/earnings")
JPX_INDEX = "https://www.jpx.co.jp/listing/event-schedules/financial-announcement/index.html"
TV_COLS = ["earnings_release_next_date", "earnings_release_date"]


def cal_path() -> Path:
    p = DATA_DIR / "earnings"
    p.mkdir(parents=True, exist_ok=True)
    return p / "calendar.json"


def load() -> dict[str, Any]:
    try:
        c = json.loads(cal_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    c.setdefault("config", {"convention": "end", "jpx_index": JPX_INDEX, "auto": True, "last_refresh": None})
    for k in ("companies", "quarters"):
        c.setdefault(k, {})
    c.setdefault("jpx", {"records": [], "fetched": None, "files": []})
    c.setdefault("log", [])
    return c


def save(c: dict[str, Any]) -> None:
    tmp = cal_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cal_path())


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _coverage_items() -> list[dict[str, Any]]:
    from .api_coverage import state
    return state()["items"]


def read_xlsx_rows(content: bytes) -> list[list[Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    rows: list[list[Any]] = []
    for ws in wb.worksheets:
        rows += [list(r) for r in ws.iter_rows(values_only=True)]
    return rows


async def fetch_jpx(index_url: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Download the JPX 決算発表予定日 index and every xlsx linked from it."""
    async with httpx.AsyncClient(timeout=40, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as h:
        r = await h.get(index_url)
        r.raise_for_status()
        links = sorted(set(re.findall(r'href="([^"]+\.xlsx)"', r.text)))
        if not links:
            raise ValueError("JPX のページに xlsx へのリンクが見つからない（ページ構成が変わった可能性）")
        recs: list[dict[str, Any]] = []
        for href in links:
            url = href if href.startswith("http") else httpx.URL(index_url).join(href)
            f = await h.get(str(url))
            f.raise_for_status()
            recs += E.parse_jpx_rows(read_xlsx_rows(f.content))
    return recs, [str(x) for x in links]


def _relabel(c: dict[str, Any], t: str, fye: int, why: str) -> None:
    """FYE month / convention changed → re-label the company's quarter pages (nothing is deleted)."""
    qs = c["quarters"].get(t) or {}
    if not qs:
        return
    new, dropped = E.rekey(qs, fye, c["config"].get("convention", "end"))
    c["quarters"][t] = new
    if dropped:
        c.setdefault("archive", {}).setdefault(t, []).extend({**q, "archived": _now(), "why": why} for q in dropped)


def _merge_candidates(q: dict[str, Any], cands: list[dict[str, Any]], run: int) -> None:
    """Add this run's candidates to the quarter's history; a candidate seen again is re-stamped with this run."""
    hist = q.setdefault("candidates", [])
    idx = {(x["source"], x["date"]): x for x in hist}
    for x in cands:
        k = (x["source"], x["date"])
        if k in idx:
            idx[k].update(status=x["status"], fetched=x["fetched"], run=run)
        else:
            hist.append({**x, "first_seen": x["fetched"], "run": run})
    q["candidates"] = sorted(hist, key=lambda x: (x.get("run") or 0, x.get("fetched") or ""))[-12:]


async def refresh(c: dict[str, Any], use_jpx: bool = True, use_tv: bool = True, tickers: list[str] | None = None) -> dict[str, Any]:
    today = dt.date.today()
    conv = c["config"].get("convention", "end")
    errors: dict[str, str] = {}
    items = [x for x in _coverage_items() if not tickers or x["ticker"] in tickers]
    # 1) JPX official schedule (also the most reliable fiscal-year-end month)
    if use_jpx:
        try:
            recs, files = await fetch_jpx(c["config"].get("jpx_index") or JPX_INDEX)
            c["jpx"] = {"records": recs, "fetched": _now(), "files": files, "source": "download"}
        except Exception as e:  # noqa: BLE001 - keep the last good schedule
            errors["jpx"] = f"{type(e).__name__}: {e}（前回取得分または手動アップロード分を使用）"
    jpx_by: dict[str, list[dict[str, Any]]] = {}
    for r in c["jpx"].get("records", []):
        jpx_by.setdefault(r["ticker"], []).append(r)
    # 2) TradingView next / last release dates
    tv: dict[str, dict[str, Any]] = {}
    if use_tv and items:
        try:
            tv = await S.web.scan_symbols([x["symbol"] for x in items], TV_COLS, TV_COLS[:1])
        except Exception as e:  # noqa: BLE001
            errors["tradingview"] = str(e)
    from .coverage import to_date

    changes = []
    fetched = _now()
    c["runs"] = run = int(c.get("runs") or 0) + 1
    for it in items:
        t = it["ticker"]
        comp = c["companies"].setdefault(t, {})
        comp["name"] = it.get("name") or comp.get("name")
        # fiscal-year-end month: manual > JPX > Notion 銘柄マスタ
        if comp.get("fye_source") != "手入力":
            jm = next((r.get("fye_month") for r in jpx_by.get(t, []) if r.get("fye_month")), None)
            if jm:
                if comp.get("fye_month") and comp["fye_month"] != jm:
                    changes.append({"ticker": t, "qid": None, "what": "決算期末月", "from": comp["fye_month"], "to": jm, "source": "JPX"})
                elif it.get("fye_month") and it["fye_month"] != jm and comp.get("fye_notion_flagged") != it["fye_month"]:
                    # the Notion 銘柄マスタ disagrees with the official schedule → keep JPX, flag Notion
                    changes.append({"ticker": t, "qid": None, "what": "決算期末月（Notion と不一致）", "from": it["fye_month"], "to": jm, "source": "JPX"})
                    comp["fye_notion_flagged"] = it["fye_month"]
                comp["fye_month"], comp["fye_source"] = jm, "JPX 決算発表予定日一覧"
            elif it.get("fye_month") and not comp.get("fye_month"):
                comp["fye_month"], comp["fye_source"] = it["fye_month"], "Notion 銘柄マスタ"
        fye = comp.get("fye_month")
        if not fye:
            continue
        if comp.get("quarters_fye") not in (None, fye):
            _relabel(c, t, fye, f"決算期末月 {comp['quarters_fye']}→{fye}")
        comp["quarters_fye"] = fye
        qs = c["quarters"].setdefault(t, {})
        for sk in E.quarters_around(today, fye, 8, 4, conv):
            q = qs.setdefault(sk["id"], {})
            for k in ("fy", "q", "period_start", "period_end", "label", "label_ja"):
                q[k] = sk[k]
            q.setdefault("id", sk["id"])
        cands: dict[str, list[dict[str, Any]]] = {}

        def add(date: dt.date | None, status: str, source: str, q_hint: int | None = None) -> None:
            if not date:
                return
            hit = E.quarter_for_release(date, fye, q_hint, conv)
            if hit:
                cands.setdefault(E.qid(hit[0], hit[1]), []).append({"date": date.isoformat(), "status": status, "source": source, "fetched": fetched})

        for r in jpx_by.get(t, []):
            add(dt.date.fromisoformat(r["date"]), "確定", "JPX 決算発表予定日一覧", r.get("q"))
        sc = tv.get(it["symbol"]) or {}
        nd, ld = to_date(sc.get("earnings_release_next_date")), to_date(sc.get("earnings_release_date"))
        add(nd, "予定" if nd and nd >= today else "発表済", "TradingView（次回）")
        add(ld, "発表済", "TradingView（前回）")
        ordered = sorted(qs.values(), key=lambda x: x["period_end"])
        for q in ordered:
            _merge_candidates(q, cands.get(q["id"], []), run)
            prev = qs.get(E.qid(q["fy"] - 1, q["q"]))
            before = dict(q.get("earnings") or {})
            # candidates seen in this run are "current"; older ones stay as history. When TradingView was not
            # consulted (e.g. after a JPX upload) its latest view is kept, so dates do not flip to 推定 and back.
            hist = q.get("candidates", [])
            current = [x for x in hist if x.get("run") == run]
            if not use_tv:
                tv_old = [x for x in hist if x["source"].startswith("TradingView") and x.get("run") != run]
                if tv_old:
                    last = max(x.get("run") or 0 for x in tv_old)
                    current += [x for x in tv_old if (x.get("run") or 0) == last]
            current = current or [x for x in hist if x["status"] in ("確定", "発表済")]
            q["earnings"] = E.resolve(q, current, prev, E.typical_lag(ordered, q["q"]), today)
            q["state"] = E.quarter_state(q, today)
            moved = (before.get("date"), before.get("status")) != (q["earnings"].get("date"), q["earnings"].get("status"))
            # estimate → estimate shifts (e.g. a re-based 前年同期 + 364) are derivative: not logged
            if before and moved and not (before.get("status") == "推定" and q["earnings"].get("status") == "推定"):
                changes.append({"ticker": t, "qid": q["id"], "what": "決算日", "from": f"{before.get('date')} {before.get('status')}",
                                "to": f"{q['earnings']['date']} {q['earnings']['status']}", "source": q["earnings"].get("source")})
    c["log"] = (c["log"] + [{**x, "at": fetched} for x in changes])[-1000:]
    c["config"]["last_refresh"] = fetched
    save(c)
    return {"companies": len(items), "changes": changes[:100], "n_changes": len(changes), "errors": errors,
            "jpx_records": len(c["jpx"].get("records", []))}


def company_view(c: dict[str, Any], ticker: str) -> dict[str, Any]:
    today = dt.date.today()
    qs = sorted((c["quarters"].get(ticker) or {}).values(), key=lambda x: x["period_end"])
    for q in qs:
        q["state"] = E.quarter_state(q, today)
    nx, ls = E.next_earnings(qs, today), E.last_earnings(qs, today)
    return {"ticker": ticker, "company": c["companies"].get(ticker) or {}, "quarters": qs,
            "next": nx and {"id": nx["id"], "label": nx["label"], "label_ja": nx["label_ja"], "period_end": nx["period_end"], **nx["earnings"],
                            "days": (dt.date.fromisoformat(nx["earnings"]["date"]) - today).days},
            "last": ls and {"id": ls["id"], "label": ls["label"], **ls["earnings"]},
            "convention": c["config"].get("convention", "end")}


def summary(ticker: str, c: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Compact next/last earnings for COV / STK / reports / AUTO (pass ``c`` to avoid re-reading the file)."""
    c = c if c is not None else load()
    if ticker not in c["quarters"]:
        return None
    v = company_view(c, ticker)
    return {"next": v["next"]["date"] if v["next"] else None, "next_title": v["next"]["label"] if v["next"] else None,
            "next_label_ja": v["next"]["label_ja"] if v["next"] else None, "next_status": v["next"]["status"] if v["next"] else None,
            "next_source": v["next"]["source"] if v["next"] else None, "days": v["next"]["days"] if v["next"] else None,
            "next_period_end": v["next"]["period_end"] if v["next"] else None,
            "last": v["last"]["date"] if v["last"] else None, "last_title": v["last"]["label"] if v["last"] else None,
            "fye_month": v["company"].get("fye_month"), "fye_source": v["company"].get("fye_source")}


# ---- endpoints ----------------------------------------------------------------------------------
class RefreshReq(BaseModel):
    jpx: bool = True
    tradingview: bool = True
    tickers: list[str] | None = None


@router.post("/refresh")
async def refresh_ep(req: RefreshReq):
    c = load()
    if not _coverage_items():
        raise HTTPException(400, "カバレッジが空（COV → SYNC FROM NOTION、または銘柄を追加）")
    return await refresh(c, req.jpx, req.tradingview, [t.split(":")[-1].upper() for t in req.tickers] if req.tickers else None)


@router.post("/jpx/import")
async def jpx_import(file: UploadFile = File(...)):
    """Upload the JPX 決算発表予定日 xlsx by hand (when the download is blocked), then refresh."""
    try:
        recs = E.parse_jpx_rows(read_xlsx_rows(await file.read()))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"JPX ファイルを読めない: {e}") from e
    c = load()
    new_by: dict[str, list[dt.date]] = {}
    for x in recs:
        new_by.setdefault(x["ticker"], []).append(dt.date.fromisoformat(x["date"]))
    # a company reports about every 91 days: an older record within 75 days of a new one is the same
    # announcement (date revised by the company) and is replaced
    old = [r for r in c["jpx"].get("records", [])
           if not any(abs((dt.date.fromisoformat(r["date"]) - d).days) <= 75 for d in new_by.get(r["ticker"], []))]
    c["jpx"] = {"records": old + recs, "fetched": _now(), "files": [file.filename], "source": "upload"}
    save(c)
    res = await refresh(load(), use_jpx=False, use_tv=False)
    return {"records": len(recs), **res}


@router.get("/calendar")
async def calendar_ep(days: int = 90):
    c = load()
    today = dt.date.today()
    rows = []
    names = {x["ticker"]: x for x in _coverage_items()}
    for t, qs in c["quarters"].items():
        for q in qs.values():
            e = q.get("earnings") or {}
            if e.get("date"):
                d = (dt.date.fromisoformat(e["date"]) - today).days
                if -3 <= d <= days and e.get("status") != "発表済":
                    rows.append({"ticker": t, "name": (names.get(t) or {}).get("name") or c["companies"].get(t, {}).get("name"),
                                 "id": q["id"], "label": q["label"], "label_ja": q["label_ja"], "date": e["date"], "days": d,
                                 "status": e["status"], "source": e.get("source")})
    rows.sort(key=lambda r: (r["date"], r["ticker"]))
    return {"rows": rows, "last_refresh": c["config"].get("last_refresh"), "jpx_fetched": c["jpx"].get("fetched")}


@router.get("/log")
async def log_ep(limit: int = 200):
    return {"log": load()["log"][-limit:][::-1]}


@router.get("/config")
async def get_config():
    return load()["config"]


@router.put("/config")
async def put_config(body: dict[str, Any]):
    c = load()
    for k in ("convention", "jpx_index", "auto"):
        if k in body:
            c["config"][k] = body[k]
    if c["config"]["convention"] not in ("end", "start_plus_1"):
        c["config"]["convention"] = "end"
    if "convention" in body:  # labels depend on the convention → re-label (notes and pins are kept)
        for t in list(c["quarters"]):
            fye = (c["companies"].get(t) or {}).get("fye_month")
            if fye:
                _relabel(c, t, fye, "表記の変更")
    save(c)
    return c["config"]


@router.get("/{ticker}")
async def company_ep(ticker: str):
    return company_view(load(), ticker.split(":")[-1].upper())


class FyeReq(BaseModel):
    month: int


@router.put("/{ticker}/fye")
async def fye_ep(ticker: str, req: FyeReq):
    if not 1 <= req.month <= 12:
        raise HTTPException(400, "1-12")
    c = load()
    t = ticker.split(":")[-1].upper()
    comp = c["companies"].setdefault(t, {})
    if comp.get("fye_month") != req.month:
        c["log"].append({"at": _now(), "ticker": t, "qid": None, "what": "決算期末月", "from": comp.get("fye_month"), "to": req.month, "source": "手入力"})
    comp.update({"fye_month": req.month, "fye_source": "手入力"})
    save(c)
    await refresh(load(), use_jpx=False, use_tv=False, tickers=[t])
    return company_view(load(), t)


class QuarterReq(BaseModel):
    earnings_date: str | None = None     # "YYYY-MM-DD" pins the date; "" removes the pin
    notes: str | None = None
    checklist: dict[str, Any] | None = None


@router.put("/{ticker}/{qid}")
async def quarter_ep(ticker: str, qid: str, req: QuarterReq):
    c = load()
    t = ticker.split(":")[-1].upper()
    q = (c["quarters"].get(t) or {}).get(qid)
    if not q:
        raise HTTPException(404, "quarter not found (refresh first)")
    if req.earnings_date is not None:
        if req.earnings_date == "":
            q["earnings"] = {}
        else:
            d = dt.date.fromisoformat(req.earnings_date[:10])
            before = q.get("earnings") or {}
            q["earnings"] = {"date": d.isoformat(), "status": "手入力", "source": "手入力", "fetched": _now()}
            c["log"].append({"at": _now(), "ticker": t, "qid": qid, "what": "決算日", "from": f"{before.get('date')} {before.get('status')}",
                             "to": f"{d.isoformat()} 手入力", "source": "手入力"})
    if req.notes is not None:
        q["notes"] = req.notes
    if req.checklist is not None:
        q["checklist"] = req.checklist
    q["updated"] = _now()
    save(c)
    if req.earnings_date == "":
        await refresh(load(), use_jpx=False, use_tv=False, tickers=[t])
    return company_view(load(), t)


@router.post("/{ticker}/{qid}/folder")
async def quarter_folder(ticker: str, qid: str):
    """Local folder for the quarter's files: <stock folder>/quarters/FY2027_2Q/ (+ notes.md)."""
    from .api_coverage import _item, _open_path, state, stock_dir

    cov = state()
    it = _item(cov, ticker)
    c = load()
    q = (c["quarters"].get(it["ticker"]) or {}).get(qid)
    if not q:
        raise HTTPException(404, "quarter not found")
    p = stock_dir(cov, it) / "quarters" / qid.replace("-", "_")
    p.mkdir(parents=True, exist_ok=True)
    notes = p / "notes.md"
    if not notes.exists():
        notes.write_text(f"# {it['ticker']} {it.get('name') or ''} — {q['label']}（{q['label_ja']}）\n\n"
                         f"- 期間: {q['period_start']} 〜 {q['period_end']}\n- 決算発表: {(q.get('earnings') or {}).get('date')}"
                         f"（{(q.get('earnings') or {}).get('status')}）\n\n{q.get('notes') or ''}\n", encoding="utf-8")
    return {"path": str(p), "opened": _open_path(p)}
