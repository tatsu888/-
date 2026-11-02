import math
import random

from fastapi.testclient import TestClient

from app import fourier


def test_fft_matches_dft():
    x = [complex(math.sin(i) + 0.3 * i % 2) for i in range(16)]
    f = fourier._fft(x)
    for k in range(16):
        d = sum(x[t] * complex(math.cos(-2 * math.pi * k * t / 16), math.sin(-2 * math.pi * k * t / 16)) for t in range(16))
        assert abs(f[k] - d) < 1e-9


def test_periodogram_finds_known_cycles():
    vals = [100 * math.exp(0.0005 * t) * (1 + 0.05 * math.sin(2 * math.pi * t / 21) + 0.02 * math.sin(2 * math.pi * t / 63))
            for t in range(512)]
    pg = fourier.periodogram(vals)
    top = [round(p["period"]) for p in pg["peaks"][:2]]
    assert any(abs(p - 21) <= 1 for p in top) and any(abs(p - 64) <= 4 for p in top)


def test_harmonic_forecast_extrapolates_seasonality():
    # quarterly KPI with a strong Q4 seasonal peak
    vals = [100 * (1.02 ** (t / 4)) * (1.25 if t % 4 == 3 else 1.0) for t in range(24)]
    fc = fourier.harmonic_forecast(vals, 4, k=2, how="loglinear", periods=[4, 2])
    q4 = fc["forecast"][3]
    assert q4 > max(fc["forecast"][:3]) and fc["r2"] > 0.95


def test_backtest_skill_random_walk_vs_cycle():
    rng = random.Random(3)
    rw = [100.0]
    for _ in range(600):
        rw.append(rw[-1] * math.exp(rng.gauss(0, 0.01)))
    bt = fourier.backtest(rw, horizon=20, k=3)
    assert bt["origins"] > 3 and bt["mape"]["naive"] is not None
    cyc = [100 + 10 * math.sin(2 * math.pi * t / 30) + rng.gauss(0, 0.3) for t in range(600)]
    bt2 = fourier.backtest(cyc, horizon=10, k=1, how="linear")
    assert bt2["skill_vs_naive"] > 0.3 and bt2["verdict"] == "beats naive"


def test_fourier_api_and_harness_method():
    from app.harness.runner import run
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/analytics/fourier", params={"symbol": "NASDAQ:AAPL", "bars": 300, "horizon": 10})
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["series"]["forecast"]) == 10 and d["periodogram"]["peaks"] and "skill_vs_naive" in d["backtest"]
    spec = {"forecast_years": ["Q1", "Q2", "Q3", "Q4"],
            "history": {"years": [f"q{i}" for i in range(12)], "revenue": [100 * (1.25 if i % 4 == 3 else 1) for i in range(12)]},
            "lines": {"revenue": {"method": "fourier", "params": {"periods": [4, 2]}}}}
    res = run(spec, uncertainty=False)
    rev = res["projection"]["lines"]["revenue"]
    assert abs(rev[3] / rev[0] - 1.25) < 0.01  # exact seasonal shape recovered with the 4- and 2-quarter harmonics
    assert next(c for c in res["checks"] if c["id"] == "assumption_sources")["status"] == "PASS"
