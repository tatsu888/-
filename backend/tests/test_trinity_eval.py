"""ALIGN / CHECK / EVAL: alignment states and arbitration rules, the pre-order check through gates ①–④ and the book,
grading of past AUTO verdicts without overlapping windows, the price-reproducible M and 需給 backtests, the API."""
import datetime as dt
import json
import math

from fastapi.testclient import TestClient

from app import trinity_eval as E


def row(sym, f_dir, m, l, conv=1, size=1.0, **kw):
    return {"symbol": sym, "name": sym, "f": {"direction": f_dir, "score": 3.8 if f_dir == "LONG" else 2.2 if f_dir == "SHORT" else None,
                                              "source": kw.pop("src", "RULE")},
            "m": {"view": m, "reason": "テスト", "next_view": kw.pop("next_view", 0)},
            "l": {"view": l, "zone": "中間帯", "crowded": kw.pop("crowded", False), "vol_pct": kw.pop("vol", 25.0)},
            "direction": f_dir if f_dir in ("LONG", "SHORT") and conv else "NEUTRAL", "conviction": conv, "size_pct": size,
            "flags": kw.pop("flags", []), **kw}


def test_align_states_rules_grid_and_changes():
    assert E.align_row(row("A", "LONG", 1, 1, 3))["state"] == "ALIGN3"
    assert E.align_row(row("B", "SHORT", -1, 0, 2))["state"] == "ALIGN2"                 # M with the short
    assert E.align_row(row("C", "LONG", 0, 0))["state"] == "F_ONLY"
    c = E.align_row(row("D", "LONG", -1, 1, 1))
    assert c["state"] == "CONF_M" and any("ペアで持つ" in r for r in c["rules"])
    assert E.align_row(row("E", "SHORT", 0, 1, 0))["state"] == "CONF_L"
    assert E.align_row(row("F", "LONG", -1, -1, 0))["state"] == "CONF_ML"
    assert E.align_row(row("G", "N/A", 1, 1, 0))["state"] == "NO_F_ML" and E.align_row(row("H", "N/A", 1, 0, 0))["state"] == "NONE"
    moat = E.align_row(row("I", "SHORT", -1, -1, 3, flags=["裁定: 3.5句合致企業 → 個別ショートではなく"]))
    assert any("哲学側を優先" in r for r in moat["rules"])
    crowd = E.align_row(row("J", "LONG", 1, 0, 2, crowded=True, vol=45.0))
    assert any("Market Timing" in r for r in crowd["rules"]) and any("ケリー公式" in r for r in crowd["rules"])
    snap = {"generated_at": "2026-11-02T08:00:00", "quadrant": {"q": 1, "name": "1. 回復"},
            "rows": [row("A", "LONG", 1, 1, 3, 3.0), row("D", "LONG", -1, 1, 1, 1.0), row("B", "SHORT", -1, 0, 2, 1.3), row("G", "N/A", 1, 1, 0, 0)]}
    prev = {"rows": [row("A", "LONG", 1, 0, 2, 2.0), row("D", "LONG", -1, 1, 1, 1.0)]}
    a = E.align(snap, prev)
    assert a["grid"]["LONG"][0][2][0]["symbol"] == "A"                 # 需給 順風 (top row) × マクロ 順風 (right column)
    assert a["grid"]["LONG"][0][0][0]["symbol"] == "D" and a["grid"]["SHORT"][1][2][0]["symbol"] == "B"
    assert abs(a["book"]["aligned_share"] - (3.0 + 1.3) / 5.3) < 1e-9 and a["book"]["conflict_pct"] == 1.0
    assert [x["symbol"] for x in a["candidates"]] == ["G"] and a["changes"] == [{"symbol": "A", "name": "A", "from": "二位一致", "to": "三位一致"}]
    assert E.align(None)["error"]


