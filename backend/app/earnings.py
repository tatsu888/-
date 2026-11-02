"""Independent earnings / fiscal-quarter system (the terminal is the system of record — not Notion).

Per company: fiscal-year-end month (with its source) and quarter "pages" (FY, Q, period, earnings date,
status, notes, checklist, links). Next earnings dates are filled MECHANICALLY with a fixed priority:

    1. 手入力 (manual pin)                — never overwritten by the machine
    2. 確定   JPX 決算発表予定日一覧         — official schedule (xlsx; downloaded or uploaded)
    3. 予定   TradingView スキャナー        — earnings_release_next_date
    4. 発表済 TradingView 前回決算日        — earnings_release_date (actual, for the quarter it reports)
    5. 推定   前年同期の発表日 + 364 日      — same weekday one year later
    6. 推定   四半期末 + その会社の通常の日数 — median past lag (default 40 days, 本決算 45 days)
Every candidate is kept with its source and fetch time; changes are logged.

FY label conventions:
    "end"          (default, standard 決算期 naming) FY = calendar year in which the fiscal year ENDS
                   2026年12月期 = FY2026 (Jan–Dec 2026);  2027年3月期 = FY2027 (Apr 2026–Mar 2027)
    "start_plus_1" (ATLAS pages as found in Notion)   FY = start year + 1 (differs only for 12月決算)
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import unicodedata
from statistics import median
from typing import Any

D = dt.date
KIND_Q = {"第１四半期": 1, "第1四半期": 1, "1Q": 1, "第２四半期": 2, "第2四半期": 2, "中間": 2, "2Q": 2,
          "第３四半期": 3, "第3四半期": 3, "3Q": 3, "本決算": 4, "通期": 4, "期末": 4, "4Q": 4}


# ---------------------------------------------------------------------------
# fiscal calendar
# ---------------------------------------------------------------------------
def month_end(y: int, m: int) -> D:
    return D(y, m, calendar.monthrange(y, m)[1])


def add_months(d: D, n: int) -> D:
    y, m = divmod(d.month - 1 + n, 12)
    return month_end(d.year + y, m + 1)


def fy_of(quarter_end: D, fye_month: int, convention: str = "end") -> tuple[int, int]:
    """(FY label, quarter n) of the quarter ending at ``quarter_end``."""
    start_month = fye_month % 12 + 1
    k = (quarter_end.month - start_month) % 12
    n = k // 3 + 1
    start_year = quarter_end.year if quarter_end.month >= start_month else quarter_end.year - 1
    end_year = start_year if fye_month == 12 else start_year + 1
    return (end_year if convention == "end" else start_year + 1), n


def quarter_end_of(fy: int, q: int, fye_month: int, convention: str = "end") -> D:
    end_year = fy if convention == "end" else (fy - 1 if fye_month == 12 else fy)
    fy_end = month_end(end_year, fye_month)
    return add_months(fy_end, -3 * (4 - q))


def qid(fy: int, q: int) -> str:
    return f"FY{fy}-{q}Q"


def labels(fy: int, q: int, fye_month: int, convention: str = "end") -> dict[str, str]:
    end = quarter_end_of(fy, 4, fye_month, convention)
    kind = "本決算" if q == 4 else f"第{q}四半期"
    return {"label": f"FY{fy} {q}Q", "label_ja": f"{end.year}年{fye_month}月期 {kind}"}


def quarters_around(today: D, fye_month: int, back: int = 8, ahead: int = 4, convention: str = "end") -> list[dict[str, Any]]:
    """Quarter skeletons: ``back`` ended quarters + the current one + ``ahead`` future ones."""
    # quarter ends are the months ≡ fye_month (mod 3)
    m = today.month
    y = today.year
    while (m - fye_month) % 3:
        m += 1
        if m > 12:
            m, y = 1, y + 1
    cur_end = month_end(y, m)
    out = []
    for k in range(-back, ahead + 1):
        e = add_months(cur_end, 3 * k)
        fy, q = fy_of(e, fye_month, convention)
        out.append({"id": qid(fy, q), "fy": fy, "q": q, "period_start": (add_months(e, -3) + dt.timedelta(days=1)).isoformat(),
                    "period_end": e.isoformat(), **labels(fy, q, fye_month, convention)})
    return out


def rekey(quarters: dict[str, dict[str, Any]], fye_month: int, convention: str = "end") -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Re-label stored quarter pages after the FYE month or the FY convention changed — notes, checklist,
    pinned dates and candidates are kept (they belong to the period, not to the label). Quarters whose
    period end is not a quarter end under the new FYE are returned separately (to be archived, never deleted)."""
    out: dict[str, dict[str, Any]] = {}
    dropped: list[dict[str, Any]] = []
    for q in sorted(quarters.values(), key=lambda x: x.get("period_end", "")):
        pe = D.fromisoformat(q["period_end"])
        if (pe.month - fye_month) % 3 or pe != month_end(pe.year, pe.month):
            dropped.append(q)
            continue
        fy, n = fy_of(pe, fye_month, convention)
        nid = qid(fy, n)
        out[nid] = {**q, "id": nid, "fy": fy, "q": n, "period_start": (add_months(pe, -3) + dt.timedelta(days=1)).isoformat(),
                    **labels(fy, n, fye_month, convention)}
    return out, dropped


