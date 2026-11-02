"""BRIEF — the morning brief (rule-based; no AI, no new numbers — everything comes from the terminal's own data).

Sections
    markets     main indices / FX / rates / commodities: last, 1D, 1W, 1M (yields in bp)
    macro       Growth × Liquidity quadrant from the AUTO Trinity snapshot (current → next)
    factors     style factors from the factor library (Notion 04.4 list): best / worst over 1W, with 1D and 1M
    auto        Trinity AUTO: changes since the previous day, strongest LONG / SHORT ideas, book gross / net
    earnings    today, tomorrow, the next 7 days (status, typical move, AUTO view) and the last few days' reactions
    portfolio   earnings risk of the holdings: weight × typical earnings move (only when the move is known)
    margin      信用残: the largest week-on-week changes of 信用倍率 in the coverage
    health      where the data came from and how fresh it is (SIM is flagged as DEMO)
"""
from __future__ import annotations

from typing import Any

MARKETS: list[tuple[str, str, str]] = [
    ("日経平均", "TVC:NI225", "pct"), ("TOPIX", "TVC:TOPIX", "pct"), ("S&P 500", "SP:SPX", "pct"),
    ("NASDAQ 100", "NASDAQ:NDX", "pct"), ("SOX（半導体）", "NASDAQ:SOX", "pct"), ("VIX", "TVC:VIX", "pct"),
    ("ドル円", "FX:USDJPY", "pct"), ("米10年金利", "TVC:US10Y", "bp"), ("日10年金利", "TVC:JP10Y", "bp"),
    ("WTI 原油", "TVC:USOIL", "pct"), ("金", "TVC:GOLD", "pct"), ("ビットコイン", "BINANCE:BTCUSDT", "pct"),
]


def market_row(label: str, symbol: str, kind: str, bars: list[dict[str, Any]] | None) -> dict[str, Any]:
    closes = [b["close"] for b in (bars or []) if b.get("close")]
    row: dict[str, Any] = {"label": label, "symbol": symbol, "kind": kind}
    if len(closes) < 2:
        return {**row, "error": "データなし"}
    last = closes[-1]

    def ch(n: int) -> float | None:
        if len(closes) <= n:
            return None
        a = closes[-1 - n]
        return (last - a) * 100 if kind == "bp" else (last / a - 1) * 100

    return {**row, "last": last, "d1": ch(1), "w1": ch(5), "m1": ch(21)}


def factor_section(rows: list[dict[str, Any]], n: int = 3) -> dict[str, Any]:
    use = [r for r in rows if r.get("1W") is not None]
    use.sort(key=lambda r: -r["1W"])
    return {"rows": rows, "best": use[:n], "worst": use[-n:][::-1] if len(use) > n else []}


def _idea(r: dict[str, Any]) -> dict[str, Any]:
    return {"symbol": r["symbol"], "name": r.get("name"), "direction": r["direction"], "conviction": r["conviction"],
            "size_pct": r.get("size_pct"), "f": (r.get("f") or {}).get("score"), "flags": (r.get("flags") or [])[:3],
            "days_to_earnings": r.get("days_to_earnings")}


def sector_rotation(sectors: Any) -> dict[str, dict[str, list[str]]]:
    """RRG quadrants of the sector ETFs from the AUTO snapshot ({"JP17": [...], "US11": [...]}) → names per quadrant."""
    out: dict[str, dict[str, list[str]]] = {}
    for region, rows in (sectors.items() if isinstance(sectors, dict) else []):
        for r in rows or []:
            if r.get("quadrant_ja"):
                out.setdefault(region, {}).setdefault(r["quadrant_ja"], []).append(r.get("label") or r.get("symbol"))
    return out


def auto_section(latest: dict[str, Any] | None, changes: list[dict[str, Any]], n: int = 6) -> dict[str, Any]:
    if not latest:
        return {"available": False}
    # a symbol that newly entered the universe as NEUTRAL is not news
    changes = [c for c in changes if not (c.get("what") == "new" and str(c.get("to") or "").startswith("NEUTRAL"))]
    rows = latest.get("rows") or []
    longs = [r for r in rows if r.get("direction") == "LONG" and (r.get("size_pct") or 0) > 0]
    shorts = [r for r in rows if r.get("direction") == "SHORT" and (r.get("size_pct") or 0) > 0]
    key = lambda r: (-r["conviction"], -(r.get("size_pct") or 0))  # noqa: E731
    return {"available": True, "generated_at": latest.get("generated_at"), "quadrant": latest.get("quadrant"),
            "next_quadrant": latest.get("next_quadrant"), "book": latest.get("book"), "universe": latest.get("universe"),
            "changes": changes[:30], "n_changes": len(changes),
            "longs": [_idea(r) for r in sorted(longs, key=key)[:n]], "shorts": [_idea(r) for r in sorted(shorts, key=key)[:n]],
            "sectors": sector_rotation(latest.get("sectors")),
            "errors": sorted((latest.get("errors") or {}).keys())}


