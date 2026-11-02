from fastapi.testclient import TestClient

from app import screener as SC


def test_local_screen_and_validation():
    rows = [{"symbol": "A", "price_earnings_ttm": 10, "return_on_equity": 15},
            {"symbol": "B", "price_earnings_ttm": 30, "return_on_equity": 20},
            {"symbol": "C", "price_earnings_ttm": 8, "return_on_equity": None}]
    f = SC.PRESET_SCREENS["value_quality"]["filters"][:2]
    assert [r["symbol"] for r in SC.run_local(rows, f, "return_on_equity", "desc", 10)] == ["A"]
    assert SC.validate([{"left": "nope", "operation": "greater", "right": 1}])
    assert SC.validate([{"left": "close", "operation": "in_range", "right": 5}])
    assert not SC.validate(f)


def test_screener_and_models_for_symbol_api():
    from app.main import app

    with TestClient(app) as c:
        f = c.get("/api/screener/fields").json()
        assert "price_earnings_ttm" in f["fields"] and "momentum" in f["presets"]
        r = c.post("/api/screener/custom", json={"filters": [{"left": "close", "operation": "greater", "right": 0}],
                                                 "sort_by": "change", "order": "desc", "limit": 5}).json()
        assert r["source"] == "sim" and len(r["rows"]) == 5
        ch = [x["change"] for x in r["rows"]]
        assert ch == sorted(ch, reverse=True)
        assert c.post("/api/screener/custom", json={"filters": [{"left": "x", "operation": "greater", "right": 0}]}).status_code == 400
        spec = c.get("/api/harness/models/sample_manufacturer", params={"example": True}).json()
        c.put("/api/harness/models/sample_for_tear", json=spec)
        m = c.get("/api/harness/for_symbol", params={"symbol": "SAMPLE:MFG"}).json()
        assert m and m[0]["summary"]["dcf_price"] > 0