def quarter_for_release(release: D, fye_month: int, q_hint: int | None = None, convention: str = "end",
                        min_gap: int = 7, max_gap: int = 120) -> tuple[int, int, D] | None:
    """Which quarter an earnings release on ``release`` reports (optionally constrained to quarter q_hint)."""
    e = month_end(release.year, release.month)
    for _ in range(10):
        gap = (release - e).days
        if gap >= min_gap and (e.month - fye_month) % 3 == 0:
            if gap > max_gap:
                return None
            fy, q = fy_of(e, fye_month, convention)
            if q_hint is None or q == q_hint:
                return fy, q, e
        e = add_months(e, -1)
    return None


# ---------------------------------------------------------------------------
# JPX 決算発表予定日一覧 parser (header detection by text; layouts change)
# ---------------------------------------------------------------------------
JPX_HEAD = {"date": ("決算発表予定日", "発表予定日", "予定日"), "code": ("コード", "証券コード"), "name": ("会社名", "銘柄名"),
            "period": ("決算期末", "決算期"), "kind": ("種別", "決算種別", "区分", "四半期")}


def _norm(s: Any) -> str:
    """Full-width → half-width (NFKC) and no whitespace: "第２四半期" → "第2四半期", "６８５７" → "6857"."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s or "")))


def _date(v: Any) -> D | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, D):
        return v
    s = _norm(v)
    m = re.search(r"(\d{4})[/\-年.](\d{1,2})[/\-月.](\d{1,2})", s)
    if m:
        try:
            return D(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def parse_jpx_rows(rows: list[list[Any]]) -> list[dict[str, Any]]:
    hi, cols = None, {}
    for i, row in enumerate(rows[:40]):
        h = [_norm(x) for x in row]
        c = {}
        for f, keys in JPX_HEAD.items():
            for j, x in enumerate(h):
                if any(k in x for k in keys) and f not in c:
                    c[f] = j
        if {"date", "code"} <= c.keys():
            hi, cols = i, c
            break
    if hi is None:
        raise ValueError("header with 発表予定日 / コード not found")
    out = []
    for row in rows[hi + 1:]:
        if len(row) <= max(cols.values()):
            continue
        code = _norm(row[cols["code"]]).replace(".0", "")
        if not re.fullmatch(r"\d{3}[0-9A-Z]", code):
            continue
        d = _date(row[cols["date"]])
        if not d:
            continue
        rec: dict[str, Any] = {"ticker": code, "date": d.isoformat(), "name": str(row[cols["name"]]).strip() if "name" in cols else None}
        if "kind" in cols:
            k = _norm(row[cols["kind"]])
            rec["q"] = next((v for key, v in KIND_Q.items() if key in k), None)
        if "period" in cols:
            p = _norm(row[cols["period"]])
            m = re.search(r"(?:(\d{4})[年/.\-])?(\d{1,2})月", p) or re.search(r"(\d{4})[/.\-](\d{1,2})", p)
            if m:
                rec["fye_month"] = int(m.group(2))
                rec["fye_year"] = int(m.group(1)) if m.group(1) else None
        out.append(rec)
    if not out:
        raise ValueError("no rows parsed")
    return out


# ---------------------------------------------------------------------------
# resolution (mechanical fill)
# ---------------------------------------------------------------------------
PRIORITY = {"手入力": 0, "確定": 1, "予定": 2, "発表済": 1, "推定": 5}


def same_weekday_next_year(d: D) -> D:
    return d + dt.timedelta(days=364)


def typical_lag(quarters: list[dict[str, Any]], q: int) -> int:
    lags = []
    for x in quarters:
        e = x.get("earnings") or {}
        if e.get("status") in ("発表済", "確定", "手入力") and e.get("date") and (x["q"] == 4) == (q == 4):
            lags.append((D.fromisoformat(e["date"]) - D.fromisoformat(x["period_end"])).days)
    return int(median(lags)) if len(lags) >= 2 else (45 if q == 4 else 40)


def _better(c: dict[str, Any], b: dict[str, Any]) -> bool:
    rc, rb = PRIORITY.get(c["status"], 9), PRIORITY.get(b["status"], 9)
    if rc != rb:
        return rc < rb
    return (c.get("run") or 0, c.get("fetched") or "") > (b.get("run") or 0, b.get("fetched") or "")


def resolve(quarter: dict[str, Any], candidates: list[dict[str, Any]], prev_year: dict[str, Any] | None, lag: int,
            today: D) -> dict[str, Any]:
    """Pick the earnings date of one quarter from its candidates (see module docstring for the order)."""
    cur = quarter.get("earnings") or {}
    if cur.get("status") == "手入力":
        return cur
    best = None
    for c in candidates:   # lowest rank wins; on a tie the newer run / fetch wins, then the first listed
        if best is None or _better(c, best):
            best = c
    if best:
        out = {"date": best["date"], "status": best["status"], "source": best["source"], "fetched": best.get("fetched")}
        if out["status"] == "確定" and D.fromisoformat(out["date"]) < today:
            out["status"] = "発表済"  # the scheduled day has passed
        return out
    pe = D.fromisoformat(quarter["period_end"])
    pe_e = (prev_year or {}).get("earnings") or {}
    if pe_e.get("date") and pe_e.get("status") in ("発表済", "確定", "手入力"):
        d = same_weekday_next_year(D.fromisoformat(pe_e["date"]))
        return {"date": d.isoformat(), "status": "推定", "source": f"前年同期（{pe_e['date']}）+ 364 日"}
    d = pe + dt.timedelta(days=lag)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return {"date": d.isoformat(), "status": "推定", "source": f"四半期末 + {lag} 日（通常の日数）"}


def quarter_state(quarter: dict[str, Any], today: D) -> str:
    ps, pe = D.fromisoformat(quarter["period_start"]), D.fromisoformat(quarter["period_end"])
    e = quarter.get("earnings") or {}
    if today < ps:
        return "未到来"
    if today <= pe:
        return "期中"
    if e.get("status") == "発表済" or (e.get("date") and D.fromisoformat(e["date"]) < today):
        return "発表済（推定）" if e.get("status") == "推定" else "発表済"   # an estimated date that has passed
    return "決算待ち"


def next_earnings(quarters: list[dict[str, Any]], today: D) -> dict[str, Any] | None:
    up = [q for q in quarters if (q.get("earnings") or {}).get("date") and D.fromisoformat(q["earnings"]["date"]) >= today
          and q["earnings"]["status"] != "発表済"]
    up.sort(key=lambda q: q["earnings"]["date"])
    return up[0] if up else None


def last_earnings(quarters: list[dict[str, Any]], today: D) -> dict[str, Any] | None:
    done = [q for q in quarters if (q.get("earnings") or {}).get("date") and D.fromisoformat(q["earnings"]["date"]) < today
            and q["earnings"]["status"] in ("発表済", "手入力", "確定")]
    done.sort(key=lambda q: q["earnings"]["date"])
    return done[-1] if done else None
