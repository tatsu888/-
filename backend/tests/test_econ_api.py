"""ECON API end to end with a stubbed fetcher (no network): update → store → releases → derived → dashboard → flows,
code fixes, custom series, CSV upload, regime."""
import datetime as dt
import math
import time

from fastapi.testclient import TestClient

from app import api_econ as AE
from app.econ import analysis as A
from app.econ import sources as SRC

IDS = ["US.IP", "US.RETAIL", "US.HOUST", "US.UNRATE", "US.CPI", "US.CORECPI", "US.PPI", "US.M2", "US.NFCI", "US.HY_OAS",
       "US.FED_ASSETS", "US.TGA", "US.RRP", "JP.UNEMP", "JP.BOJ_ASSETS", "JP.USDJPY"]


def fake_factory(months_extra: int = 0, seen: dict | None = None):
    def series(e):
        f = e["freq"]
        if f == "M":
            n = 200 + months_extra
            return [(A.add_months("2010-01", i) + "-01", 100 + i * 0.3 + 3 * math.sin(i / 5)) for i in range(n)]
        if f == "W":
            start = dt.date(2015, 1, 2)
            n = 560 + months_extra * 4
            return [((start + dt.timedelta(weeks=i)).isoformat(), 7_000_000 + 5_000 * i + 20_000 * math.sin(i / 7)) for i in range(n)]
        start = dt.date(2016, 1, 4)
        n = 2700 + months_extra * 21
        return [((start + dt.timedelta(days=i)).isoformat(), 2.0 + 0.5 * math.sin(i / 50)) for i in range(n)]

    async def fake(client, e, rec):
        if seen is not None:
            seen[e["id"]] = e
        if e["id"] == "JP.UNEMP" and not e.get("resolved"):
            raise SRC.SourceError("ESTAT_APP_ID が未設定")
        obs = series(e)
        if e["id"] == "JP.USDJPY":
            obs = [(d, 150.0) for d, _ in obs]
        return obs, ({"resolved": e["resolved"]} if e.get("resolved") else {})
    return fake


def run_update(c, ids, force=True):
    r = c.post("/api/econ/update", json={"ids": ids, "force": force}).json()
    assert r["started"]
    for _ in range(200):
        st = c.get("/api/econ/status").json()
        if not st["job"]["running"]:
            return st
        time.sleep(0.05)
    raise AssertionError("update did not finish")


