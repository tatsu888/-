"""End-to-end test of TradingViewProvider against a local fake websocket server (tests/fake_tv.py),
plus the HTTP endpoint parsers (search / scanner / news / calendar / Yahoo) with mocked transports."""
import asyncio
import json

import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.tradingview import TradingViewProvider
from app.providers.tv_web import TVWeb
from app.providers.yahoo import YahooProvider
from tests.fake_tv import BAD, FakeTV


async def wait_for(cond, timeout=5.0):
    t = 0.0
    while not cond():
        await asyncio.sleep(0.02)
        t += 0.02
        if t > timeout:
            raise AssertionError("condition not met in time")


async def test_tradingview_provider_end_to_end():
    fake = FakeTV()
    await fake.start()
    prov = TradingViewProvider("tok123", ws_url=fake.url)
    quotes, bars = [], []
    prov.on_quote = lambda q: quotes.append(q)
    prov.on_bar = lambda s, iv, b: bars.append((s, iv, b))
    await prov.start()
    try:
        await wait_for(lambda: prov.status == "connected")
        assert fake.methods("set_auth_token") == [["tok123"]]
        fields = fake.methods("quote_set_fields")[0]
        assert "lp" in fields and "update_mode" in fields

        # streaming quotes, incl. partial-update merge
        await prov.set_quote_symbols({"NASDAQ:AAPL"})
        await wait_for(lambda: any(q["symbol"] == "NASDAQ:AAPL" and q["last"] == 111.5 for q in quotes))
        q = [q for q in quotes if q["symbol"] == "NASDAQ:AAPL"][-1]
        assert q["name"] == "desc NASDAQ:AAPL" and q["delay_sec"] == 900 and q["source"] == "tradingview"
        assert fake.heartbeat_echoes >= 1

        # snapshot for a symbol not being streamed
        snap = await prov.get_quotes(["NYSE:IBM"])
        assert snap[0]["last"] is not None
        bad = await prov.get_quotes([BAD])
        assert bad[0]["error"]

        # history over a short-lived connection
        hist = await prov.get_history("NASDAQ:AAPL", "1D", 30)
        assert len(hist) == 30 and hist[0]["time"] < hist[-1]["time"] and hist[-1]["close"] == 39.5
        with pytest.raises(ProviderError):
            await prov.get_history(BAD, "1D", 10)

        # live bars via chart session + du
        await prov.set_bar_subscriptions({("NASDAQ:AAPL", "5")})
        await wait_for(lambda: any(s == "NASDAQ:AAPL" and iv == "5" for s, iv, _ in bars))
        cs = fake.methods("create_series")[-1]
        assert cs[4] == "5"  # TradingView resolution string
        await prov.set_bar_subscriptions(set())
        await wait_for(lambda: bool(fake.methods("chart_delete_session")))

        # reconnect: server drops the socket -> provider reconnects and re-subscribes
        adds_before = len(fake.methods("quote_add_symbols"))
        conns_before = fake.connections
        await fake.drop_all()
        await wait_for(lambda: fake.connections > conns_before, timeout=6)
        await wait_for(lambda: len(fake.methods("quote_add_symbols")) > adds_before, timeout=6)
        assert "NASDAQ:AAPL" in fake.methods("quote_add_symbols")[-1]
    finally:
        await prov.stop()
        await fake.stop()


# ---------------------------------------------------------------- HTTP parsers (mocked)
def mock_client(routes):
    def handler(req: httpx.Request) -> httpx.Response:
        for key, resp in routes.items():
            if key in str(req.url):
                status, body = resp if isinstance(resp, tuple) else (200, resp)
                return httpx.Response(status, text=body if isinstance(body, str) else json.dumps(body))
        return httpx.Response(404, text="no route")
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_search_and_screener_parsing():
    http = mock_client({
        "symbol_search": {"symbols": [{"symbol": "<em>AAPL</em>", "description": "Apple Inc.", "type": "stock",
                                        "exchange": "NASDAQ"}], "symbols_remaining": 0},
        "scanner.tradingview.com/america/scan": {"totalCount": 1, "data": [{"s": "NASDAQ:AAPL", "d": [
            "AAPL", "Apple", 230.0, 1.5, 3.4, 5e7, 228, 231, 227, 3.5e12, 35.1, "NASDAQ", "USD", "stock"]}]},
    })
    prov = TradingViewProvider(ws_url="ws://127.0.0.1:9/none", http=http)
    res = await prov.search("aapl")
    assert res[0]["symbol"] == "NASDAQ:AAPL" and res[0]["ticker"] == "AAPL"
    sc = await prov.screener("america", "gainers", 5)
    assert sc[0]["symbol"] == "NASDAQ:AAPL" and sc[0]["change_pct"] == 1.5 and sc[0]["market_cap"] == 3.5e12


