"""ECON source adapters (official statistics APIs). Parsers are pure functions; fetchers take an httpx.AsyncClient
so tests can inject a mock transport.

    FRED       https://fred.stlouisfed.org/graph/fredgraph.csv?id=ID      (no key)  — or the JSON API with FRED_API_KEY
    e-Stat     https://api.e-stat.go.jp/rest/3.0/app/json/...             (ESTAT_APP_ID) — tables are found by search
    ECB        https://data-api.ecb.europa.eu/service/data/FLOW/KEY       (no key, SDMX csv)
    Eurostat   https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/DATASET?filters   (JSON-stat 2.0)
    World Bank https://api.worldbank.org/v2/country/ISO3/indicator/IND  (no key)
    DBnomics   https://api.db.nomics.world/v22/series/PROVIDER/DATASET/SERIES (no key; IMF, OECD, BIS, national stats)
Every adapter returns observations [(YYYY-MM-DD, value)] ascending; a period is dated by its first day.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
from typing import Any

import httpx

Obs = list[tuple[str, float]]
UA = {"User-Agent": "Mozilla/5.0 (analyst-terminal; macro statistics)"}
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_API = "https://api.stlouisfed.org/fred"
ESTAT = "https://api.e-stat.go.jp/rest/3.0/app/json"
ECB = "https://data-api.ecb.europa.eu/service/data"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
WB = "https://api.worldbank.org/v2/country"
DBNOMICS = "https://api.db.nomics.world/v22"


class SourceError(Exception):
    pass


def fred_key() -> str | None:
    return os.environ.get("FRED_API_KEY") or None


def estat_app_id() -> str | None:
    return os.environ.get("ESTAT_APP_ID") or None


def estat_app_id_problem(v: str | None = None) -> str | None:
    """The e-Stat API needs the APPLICATION ID issued on e-Stat's My Page — not the login e-mail address."""
    v = (v if v is not None else estat_app_id() or "").strip()
    if not v:
        return None
    if "@" in v:
        return ("ESTAT_APP_ID にメールアドレス（ログイン ID）が入っている。e-Stat にログイン → マイページ →"
                "「API 機能（アプリケーション ID 発行）」で発行した ID（英数字）を設定する")
    if not re.fullmatch(r"[0-9A-Za-z]{20,64}", v):
        return "ESTAT_APP_ID の形式が違う（e-Stat のマイページで発行した英数字のアプリケーション ID を設定する）"
    return None