def test_update_store_releases_dashboard_flows(monkeypatch):
    from app.main import app

    monkeypatch.setattr(AE, "fetch_entry", fake_factory())
    with TestClient(app) as c:
        st = run_update(c, IDS)
        assert st["job"]["last_summary"]["ok"] == len(IDS) - 1 and st["job"]["last_summary"]["errors"] == 1
        assert any(x["id"] == "JP.UNEMP" and "ESTAT_APP_ID" in x["error"] for x in st["errors"])
        assert st["keys"] == {"FRED_API_KEY": False, "ESTAT_APP_ID": False}
        rows = {r["id"]: r for r in c.get("/api/econ/catalog", params={"country": "US"}).json()["rows"]}
        assert rows["US.IP"]["status"] == "ok" and rows["US.IP"]["z"] is not None and rows["US.GDP"]["status"] == "未取得"
        assert rows["US.NET_LIQ"]["status"] == "ok"                                   # derived from FED_ASSETS / TGA / RRP
        s = c.get("/api/econ/series/US.NET_LIQ").json()
        assert s["obs"] and s["entry"]["source"] == "derived" and s["flows"]["n"] > 0
        assert c.get("/api/econ/releases").json()["rows"] == []                      # the first load is not a release
        # the next month arrives → releases (with a mechanical surprise) for the monthly / weekly series
        monkeypatch.setattr(AE, "fetch_entry", fake_factory(1))
        run_update(c, IDS)
        rel = c.get("/api/econ/releases").json()["rows"]
        ids = {r["id"] for r in rel}
        assert {"US.UNRATE", "US.CPI", "US.FED_ASSETS"} <= ids and not ids & {"US.HY_OAS", "US.RRP"}   # daily series: no releases
        cpi = next(r for r in rel if r["id"] == "US.CPI")
        assert cpi["key"] and cpi["ref"] == A.add_months("2010-01", 200) + "-01" and cpi["surprise"] is not None
        d = c.get("/api/econ/dashboard").json()
        us = d["countries"]["US"]
        assert set(us["composites"]) == {"growth", "inflation", "liquidity"} and us["quadrant"]["available"]
        assert d["heatmap"]["US"]["物価"]["n"] == 3
        f = c.get("/api/econ/flows").json()["groups"]
        cb = f["中銀の流動性"]
        names = {r["id"] for r in cb["rows"]}
        assert {"US.FED_ASSETS", "US.TGA", "US.RRP", "JP.BOJ_ASSETS", "US.NET_LIQ"} <= names
        assert set(cb["total"]["members"]) == {"US.FED_ASSETS", "US.TGA", "US.RRP", "JP.BOJ_ASSETS"}     # NET_LIQ not double counted
        boj = next(r for r in cb["rows"] if r["id"] == "JP.BOJ_ASSETS")
        assert boj["usd_sums"] and boj["in_total"]                                     # 億円 → ドル（USDJPY 150）
        mx = c.get("/api/econ/matrix").json()
        us = next(r for r in mx["rows"] if r["country"] == "US")
        assert [col["key"] for col in mx["columns"]][:4] == ["GDP", "CPI", "CORE", "UNEMP"]
        assert us["cells"]["CPI"]["id"] == "US.CPI" and us["cells"]["CPI"]["pct"] and us["cells"]["CPI"]["value"] is not None
        assert us["cells"]["UNEMP"]["good"] == -1 and "GDP" not in us["cells"]                # not fetched → empty cell


def test_fixes_custom_upload_regime_and_estat_pin(monkeypatch, tmp_path):
    from app.main import app

    seen = {}
    monkeypatch.setattr(AE, "fetch_entry", fake_factory(seen=seen))
    with TestClient(app) as c:
        # fix a code, pin an e-Stat table, switch a series off
        assert c.put("/api/econ/override/US.IP", json={"code": "IPB50001N"}).json()["ok"]
        assert next(r for r in c.get("/api/econ/catalog", params={"q": "US.IP"}).json()["rows"] if r["id"] == "US.IP")["code"] == "IPB50001N"
        pin = {"statsDataId": "0003000002", "codes": {"tab": "02", "cat01": "120", "area": "00000"}}
        c.put("/api/econ/override/JP.UNEMP", json={"resolved": pin})
        run_update(c, ["JP.UNEMP"])
        assert seen["JP.UNEMP"]["resolved"]["statsDataId"] == "0003000002" and seen["JP.UNEMP"]["resolved"]["pinned"]
        assert c.get("/api/econ/series/JP.UNEMP").json()["row"]["status"] == "ok"
        c.put("/api/econ/override/US.HOUST", json={"disabled": True})
        assert all(r["id"] != "US.HOUST" for r in c.get("/api/econ/catalog").json()["rows"])
        c.put("/api/econ/override/US.HOUST", json={"disabled": False, "clear": True})
        assert any(r["id"] == "US.HOUST" for r in c.get("/api/econ/catalog").json()["rows"])
        assert c.post("/api/econ/custom", json={"entry": {"id": "bad id!", "source": "fred"}}).status_code == 400
        ok = c.post("/api/econ/custom", json={"entry": {"id": "US.MY_SERIES", "name": "自分の系列", "source": "fred", "code": "PCOPPUSDM",
                                                        "freq": "M", "tf": "yoy", "axis": "growth", "country": "US"}}).json()
        assert ok["ok"] and any(r["id"] == "US.MY_SERIES" and r["custom"] for r in c.get("/api/econ/catalog").json()["rows"])
        c.delete("/api/econ/custom/US.MY_SERIES")
        # upload: MOF-style weekly CSV (Shift_JIS, date ranges) → a flow series
        csv_text = "対外及び対内証券売買契約等の状況（週次）\n期間,対内 株式 ネット,対内 中長期債 ネット\n"
        for i in range(20):
            a = dt.date(2026, 1, 4) + dt.timedelta(weeks=i)
            b = a + dt.timedelta(days=6)
            csv_text += f"{a.year}年{a.month}月{a.day}日～{b.month}月{b.day}日,{1000 + i * 10},{-500 + i}\n"
        up = c.post("/api/econ/upload", files={"file": ("week.csv", csv_text.encode("cp932"))}).json()
        assert up["date_col"] == 0 and [x["name"] for x in up["columns"]] == ["対内 株式 ネット", "対内 中長期債 ネット"]
        ap = c.post("/api/econ/upload/apply", json={"token": up["token"], "columns": [
            {"index": 1, "entry": {"id": "JP.MOF_IN_EQ_W", "name": "対内株式（週次、財務省）", "country": "JP", "category": "貿易・対外",
                                   "axis": "liquidity", "freq": "W", "tf": "lvl", "unit": "億円",
                                   "flow": {"kind": "flow", "group": "国際資本フロー", "ccy": "JPY", "mult": 1e8, "sign": 1}}}]}).json()
        assert ap["series"][0]["n"] == 20 and ap["series"][0]["last"][0] == (dt.date(2026, 1, 4) + dt.timedelta(weeks=19, days=6)).isoformat()
        g = c.get("/api/econ/flows").json()["groups"]["国際資本フロー"]
        row = next(r for r in g["rows"] if r["id"] == "JP.MOF_IN_EQ_W")
        assert row["kind"] == "flow" and row["sums"]["4 週"] == sum(1000 + i * 10 for i in range(16, 20))
        # regime against an asset (SIM price → flagged DEMO)
        run_update(c, ["US.CPI"])
        r = c.get("/api/econ/regime", params={"id": "US.CPI", "asset": "TVC:TOPIX"}).json()
        assert r["demo"] is True and "states" in r and r["lag_m"] == 1
        assert c.get("/api/econ/regime", params={"id": "US.GDP"}).status_code == 400   # no data yet


