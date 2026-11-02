"""ECON source adapters: parsers in each provider's response format, e-Stat table discovery, FRED via a mock transport."""
import asyncio
import json

import httpx
import pytest

from app.econ import sources as S


def test_period_start_and_numbers():
    assert S.period_start("2024-01-15") == "2024-01-15" and S.period_start("2024M03") == "2024-03-01"
    assert S.period_start("2024-Q3") == "2024-07-01" and S.period_start("2024") == "2024-01-01" and S.period_start("2024-13") is None
    assert S.num(".") is None and S.num("1,234.5") == 1234.5 and S.num("-") is None and S.num("***") is None


def test_fred_csv_json():
    new = "observation_date,UNRATE\n2024-01-01,3.7\n2024-02-01,.\n2024-03-01,3.8\n"
    old = "DATE,UNRATE\n2024-01-01,3.7\n"
    assert S.parse_fred_csv(new) == [("2024-01-01", 3.7), ("2024-03-01", 3.8)] and S.parse_fred_csv(old)[0][1] == 3.7
    with pytest.raises(S.SourceError):
        S.parse_fred_csv("<html>error</html>")
    js = {"observations": [{"date": "2024-01-01", "value": "4.0"}, {"date": "2024-02-01", "value": "."}]}
    assert S.parse_fred_json(js) == [("2024-01-01", 4.0)]


STATS_LIST = {"GET_STATS_LIST": {"RESULT": {"STATUS": 0}, "DATALIST_INF": {"NUMBER": 2, "TABLE_INF": [
    {"@id": "0003000001", "STAT_NAME": {"@code": "00200531", "$": "労働力調査"}, "STATISTICS_NAME": "労働力調査 基本集計 全都道府県",
     "TITLE": {"@no": "1", "$": "年齢階級別労働力人口（原数値）"}, "CYCLE": "月次", "UPDATED_DATE": "2026-10-31"},
    {"@id": "0003000002", "STAT_NAME": {"@code": "00200531", "$": "労働力調査"}, "STATISTICS_NAME": "労働力調査 基本集計 全都道府県",
     "TITLE": {"@no": "2", "$": "就業状態別人口・完全失業率（季節調整値）"}, "CYCLE": "月次", "UPDATED_DATE": "2026-10-31"}]}}}
META_1 = {"GET_META_INFO": {"RESULT": {"STATUS": 0}, "METADATA_INF": {"CLASS_INF": {"CLASS_OBJ": [
    {"@id": "tab", "@name": "表章項目", "CLASS": {"@code": "01", "@name": "人口", "@level": "1"}},
    {"@id": "cat01", "@name": "年齢階級", "CLASS": [{"@code": "000", "@name": "総数", "@level": "1"}, {"@code": "010", "@name": "15～24歳", "@level": "2"}]},
    {"@id": "time", "@name": "時間軸（月次）", "CLASS": [{"@code": "2026000901", "@name": "2026年9月"}]}]}}}}
META_2 = {"GET_META_INFO": {"RESULT": {"STATUS": 0}, "METADATA_INF": {"CLASS_INF": {"CLASS_OBJ": [
    {"@id": "tab", "@name": "表章項目", "CLASS": [{"@code": "01", "@name": "実数"}, {"@code": "02", "@name": "季節調整値"}]},
    {"@id": "cat01", "@name": "就業状態", "CLASS": [{"@code": "100", "@name": "労働力人口"}, {"@code": "110", "@name": "完全失業者"},
                                                  {"@code": "120", "@name": "完全失業率"}]},
    {"@id": "area", "@name": "地域", "CLASS": [{"@code": "00000", "@name": "全国"}, {"@code": "13000", "@name": "東京都"}]},
    {"@id": "time", "@name": "時間軸（月次）", "CLASS": [{"@code": "2026000801", "@name": "2026年8月"}]}]}}}}


def _data(values, next_key=None):
    r = {"GET_STATS_DATA": {"RESULT": {"STATUS": 0}, "STATISTICAL_DATA": {"DATA_INF": {"VALUE": values}}}}
    if next_key:
        r["GET_STATS_DATA"]["STATISTICAL_DATA"]["RESULT_INF"] = {"NEXT_KEY": next_key}
    return r


