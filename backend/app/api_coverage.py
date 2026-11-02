"""COV endpoints — coverage list from the Notion 銘柄マスタ, earnings dates → Notion, local folders, per-stock
Excel / folder / Notion / fundamental report. Pure logic lives in coverage.py; Notion calls in notion_api.py.

Every write to Notion or to the disk is a separate explicit call with ``apply``; without it the endpoint only
returns the plan (dry run)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import coverage as C
from .notion_api import EARNINGS_PROPS, NotionClient, NotionError, parse_master_row
from .state import DATA_DIR, S

router = APIRouter(prefix="/api/coverage")
MARKER = ".coverage.json"
EARN_COLS = ["description", "earnings_release_next_date", "earnings_release_date", "close"]
REPORT_COLS = ["description", "close", "market_cap_basic", "price_earnings_ttm", "price_book_ratio", "enterprise_value_ebitda_ttm",
               "dividend_yield_recent", "return_on_equity", "operating_margin", "total_revenue_yoy_growth_ttm", "Perf.1M"]
REPORT_FALLBACK = ["description", "close", "market_cap_basic", "price_earnings_ttm", "price_book_ratio", "dividend_yield_recent"]


# ---- state ------------------------------------------------------------------------------------
def state() -> dict[str, Any]:
    cov = S.store.get("coverage") or {}
    cov.setdefault("items", [])
    cov.setdefault("pages", {})
    cfg = cov.setdefault("config", {})
    cfg.setdefault("layout", "sector")
    return cov


def save(cov: dict[str, Any]) -> None:
    S.store.set("coverage", cov)


def root_dir(cov: dict[str, Any] | None = None) -> Path:
    cfg = (cov or state())["config"]
    raw = cfg.get("root") or os.environ.get("COVERAGE_DIR")
    return Path(raw).expanduser() if raw else (S.excel.roots[0] / "Coverage")


def ensure_excel_root(root: Path) -> None:
    """Files under the coverage root must be visible to XLS (auto-link by ticker in the path)."""
    r = root.resolve()
    for ex in S.excel.roots:
        exr = ex.resolve()
        if r == exr or exr in r.parents:
            return
    S.excel.roots.append(root)


def db_id(cov: dict[str, Any]) -> str:
    v = cov["config"].get("db_id") or os.environ.get("NOTION_COVERAGE_DB", "")
    if not v:
        raise HTTPException(400, "銘柄マスタのデータベース ID が未設定（COV の SETTINGS か .env の NOTION_COVERAGE_DB）")
    return v


def micro_page(cov: dict[str, Any]) -> str | None:
    return cov["config"].get("micro_page") or os.environ.get("NOTION_MICRO_PAGE") or None


def markers(root: Path) -> dict[str, Path]:
    """{ticker: folder} from .coverage.json markers (depth ≤ 2 below the root)."""
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for p in list(root.glob(f"*/{MARKER}")) + list(root.glob(f"*/*/{MARKER}")):
        try:
            t = json.loads(p.read_text(encoding="utf-8")).get("ticker")
        except (OSError, ValueError):
            continue
        if t:
            out[str(t)] = p.parent
    return out


def _item(cov: dict[str, Any], ticker: str) -> dict[str, Any]:
    t = ticker.split(":")[-1].upper()
    it = next((x for x in cov["items"] if x["ticker"] == t), None)
    if not it:
        raise HTTPException(404, f"{t} はカバレッジにない（SYNC FROM NOTION）")
    return it


# ---- list / config ---------------------------------------------------------------------------------
@router.get("")
async def coverage_list():
    cov = state()
    root = root_dir(cov)
    ensure_excel_root(root)
    mk = markers(root)
    files = S.excel.list_files()
    manual = S.store.get("excel_links") or {}
    snap = {}
    try:
        from .api_trinity import _read, tdir
        snap = {r["symbol"]: r for r in (_read(tdir() / "latest.json") or {}).get("rows", [])}
    except Exception:  # noqa: BLE001
        pass
    today = dt.date.today()
    out = []
    from .api_earnings import load as earn_load, summary as earn_summary
    ecal = earn_load()
    for it in cov["items"]:
        pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(it['ticker'])}(?![A-Za-z0-9])", re.I)
        nfiles = sum(1 for f in files if pat.search(f["path"])) + len(manual.get(it["symbol"], []))
        e = earn_summary(it["ticker"], ecal) or {}
        a = snap.get(it["symbol"])
        out.append({**it, "earnings": e, "folder": str(mk[it["ticker"]].relative_to(root)) if it["ticker"] in mk and root in mk[it["ticker"]].parents else None,
                    "excel_files": nfiles, "page": cov["pages"].get(it["ticker"]),
                    "auto": {"direction": a["direction"], "conviction": a["conviction"], "f": a["f"]["score"]} if a else None})
    return {"items": out, "config": {**cov["config"], "root_resolved": str(root)}, "synced_at": cov.get("synced_at"),
            "notion_token": bool(os.environ.get("NOTION_TOKEN")), "db_id": cov["config"].get("db_id") or os.environ.get("NOTION_COVERAGE_DB"),
            "micro_page": micro_page(cov), "pages_found": len(cov["pages"])}


class CovConfig(BaseModel):
    root: str | None = None
    layout: str | None = None
    db_id: str | None = None
    micro_page: str | None = None


@router.put("/config")
async def put_config(req: CovConfig):
    cov = state()
    for k, v in req.model_dump().items():
        if v is not None:
            cov["config"][k] = v.strip() if isinstance(v, str) else v
    if cov["config"].get("layout") not in ("sector", "ticker"):
        cov["config"]["layout"] = "sector"
    save(cov)
    ensure_excel_root(root_dir(cov))
    return {"config": cov["config"], "root_resolved": str(root_dir(cov))}


# ---- sync from Notion -----------------------------------------------------------------------------
@router.post("/sync")
async def sync():
    cov = state()
    nc = NotionClient()
    try:
        rows = await nc.query_database(db_id(cov))
        items = [x for x in (parse_master_row(r) for r in rows) if x]
        pages = await nc.company_pages(micro_page(cov)) if micro_page(cov) else {}
    except NotionError as e:
        raise HTTPException(e.status, str(e)) from e
    finally:
        await nc.close()
    old = {x["ticker"]: x for x in cov["items"]}
    for it in items:  # keep locally collected data (earnings) across syncs
        if it["ticker"] in old and old[it["ticker"]].get("earnings"):
            it["earnings"] = old[it["ticker"]]["earnings"]
    items.sort(key=lambda x: (x.get("gics_group") or "~", x["ticker"]))
    cov["items"], cov["pages"] = items, pages or cov["pages"]
    cov["synced_at"] = dt.datetime.now().isoformat(timespec="seconds")
    save(cov)
    missing = [x["ticker"] for x in items if x["ticker"] not in cov["pages"]]
    return {"items": len(items), "pages": len(cov["pages"]), "without_page": missing[:50], "calls": nc.calls,
            "removed": sorted(set(old) - {x["ticker"] for x in items})}


# ---- earnings ------------------------------------------------------------------------------------
@router.post("/earnings/refresh")
async def earnings_refresh():
    """Mechanical fill of earnings dates in the independent calendar (JPX → TradingView → estimates)."""
    from .api_earnings import load, refresh

    if not state()["items"]:
        raise HTTPException(400, "カバレッジが空（SYNC FROM NOTION）")
    res = await refresh(load())
    return {"updated": res["companies"], "of": len(state()["items"]), **res}


class EarnManual(BaseModel):
    next: str


@router.put("/{ticker}/earnings")
async def earnings_manual(ticker: str, req: EarnManual):
    """Pin a date by hand: stored in the independent calendar on the quarter it reports (never overwritten)."""
    from . import earnings as E
    from .api_earnings import load, refresh, save, summary

    cov = state()
    it = _item(cov, ticker)
    d = C.to_date(req.next)
    if not d:
        raise HTTPException(400, "YYYY-MM-DD")
    c = load()
    if it["ticker"] not in c["quarters"]:
        await refresh(c, use_jpx=False, use_tv=False, tickers=[it["ticker"]])
        c = load()
    fye = (c["companies"].get(it["ticker"]) or {}).get("fye_month") or it.get("fye_month")
    if not fye:
        raise HTTPException(400, "決算期末月が不明（PUT /api/earnings/<ticker>/fye で設定）")
    hit = E.quarter_for_release(d, fye, None, c["config"].get("convention", "end"))
    q = (c["quarters"].get(it["ticker"]) or {}).get(E.qid(hit[0], hit[1])) if hit else None
    if not q:
        raise HTTPException(400, "この日付に対応する四半期がない")
    q["earnings"] = {"date": d.isoformat(), "status": "手入力", "source": "手入力", "fetched": dt.datetime.now().isoformat(timespec="seconds")}
    save(c)
    s = summary(it["ticker"]) or {}
    return {**s, "next_title_base": q["label"], "pinned": q["id"]}


@router.get("/calendar")
async def calendar(days: int = 90):
    from .api_earnings import calendar_ep
    return await calendar_ep(days)


class NotionEarnReq(BaseModel):
    apply: bool = False
    create_pages: bool = True
    update_master: bool = True
    add_properties: bool = False
    days_ahead: int = 60
    tickers: list[str] | None = None


@router.post("/notion/earnings")
async def notion_earnings(req: NotionEarnReq):
    """OPTIONAL export (not the system of record — the terminal's earnings calendar is). Writes the next earnings
    date to Notion: the 銘柄マスタ row and a quarter page under the company page (only when none exists yet)."""
    cov = state()
    today = dt.date.today()
    want = {t.split(":")[-1].upper() for t in req.tickers} if req.tickers else None
    plan = []
    from .api_earnings import load as earn_load, summary as earn_summary
    ecal = earn_load()
    atlas = ecal["config"].get("convention", "end") == "start_plus_1"
    for it in cov["items"]:
        e = earn_summary(it["ticker"], ecal) or {}
        base = e.get("next_title")
        ended = bool(e.get("next_period_end")) and e["next_period_end"] < today.isoformat()
        e["next_title_base"], e["next_title"] = base, (base + (" ■" if ended else "") if base else None)   # ATLAS page title style
        if want and it["ticker"] not in want:
            continue
        if not e.get("next"):
            continue
        days = (dt.date.fromisoformat(e["next"]) - today).days
        if not want and not (-3 <= days <= req.days_ahead):
            continue
        page = cov["pages"].get(it["ticker"])
        fye = e.get("fye_month") or it.get("fye_month")
        plan.append({"ticker": it["ticker"], "name": it.get("name"), "date": e["next"], "days": days, "status": e.get("next_status"),
                     "source": e.get("next_source"), "title": e.get("next_title"), "title_base": e.get("next_title_base"),
                     "note": "12月決算: ATLAS の既存ページと FY が 1 年ずれる（標準の表記）" if fye == 12 and not atlas else None,
                     "page": page["id"] if page else None, "master": it.get("master_page_id"),
                     "page_action": ("create?" if page and e.get("next_title") else "決算期末月なし" if page else "個社ページなし") if req.create_pages else "skip",
                     "master_action": ("update" if it.get("master_page_id") else "行なし") if req.update_master else "skip"})
    if not req.apply:
        return {"apply": False, "plan": plan}
    nc = NotionClient()
    try:
        if req.add_properties and req.update_master:
            schema = (await nc.database(db_id(cov))).get("properties", {})
            add = {}
            if EARNINGS_PROPS["next_date"] not in schema:
                add[EARNINGS_PROPS["next_date"]] = {"date": {}}
            if EARNINGS_PROPS["next_title"] not in schema:
                add[EARNINGS_PROPS["next_title"]] = {"rich_text": {}}
            if add:
                await nc.add_database_properties(db_id(cov), add)
        for p in plan:
            if p["master_action"] == "update":
                try:
                    props: dict[str, Any] = {EARNINGS_PROPS["next_date"]: {"date": {"start": p["date"]}}}
                    if p.get("title_base"):
                        props[EARNINGS_PROPS["next_title"]] = {"rich_text": [{"text": {"content": p["title_base"]}}]}
                    await nc.update_properties(p["master"], props)
                    p["master_action"] = "updated"
                except NotionError as ex:
                    p["master_action"] = f"error: {ex}"
            if p["page_action"] == "create?":
                try:
                    existing = await nc.child_pages(p["page"], 1)
                    hit = next((x for x in existing if x["title"].startswith(p["title_base"])), None)
                    if hit:
                        p["page_action"] = f"exists ({hit['title']})"
                        continue
                    body = [{"object": "block", "type": "callout", "callout": {
                        "rich_text": [{"type": "text", "text": {"content": f"決算発表日: {p['date']}（{p.get('status') or ''}・{p.get('source') or ''}、{today.isoformat()} ターミナルの決算カレンダーより）"}}],
                        "icon": {"type": "emoji", "emoji": "📅"}}}]
                    np = await nc.create_page(p["page"], p["title"], body)
                    p["page_action"] = "created"
                    p["page_url"] = np.get("url")
                except NotionError as ex:
                    p["page_action"] = f"error: {ex}"
    except NotionError as e:
        raise HTTPException(e.status, str(e)) from e
    finally:
        await nc.close()
    return {"apply": True, "plan": plan, "calls": nc.calls}


# ---- folders -------------------------------------------------------------------------------------------
class FolderReq(BaseModel):
    apply: bool = False
    layout: str | None = None
    tickers: list[str] | None = None


# ---- move the whole root (e.g. to OneDrive) -----------------------------------------------------------
class MoveRootReq(BaseModel):
    to: str
    apply: bool = False


LOCK_FILE = re.compile(r"^~\$|^\.~lock\.|\.tmp$", re.I)      # Office / LibreOffice lock files, temp files


def _move_plan(src: Path, dst: Path) -> dict[str, Any]:
    files: list[tuple[Path, int]] = []
    same: set[str] = set()
    clash: list[str] = []
    for p in sorted(src.rglob("*")):
        if not p.is_file() or LOCK_FILE.search(p.name):
            continue
        rel, st = p.relative_to(src), p.stat()
        files.append((rel, st.st_size))
        t = dst / rel
        if t.exists():
            ts = t.stat()
            if ts.st_size == st.st_size and abs(ts.st_mtime - st.st_mtime) < 2:
                same.add(rel.as_posix())          # an earlier, interrupted run already copied it
            else:
                clash.append(rel.as_posix())
    top = sorted({r.parts[0] for r, _ in files})
    return {"from": str(src), "to": str(dst), "files": len(files), "bytes": sum(n for _, n in files), "top": top[:200],
            "n_top": len(top), "already": len(same), "conflicts": clash[:100], "n_conflicts": len(clash),
            "_files": files, "_same": same}


def _copy_verify(src: Path, dst: Path, files: list[tuple[Path, int]], same: set[str]) -> dict[str, Any]:
    errors = []
    for rel, _ in files:
        if rel.as_posix() in same:
            continue
        try:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, dst / rel)
        except OSError as e:
            errors.append(f"{rel.as_posix()}: {e}")
    bad = [rel.as_posix() for rel, _ in files
           if not (dst / rel).is_file() or (src / rel).is_file() and (dst / rel).stat().st_size != (src / rel).stat().st_size]
    return {"errors": errors[:50], "n_errors": len(errors), "mismatch": bad[:50], "n_mismatch": len(bad)}


@router.post("/move_root")
async def move_root(req: MoveRootReq):
    """Move the whole coverage root — stock folders, Excel models, reports, quarter folders and the earnings calendar
    (_terminal) — to a new place such as OneDrive: COPY → verify every file → switch the root. The old folder is
    never deleted (check the new place, then delete it by hand). apply=false returns the plan only."""
    cov = state()
    src = root_dir(cov).resolve()
    raw = req.to.strip().strip('"')
    if not raw:
        raise HTTPException(400, "移動先を入力")
    dst = Path(raw).expanduser()
    if not dst.is_absolute():
        raise HTTPException(400, "移動先は絶対パスで（例 C:\\Users\\<you>\\OneDrive\\Coverage）")
    dst = dst.resolve()
    if dst == src or src in dst.parents or dst in src.parents:
        raise HTTPException(400, "移動先が今のルートと同じ、またはその内側／外側")
    if not src.is_dir():
        raise HTTPException(400, f"今のルートがない: {src}")
    plan = await asyncio.to_thread(_move_plan, src, dst)
    public = {k: v for k, v in plan.items() if not k.startswith("_")}
    if not req.apply:
        return {"apply": False, **public}
    if plan["n_conflicts"]:
        raise HTTPException(409, f"移動先に内容の違う同名ファイルが {plan['n_conflicts']} 件ある（例 {plan['conflicts'][0]}）。"
                                 "別の場所を指定するか、移動先を整理してから")
    res = await asyncio.to_thread(_copy_verify, src, dst, plan["_files"], plan["_same"])
    if res["n_errors"] or res["n_mismatch"]:
        return {"apply": True, "switched": False, **public, **res,
                "message": "コピーできないファイルがあったため、ルートは切り替えていない（Excel で開いているファイルを閉じて再実行。"
                           "コピー済みのものは次回スキップされる）"}
    before = {f["id"]: (Path(f["root"]) / f["path"]).resolve() for f in S.excel.list_files()}
    cov["config"]["root"] = str(dst)
    save(cov)
    idx = next((i for i, r in enumerate(S.excel.roots) if r.resolve() == src), None)
    if idx is not None:                       # the old root joined the Excel library as the coverage root:
        S.excel.roots[idx] = dst              # take its slot, so file ids (and links) stay the same
    else:
        ensure_excel_root(dst)
    # manual Excel links → the same files (moved ones in the new root), whatever their ids are now
    after = {(Path(f["root"]) / f["path"]).resolve(): f["id"] for f in S.excel.list_files()}
    links, n = dict(S.store.get("excel_links") or {}), 0
    for sym, ids in links.items():
        new_ids = []
        for fid in ids:
            p = before.get(fid)
            nid = after.get((dst / p.relative_to(src)).resolve() if src in p.parents else p) if p else None
            new_ids.append(nid or fid)
            n += bool(nid and nid != fid)
        links[sym] = new_ids
    if n:
        S.store.set("excel_links", links)
    return {"apply": True, "switched": True, **public, **res, "root": str(dst), "old_root_kept": str(src), "links_remapped": n,
            "message": f"{plan['files']} 件をコピーして確認し、ルートを {dst} に切り替えた。元のフォルダ {src} は残してある"
                       "（確認後に手で削除。削除するまでは XLS に同じファイルが見えることがある）"}


@router.post("/folders")
async def folders(req: FolderReq):
    cov = state()
    layout = req.layout or cov["config"].get("layout", "sector")
    root = root_dir(cov)
    items = [x for x in cov["items"] if not req.tickers or x["ticker"] in {t.split(":")[-1].upper() for t in req.tickers}]
    plan = C.plan_folders(items, root, layout, markers(root))
    if not req.apply:
        return {"apply": False, "root": str(root), "layout": layout, "plan": plan,
                "summary": {a: sum(1 for p in plan if p["action"] == a) for a in ("create", "adopt", "move", "ok")}}
    root.mkdir(parents=True, exist_ok=True)
    byt = {x["ticker"]: x for x in items}
    for p in plan:
        target = Path(p["to"])
        try:
            if p["action"] == "move":
                if target.exists():
                    p["result"] = "移動先が既に存在（スキップ）"
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(p["from"], str(target))
            target.mkdir(parents=True, exist_ok=True)
            (target / "reports").mkdir(exist_ok=True)
            it = byt[p["ticker"]]
            (target / MARKER).write_text(json.dumps({"ticker": it["ticker"], "name": it.get("name"), "gics_group": it.get("gics_group"),
                                                     "tool": "analyst-terminal"}, ensure_ascii=False, indent=1), encoding="utf-8")
            p["result"] = "done"
        except OSError as e:
            p["result"] = f"error: {e}"
    cov["config"]["layout"] = layout
    save(cov)
    ensure_excel_root(root)
    return {"apply": True, "root": str(root), "layout": layout, "plan": plan}


def stock_dir(cov: dict[str, Any], it: dict[str, Any], create: bool = True) -> Path:
    root = root_dir(cov)
    cur = markers(root).get(it["ticker"])
    if cur:
        return cur
    target = root / C.rel_stock_dir(it, cov["config"].get("layout", "sector"))
    if create:
        target.mkdir(parents=True, exist_ok=True)
        (target / "reports").mkdir(exist_ok=True)
        (target / MARKER).write_text(json.dumps({"ticker": it["ticker"], "name": it.get("name"), "tool": "analyst-terminal"},
                                                ensure_ascii=False), encoding="utf-8")
        ensure_excel_root(root)
    return target


def _open_path(p: Path) -> bool:
    """Open a folder/file with the OS (only meaningful when the server runs on the user's PC)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, AttributeError):
        return False


@router.post("/{ticker}/open_folder")
async def open_folder(ticker: str):
    cov = state()
    p = stock_dir(cov, _item(cov, ticker))
    return {"path": str(p), "opened": _open_path(p)}


@router.post("/{ticker}/excel")
async def open_excel(ticker: str, create: bool = True):
    """Open the stock's linked Excel in Excel; with none linked, create <ticker>_<社名>_model.xlsx in its folder."""
    cov = state()
    it = _item(cov, ticker)
    linked = S.excel.match_symbol(it["symbol"], S.store.get("excel_links") or {})
    created = None
    if not linked and create:
        import openpyxl

        folder = stock_dir(cov, it)
        path = folder / f"{C.stock_folder_name(it['ticker'], it.get('name'))}_model.xlsx"
        if not path.exists():
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Model"
            ws.append([f"{it['ticker']} {it.get('name') or ''}", None, "FYE", it.get("fye_month")])
            ws.append(["項目", "FY-2", "FY-1", "FY0", "FY+1", "FY+2"])
            for row in ("売上高", "営業利益", "営業利益率", "純利益", "EPS"):
                ws.append([row])
            wb.create_sheet("Assumptions").append(["前提", "値", "出典"])
            wb.create_sheet("Notes").append(["日付", "メモ"])
            wb.save(path)
        created = str(path)
        linked = S.excel.match_symbol(it["symbol"], S.store.get("excel_links") or {})
    if not linked:
        raise HTTPException(404, "紐付いた Excel がない")
    res = {}
    try:
        res = S.excel.open_native(linked[0]["id"])
    except Exception as e:  # noqa: BLE001 - not possible on a headless server; the UI still shows XLS
        res = {"opened": False, "error": str(e)}
    return {"file": linked[0], "created": created, **res}


# ---- fundamental report ---------------------------------------------------------------------------------
class ReportReq(BaseModel):
    to_notion: bool = False
    save: bool = True
    source: str | None = None


@router.post("/{ticker}/report")
async def report(ticker: str, req: ReportReq):
    from .analytics import performance
    from .api_analysis import _many
    from .api_insight import xray_inputs

    cov = state()
    it = _item(cov, ticker)
    sym = it["symbol"]
    errors: dict[str, str] = {}
    scan: dict[str, Any] = {}
    peers_items = [x for x in cov["items"] if x.get("gics_sub") and x.get("gics_sub") == it.get("gics_sub") and x["ticker"] != it["ticker"]]
    try:
        scan_all = await S.web.scan_symbols([sym] + [p["symbol"] for p in peers_items[:20]], REPORT_COLS, REPORT_FALLBACK)
        scan = scan_all.get(sym) or {}
    except Exception as e:  # noqa: BLE001
        scan_all, errors["scanner"] = {}, str(e)
    series, err = await _many([sym], "1D", 400, req.source)
    errors.update(err)
    perf = {}
    if series.get(sym):
        p = performance(series[sym])
        perf = {"1M": p.get("1M"), "3M": p.get("3M"), "1Y": p.get("1Y"), "vol_1y": p.get("VOL_1Y")}
        if not scan.get("close"):
            scan = {**scan, "close": series[sym][-1]["close"]}
    snap_rows: dict[str, Any] = {}
    try:
        from .api_trinity import _read, tdir
        snap_rows = {r["symbol"]: r for r in (_read(tdir() / "latest.json") or {}).get("rows", [])}
    except Exception:  # noqa: BLE001
        pass
    xr = None
    try:
        etf = C.TOPIX17_ETF.get(it.get("topix17") or "")
        res, _, xerr = await xray_inputs([sym], {sym: etf}, 252, req.source)
        xr = res.get(sym)
        errors.update({k: v for k, v in xerr.items() if k == sym})
    except Exception as e:  # noqa: BLE001
        errors["xray"] = str(e)
    chip = None
    try:
        from .api_framework import top_bottom
        chip = await top_bottom(sym, source=req.source)
    except Exception as e:  # noqa: BLE001
        errors["chip"] = str(e)
    cards = (S.store.get("scorecards") or {}).get(sym) or []
    tr = None
    txs = (S.store.get("transcripts") or {}).get(sym) or []
    if txs:
        from . import transcripts as TX
        cur = txs[-1]
        d = TX.diff(txs[-2]["text"], cur["text"]) if len(txs) > 1 else None
        a = TX.analyze(cur["text"])
        tr = {"period": cur["period"], "net_tone": a["tone"]["net_tone"], "change_score": d["change_score"] if d else None,
              "evasiveness": a.get("evasiveness_avg")}
    themes = [t["name"] for t in (S.store.get("themes") or []) if any(m.get("symbol") == sym for m in (t.get("longs") or []) + (t.get("shorts") or []))]
    peers = []
    for pi in peers_items[:20]:
        ps = scan_all.get(pi["symbol"]) or {}
        a = snap_rows.get(pi["symbol"])
        peers.append({"ticker": pi["ticker"], "name": pi.get("name"), "pe": ps.get("price_earnings_ttm"), "pb": ps.get("price_book_ratio"),
                      "ret_1m": ps.get("Perf.1M"), "verdict": f"{a['direction']} c{a['conviction']}" if a else None})
    margin = None
    try:
        from .api_research import mstore
        from .margin import stock_analysis
        ms = mstore().series(it["ticker"])
        if ms:
            margin = stock_analysis(ms, series.get(sym) or [])
    except Exception as e:  # noqa: BLE001
        errors["margin"] = str(e)
    from .api_earnings import summary as earn_summary
    ctx = {"item": it, "scan": scan, "perf": perf, "earnings": earn_summary(it["ticker"]) or it.get("earnings"), "auto_row": snap_rows.get(sym), "margin": margin,
           "scorecard": cards[-1] if cards else None, "xray": xr, "chip": chip, "peers": peers, "transcript": tr, "themes": themes,
           "generated_at": dt.datetime.now().isoformat(timespec="seconds"), "source": req.source or S.registry.active_name}
    rep = C.build_report(ctx)
    out: dict[str, Any] = {"title": rep["title"], "markdown": rep["markdown"], "errors": errors}
    if req.save:
        folder = stock_dir(cov, it)
        path = folder / "reports" / f"{dt.date.today().isoformat()}_{it['ticker']}_ファンダメンタル.md"
        path.write_text(rep["markdown"], encoding="utf-8")
        out["path"] = str(path)
    if req.to_notion:
        page = cov["pages"].get(it["ticker"])
        if not page:
            raise HTTPException(400, "Notion の個社ページが見つからない（SYNC FROM NOTION で MICRO ページを設定）")
        nc = NotionClient()
        try:
            np = await nc.create_page(page["id"], f"ターミナル・レポート {dt.date.today().isoformat()}", C.notion_blocks(rep))
            out["notion_url"] = np.get("url")
        except NotionError as e:
            raise HTTPException(e.status, str(e)) from e
        finally:
            await nc.close()
    return out


def coverage_symbols() -> list[str]:
    return [x["symbol"] for x in state()["items"]]


def coverage_meta() -> dict[str, dict[str, Any]]:
    return {x["symbol"]: x for x in state()["items"]}


_ = DATA_DIR  # data dir is used indirectly through the store / excel library
