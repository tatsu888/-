import math

from app import analytics as A
from app.intervals import bucket_start, normalize_interval
from app.models import make_bar


def bars_from(closes):
    return [make_bar(86400 * i, c, c * 1.01, c * 0.99, c, 1000) for i, c in enumerate(closes)]


def test_sma_ema_rsi():
    v = [float(i) for i in range(1, 21)]
    assert A.sma(v, 5)[4] == 3.0 and A.sma(v, 5)[3] is None
    assert A.ema(v, 5)[4] == 3.0
    assert A.rsi(v, 14)[-1] == 100.0
    line, sig, hist = A.macd([100 + math.sin(i / 3) for i in range(80)])
    assert line[-1] is not None and sig[-1] is not None and hist[-1] is not None


def test_intervals():
    assert normalize_interval("1h") == "60" and normalize_interval("d") == "1D"
    assert bucket_start(86400 * 7 + 100, "1W") % 86400 == 0
    assert bucket_start(125, "1") == 120


def test_correlation_identical_series():
    b = bars_from([100 * (1.01 ** i) * (1 + 0.02 * math.sin(i)) for i in range(60)])
    res = A.correlation_matrix({"A": b, "B": b})
    assert abs(res["matrix"][0][1] - 1) < 1e-9


def test_backtest_no_lookahead_buy_hold():
    closes = [100, 110, 121, 133.1]
    res = A.backtest(bars_from(closes), "buy_hold", fee_bps=0)
    assert abs(res["stats"]["total_return_pct"] - 33.1) < 1e-6
    assert abs(res["stats"]["buy_hold_return_pct"] - 33.1) < 1e-6


def test_technical_rating_uptrend():
    res = A.technical_rating(bars_from([100 + i for i in range(250)]))
    assert res["moving_averages"]["score"] == 1.0


def test_performance_windows():
    p = A.performance(bars_from([100.0] * 300 + [110.0]))
    assert abs(p["1D"] - 10) < 1e-9 and abs(p["1M"] - 10) < 1e-9
