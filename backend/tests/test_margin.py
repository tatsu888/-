import io

import openpyxl
from fastapi.testclient import TestClient

from app import margin as M

JPX_LIKE = [
    ["銘柄別信用取引週末残高", None, None, None, None, None, None],
    ["2026年10月30日申込分", None, None, None, None, None, None],
    ["コード", "銘柄名", "売残高 一般", "売残高 制度", "売残高 合計", "買残高 合計", "買残高 前週比"],
    ["72030", "トヨタ自動車", "100", "1,200,000", "1,200,100", "3,600,300", "△50,000"],
    ["6758", "ソニーグループ", "0", "500,000", "500,000", "250,000", "10,000"],
    ["", "合計", "", "", "9,999", "9,999", ""],
]


def test_detect_and_parse_jpx_like_layout():
    recs = M.parse_rows(JPX_LIKE)
    assert recs[0] == {"code": "7203", "date": "2026-10-30", "long": 3600300.0, "short": 1200100.0, "name": "トヨタ自動車"}
    assert recs[1]["code"] == "6758" and len(recs) == 2  # total row skipped


def test_generic_csv_with_date_column_and_cp932():
    text = "date,code,name,long,short\n2026-10-23,7203,Toyota,3000000,1000000\n2026-10-30,7203,Toyota,3600000,1200000\n"
    rows = M.read_file(text.encode("cp932"), "m.csv")
    recs = M.parse_rows(rows)
    assert [r["date"] for r in recs] == ["2026-10-23", "2026-10-30"]


def test_stock_analysis_and_ranking(tmp_path):
    st = M.MarginStore(tmp_path)
    for w, (lng, sht) in enumerate([(100, 50), (120, 50), (150, 40), (90, 60), (80, 100)]):
        st.add([{"code": "7203", "date": f"2026-10-{w * 7 + 1:02d}", "long": lng, "short": sht, "name": "T"},
                {"code": "6758", "date": f"2026-10-{w * 7 + 1:02d}", "long": 10, "short": 40, "name": "S"}])
    a = M.stock_analysis(st.series("7203"))
    assert a["latest"]["ratio"] == 0.8 and a["rows"][2]["ratio"] == 3.75 and a["rows"][1]["long_chg"] == 20
    assert a["ratio_percentile"] == 20.0
    rk = M.ranking(st)
    r = {x["code"]: x for x in rk["rows"]}
    assert rk["date"] == "2026-10-29" and r["6758"]["ratio"] == 0.25 and abs(r["7203"]["ratio_chg"] - (0.8 - 1.5)) < 1e-9


def test_margin_api_upload_xlsx_and_stock():
    from app.main import app

    wb = openpyxl.Workbook()
    for row in JPX_LIKE:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    with TestClient(app) as c:
        r = c.post("/api/margin/import", files={"file": ("syumatsu.xlsx", buf.getvalue())})
        assert r.status_code == 200, r.text
        assert r.json()["codes"] == 2
        bad = c.post("/api/margin/import", files={"file": ("x.csv", b"a,b\n1,2\n")})
        assert bad.status_code == 400
        assert c.get("/api/margin/dates").json()["dates"] == ["2026-10-30"]
        rk = c.get("/api/margin/ranking").json()
        assert {x["code"] for x in rk["rows"]} == {"7203", "6758"}
        s = c.get("/api/margin/stock", params={"symbol": "TSE:7203"}).json()
        assert s["latest"]["ratio"] > 2.9 and s["adv20"] and s["buy_days"] > 0
