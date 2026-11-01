from app.providers.yahoo import parse_chart, resample, to_yahoo


def test_symbol_mapping():
    assert to_yahoo("NASDAQ:AAPL") == "AAPL"
    assert to_yahoo("TSE:7203") == "7203.T"
    assert to_yahoo("FX:USDJPY") == "USDJPY=X"
    assert to_yahoo("BINANCE:BTCUSDT") == "BTC-USD"
    assert to_yahoo("SP:SPX") == "^GSPC"
    assert to_yahoo("TVC:NI225") == "^N225"


def test_parse_chart_and_resample():
    data = {"chart": {"result": [{"meta": {"regularMarketPrice": 3}, "timestamp": [0, 3600, 7200, 14400],
                                  "indicators": {"quote": [{"open": [1, 2, None, 4], "high": [2, 3, 3, 5],
                                                            "low": [0.5, 1, 1, 3], "close": [2, 3, 3, 4.5],
                                                            "volume": [10, 20, 30, 40]}]}}]}}
    meta, bars = parse_chart(data)
    assert meta["regularMarketPrice"] == 3 and len(bars) == 3  # None row dropped
    r = resample(bars, "240")
    assert len(r) == 2 and r[0]["open"] == 1 and r[0]["close"] == 3 and r[0]["volume"] == 30