def test_check_trade_gates_and_the_book():
    good = row("TSE:6857", "LONG", 1, 0, 2, 2.0, days_to_earnings=20)
    card = {"total": 3.9, "direction": "LONG", "moat_qualifies": False}
    r = E.check_trade({"symbol": "TSE:6857", "side": "LONG", "weight": 2.0, "sector": "Electronic Technology"}, good, card, [])
    assert r["verdict"] == "発注可" and [g["status"] for g in r["gates"][:4]] == ["PASS", "PASS", "PASS", "PASS"]
    # macro against: a single name fails ①; as a pair it is allowed with a warning (05.2)
    bad_m = row("TSE:6857", "LONG", -1, 0, 0, 0.0)
    assert E.check_trade({"symbol": "TSE:6857", "side": "LONG", "weight": 2.0}, bad_m, card, [])["blocked_at"] == "① マクロ関門"
    p = E.check_trade({"symbol": "TSE:6857", "side": "LONG", "weight": 2.0, "pair_with": "TSE:8035"}, bad_m, card, [],
                      pair={"pair_sigma_pct": 18.0, "beta_net_gross": 0.1, "pair_correlation": 0.7, "entry_blocked": False})
    assert p["verdict"] == "条件付きで可" and p["gates"][0]["status"] == "WARN" and p["book_after"]["pairs"] == 1
    # a short of a 3.5句 company, too big, small cap, no type, no catalyst
    s = E.check_trade({"symbol": "TSE:1111", "side": "SHORT", "weight": 3.5, "mcap_usd": 5e8},
                      row("TSE:1111", "SHORT", -1, 0, 2, 1.3), {"total": 2.2, "direction": "SHORT", "moat_qualifies": True}, [])
    texts = " ".join(i["text"] for g in s["gates"] for i in g["items"])
    assert s["verdict"] == "見送り" and "哲学側を優先" in texts and "小型株ショート禁止" in texts and "カタリスト" in texts and "型を宣言" in texts
    # Kelly: negative expectation fails ④; above the recommendation warns
    from app import framework as F
    k_bad = F.kelly(0.4, 0.1, 0.2, "long")
    assert E.check_trade({"symbol": "TSE:6857", "side": "LONG", "weight": 1.0}, good, card, [], kelly=k_bad)["gates"][3]["status"] == "FAIL"
    k = F.kelly(0.6, 0.3, 0.15, "long")
    w = E.check_trade({"symbol": "TSE:6857", "side": "LONG", "weight": 2.9}, good, card, [], kelly=k)
    assert w["gates"][3]["status"] == ("WARN" if 2.9 > k["recommended_pct"] else "PASS")
    # the book: the order pushes a sector net over ±5 %
    book = [{"symbol": "TSE:6758", "weight": 4.0, "sector": "Electronic Technology"}, {"symbol": "TSE:8306", "weight": -4.0, "sector": "Finance"}]
    b = E.check_trade({"symbol": "TSE:6857", "side": "LONG", "weight": 2.0, "sector": "Electronic Technology"}, good, card, book)
    assert b["gates"][3]["status"] == "FAIL" and any("セクター・ネット" in i["text"] for i in b["gates"][3]["items"])
    assert b["book_before"]["net"] == 0 and b["book_after"]["net"] == 2.0
    # an order adds to what the book holds: 3 % held + 2 % → 5 % > the 4 % absolute cap
    held = E.check_trade({"symbol": "TSE:6758", "side": "LONG", "weight": 2.0}, row("TSE:6758", "LONG", 1, 0, 2, 2.0), card, book)
    assert held["position_after"] == 6.0 and held["gates"][3]["status"] == "FAIL" and "既存 +4.00%" in held["gates"][3]["items"][0]["text"]
    close = E.check_trade({"symbol": "TSE:8306", "side": "LONG", "weight": 4.0}, None, None, book)      # buying back a short
    assert close["position_after"] == 0 and close["book_after"]["names"] == 1
    # outside the AUTO universe: open items, no verdict yet
    o = E.check_trade({"symbol": "TSE:9999", "side": "LONG", "weight": 1.0}, None, None, [])
    assert o["verdict"] == "見送り" and o["gates"][0]["status"] == "OPEN"            # ② fails without any fundamental direction