# ---------------------------------------------------------------------------------------------------
# dates & numbers
# ---------------------------------------------------------------------------------------------------
def period_start(s: Any) -> str | None:
    """'2024-01-15' / '2024-01' / '2024M01' / '2024-Q1' / '2024Q1' / '2024' → first day of the period."""
    t = str(s or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.fullmatch(r"(\d{4})-?M?(\d{1,2})", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}-01"
    m = re.fullmatch(r"(\d{4})-?Q([1-4])", t)
    if m:
        return f"{m.group(1)}-{(int(m.group(2)) - 1) * 3 + 1:02d}-01"
    m = re.fullmatch(r"(\d{4})-?S([12])", t)
    if m:
        return f"{m.group(1)}-{'01' if m.group(2) == '1' else '07'}-01"
    if re.fullmatch(r"\d{4}", t):
        return f"{t}-01-01"
    return None


def num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    t = str(v).strip().replace(",", "")
    if t in ("", ".", "-", "NA", "NaN", "nan", "…", "...", "***", "x", "X", "―", "－"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _sorted(rows: list[tuple[str, float]]) -> Obs:
    d: dict[str, float] = {}
    for k, v in rows:
        d[k] = v
    return sorted(d.items())


# ---------------------------------------------------------------------------------------------------
# FRED
# ---------------------------------------------------------------------------------------------------
def parse_fred_csv(text: str) -> Obs:
    r = csv.reader(io.StringIO(text))
    head = next(r, None)
    if not head or len(head) < 2 or "date" not in head[0].lower():
        raise SourceError(f"FRED: 想定外の応答（{(text or '')[:80]!r}）")
    out = []
    for row in r:
        if len(row) >= 2:
            d, v = period_start(row[0]), num(row[1])
            if d and v is not None:
                out.append((d, v))
    return _sorted(out)


def parse_fred_json(obj: dict[str, Any]) -> Obs:
    if "observations" not in obj:
        raise SourceError(f"FRED: {obj.get('error_message') or obj}")
    return _sorted([(o["date"], v) for o in obj["observations"] if (v := num(o.get("value"))) is not None])


async def fred(client: httpx.AsyncClient, code: str) -> Obs:
    key = fred_key()
    if key:
        r = await client.get(f"{FRED_API}/series/observations", params={"series_id": code, "api_key": key, "file_type": "json"})
        if r.status_code == 200:
            return parse_fred_json(r.json())
        if r.status_code not in (400, 404):
            r.raise_for_status()
        raise SourceError(f"FRED: {r.status_code} {r.text[:120]}")
    r = await client.get(FRED_CSV, params={"id": code})
    r.raise_for_status()
    return parse_fred_csv(r.text)


async def fred_search(client: httpx.AsyncClient, q: str, limit: int = 40) -> list[dict[str, Any]]:
    key = fred_key()
    if not key:
        raise SourceError("FRED の検索には FRED_API_KEY が必要（.env）")
    r = await client.get(f"{FRED_API}/series/search", params={"search_text": q, "api_key": key, "file_type": "json", "limit": limit,
                                                              "order_by": "popularity", "sort_order": "desc"})
    r.raise_for_status()
    return [{"code": s["id"], "title": s.get("title"), "freq": s.get("frequency_short"), "unit": s.get("units_short"),
             "sa": s.get("seasonal_adjustment_short"), "last": s.get("observation_end"), "popularity": s.get("popularity")}
            for s in r.json().get("seriess", [])]


# ---------------------------------------------------------------------------------------------------
# e-Stat (Japan) — tables are FOUND from a search recipe, then pinned (statsDataId + class codes)
# ---------------------------------------------------------------------------------------------------
TOTAL_WORDS = ("総数", "総計", "合計", "全国", "男女計", "総合", "全体", "全産業", "調査産業計", "計")


def _list(x: Any) -> list[Any]:
    return x if isinstance(x, list) else [] if x is None else [x]


def _text(x: Any) -> str:
    return str(x.get("$", "")) if isinstance(x, dict) else str(x or "")


def estat_time(code: str) -> str | None:
    """e-Stat time codes: YYYY + kind(2) + start month(2) + end month(2). 2024000101 = 2024年1月,
    2024000103 = 2024年1〜3月期, 2024000000 = 2024年, 2024100000 = 2024年度 (April)."""
    t = str(code or "")
    if not re.fullmatch(r"\d{10}", t):
        return period_start(t)
    y, kind, m1, m2 = int(t[:4]), t[4:6], int(t[6:8]), int(t[8:10])
    if m1 == 0 and m2 == 0:
        return f"{y}-04-01" if kind == "10" else f"{y}-01-01"
    if 1 <= m1 <= 12:
        return f"{y}-{m1:02d}-01"
    return None


def _result(obj: dict[str, Any], root: str) -> dict[str, Any]:
    body = obj.get(root) or {}
    res = body.get("RESULT") or {}
    st = int(res.get("STATUS", 0) or 0)
    if st not in (0, 1, 2):
        raise SourceError(f"e-Stat: {res.get('ERROR_MSG') or st}")
    return body


def estat_tables(obj: dict[str, Any]) -> list[dict[str, Any]]:
    body = _result(obj, "GET_STATS_LIST")
    out = []
    for t in _list((body.get("DATALIST_INF") or {}).get("TABLE_INF")):
        sn = t.get("STAT_NAME") or {}
        out.append({"id": t.get("@id"), "stat_name": _text(sn), "stat_code": sn.get("@code") if isinstance(sn, dict) else None,
                    "title": _text(t.get("TITLE")), "statistics_name": _text(t.get("STATISTICS_NAME")),
                    "cycle": _text(t.get("CYCLE")), "updated": _text(t.get("UPDATED_DATE")),
                    "survey": _text(t.get("SURVEY_DATE"))})
    return out


def estat_classes(obj: dict[str, Any], root: str = "GET_META_INFO") -> list[dict[str, Any]]:
    body = _result(obj, root)
    inf = body.get("METADATA_INF") or body.get("STATISTICAL_DATA") or {}
    out = []
    for c in _list((inf.get("CLASS_INF") or {}).get("CLASS_OBJ")):
        out.append({"id": c.get("@id"), "name": c.get("@name"),
                    "classes": [{"code": k.get("@code"), "name": k.get("@name", ""), "level": k.get("@level"), "unit": k.get("@unit")}
                                for k in _list(c.get("CLASS"))]})
    return out


def estat_choose(classes: list[dict[str, Any]], select: list[str], title: str = "") -> dict[str, Any]:
    """Pick one code per class (time excluded): the class item whose name contains the most select words, else the
    total ("総数・全国・計" …), else the first. Returns the codes and which select words were matched."""
    codes, names, matched = {}, {}, {w for w in select if w and w in title}
    for c in classes:
        if c["id"] == "time" or not c["classes"]:
            continue
        best, best_key = None, None
        for k in c["classes"]:
            hits = [w for w in select if w and w in k["name"]]
            if hits:
                key = (len(hits), sum(len(w) for w in hits), -len(k["name"]))
                if best_key is None or key > best_key:
                    best, best_key = k, key
        if best is None:
            best = next((k for k in c["classes"] if k["name"].strip() in TOTAL_WORDS), None) \
                or next((k for k in c["classes"] if any(w in k["name"] for w in TOTAL_WORDS[:7])), None) or c["classes"][0]
        else:
            matched |= {w for w in select if w and w in best["name"]}
        codes[c["id"]], names[c["id"]] = best["code"], best["name"]
    return {"codes": codes, "names": names, "matched": sorted(matched)}


def estat_values(obj: dict[str, Any], codes: dict[str, str]) -> Obs:
    body = _result(obj, "GET_STATS_DATA")
    vals = _list(((body.get("STATISTICAL_DATA") or {}).get("DATA_INF") or {}).get("VALUE"))
    out = []
    for v in vals:
        if any(v.get(f"@{k}") not in (None, c) for k, c in codes.items()):
            continue
        d, x = estat_time(v.get("@time", "")), num(v.get("$"))
        if d and x is not None:
            out.append((d, x))
    return _sorted(out)


def _cd(cid: str) -> str:
    return "cd" + cid[:1].upper() + cid[1:]


async def estat_resolve(client: httpx.AsyncClient, spec: dict[str, Any], app_id: str, top: int = 6) -> dict[str, Any]:
    params = {"appId": app_id, "searchWord": spec["search"], "limit": 100, "lang": "J"}
    if spec.get("stats_code"):
        params["statsCode"] = spec["stats_code"]
    tables = estat_tables((await client.get(f"{ESTAT}/getStatsList", params=params)).json())
    if not tables and spec.get("stats_code"):
        params.pop("statsCode")
        tables = estat_tables((await client.get(f"{ESTAT}/getStatsList", params=params)).json())
    if spec.get("cycle"):
        tables = [t for t in tables if not t["cycle"] or spec["cycle"] in t["cycle"]] or tables
    stat, sel = spec.get("stat") or "", spec.get("select") or []

    def score(t: dict[str, Any]) -> tuple[int, str]:
        s = 3 * (bool(stat) and (stat in t["stat_name"] or stat in t["statistics_name"] or stat in t["title"]))
        return s + sum(w in t["title"] for w in sel), t["updated"]

    tables.sort(key=score, reverse=True)
    tried = []
    for t in tables[:top]:
        meta = estat_classes((await client.get(f"{ESTAT}/getMetaInfo", params={"appId": app_id, "statsDataId": t["id"],
                                                                                  "lang": "J"})).json())
        ch = estat_choose(meta, sel, t["title"])
        tried.append({"id": t["id"], "title": t["title"], "matched": ch["matched"]})
        if set(ch["matched"]) >= set(sel):
            return {"statsDataId": t["id"], "title": t["title"], "stat_name": t["stat_name"], "cycle": t["cycle"],
                    "updated": t["updated"], "codes": ch["codes"], "names": ch["names"],
                    "resolved_at": dt.datetime.now().isoformat(timespec="seconds")}
    raise SourceError(f"e-Stat: 「{spec['search']}」で条件に合う表が見つからない（候補 {len(tables)} 件、確認 {len(tried)} 件）")


async def estat_fetch(client: httpx.AsyncClient, resolved: dict[str, Any], app_id: str) -> Obs:
    params = {"appId": app_id, "statsDataId": resolved["statsDataId"], "lang": "J", "metaGetFlg": "N", "cntGetFlg": "N"}
    params.update({_cd(k): v for k, v in (resolved.get("codes") or {}).items()})
    out: Obs = []
    for _ in range(10):        # paging (NEXT_KEY) — filtered series are small
        obj = (await client.get(f"{ESTAT}/getStatsData", params=params)).json()
        out += estat_values(obj, resolved.get("codes") or {})
        nxt = (((obj.get("GET_STATS_DATA") or {}).get("STATISTICAL_DATA") or {}).get("RESULT_INF") or {}).get("NEXT_KEY")
        if not nxt:
            break
        params["startPosition"] = nxt
    return _sorted(out)


async def estat_search(client: httpx.AsyncClient, q: str, stats_code: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    app_id = estat_app_id()
    if not app_id:
        raise SourceError("e-Stat には ESTAT_APP_ID が必要（.env。e-Stat で無料登録）")
    params = {"appId": app_id, "searchWord": q, "limit": limit, "lang": "J"}
    if stats_code:
        params["statsCode"] = stats_code
    return estat_tables((await client.get(f"{ESTAT}/getStatsList", params=params)).json())


# ---------------------------------------------------------------------------------------------------
# ECB (SDMX csv), Eurostat (JSON-stat 2.0), World Bank, DBnomics
# ---------------------------------------------------------------------------------------------------
def parse_ecb_csv(text: str) -> Obs:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "TIME_PERIOD" not in rows[0] or "OBS_VALUE" not in rows[0]:
        raise SourceError(f"ECB: 想定外の応答（{(text or '')[:80]!r}）")
    return _sorted([(d, v) for r in rows if (d := period_start(r["TIME_PERIOD"])) and (v := num(r["OBS_VALUE"])) is not None])


async def ecb(client: httpx.AsyncClient, code: str) -> Obs:
    flow, key = code.split("/", 1)
    r = await client.get(f"{ECB}/{flow}/{key}", params={"format": "csvdata"})
    if r.status_code == 404:
        raise SourceError(f"ECB: 系列がない（{code}）")
    r.raise_for_status()
    return parse_ecb_csv(r.text)


def parse_jsonstat(obj: dict[str, Any]) -> Obs:
    if "dimension" not in obj or "value" not in obj:
        raise SourceError(f"Eurostat: {obj.get('error') or str(obj)[:120]}")
    ids, sizes = obj["id"], obj["size"]
    tdim = (obj.get("role") or {}).get("time", ["time"])[0]
    multi = [d for d, n in zip(ids, sizes) if n > 1 and d != tdim]
    if multi:
        raise SourceError(f"Eurostat: {', '.join(multi)} が複数 — フィルタで 1 つに絞る")
    k = ids.index(tdim)
    stride = 1
    for n in sizes[k + 1:]:
        stride *= n
    idx = obj["dimension"][tdim]["category"]["index"]
    idx = idx if isinstance(idx, dict) else {lab: i for i, lab in enumerate(idx)}
    vals = obj["value"]
    get = (lambda i: vals.get(str(i))) if isinstance(vals, dict) else (lambda i: vals[i] if i < len(vals) else None)
    return _sorted([(d, v) for lab, pos in idx.items() if (d := period_start(lab)) and (v := num(get(pos * stride))) is not None])


async def eurostat(client: httpx.AsyncClient, code: str) -> Obs:
    dataset, _, q = code.partition("?")
    params = [tuple(p.split("=", 1)) for p in q.split("&") if "=" in p] + [("format", "JSON"), ("lang", "EN")]
    r = await client.get(f"{EUROSTAT}/{dataset}", params=params)
    if r.status_code in (400, 404):
        raise SourceError(f"Eurostat: {r.status_code} {r.text[:160]}")
    r.raise_for_status()
    return parse_jsonstat(r.json())


def parse_wb(obj: Any) -> Obs:
    if not isinstance(obj, list) or len(obj) < 2:
        raise SourceError(f"World Bank: {str(obj)[:160]}")
    return _sorted([(d, v) for o in obj[1] or [] if (d := period_start(o.get("date"))) and (v := num(o.get("value"))) is not None])


async def worldbank(client: httpx.AsyncClient, code: str) -> Obs:
    iso, ind = code.split("/", 1)
    r = await client.get(f"{WB}/{iso}/indicator/{ind}", params={"format": "json", "per_page": 200})
    r.raise_for_status()
    return parse_wb(r.json())


def parse_dbnomics(obj: dict[str, Any]) -> Obs:
    docs = ((obj.get("series") or {}).get("docs")) or []
    if not docs:
        raise SourceError(f"DBnomics: {obj.get('message') or 'no series'}")
    d0 = docs[0]
    periods = d0.get("period_start_day") or d0.get("period") or []
    return _sorted([(d, v) for p, x in zip(periods, d0.get("value") or []) if (d := period_start(p)) and (v := num(x)) is not None])


async def dbnomics(client: httpx.AsyncClient, code: str) -> Obs:
    r = await client.get(f"{DBNOMICS}/series/{code}", params={"observations": 1, "format": "json"})
    if r.status_code == 404:
        raise SourceError(f"DBnomics: 系列がない（{code}）")
    r.raise_for_status()
    return parse_dbnomics(r.json())


def source_url(entry: dict[str, Any]) -> str | None:
    """Where a person can look at the series (shown in the UI)."""
    s, c = entry["source"], entry["code"]
    if s == "fred":
        return f"https://fred.stlouisfed.org/series/{c}"
    if s == "estat":
        sid = (entry.get("resolved") or {}).get("statsDataId")
        return f"https://www.e-stat.go.jp/dbview?sid={sid}" if sid else "https://www.e-stat.go.jp/"
    if s == "ecb":
        return f"https://data.ecb.europa.eu/data/datasets/{c.split('/')[0]}/{c.replace('/', '.', 1)}"
    if s == "eurostat":
        return f"https://ec.europa.eu/eurostat/databrowser/view/{c.split('?')[0]}/default/table"
    if s == "wb":
        iso, ind = c.split("/", 1)
        return f"https://data.worldbank.org/indicator/{ind}?locations={iso}"
    if s == "dbnomics":
        return f"https://db.nomics.world/{c}"
    return None