def earnings_section(rows: list[dict[str, Any]], reactions: dict[str, dict[str, Any]], typical: dict[str, dict[str, Any]],
                     auto_by_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """rows: calendar rows with ``days`` (negative = already reported). reactions: {ticker: latest reaction row}."""
    def enrich(r: dict[str, Any]) -> dict[str, Any]:
        t = r["ticker"]
        a = auto_by_ticker.get(t) or {}
        out = {**r, "typical": (typical.get(t) or {}).get("avg_abs"), "typical_n": (typical.get(t) or {}).get("n"),
               "auto": f"{a['direction']} c{a['conviction']}" if a.get("direction") else None}
        x = reactions.get(t)
        if x and r["days"] < 0:
            out["reaction"] = {k: x.get(k) for k in ("reaction_day", "r1", "x1", "vol_ratio", "kind")}
            mv = x.get("x1") if x.get("x1") is not None else x.get("r1")
            if mv is not None and out["typical"]:
                out["reaction"]["vs_typical"] = abs(mv) / out["typical"]
        return out

    ex = [enrich(r) for r in rows]
    return {"today": [r for r in ex if r["days"] == 0], "tomorrow": [r for r in ex if r["days"] == 1],
            "week": [r for r in ex if 2 <= r["days"] <= 7], "recent": [r for r in ex if r["days"] < 0]}


def portfolio_section(positions: list[dict[str, Any]], values: dict[str, float], upcoming: dict[str, dict[str, Any]],
                      typical: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Earnings in the next 14 days for the holdings: weight of gross × typical earnings move (market-adjusted mean
    |move|). Positions without a known typical move are listed with the swing left empty — never guessed."""
    gross = sum(abs(v) for v in values.values())
    rows = []
    for p in positions:
        s = p.get("symbol") or ""
        t = s.split(":")[-1]
        e = upcoming.get(t)
        if not e or s not in values:
            continue
        w = values[s] / gross * 100 if gross else None
        mv = (typical.get(t) or {}).get("avg_abs")
        rows.append({"symbol": s, "ticker": t, "date": e["date"], "days": e["days"], "status": e["status"], "label": e.get("label"),
                     "value": values[s], "weight_pct": w, "typical_pct": mv * 100 if mv is not None else None,
                     "swing_pct_of_gross": abs(w) * mv if w is not None and mv is not None else None,
                     "swing_value": abs(values[s]) * mv if mv is not None else None})
    rows.sort(key=lambda r: (r["date"], -(r["swing_pct_of_gross"] or 0)))
    known = [r["swing_pct_of_gross"] for r in rows if r["swing_pct_of_gross"] is not None]
    return {"rows": rows, "gross": gross, "total_swing_pct": sum(known) if known else None,
            "unknown": sum(r["swing_pct_of_gross"] is None for r in rows), "positions": len(positions)}


def margin_section(items: list[dict[str, Any]], series_of, n: int = 8) -> dict[str, Any]:
    """series_of(code) → weekly [{date, long, short}] (JPX 信用残). Largest week-on-week changes of 信用倍率."""
    rows = []
    last_date = None
    for it in items:
        if not str(it.get("symbol", "")).upper().startswith("TSE:"):
            continue
        ms = series_of(it["ticker"])
        if len(ms) < 2:
            continue
        a, b = ms[-2], ms[-1]
        ra = a["long"] / a["short"] if a.get("short") else None
        rb = b["long"] / b["short"] if b.get("short") else None
        last_date = max(last_date or b["date"], b["date"])
        rows.append({"ticker": it["ticker"], "name": it.get("name"), "date": b["date"], "ratio": rb, "ratio_prev": ra,
                     "ratio_chg": rb - ra if ra is not None and rb is not None else None,
                     "long_chg_pct": (b["long"] / a["long"] - 1) * 100 if a.get("long") else None,
                     "short_chg_pct": (b["short"] / a["short"] - 1) * 100 if a.get("short") else None})
    rows.sort(key=lambda r: -abs(r["long_chg_pct"] or 0))
    return {"rows": rows[:n], "covered": len(rows), "last_date": last_date}


# ---- markdown ---------------------------------------------------------------------------------------
def _p(v: Any, d: int = 1, sign: bool = True) -> str:
    if v is None:
        return "—"
    return f"{'+' if sign and v > 0 else ''}{v:.{d}f}%"


def _bp(v: Any) -> str:
    return "—" if v is None else f"{'+' if v > 0 else ''}{v:.0f}bp"


def render_md(b: dict[str, Any]) -> str:
    h = b.get("health") or {}
    out = [f"# 朝のブリーフ {b['date']}", "",
           f"作成 {b['generated_at']} · データ {h.get('provider')}{'（SIM — DEMO データ。市場の実際の値ではない）' if h.get('demo') else ''}", ""]
    out += ["## 市場", "", "| | 終値 | 1日 | 1週 | 1か月 |", "|---|---:|---:|---:|---:|"]
    for r in b["markets"]:
        if r.get("error"):
            out.append(f"| {r['label']} | {r['error']} | | | |")
            continue
        f = _bp if r["kind"] == "bp" else _p
        out.append(f"| {r['label']} | {r['last']:,.2f} | {f(r['d1'])} | {f(r['w1'])} | {f(r['m1'])} |")
    a = b["auto"]
    if a.get("available"):
        q, nq = a.get("quadrant") or {}, a.get("next_quadrant") or {}
        out += ["", "## マクロ局面（成長 × 流動性）", "", f"- 現在: **{q.get('name') or '—'}** → 次: {nq.get('name') or '—'}"]
        for region, title in (("JP17", "日本（TOPIX-17）"), ("US11", "米国")):
            qs = (a.get("sectors") or {}).get(region) or {}
            if qs:
                out.append(f"- セクター回転 {title}: " + " / ".join(f"{k}: {'、'.join(v)}" for k, v in qs.items()))
    f = b["factors"]
    out += ["", "## ファクター（スタイル、1 週）", ""]
    if f["rows"]:
        out.append("- 強い: " + "、".join(f"{r['factor']} {_p(r['1W'])}" for r in f["best"]))
        out.append("- 弱い: " + "、".join(f"{r['factor']} {_p(r['1W'])}" for r in f["worst"]))
    else:
        out.append("- ファクター・ライブラリが未作成（FCTR / AUTO）")
    out += ["", "## 三位一体 AUTO", ""]
    if a.get("available"):
        bk = a.get("book") or {}
        out.append(f"- 対象 {a.get('universe')} 銘柄 · グロス {_p(bk.get('gross_pct'), 1, False)} · ネット {_p(bk.get('net_pct'))} · 前日からの変化 {a['n_changes']} 件")
        for c in a["changes"][:12]:
            out.append(f"  - {c['symbol']}: {c.get('from') or '新規'} → {c['to']}")
        for side, key in (("LONG", "longs"), ("SHORT", "shorts")):
            if a[key]:
                out.append(f"- {side}: " + "、".join(f"{x['symbol']} c{x['conviction']}（{_p(x['size_pct'], 2, False)}）" for x in a[key]))
    else:
        out.append("- AUTO の結果がまだない")
    e = b["earnings"]
    out += ["", "## 決算", ""]
    for title, key in (("今日", "today"), ("明日", "tomorrow"), ("今週（2〜7 日後）", "week")):
        rows = e[key]
        out.append(f"- {title}: " + ("、".join(f"{r['ticker']} {r.get('name') or ''} {r['label']}（{r['status']}{'、通常 ±' + format(r['typical'] * 100, '.1f') + '%' if r.get('typical') else ''}）" for r in rows) or "なし"))
    if e["recent"]:
        out.append("- 直近の決算と反応:")
        for r in e["recent"]:
            x = r.get("reaction") or {}
            mv = x.get("x1") if x.get("x1") is not None else x.get("r1")
            big = "（通常の {:.1f} 倍）".format(x["vs_typical"]) if x.get("vs_typical") else ""
            out.append(f"  - {r['ticker']} {r.get('name') or ''} {r['label']} {r['date']}: {_p(mv * 100 if mv is not None else None)}{big}")
    p = b["portfolio"]
    out += ["", "## ポートフォリオの決算リスク（14 日以内）", ""]
    if p["rows"]:
        out += ["| 銘柄 | 決算 | 状態 | 比率 | 通常の値動き | 想定の振れ（グロス比） |", "|---|---|---|---:|---:|---:|"]
        for r in p["rows"]:
            out.append(f"| {r['symbol']} | {r['date']}（{r['days']}日後） | {r['status']} | {_p(r['weight_pct'], 1, False)} | "
                       f"{'±' + format(r['typical_pct'], '.1f') + '%' if r['typical_pct'] is not None else '不明'} | "
                       f"{_p(r['swing_pct_of_gross'], 2, False) if r['swing_pct_of_gross'] is not None else '—'} |")
        if p["total_swing_pct"] is not None:
            out.append(f"\n合計の想定の振れ（単純合計）: {_p(p['total_swing_pct'], 2, False)}（通常の値動きが分かる {len(p['rows']) - p['unknown']} 銘柄）")
    else:
        out.append(f"- 14 日以内に決算のある保有銘柄なし（保有 {p['positions']}）")
    m = b["margin"]
    out += ["", f"## 信用残（{m.get('last_date') or '未取り込み'}）", ""]
    for r in m["rows"]:
        out.append(f"- {r['ticker']} {r.get('name') or ''}: 信用倍率 {r['ratio']:.2f}" if r.get("ratio") is not None else f"- {r['ticker']}: 売残なし")
        out[-1] += f"（前週 {r['ratio_prev']:.2f}）" if r.get("ratio_prev") is not None else ""
        out[-1] += f" · 買残 {_p(r['long_chg_pct'])} · 売残 {_p(r['short_chg_pct'])}"
    if not m["rows"]:
        out.append("- 信用残のデータなし（MRGN で JPX のファイルを取り込む）")
    out += ["", "## データの状態", ""]
    for k, v in (h.get("items") or {}).items():
        out.append(f"- {k}: {v}")
    out += ["", "---", "ルールベースで作成（AI は使っていない）。数値はターミナルのデータから。"]
    return "\n".join(out) + "\n"
