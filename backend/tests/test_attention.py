import json

import httpx

from app import attention as A


def test_lexicon_and_aggregate():
    assert A.lexicon_score("Strong beat, upgrade, going to the moon") > 0
    assert A.lexicon_score("下方修正で暴落、売り") < 0
    assert A.lexicon_score("nothing here") is None
    agg = A.aggregate_sentiment([{"label": "Bullish"}, {"label": "Bearish"}, {"text": "buy buy breakout"}])
    assert agg["with_signal"] == 3 and abs(agg["bullish_share"] - 200 / 3) < 1e-6


def test_spike():
    s = A.spike([10, 11, 9, 10, 12, 10, 11, 9, 10, 11, 10, 12, 40])
    assert s["spike"] and s["z"] > 5


async def test_google_trends_client_mocked():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if "/explore" in str(req.url):
            body = {"widgets": [{"id": "TIMESERIES", "token": "T1", "request": {"x": 1}},
                                {"id": "RELATED_QUERIES", "token": "R1",
                                 "request": {"restriction": {"complexKeywordsRestriction": {"keyword": [{"value": "nvidia"}]}}}}]}
        elif "multiline" in str(req.url):
            body = {"default": {"timelineData": [{"time": str(1700000000 + 604800 * i), "value": [10 + i], "isPartial": i == 19} for i in range(20)]}}
        else:
            body = {"default": {"rankedList": [{"rankedKeyword": [{"query": "nvidia stock", "value": 100}]},
                                               {"rankedKeyword": [{"query": "nvidia blackwell", "formattedValue": "Breakout"}]}]}}
        return httpx.Response(200, text=")]}',\n" + json.dumps(body))

    gt = A.GoogleTrends(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = await gt.interest(["nvidia"], "JP")
    assert len(res["series"]["nvidia"]) == 20 and res["series"]["nvidia"][-1]["partial"]
    assert res["related"]["nvidia"]["rising"][0]["query"] == "nvidia blackwell"
    assert any("token=T1" in c for c in calls)


async def test_x_and_stocktwits_mocked():
    def xh(req):
        assert req.headers["Authorization"] == "Bearer tok"
        if "counts" in str(req.url):
            return httpx.Response(200, json={"data": [{"start": f"2026-10-{d:02d}T00:00:00Z", "tweet_count": c} for d, c in
                                                      zip(range(25, 32), [10, 12, 9, 11, 10, 12, 60])]})
        return httpx.Response(200, json={"data": [{"text": "huge beat, buy", "public_metrics": {"like_count": 50}},
                                                  {"text": "sell, crash incoming", "public_metrics": {"like_count": 1}}]})
    x = A.XClient("tok", http=httpx.AsyncClient(transport=httpx.MockTransport(xh)))
    r = await x.analyze("$NVDA")
    assert r["spike"]["spike"] and r["sentiment"]["bullish_share"] > 50
    assert (await _no_token()).startswith("X_BEARER_TOKEN")

    def sh(req):
        return httpx.Response(200, json={"symbol": {"watchlist_count": 1000}, "messages": [
            {"body": "to the moon", "created_at": "2026-11-01T00:00:00Z", "entities": {"sentiment": {"basic": "Bullish"}}},
            {"body": "meh", "created_at": "2026-11-01T01:00:00Z", "entities": {"sentiment": None}}]})
    st = A.StockTwits(http=httpx.AsyncClient(transport=httpx.MockTransport(sh)))
    s = await st.symbol("NVDA")
    assert s["sentiment"]["bullish_share"] == 100 and s["by_day"][0]["posts"] == 2


async def _no_token():
    from app.providers.base import ProviderError
    try:
        await A.XClient("").analyze("x")
    except ProviderError as e:
        return str(e)
    return ""


def test_attention_vs_price_detects_lead():
    import random
    rng = random.Random(1)
    att, closes, price, a = [], {}, 100.0, 50.0
    shocks = [rng.gauss(0, 5) for _ in range(80)]
    for i in range(80):
        d = f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}"
        a += shocks[i]
        att.append({"date": d, "value": a})
        if i >= 1:
            price *= 1 + shocks[i - 1] * 0.004 + rng.gauss(0, 0.002)
        closes[d] = price
    res = A.attention_vs_price(att, closes, 3)
    assert res["best_lead"]["lag"] == 1 and res["best_lead"]["corr"] > 0.5
