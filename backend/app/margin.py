"""Japan margin trading balances (信用取引残高) — import + analysis.

Source: JPX publishes weekly per-stock margin balances (銘柄別信用取引週末残高) every Tuesday for the
previous Friday. File layouts change from time to time, so the importer detects columns by their
Japanese/English header text instead of fixed positions:
    code   : コード / 銘柄コード / code
    name   : 銘柄名 / name                       (optional)
    date   : 日付 / 申込日 / date                 (optional; else the date given at import)
    short  : 売残 / 売り残 / 売残高 / short        (prefers the 合計/total column)
    long   : 買残 / 買い残 / 買残高 / long         (prefers the 合計/total column)
Units are shares (株). Stored in <data>/margin/margin.json as {code: {date: {long, short, name}}}.

Metrics
    信用倍率 (margin ratio) = 買残 / 売残   (> 1: more margin longs = potential selling overhang;
                                             < 1: 売り長 = potential short-covering demand)
    buy_days = 買残 / 20-day average daily volume   (days of volume needed to unwind the longs)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import re
from pathlib import Path
from typing import Any

HEADER_KEYS = {
    "code": ("コード", "銘柄コード", "code"),
    "name": ("銘柄名", "名称", "name"),
    "date": ("日付", "申込日", "基準日", "date"),
    "short": ("売残", "売り残", "売残高", "short"),
    "long": ("買残", "買い残", "買残高", "long"),
}


def _norm(s: Any) -> str:
    return re.sub(r"\s+", "", str(s or "")).replace("　", "").lower()


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("△", "-").replace("▲", "-").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _date(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.search(r"(\d{4})[/\-年.](\d{1,2})[/\-月.](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def detect_columns(header: list[Any]) -> dict[str, int]:
    """Map logical fields to column indexes. For long/short prefer a column mentioning 合計/total."""
    h = [_norm(x) for x in header]
    out: dict[str, int] = {}
    for field, keys in HEADER_KEYS.items():
        cands = [i for i, x in enumerate(h) if any(k.lower() in x for k in keys)]
        if field in ("long", "short"):
            # exclude change columns (前週比 / 増減)
            cands = [i for i in cands if not any(t in h[i] for t in ("前週比", "増減", "change"))]
            total = [i for i in cands if any(t in h[i] for t in ("合計", "total", "計"))]
            cands = total or cands
        if cands:
            out[field] = cands[0]
    return out


def parse_rows(rows: list[list[Any]], default_date: str | None = None) -> list[dict[str, Any]]:
    """Find the header row (first row with code + long + short) and parse the records below it."""
    for hi, row in enumerate(rows[:40]):
        cols = detect_columns(row)
        if {"code", "long", "short"} <= cols.keys():
            break
    else:
        raise ValueError("header row with コード / 売残 / 買残 columns not found")
    # a date may also appear in the title rows above the header ("2026年10月31日申込分")
    title_date = next((d for r in rows[:hi] for c in r if (d := _date(c))), None)
    out = []
    for row in rows[hi + 1:]:
        if not row or len(row) <= max(cols.values()):
            continue
        code = str(row[cols["code"]] or "").strip()
        code = code[:-2] if code.endswith(".0") else code
        if not re.fullmatch(r"\d{4}|\d{3}[A-Z]|\d{5}", code):
            continue
        lng, sht = _num(row[cols["long"]]), _num(row[cols["short"]])
        if lng is None or sht is None:
            continue
        date = _date(row[cols["date"]]) if "date" in cols else None
        date = date or title_date or default_date
        if not date:
            raise ValueError("no date column/title date — pass the balance date when importing")
        out.append({"code": code[:4] if len(code) == 5 and code.endswith("0") else code, "date": date,
                    "long": lng, "short": sht, "name": (str(row[cols["name"]]).strip() if "name" in cols else None)})
    if not out:
        raise ValueError("no data rows parsed")
    return out


def read_file(content: bytes, filename: str) -> list[list[Any]]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if name.endswith(".xls"):
        raise ValueError(".xls (old Excel) is not supported — save as .xlsx or CSV")
    for enc in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("cannot decode CSV (utf-8 / cp932)")
    return [r for r in csv.reader(io.StringIO(text))]


class MarginStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "margin" / "margin.json"
        self.data: dict[str, dict[str, dict[str, Any]]] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        dates = set()
        for r in records:
            self.data.setdefault(r["code"], {})[r["date"]] = {"long": r["long"], "short": r["short"], "name": r.get("name")}
            dates.add(r["date"])
        self.save()
        return {"records": len(records), "dates": sorted(dates), "codes": len({r["code"] for r in records})}

    def dates(self) -> list[str]:
        return sorted({d for v in self.data.values() for d in v})

    def series(self, code: str) -> list[dict[str, Any]]:
        s = self.data.get(code, {})
        return [{"date": d, **s[d]} for d in sorted(s)]


def ratio(long: float, short: float) -> float | None:
    return long / short if short else None


def stock_analysis(series: list[dict[str, Any]], bars: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Time series of 信用倍率 etc. + price join + percentile + forward-return relation."""
    if not series:
        return {"error": "no margin data for this code"}
    rows = []
    for i, r in enumerate(series):
        prev = series[i - 1] if i else None
        rows.append({"date": r["date"], "long": r["long"], "short": r["short"], "ratio": ratio(r["long"], r["short"]),
                     "long_chg": r["long"] - prev["long"] if prev else None,
                     "short_chg": r["short"] - prev["short"] if prev else None})
    ratios = sorted(x["ratio"] for x in rows if x["ratio"] is not None)
    last = rows[-1]
    pct = (sum(1 for v in ratios if v <= last["ratio"]) / len(ratios) * 100) if last["ratio"] is not None and ratios else None
    out: dict[str, Any] = {"rows": rows, "latest": last, "ratio_percentile": pct, "weeks": len(rows),
                           "name": series[-1].get("name")}
    if bars:
        closes = {dt.datetime.fromtimestamp(b["time"], tz=dt.timezone.utc).strftime("%Y-%m-%d"): b for b in bars}
        cd = sorted(closes)

        def close_on_or_before(d: str) -> float | None:
            prior = [x for x in cd if x <= d]
            return closes[prior[-1]]["close"] if prior else None

        for r in rows:
            r["close"] = close_on_or_before(r["date"])
        vols = [b["volume"] for b in bars[-20:] if b.get("volume")]
        adv = sum(vols) / len(vols) if vols else None
        out["adv20"] = adv
        out["buy_days"] = last["long"] / adv if adv else None
        out["sell_days"] = last["short"] / adv if adv else None
        # does a rising 信用倍率 precede weak returns? corr(Δratio_t, return_{t→t+4w})
        pairs = []
        for i in range(1, len(rows) - 4):
            a, b, c = rows[i - 1], rows[i], rows[i + 4]
            if None not in (a["ratio"], b["ratio"], b.get("close"), c.get("close")) and b["close"]:
                pairs.append((b["ratio"] - a["ratio"], c["close"] / b["close"] - 1))
        if len(pairs) >= 8:
            from .stats import pearson

            out["ratio_change_vs_fwd4w"] = {"corr": pearson([p[0] for p in pairs], [p[1] for p in pairs]), "n": len(pairs)}
    return out


def ranking(store: MarginStore, date: str | None = None, min_long: float = 0) -> dict[str, Any]:
    dates = store.dates()
    if not dates:
        return {"date": None, "rows": []}
    date = date or dates[-1]
    prev = max((d for d in dates if d < date), default=None)
    rows = []
    for code, s in store.data.items():
        if date not in s:
            continue
        cur = s[date]
        if cur["long"] < min_long:
            continue
        p = s.get(prev) if prev else None
        r = ratio(cur["long"], cur["short"])
        rp = ratio(p["long"], p["short"]) if p else None
        rows.append({"code": code, "symbol": f"TSE:{code}", "name": cur.get("name"), "long": cur["long"], "short": cur["short"],
                     "ratio": r, "ratio_prev": rp, "ratio_chg": (r - rp) if r is not None and rp is not None else None,
                     "long_chg_pct": ((cur["long"] / p["long"] - 1) * 100) if p and p["long"] else None,
                     "short_chg_pct": ((cur["short"] / p["short"] - 1) * 100) if p and p["short"] else None})
    return {"date": date, "previous": prev, "rows": rows}


def finite(v: Any) -> Any:
    return None if isinstance(v, float) and not math.isfinite(v) else v