def test_estat_parsers():
    t = S.estat_tables(STATS_LIST)
    assert [x["id"] for x in t] == ["0003000001", "0003000002"] and t[1]["title"].startswith("就業状態別") and t[0]["cycle"] == "月次"
    ch = S.estat_choose(S.estat_classes(META_2), ["完全失業率", "季節調整"], "就業状態別人口・完全失業率（季節調整値）")
    assert ch["codes"] == {"tab": "02", "cat01": "120", "area": "00000"} and set(ch["matched"]) == {"完全失業率", "季節調整"}
    assert S.estat_time("2026000901") == "2026-09-01" and S.estat_time("2026000103") == "2026-01-01"
    assert S.estat_time("2025000000") == "2025-01-01" and S.estat_time("2025100000") == "2025-04-01"
    vals = [{"@tab": "02", "@cat01": "120", "@area": "00000", "@time": "2026000801", "$": "2.6"},
            {"@tab": "02", "@cat01": "120", "@area": "13000", "@time": "2026000801", "$": "2.9"},     # other area → dropped
            {"@tab": "02", "@cat01": "120", "@area": "00000", "@time": "2026000901", "$": "-"}]
    assert S.estat_values(_data(vals), {"tab": "02", "cat01": "120", "area": "00000"}) == [("2026-08-01", 2.6)]
    one = _data({"@tab": "02", "@time": "2026000901", "$": "2.5"})                                     # a single VALUE is a dict
    assert S.estat_values(one, {"tab": "02"}) == [("2026-09-01", 2.5)]
    with pytest.raises(S.SourceError):
        S.estat_tables({"GET_STATS_LIST": {"RESULT": {"STATUS": 100, "ERROR_MSG": "認証に失敗"}}})


def test_estat_resolve_and_fetch_with_paging():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.url.path, dict(req.url.params)))
        p = req.url.path
        if p.endswith("getStatsList"):
            return httpx.Response(200, json=STATS_LIST)
        if p.endswith("getMetaInfo"):
            return httpx.Response(200, json=META_1 if req.url.params["statsDataId"] == "0003000001" else META_2)
        if p.endswith("getStatsData"):
            if req.url.params.get("startPosition"):
                return httpx.Response(200, json=_data([{"@tab": "02", "@cat01": "120", "@area": "00000", "@time": "2026000901", "$": "2.5"}]))
            return httpx.Response(200, json=_data([{"@tab": "02", "@cat01": "120", "@area": "00000", "@time": "2026000801", "$": "2.6"}],
                                                  next_key="2"))
        return httpx.Response(404)

    spec = {"stat": "労働力調査", "stats_code": "00200531", "search": "完全失業率 季節調整", "select": ["完全失業率", "季節調整"], "cycle": "月次"}

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            r = await S.estat_resolve(c, spec, "APP")
            return r, await S.estat_fetch(c, r, "APP")

    r, obs = asyncio.run(go())
    assert r["statsDataId"] == "0003000002" and r["codes"] == {"tab": "02", "cat01": "120", "area": "00000"}
    assert obs == [("2026-08-01", 2.6), ("2026-09-01", 2.5)]
    data_calls = [q for p, q in calls if p.endswith("getStatsData")]
    assert data_calls[0]["cdCat01"] == "120" and data_calls[0]["cdArea"] == "00000" and data_calls[1]["startPosition"] == "2"
    assert all(q["appId"] == "APP" for _, q in calls)


def test_ecb_eurostat_wb_dbnomics():
    ecb = "KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS\nICP.M.U2.N.000000.4.ANR,M,2026-08,2.0,A\nICP.M.U2.N.000000.4.ANR,M,2026-09,2.2,A\n"
    assert S.parse_ecb_csv(ecb) == [("2026-08-01", 2.0), ("2026-09-01", 2.2)]
    js = {"version": "2.0", "class": "dataset", "id": ["freq", "unit", "geo", "time"], "size": [1, 1, 1, 3],
          "dimension": {"freq": {"category": {"index": {"M": 0}}}, "unit": {"category": {"index": {"PC_ACT": 0}}},
                        "geo": {"category": {"index": {"EA20": 0}}},
                        "time": {"category": {"index": {"2026-07": 0, "2026-08": 1, "2026-09": 2}}}},
          "value": {"0": 6.2, "2": 6.3}}
    assert S.parse_jsonstat(js) == [("2026-07-01", 6.2), ("2026-09-01", 6.3)]
    assert S.parse_jsonstat({**js, "value": [6.2, None, 6.3]}) == [("2026-07-01", 6.2), ("2026-09-01", 6.3)]
    with pytest.raises(S.SourceError):
        S.parse_jsonstat({**js, "size": [1, 1, 2, 3]})                       # an unfiltered dimension
    wb = [{"page": 1}, [{"date": "2025", "value": 0.1}, {"date": "2024", "value": None}, {"date": "2023", "value": 1.7}]]
    assert S.parse_wb(wb) == [("2023-01-01", 1.7), ("2025-01-01", 0.1)]
    db = {"series": {"docs": [{"period_start_day": ["2026-01-01", "2026-02-01"], "value": [1.5, "NA"]}]}}
    assert S.parse_dbnomics(db) == [("2026-01-01", 1.5)]


