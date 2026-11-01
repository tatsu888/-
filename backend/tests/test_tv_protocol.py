from app.providers import tv_protocol as P
from app.providers.tradingview import parse_scan_row


def test_frame_roundtrip():
    msg = P.encode("quote_add_symbols", ["qs_x", "NASDAQ:AAPL"])
    assert msg.startswith("~m~")
    frames = P.split_frames(msg + P.frame("~h~12"))
    assert len(frames) == 2
    assert P.parse_payload(frames[0]) == {"m": "quote_add_symbols", "p": ["qs_x", "NASDAQ:AAPL"]}
    assert P.is_heartbeat(frames[1])
    assert P.parse_payload(frames[1]) is None


def test_map_quote_values_and_delay():
    v = P.map_quote_values({"lp": 10.5, "ch": 0.5, "chp": 5.0, "update_mode": "delayed_streaming_900",
                            "description": "Apple", "unknown": 1})
    assert v == {"last": 10.5, "change": 0.5, "change_pct": 5.0, "delay_sec": 900, "name": "Apple"}
    assert P.delay_from_update_mode("streaming") == 0
    assert P.delay_from_update_mode(None) is None


def test_series_bars():
    payload = {"sds_1": {"s": [{"i": 0, "v": [1700000000, 1, 2, 0.5, 1.5, 100]}, {"i": 1, "v": [1]}]}}
    assert P.series_bars(payload, "sds_1") == [[1700000000, 1, 2, 0.5, 1.5, 100]]
    assert P.series_bars(payload, "sds_2") == []


def test_resolve_symbol_param():
    assert P.resolve_symbol_param("TSE:7203").startswith('={"symbol":"TSE:7203"')


def test_parse_scan_row():
    from app.providers.tradingview import SCAN_COLUMNS
    d = {c: None for c in SCAN_COLUMNS}
    d.update(close=100.0, change=2.0, change_abs=1.96, description="Foo")
    q = parse_scan_row({"s": "NYSE:FOO", "d": [d[c] for c in SCAN_COLUMNS]}, "tradingview")
    assert q["symbol"] == "NYSE:FOO" and q["last"] == 100.0 and q["change_pct"] == 2.0 and q["name"] == "Foo"