def _days(n, start=dt.date(2025, 1, 6)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def test_grade_auto_without_overlap():
    ds = _days(200)
    mkt = {d: 100.0 for d in ds}
    up = {d: 100 * math.exp(0.001 * i) for i, d in enumerate(ds)}         # +0.1 %/day vs a flat market
    dn = {d: 100 * math.exp(-0.001 * i) for i, d in enumerate(ds)}
    snaps = []
    for i in range(0, 150, 5):                                             # a snapshot every 5 sessions
        snaps.append((ds[i], {"rows": [row("TSE:1", "LONG", 1, 1, 3, 3.0), row("TSE:2", "SHORT", 0, 0, 1, 1.0),
                                       row("TSE:3", "LONG", 0, -1, 1, 1.0)]}))
    g = E.grade_auto(snaps, {"TSE:1": up, "TSE:2": dn, "TSE:3": dn}, {s: "TVC:TOPIX" for s in ("TSE:1", "TSE:2", "TSE:3")},
                     {"TVC:TOPIX": mkt}, (5, 21))
    h5, h21 = g["horizons"]["5"], g["horizons"]["21"]
    assert h5["dates_used"] == 30 and h21["dates_used"] == 6                  # snapshots 0, 25, 50 … 125: windows never overlap
    s = h21["stats"]
    assert s["c3"]["hit"] == 1.0 and abs(s["c3"]["mean_pct"] - 2.1) < 1e-6        # long the riser: +0.1 % × 21
    assert s["dir:SHORT"]["hit"] == 1.0 and s["state:CONF_L"]["mean_pct"] < 0      # the conflicted long lost
    assert s["c1"]["n"] == 12 and 0 < s["ALL"]["hit_lo"] < s["ALL"]["hit_post"] < s["ALL"]["hit_hi"] < 1
    assert h5["verdict"] is not None and "整合" in h5["verdict"]
    assert E.sample_dates(ds[:30], ds, 10) == [ds[0], ds[10], ds[20]]


def test_backtests_m_and_l():
    ds = _days(400)
    topix = {d: 100.0 for d in ds}
    rise = {d: 100 * math.exp(0.0005 * i) for i, d in enumerate(ds)}
    fall = {d: 100 * math.exp(-0.0005 * i) for i, d in enumerate(ds)}
    sectors = {"TSE:1625": rise, "TSE:1624": rise, "TSE:1617": fall, "TSE:1621": fall}   # tech, cyclical | defensive ×2
    path = [{"date": d, "q": 1} for d in ds[:300]]                                        # 1. 回復: tech / cyclical favoured
    m = E.backtest_m(path, sectors, topix, step=21, horizons=(21,))
    sp = m["horizons"]["21"]["spread"]
    assert sp["n"] > 10 and abs(sp["mean_pct"] - 2.1) < 1e-6 and sp["hit"] == 1.0
    assert m["horizons"]["21"]["by_view"]["+1"]["mean_pct"] > 0 > m["horizons"]["21"]["by_view"]["-1"]["mean_pct"]
    # 需給: the AUTO rule on bars available at each date (structure; SIM-like random volumes)
    import random
    rnd = random.Random(3)
    t0 = int(dt.datetime(2025, 1, 6, tzinfo=dt.timezone.utc).timestamp())
    bars, p = [], 100.0
    for i in range(600):
        p *= math.exp(rnd.gauss(0, 0.015))
        bars.append({"time": t0 + i * 86400, "open": p, "high": p, "low": p, "close": p, "volume": rnd.uniform(1e5, 1e6)})
    from app.quant import closes_by_date
    mk = {d: 100.0 for d in closes_by_date(bars)}
    lres = E.backtest_l({"TSE:1": bars}, {"TSE:1": "TVC:TOPIX"}, {"TVC:TOPIX": mk}, step=21, horizons=(21,))
    assert lres["observations"] > 10 and set(lres["horizons"]["21"]["by_zone"]) == {"天井寄り", "中間帯", "底寄り"}


def test_align_check_eval_api_sim(tmp_path, monkeypatch):
    from app import api_trinity
    from app.main import app

    d = tmp_path / "trinity"
    (d / "history").mkdir(parents=True)
    monkeypatch.setattr(api_trinity, "tdir", lambda: d)
    with TestClient(app) as c:
        assert c.get("/api/trinity/align").status_code == 404
        today = dt.date.today()
        snap = {"generated_at": f"{today}T08:00:00", "quadrant": {"q": 1, "name": "1. 回復"},
                "rows": [row("TSE:7203", "LONG", 1, 1, 3, 3.0, sector="Consumer Durables"), row("TSE:6758", "N/A", 1, 1, 0, 0)]}
        (d / "latest.json").write_text(json.dumps(snap), encoding="utf-8")
        for k in range(1, 40):
            day = today - dt.timedelta(days=k * 3)
            (d / "history" / f"{day}.json").write_text(json.dumps({**snap, "generated_at": f"{day}T08:00:00"}), encoding="utf-8")
        a = c.get("/api/trinity/align").json()
        assert a["states"][0]["symbols"] == ["TSE:7203"] and a["candidates"][0]["symbol"] == "TSE:6758"
        r = c.post("/api/trinity/check", json={"symbol": "TSE:7203", "side": "LONG", "weight": 2.0, "pair_with": "TSE:7267",
                                               "pw": 0.6, "xw": 0.3, "xl": 0.15}).json()
        assert r["auto_row"]["conviction"] == 3 and r["pair"] and r["kelly"]["e"] > 0 and r["gates"][3]["items"]
        o = c.post("/api/trinity/check", json={"symbol": "TSE:9984", "side": "SHORT", "weight": 1.0, "short_type": "catalyst"}).json()
        assert o["auto_row"]["mini"] and o["gates"][1]["status"] == "FAIL"           # no score sheet → no fundamental direction
        assert c.post("/api/trinity/check", json={"symbol": "7203", "side": "LONG", "weight": 1}).status_code == 400
        c.put("/api/trinity/config", json={"extra": ["TSE:7203", "TSE:6758"], "sources": []})
        ev = c.get("/api/trinity/eval", params={"horizons": "5,21"}).json()
        assert ev["auto"]["snapshots"] == 39 and ev["auto"]["horizons"]["21"]["stats"]["c3"]["n"] > 0
        assert ev["m"]["horizons"]["21"]["spread"]["n"] > 10 and ev["l"]["observations"] > 0 and ev["notes"]
