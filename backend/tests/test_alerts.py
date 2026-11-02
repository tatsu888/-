import asyncio

from app.alerts import AlertEngine, check, check_indicator
from app.models import make_bar
from app.store import Store


def bars(closes, vols=None):
    return [make_bar(86400 * i, c, c * 1.01, c * 0.99, c, (vols or [1000] * len(closes))[i]) for i, c in enumerate(closes)]


def test_price_conditions():
    assert check("cross_up", 10, 10.5, 9.9, None) and not check("cross_up", 10, 10.5, 10.1, None)
    assert check("change_pct_below", -3, 100, None, -3.5)


def test_indicator_conditions():
    up = [100 + i for i in range(60)]
    assert check_indicator("rsi_above", 70, bars(up))[0]
    assert not check_indicator("rsi_below", 30, bars(up))[0]
    # price crosses above SMA20 on the last bar
    series = [100.0] * 30 + [95.0] * 10 + [110.0]
    hit, sma = check_indicator("price_cross_sma_up", 20, bars(series))
    assert hit and sma is not None
    # golden cross: long decline then sharp rally so SMA50 crosses SMA200 exactly at the end
    s = [200 - i * 0.5 for i in range(200)] + [100 + i * 3 for i in range(60)]
    crossed_at = None
    for k in range(200, len(s)):
        if check_indicator("golden_cross", 0, bars(s[: k + 1]))[0]:
            crossed_at = k
            break
    assert crossed_at is not None
    assert not check_indicator("golden_cross", 0, bars(s[: crossed_at + 2]))[0]  # only on the crossing bar
    v = [1000] * 25 + [5000]
    assert check_indicator("volume_spike", 3, bars([100] * 26, v))[0]
    assert check_indicator("breakout_high", 20, bars([100] * 25 + [105]))[0]
    assert check_indicator("breakout_low", 20, bars([100] * 25 + [90]))[0]


def test_indicator_alerts_fire_once_per_bar(tmp_path):
    eng = AlertEngine(Store(tmp_path / "s.json"))
    a = eng.create("X:Y", "rsi_above", 70, once=False)
    assert a["kind"] == "indicator" and "X:Y" not in eng.symbols()
    data = bars([100 + i for i in range(60)])

    async def hist(s, iv, n):
        return data

    fired = asyncio.run(eng.evaluate_indicators(hist))
    assert len(fired) == 1 and fired[0]["observed"] > 70
    assert asyncio.run(eng.evaluate_indicators(hist)) == []  # same bar → not again
    data.append(make_bar(86400 * 60, 161, 162, 160, 161, 1000))
    assert len(asyncio.run(eng.evaluate_indicators(hist))) == 1  # new bar → fires again (once=False)