async def test_scanner_error_body_is_surfaced():
    http = mock_client({"scan": (400, '{"error":"Unknown field \\"foo_bar\\""}')})
    web = TVWeb(http=http)
    with pytest.raises(ProviderError) as e:
        await web.scan_symbols(["NASDAQ:AAPL"], ["foo_bar"])
    assert "foo_bar" in str(e.value) and "HTTP 400" in str(e.value)


async def test_scan_symbols_fallback_columns():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body["columns"])
        if "bad_col" in body["columns"]:
            return httpx.Response(400, text="Unknown field bad_col")
        return httpx.Response(200, json={"data": [{"s": "TSE:7203", "d": [1.0 for _ in body["columns"]]}]})
    web = TVWeb(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = await web.scan_symbols(["TSE:7203"], ["close", "bad_col"], ["close"])
    assert out == {"TSE:7203": {"close": 1.0}} and len(calls) == 2


async def test_news_calendar_fundamentals_parsing():
    import datetime as dt
    http = mock_client({
        "news-headlines": {"items": [{"id": "n1", "title": "Apple beats", "provider": "reuters", "published": 1700000000,
                                      "urgency": 2, "storyPath": "/news/n1", "relatedSymbols": [{"symbol": "NASDAQ:AAPL"}]}]},
        "economic-calendar": {"status": "ok", "result": [
            {"id": "e2", "date": "2026-11-06T13:30:00.000Z", "country": "US", "title": "Nonfarm Payrolls",
             "importance": 1, "actual": None, "forecast": 150, "previous": 120},
            {"id": "e1", "date": "2026-11-05T00:30:00.000Z", "country": "JP", "title": "CPI", "importance": 0}]},
        "scanner.tradingview.com/america/scan": {"data": [{"s": "NASDAQ:AAPL", "d": ["AAPL", "Apple"] + [None] * 34}]},
    })
    web = TVWeb(http=http)
    n = await web.news("NASDAQ:AAPL")
    assert n[0]["url"] == "https://www.tradingview.com/news/n1" and n[0]["symbols"] == ["NASDAQ:AAPL"]
    now = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
    cal = await web.calendar(now, now + dt.timedelta(days=7), ["US", "JP"])
    assert [c["id"] for c in cal] == ["e1", "e2"]  # sorted by date
    f = await web.fundamentals("NASDAQ:AAPL")
    assert f["market"] == "america" and f["fields"]["description"] == "Apple"


async def test_yahoo_provider_parsing():
    chart = {"chart": {"result": [{"meta": {"regularMarketPrice": 2800.0, "chartPreviousClose": 2750.0,
                                            "currency": "JPY", "exchangeName": "JPX", "longName": "Toyota"},
                                   "timestamp": [1700000000, 1700086400],
                                   "indicators": {"quote": [{"open": [1, 2], "high": [2, 3], "low": [0.5, 1],
                                                             "close": [1.5, 2.5], "volume": [10, 20]}]}}],
                       "error": None}}
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if "/search" in str(req.url):
            return httpx.Response(200, json={"quotes": [{"symbol": "7203.T", "longname": "Toyota", "exchange": "JPX"}]})
        return httpx.Response(200, json=chart)
    y = YahooProvider(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    q = (await y.get_quotes(["TSE:7203"]))[0]
    assert q["last"] == 2800.0 and q["currency"] == "JPY" and abs(q["change_pct"] - 50 / 2750 * 100) < 1e-9
    assert "7203.T" in seen[0]
    h = await y.get_history("TSE:7203", "1D", 10)
    assert [b["close"] for b in h] == [1.5, 2.5]
    assert (await y.search("toyota"))[0]["symbol"] == "7203.T"


async def test_diagnostics_against_fake_tradingview(monkeypatch):
    from app import diagnose
    from app.providers import tv_protocol as P

    fake = FakeTV()
    await fake.start()
    monkeypatch.setattr(P, "WS_URL", fake.url)
    try:
        rep = await diagnose.run_diagnostics(check_symbols=True)
    finally:
        await fake.stop()
    st = {c["check"]: c["status"] for c in rep["checks"]}
    assert st["tradingview.websocket"] == "PASS"
    assert st["tradingview.quotes"] == "PASS"
    assert st["tradingview.history"] == "PASS"
    sym = next(c for c in rep["checks"] if c["check"] == "configured_symbols")
    assert "TradingView invalid: []" in sym["detail"]
    md = diagnose.to_markdown(rep)
    assert "| PASS | tradingview.quotes |" in md
    # HTTP endpoints are unreachable offline -> reported as FAIL with a hint, never raising
    assert all(c["status"] in ("PASS", "WARN", "FAIL") for c in rep["checks"])