def test_fred_fetch_csv_and_api_key(monkeypatch):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if "fredgraph.csv" in str(req.url):
            return httpx.Response(200, text="observation_date,PAYEMS\n2026-08-01,159000\n2026-09-01,159150\n")
        return httpx.Response(200, json={"observations": [{"date": "2026-09-01", "value": "159150"}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await S.fred(c, "PAYEMS")

    assert asyncio.run(go())[-1] == ("2026-09-01", 159150.0) and "fredgraph.csv?id=PAYEMS" in seen[-1]
    monkeypatch.setenv("FRED_API_KEY", "K")
    assert asyncio.run(go()) == [("2026-09-01", 159150.0)] and "api_key=K" in seen[-1]
    assert json.dumps(S.source_url({"source": "fred", "code": "PAYEMS"})).count("fred.stlouisfed.org/series/PAYEMS") == 1


def test_estat_app_id_checks():
    assert "メールアドレス" in S.estat_app_id_problem("someone@example.com")
    assert S.estat_app_id_problem("abc") and S.estat_app_id_problem("0123456789abcdef0123456789abcdef01234567") is None
    assert S.estat_app_id_problem("") is None


def test_new_country_parsers():
    ons = {"months": [{"date": "2026 AUG", "value": "3.8"}, {"date": "2026 SEP", "value": "4.0"}], "quarters": [], "years": [{"date": "2025", "value": "3.3"}]}
    assert S.parse_ons(ons) == [("2026-08-01", 3.8), ("2026-09-01", 4.0)]
    assert S.parse_ons({"months": [], "quarters": [{"date": "2026 Q2", "value": "0.3"}], "years": []}) == [("2026-04-01", 0.3)]
    boe = "DATE,IUDBEDR\n02 Jan 2025,4.75\n07 Aug 2025,4.00\n"
    assert S.parse_boe_csv(boe) == [("2025-01-02", 4.75), ("2025-08-07", 4.0)]
    sc = [{"status": "SUCCESS", "object": {"vectorId": 41690973, "vectorDataPoint": [{"refPer": "2026-08-01", "value": 164.1}, {"refPer": "2026-09-01", "value": 164.5}]}}]
    assert S.parse_statcan(sc)[-1] == ("2026-09-01", 164.5)
    with pytest.raises(S.SourceError):
        S.parse_statcan([{"status": "FAILED", "object": "Invalid vector"}])
    assert S.parse_bcb([{"data": "01/08/2026", "valor": "4.95"}, {"data": "01/09/2026", "valor": ""}]) == [("2026-08-01", 4.95)]
    assert S.nbs_time("202609") == "2026-09-01" and S.nbs_time("2026B") == "2026-04-01" and S.nbs_time("2025") == "2025-01-01"


NBS_TREE = {"zb": [{"id": "A01", "name": "价格指数", "isParent": True}, {"id": "A02", "name": "工业", "isParent": True}],
            "A01": [{"id": "A0101", "name": "居民消费价格指数", "isParent": True}, {"id": "A0108", "name": "工业生产者出厂价格指数", "isParent": True}]}
NBS_DATA = {"returncode": 200, "returndata": {
    "wdnodes": [{"wdcode": "zb", "nodes": [{"code": "A010101", "cname": "居民消费价格指数(上年同月=100)", "unit": ""},
                                           {"code": "A010102", "cname": "居民消费价格指数(上年同期=100)", "unit": ""},
                                           {"code": "A010105", "cname": "居民消费价格指数(上月=100)", "unit": ""}]},
                {"wdcode": "sj", "nodes": [{"code": "202609"}, {"code": "202608"}]}],
    "datanodes": [{"code": "zb.A010101_sj.202609", "data": {"data": 100.3, "hasdata": True}, "wds": [{"wdcode": "zb", "valuecode": "A010101"}, {"wdcode": "sj", "valuecode": "202609"}]},
                  {"code": "zb.A010101_sj.202608", "data": {"data": 99.9, "hasdata": True}, "wds": [{"wdcode": "zb", "valuecode": "A010101"}, {"wdcode": "sj", "valuecode": "202608"}]},
                  {"code": "zb.A010105_sj.202609", "data": {"data": 100.1, "hasdata": True}, "wds": [{"wdcode": "zb", "valuecode": "A010105"}, {"wdcode": "sj", "valuecode": "202609"}]},
                  {"code": "zb.A010101_sj.202607", "data": {"data": 0, "hasdata": False}, "wds": [{"wdcode": "zb", "valuecode": "A010101"}, {"wdcode": "sj", "valuecode": "202607"}]}]}}


def test_nbs_resolve_by_names_and_fetch():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            form = dict(x.split("=") for x in req.content.decode().split("&"))
            seen.append(("tree", form["id"]))
            return httpx.Response(200, json=NBS_TREE.get(form["id"], []))
        seen.append(("data", req.url.params["dfwds"]))
        return httpx.Response(200, json=NBS_DATA)

    spec = {"db": "hgyd", "path": ["价格指数", "居民消费价格指数"], "leaf": ["居民消费价格指数", "上年同月"]}

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            r = await S.nbs_resolve(c, spec)
            return r, await S.nbs_fetch(c, r)

    r, obs = asyncio.run(go())
    assert r["parent"] == "A0101" and r["code"] == "A010101" and r["path"] == ["价格指数", "居民消费价格指数"]
    assert obs == [("2026-08-01", 99.9), ("2026-09-01", 100.3)]                      # hasdata false is skipped, other leaves ignored
    assert seen[0] == ("tree", "zb") and '"valuecode":"A0101"' in seen[-1][1]
    with pytest.raises(S.SourceError):
        S.parse_nbs(NBS_DATA, ["不存在的指标"])
