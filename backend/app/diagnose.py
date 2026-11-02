"""Connectivity & data-source self-diagnosis.

Run on the machine that will use the terminal (needs real internet):

    cd backend
    .venv/bin/python -m app.diagnose            # macOS/Linux
    .venv\\Scripts\\python -m app.diagnose       # Windows
    python -m app.diagnose --json report.json --no-symbols

Also available as GET /api/diagnose and from the SRC panel ("RUN DIAGNOSTICS").
The markdown report is designed to be pasted into an AI assistant (ChatGPT / Claude) together with
docs/HANDOFF.md so it can fix endpoint / protocol / symbol issues quickly.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import platform
import sys
import time
from typing import Any, Awaitable, Callable

from .providers.base import ProviderError

Check = dict[str, Any]


async def _timed(name: str, fn: Callable[[], Awaitable[Any]], judge: Callable[[Any], tuple[str, str]],
                 hint: str = "", timeout: float = 25.0) -> Check:
    t0 = time.perf_counter()
    try:
        res = await asyncio.wait_for(fn(), timeout)
        status, detail = judge(res)
    except asyncio.TimeoutError:
        status, detail = "FAIL", f"timeout after {timeout:.0f}s"
    except ProviderError as e:
        status, detail = "FAIL", str(e)
    except Exception as e:  # noqa: BLE001
        status, detail = "FAIL", f"{type(e).__name__}: {e}"
    return {"check": name, "status": status, "detail": detail[:500], "hint": hint if status != "PASS" else "",
            "ms": int((time.perf_counter() - t0) * 1000)}


def all_configured_symbols() -> list[str]:
    from .factors import FACTOR_SETS
    from .leadlag import THEMES
    from .universe import all_symbols

    syms = list(all_symbols())
    for cfg in FACTOR_SETS.values():
        syms += [cfg["benchmark"], *cfg["factors"].values()]
    for t in THEMES:
        syms += [t["leader"], *t["followers"]] + ([t["market"]] if t["market"] else [])
    from .macro import DEFAULT_MAP, all_macro_symbols

    syms += all_macro_symbols(DEFAULT_MAP)
    return list(dict.fromkeys(syms))


async def run_diagnostics(check_symbols: bool = True) -> dict[str, Any]:
    from .config import settings
    from .providers.tradingview import TradingViewProvider
    from .providers.tv_web import TVWeb
    from .providers.yahoo import YahooProvider, to_yahoo

    tv = TradingViewProvider(settings.tv_auth_token)
    web = TVWeb()
    yh = YahooProvider()
    checks: list[Check] = []
    await tv.start()
    try:
        async def tv_connected():
            for _ in range(150):
                if tv.status == "connected":
                    return tv.status
                await asyncio.sleep(0.1)
            return f"{tv.status} {tv.status_detail}"

        checks.append(await _timed(
            "tradingview.websocket", tv_connected,
            lambda r: ("PASS", "connected") if r == "connected" else ("FAIL", str(r)),
            "data.tradingview.com への WebSocket が張れない: プロキシ/ファイアウォール、または Origin ヘッダの拒否"))

        def judge_quotes(qs):
            ok = [q for q in qs if q.get("last") is not None]
            delays = {q["symbol"]: q.get("delay_sec") for q in ok}
            if len(ok) == len(qs):
                return "PASS", f"{len(ok)}/{len(qs)} quotes; delay_sec={delays}"
            bad = [q["symbol"] for q in qs if q.get("last") is None]
            return ("WARN" if ok else "FAIL"), f"missing: {bad}; delay_sec={delays}"

        checks.append(await _timed(
            "tradingview.quotes", lambda: tv.get_quotes(["NASDAQ:AAPL", "TSE:7203", "FX:USDJPY", "SP:SPX"]), judge_quotes,
            "qsd メッセージの形式 / quote_set_fields のフィールド名を DevTools の WS と照合 (tv_protocol.py)"))
        checks.append(await _timed(
            "tradingview.history", lambda: tv.get_history("NASDAQ:AAPL", "1D", 30),
            lambda b: ("PASS", f"{len(b)} bars, last close {b[-1]['close']}") if len(b) >= 20 else ("FAIL", f"{len(b)} bars"),
            "create_series / timescale_update の形式を確認 (tradingview.py::_fetch_history)"))
        checks.append(await _timed(
            "tradingview.history_intraday", lambda: tv.get_history("TSE:7203", "5", 30),
            lambda b: ("PASS", f"{len(b)} bars") if b else ("FAIL", "0 bars")))
        checks.append(await _timed(
            "tradingview.search", lambda: tv.search("toyota", 5),
            lambda r: ("PASS", ", ".join(x["symbol"] for x in r)) if r else ("FAIL", "no results"),
            "symbol-search の URL / パラメータ / レスポンス形式 (v3 は dict, 旧版は list)"))
        checks.append(await _timed(
            "tradingview.scanner.screener", lambda: tv.screener("america", "gainers", 5),
            lambda r: ("PASS", ", ".join(f"{q['symbol']} {q.get('change_pct')}" for q in r)) if r else ("FAIL", "no rows"),
            "scanner の列名 (SCAN_COLUMNS) — エラー本文に不正な列名が出る"))
        checks.append(await _timed(
            "tradingview.scanner.fundamentals", lambda: web.fundamentals("NASDAQ:AAPL"),
            lambda r: ("PASS" if len(r["fields"]) > 10 else "WARN", f"{len(r['fields'])} fields ({r['market']})"),
            "FUNDAMENTAL_COLUMNS の不正な列 → MINIMAL_COLUMNS に退避している場合は WARN"))

        async def earn():
            from .api_analysis import EARN_COLUMNS
            return await web.scan_symbols(["NASDAQ:AAPL", "TSE:7203"], EARN_COLUMNS)
        checks.append(await _timed(
            "tradingview.scanner.earnings_columns", earn,
            lambda r: ("PASS", json.dumps(r, default=str)[:300]) if r else ("FAIL", "empty"),
            "api_analysis.EARN_COLUMNS の列名を修正"))

        async def rv():
            from .api_analysis import RV_FIELDS
            return await web.scan_symbols(["NASDAQ:AAPL"], RV_FIELDS)
        checks.append(await _timed(
            "tradingview.scanner.rv_columns", rv,
            lambda r: ("PASS", f"{sum(v is not None for v in next(iter(r.values())).values())} non-null fields") if r else ("FAIL", "empty"),
            "api_analysis.RV_FIELDS の列名を修正"))
        checks.append(await _timed(
            "tradingview.news", lambda: web.news("NASDAQ:AAPL", "en", 5),
            lambda r: ("PASS", r[0]["title"][:80]) if r else ("WARN", "0 items"),
            "news-headlines の URL / パラメータ"))
        now = dt.datetime.now(dt.timezone.utc)
        checks.append(await _timed(
            "tradingview.calendar", lambda: web.calendar(now, now + dt.timedelta(days=7), ["US", "JP"]),
            lambda r: ("PASS", f"{len(r)} events") if r else ("WARN", "0 events"),
            "economic-calendar の URL / Origin ヘッダ"))

        # Yahoo
        checks.append(await _timed(
            "yahoo.quotes", lambda: yh.get_quotes(["NASDAQ:AAPL", "TSE:7203", "FX:USDJPY"]), judge_quotes,
            "query1.finance.yahoo.com — 401/429 の場合は cookie/crumb が必要になった可能性"))
        checks.append(await _timed(
            "yahoo.history", lambda: yh.get_history("TSE:7203", "1D", 30),
            lambda b: ("PASS", f"{len(b)} bars") if len(b) >= 20 else ("FAIL", f"{len(b)} bars")))
        checks.append(await _timed(
            "yahoo.search", lambda: yh.search("toyota", 5),
            lambda r: ("PASS", ", ".join(x["symbol"] for x in r)) if r else ("FAIL", "no results")))

        symbols: dict[str, Any] = {}
        if check_symbols:
            syms = all_configured_symbols()
            try:
                qs = await asyncio.wait_for(tv.get_quotes(syms), 40)
                symbols["tradingview_invalid"] = [q["symbol"] for q in qs if q.get("last") is None]
            except Exception as e:  # noqa: BLE001
                symbols["tradingview_error"] = str(e)
            sem = asyncio.Semaphore(6)

            async def yq(s):
                async with sem:
                    try:
                        q = (await yh.get_quotes([s]))[0]
                        return s, q.get("last") is not None
                    except Exception:  # noqa: BLE001
                        return s, False
            res = await asyncio.gather(*(yq(s) for s in syms))
            symbols["yahoo_invalid"] = [f"{s} ({to_yahoo(s)})" for s, ok in res if not ok]
            symbols["checked"] = len(syms)
            checks.append({
                "check": "configured_symbols", "ms": 0,
                "status": "PASS" if not symbols.get("tradingview_invalid") else "WARN",
                "detail": f"TradingView invalid: {symbols.get('tradingview_invalid')} | Yahoo invalid: {symbols['yahoo_invalid']}",
                "hint": "universe.py / factors.py / leadlag.py の記号を修正 (取引所プレフィックス)"})
    finally:
        await tv.stop()
        await yh.stop()
        await web.close()
    summary = {s: sum(1 for c in checks if c["status"] == s) for s in ("PASS", "WARN", "FAIL")}
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "tv_auth": "logged-in token" if settings.tv_auth_token != "unauthorized_user_token" else "anonymous"},
        "summary": summary, "checks": checks,
    }


def to_markdown(rep: dict[str, Any]) -> str:
    lines = [f"# Analyst Terminal diagnostics ({rep['generated_at']})", "",
             f"env: {rep['environment']}", f"summary: {rep['summary']}", "",
             "| status | check | ms | detail | hint |", "|---|---|---|---|---|"]
    for c in rep["checks"]:
        d = c["detail"].replace("|", "/").replace("\n", " ")
        lines.append(f"| {c['status']} | {c['check']} | {c['ms']} | {d} | {c['hint']} |")
    lines += ["", "Paste this report with docs/HANDOFF.md into your AI assistant to fix failing checks."]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="also write the report as JSON to this path")
    ap.add_argument("--no-symbols", action="store_true", help="skip validating every configured symbol")
    args = ap.parse_args()
    rep = asyncio.run(run_diagnostics(not args.no_symbols))
    print(to_markdown(rep))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
    sys.exit(1 if rep["summary"]["FAIL"] else 0)


if __name__ == "__main__":
    main()
