"""Earnings / quarter system API (independent of Notion).

Data: <coverage root>/_terminal/earnings/calendar.json — inside the coverage root, so the calendar (dates, quarter
notes, checklists, log) moves to OneDrive together with the stock folders. Quarter notes are also kept in sync,
both ways, with <stock folder>/quarters/<FY…>/notes.md.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
import shutil
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from . import earnings as E
from .state import DATA_DIR, S

router = APIRouter(prefix="/api/earnings")
JPX_INDEX = "https://www.jpx.co.jp/listing/event-schedules/financial-announcement/index.html"
TV_COLS = ["earnings_release_next_date", "earnings_release_date"]
LEGACY_PATH = DATA_DIR / "earnings" / "calendar.json"     # first version kept it in the data dir (not synced)
LOCATION = DATA_DIR / "earnings" / "location.json"        # machine-local: where the calendar was used last


def cal_path() -> Path:
    from .api_coverage import root_dir
    return root_dir() / "_terminal" / "earnings" / "calendar.json"


def _last_location() -> Path | None:
    try:
        return Path(json.loads(LOCATION.read_text(encoding="utf-8"))["path"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _remember(p: Path) -> None:
    if _last_location() != p:
        LOCATION.parent.mkdir(parents=True, exist_ok=True)
        LOCATION.write_text(json.dumps({"path": str(p)}, ensure_ascii=False), encoding="utf-8")


def _migrate(dst: Path) -> str | None:
    """A coverage root without a calendar: copy it from the old data dir, or from the root used last (e.g. the root
    was changed in SETTINGS without moving the folders). The old data-dir file is kept as a backup."""
    for src in (LEGACY_PATH, _last_location()):
        if src and src != dst and src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if src == LEGACY_PATH:
                src.rename(src.with_name(f"calendar.moved-{dt.datetime.now():%Y%m%d-%H%M%S}.json"))
            return str(src)
    return None


def load() -> dict[str, Any]:
    p = cal_path()
    moved = None if p.exists() else _migrate(p)
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    c.setdefault("config", {"convention": "end", "jpx_index": JPX_INDEX, "auto": True, "last_refresh": None})
    for k in ("companies", "quarters"):
        c.setdefault(k, {})
    c.setdefault("jpx", {"records": [], "fetched": None, "files": []})
    c.setdefault("log", [])
    if moved:
        c["log"].append({"at": _now(), "ticker": None, "qid": None, "what": "保存場所", "from": moved, "to": str(p), "source": "移行"})
        save(c)
    return c


def save(c: dict[str, Any]) -> None:
    p = cal_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    _remember(p)


# ---- quarter notes ⇄ <quarter folder>/notes.md ------------------------------------------------------
NOTES_MARK = "<!-- ここから下がメモ（ターミナルの四半期ページと同期します。この線より上はターミナルが書き換えます） -->"
_MARK_RE = re.compile(r"<!--\s*ここから下がメモ.*?-->", re.S)


def _clean(s: str | None) -> str:
    return "\n".join(x.rstrip() for x in (s or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def _digest(s: str | None) -> str:
    return hashlib.sha1(_clean(s).encode("utf-8")).hexdigest()[:16]


def notes_md(it: dict[str, Any], q: dict[str, Any]) -> str:
    e = q.get("earnings") or {}
    done = [k for k, v in (q.get("checklist") or {}).items() if v]
    head = [f"# {it['ticker']} {it.get('name') or ''} — {q['label']}（{q['label_ja']}）", "",
            f"- 期間: {q['period_start']} 〜 {q['period_end']}",
            f"- 決算発表: {e.get('date') or '—'}（{e.get('status') or '—'}・{e.get('source') or '—'}）",
            f"- 状態: {q.get('state') or '—'}"]
    if done:
        head.append(f"- チェック済み: {'、'.join(done)}")
    body = _clean(q.get("notes"))
    return "\n".join(head) + f"\n\n{NOTES_MARK}\n\n" + (body + "\n" if body else "")


_OLD_HEAD = re.compile(r"\A# [^\n]*\n+(?:- (?:期間|決算発表|状態|チェック済み): [^\n]*\n)+")


def notes_from_md(text: str) -> str:
    """The note part of notes.md: below the marker. A file without the marker (hand-written, or written by the
    first version) is all note, minus a header that the terminal generated itself (title + 期間/決算発表 lines)."""
    m = _MARK_RE.search(text)
    if m:
        return _clean(text[m.end():])
    return _clean(_OLD_HEAD.sub("", text.replace("\r\n", "\n"), count=1))


def quarter_dir(stock: Path, qid: str) -> Path:
    return stock / "quarters" / qid.replace("-", "_")


def sync_notes(it: dict[str, Any], q: dict[str, Any], folder: Path) -> str | None:
    """Two-way sync of the quarter page notes with <folder>/notes.md: the side that changed since the last sync
    wins; if both changed, the terminal's text is kept and the file's text is saved as notes.conflict-<time>.md
    (nothing is ever lost). The header above the marker is rewritten by the terminal (dates, status)."""
    if not folder.is_dir():
        return None
    f = folder / "notes.md"
    term = _clean(q.get("notes"))
    base = (q.get("notes_sync") or {}).get("digest")
    action, old = None, None
    if f.exists():
        try:
            old = f.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            return "読めない"
        fnote = notes_from_md(old)
        if fnote != term:
            if base is None:    # first sync of a file that already existed: the non-empty side wins
                fchg, tchg = bool(fnote), bool(term)
            else:
                fchg, tchg = _digest(fnote) != base, _digest(term) != base
            if fchg and not tchg:
                q["notes"], action = fnote, "ファイルから取り込み"
            elif tchg and not fchg:
                action = "ファイルへ書き出し"
            else:
                name = f"notes.conflict-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
                (folder / name).write_text(old, encoding="utf-8")
                q["notes_conflict"], action = name, f"競合（ファイル側を {name} に保存）"
    new = notes_md(it, q)
    if old != new:
        f.write_text(new, encoding="utf-8")
        action = action or ("作成" if old is None else "見出しを更新")
    d = _digest(q.get("notes"))
    if action or base != d:
        q["notes_sync"] = {"digest": d, "at": _now()}
        action = action or "同期"
    return action


QUIET = ("見出しを更新", "作成", "同期")     # sync results that are not worth a log line


def sync_company(c: dict[str, Any], t: str, it: dict[str, Any] | None, stock: Path | None) -> tuple[bool, list[dict[str, Any]]]:
    """Sync every quarter of one company that has a quarter folder → (calendar changed?, log rows)."""
    if not it or not stock:
        return False, []
    changed, rows = False, []
    for q in (c["quarters"].get(t) or {}).values():
        a = sync_notes(it, q, quarter_dir(stock, q["id"]))
        if a:
            changed = True
            if a not in QUIET:
                rows.append({"ticker": t, "qid": q["id"], "what": "メモ", "from": "", "to": a, "source": "notes.md"})
    return changed, rows


def _cov_context(t: str) -> tuple[dict[str, Any] | None, Path | None]:
    """(coverage item, existing stock folder) of a ticker."""
    from .api_coverage import markers, root_dir, state

    cov = state()
    it = next((x for x in cov["items"] if x["ticker"] == t), None)
    return it, (markers(root_dir(cov)).get(t) if it else None)


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
            current += [x for x in hist if x["status"] == "検出" and x not in current]   # market evidence does not expire
            q["earnings"] = E.resolve(q, current, prev, E.typical_lag(ordered, q["q"]), today)
            q["state"] = E.quarter_state(q, today)
            moved = (before.get("date"), before.get("status")) != (q["earnings"].get("date"), q["earnings"].get("status"))
            # estimate → estimate shifts (e.g. a re-based 前年同期 + 364) are derivative: not logged
            if before and moved and not (before.get("status") == "推定" and q["earnings"].get("status") == "推定"):
                changes.append({"ticker": t, "qid": q["id"], "what": "決算日", "from": f"{before.get('date')} {before.get('status')}",
                                "to": f"{q['earnings']['date']} {q['earnings']['status']}", "source": q["earnings"].get("source")})
    # quarter folders: refresh the notes.md headers (dates / status) and pick up notes edited in the files
    from .api_coverage import markers, root_dir
    mk = markers(root_dir())
    for it in items:
        changes += sync_company(c, it["ticker"], it, mk.get(it["ticker"]))[1]
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
            "fye_month": v["company"].get("fye_month"), "fye_source": v["company"].get("fye_source"),
            "reaction": v["company"].get("reaction")}


# ---- 決算時の株価反応 (earnings_reaction.py) ---------------------------------------------------------
REAL = ("tradingview", "yahoo")      # detected dates / stored statistics only ever come from real market data


def market_symbol(symbol: str) -> str:
    return "TVC:TOPIX" if symbol.upper().startswith(("TSE:", "OSE:")) else "SP:SPX"


def reactions_from_bars(c: dict[str, Any], t: str, bars: list[dict[str, Any]], market_bars: list[dict[str, Any]] | None,
                        provider: str, today: dt.date | None = None) -> dict[str, Any]:
    """Reaction of every reported quarter. With real market data, an estimated (推定) past date is replaced by the
    date detected from the volume spike (status 検出, logged); with SIM data nothing is written."""
    from . import earnings_reaction as R

    today = today or dt.date.today()
    ds, cl, vo = R.daily(bars)
    mkt = None
    if market_bars:
        md, mc, _ = R.daily(market_bars)
        mkt = dict(zip(md, mc))
    real = provider in REAL
    rows: list[dict[str, Any]] = []
    detected = 0
    for q in sorted((c["quarters"].get(t) or {}).values(), key=lambda x: x["period_end"]):
        e = q.get("earnings") or {}
        if not ds or not e.get("date") or not (ds[0] < e["date"] < today.isoformat()):
            continue
        st = e.get("status")
        row: dict[str, Any] = {"id": q["id"], "label": q["label"], "label_ja": q["label_ja"], "announce": e["date"], "status": st}
        if st == "検出" and (q.get("detected") or {}).get("reaction_day") in ds:
            i = ds.index(q["detected"]["reaction_day"])
            row.update(kind="検出", timing="検出（引け後と仮定）")
        elif st in E.KNOWN:
            hit = R.reaction_at_known(ds, vo, e["date"])
            if not hit:
                continue
            i, timing = hit
            row.update(kind="既知", timing=timing)
        else:                                   # 推定 → look for the volume spike
            ne = (dt.date.fromisoformat(q["period_end"]) + dt.timedelta(days=7)).isoformat()
            hit = R.detect(ds, vo, e["date"], ne)
            if not hit:
                rows.append({**row, "kind": "検出できず"})
                continue
            i = hit["index"]
            row.update(kind="検出", timing="検出（引け後と仮定）", announce=hit["announce"])
            if real:
                src = f"出来高の急増（反応日 {hit['reaction_day']}、{hit['vol_ratio']:.1f} 倍、引け後と仮定・{provider}）"
                _merge_candidates(q, [{"date": hit["announce"], "status": "検出", "source": src, "fetched": _now()}], int(c.get("runs") or 0))
                q["detected"] = {"reaction_day": hit["reaction_day"], "announce": hit["announce"],
                                 "vol_ratio": round(hit["vol_ratio"], 2), "provider": provider, "at": _now()}
                c["log"].append({"at": _now(), "ticker": t, "qid": q["id"], "what": "決算日", "from": f"{e['date']} 推定",
                                 "to": f"{hit['announce']} 検出", "source": src})
                q["earnings"] = {"date": hit["announce"], "status": "検出", "source": src}
                q["state"] = E.quarter_state(q, today)
                detected += 1
        m = R.metrics(ds, cl, vo, i, mkt)
        if m:
            rows.append({**row, **m})
    summ = R.summarize(rows)
    changed = detected > 0
    if real and summ.get("n"):                # the typical earnings move, shown in COV
        old = {k: v for k, v in ((c["companies"].get(t) or {}).get("reaction") or {}).items() if k != "at"}
        new = {**summ, "provider": provider}
        if old != new:
            c["companies"].setdefault(t, {})["reaction"] = {**new, "at": _now()}
            changed = True
    return {"ticker": t, "rows": rows, "summary": summ, "provider": provider, "real": real, "detected_now": detected,
            "changed": changed, "market": bool(mkt)}


async def _market_bars(symbol: str, source: str | None, cache: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    ms = market_symbol(symbol)
    if ms not in cache:
        try:
            cache[ms] = await S.history(ms, "1D", 800, source)
        except HTTPException:
            cache[ms] = []
    return cache[ms]


async def reactions_all(series: dict[str, list[dict[str, Any]]], provider: str, source: str | None = None) -> dict[str, Any]:
    """AUTO: detection of past announcement dates and the typical earnings move for the whole coverage (from the
    price histories AUTO already loaded). Real market data only."""
    if provider not in REAL:
        return {"skipped": f"{provider}: 検出と統計は実データのときだけ保存"}
    c = load()
    cache: dict[str, list[dict[str, Any]]] = {}
    n, changed = 0, False
    for it in _coverage_items():
        bars = series.get(it["symbol"])
        if bars and it["ticker"] in c["quarters"]:
            r = reactions_from_bars(c, it["ticker"], bars, await _market_bars(it["symbol"], source, cache), provider)
            n, changed = n + r["detected_now"], changed or r["changed"]
    if changed:
        save(c)
    if n:   # estimates of later quarters (前年同期 + 364, typical lag) are re-based on the detected dates
        await refresh(load(), use_jpx=False, use_tv=False)
    return {"detected": n}


def _ics_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line: str) -> str:
    """RFC 5545 line folding at 75 octets (never inside a UTF-8 character)."""
    out, cur, n = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if n + b > 75:
            out.append(cur)
            cur, n = " " + ch, 1 + b
        else:
            cur, n = cur + ch, n + b
    out.append(cur)
    return "\r\n".join(out)


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


@router.get("/calendar.ics")
async def calendar_ics(days: int = 180, estimates: bool = True):
    """The earnings calendar as an iCalendar file (Outlook / Google カレンダー: import, or subscribe to this URL on
    the same PC). All-day events; the status (確定・予定・推定…) is in the title."""
    cal = await calendar_ep(days)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//analyst-terminal//earnings//JA", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:決算カレンダー（ターミナル）"]
    for r in cal["rows"]:
        if r["status"] == "推定" and not estimates:
            continue
        d = dt.date.fromisoformat(r["date"])
        lines += ["BEGIN:VEVENT", f"UID:{r['ticker']}-{r['id']}@analyst-terminal", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}",
                  "SUMMARY:" + _ics_text(f"決算 {r['ticker']} {r.get('name') or ''} {r['label']}（{r['status']}）"),
                  "DESCRIPTION:" + _ics_text(f"{r['label_ja']} / 出所: {r.get('source') or ''}"),
                  "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    body = "\r\n".join(_ics_fold(x) for x in lines) + "\r\n"
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="earnings.ics"'})


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
    t = ticker.split(":")[-1].upper()
    c = load()
    company_view(c, t)                     # sets each quarter's state (used in the notes.md header)
    changed, rows = sync_company(c, t, *_cov_context(t))
    if changed:
        c["log"] = (c["log"] + [{**x, "at": _now()} for x in rows])[-1000:]
        save(c)
    return company_view(c, t)


@router.get("/{ticker}/reactions")
async def reactions_ep(ticker: str, source: str | None = None):
    """決算時の株価反応 of one company (price history of the stock and of the market)."""
    t = ticker.split(":")[-1].upper()
    it, _ = _cov_context(t)
    symbol = it["symbol"] if it else (ticker.upper() if ":" in ticker else f"TSE:{t}")
    provider = (await S.provider(source)).name
    bars = await S.history(symbol, "1D", 800, source)
    c = load()
    res = reactions_from_bars(c, t, bars, await _market_bars(symbol, source, {}), provider)
    if res["changed"]:
        save(c)
    if res["detected_now"]:
        await refresh(load(), use_jpx=False, use_tv=False, tickers=[t])
    return {**res, "symbol": symbol, "market_symbol": market_symbol(symbol)}


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
        q.pop("notes_conflict", None)      # saving from the terminal resolves a shown conflict
    if req.checklist is not None:
        q["checklist"] = req.checklist
    q["updated"] = _now()
    it, stock = _cov_context(t)
    if it and stock:
        q["state"] = E.quarter_state(q, dt.date.today()) if q.get("period_start") else q.get("state")
        a = sync_notes(it, q, quarter_dir(stock, qid))
        if a and a not in QUIET:
            c["log"].append({"at": _now(), "ticker": t, "qid": qid, "what": "メモ", "from": "", "to": a, "source": "notes.md"})
    save(c)
    if req.earnings_date == "":
        await refresh(load(), use_jpx=False, use_tv=False, tickers=[t])
    return company_view(load(), t)


@router.post("/{ticker}/{qid}/folder")
async def quarter_folder(ticker: str, qid: str):
    """The quarter's folder: <stock folder>/quarters/FY2027_2Q/ with notes.md (kept in sync with the quarter page)."""
    from .api_coverage import _item, _open_path, state, stock_dir

    cov = state()
    it = _item(cov, ticker)
    c = load()
    q = (c["quarters"].get(it["ticker"]) or {}).get(qid)
    if not q:
        raise HTTPException(404, "quarter not found")
    p = quarter_dir(stock_dir(cov, it), qid)
    p.mkdir(parents=True, exist_ok=True)
    q["state"] = E.quarter_state(q, dt.date.today())
    sync_notes(it, q, p)
    save(c)
    return {"path": str(p), "opened": _open_path(p)}