def test_upload_date_parsing():
    assert AE.parse_date_cell("2026年1月4日～1月10日") == "2026-01-10"
    assert AE.parse_date_cell("2025年12月28日～1月3日") == "2026-01-03"            # a range across the year end
    assert AE.parse_date_cell("2026/02/15") == "2026-02-15" and AE.parse_date_cell("2026-03") == "2026-03-01"
    assert AE.parse_date_cell(46000) == (dt.date(1899, 12, 30) + dt.timedelta(days=46000)).isoformat()
    assert AE.parse_date_cell("合計") is None


def test_estat_login_email_is_reported_clearly(monkeypatch):
    """A login e-mail in ESTAT_APP_ID gives a clear message instead of an e-Stat authentication error."""
    import asyncio
    from app.main import app

    monkeypatch.setenv("ESTAT_APP_ID", "someone@example.com")
    with TestClient(app) as c:
        st = c.get("/api/econ/status").json()
        assert st["keys"]["ESTAT_APP_ID"] is False and "メールアドレス" in st["key_problems"]["ESTAT_APP_ID"]
    e = next(x for x in AE.entries() if x["id"] == "JP.CPI")
    try:
        asyncio.run(AE.fetch_entry(None, e, None))
        raise AssertionError("should fail")
    except SRC.SourceError as ex:
        assert "マイページ" in str(ex)


def test_nbs_index_is_converted_to_percent():
    """China's 「上年同月 = 100」 indices are stored as year-on-year % (value − 100)."""
    import asyncio
    import httpx
    from tests.test_econ_sources import NBS_DATA, NBS_TREE

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            form = dict(x.split("=") for x in req.content.decode().split("&"))
            return httpx.Response(200, json=NBS_TREE.get(form["id"], []))
        return httpx.Response(200, json=NBS_DATA)

    e = next(x for x in AE.entries() if x["id"] == "CN.NBS_CPI")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await AE.fetch_entry(c, e, None)

    obs, meta = asyncio.run(go())
    assert [round(v, 6) for _, v in obs] == [-0.1, 0.3] and meta["resolved"]["code"] == "A010101"
