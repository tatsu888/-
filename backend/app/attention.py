"""Attention & social trends: Google Trends, X (Twitter) API v2, StockTwits — plus pure analytics.

All three are external services; nothing here fabricates data. If a source is unavailable the API
returns an error with the configuration hint.

* Google Trends  — unofficial endpoints used by trends.google.com (explore → widgetdata). No key.
                   Rate-limited (HTTP 429) easily; values are relative (0–100 within the request).
* X API v2       — official; needs ``X_BEARER_TOKEN``. ``tweets/counts/recent`` and
                   ``tweets/search/recent`` require a paid tier (Basic or higher) as of 2025.
* StockTwits     — public symbol streams with user-tagged Bullish/Bearish sentiment. No key.

Analytics (tested): spike z-score, attention momentum, lexicon sentiment (EN + JA finance words),
attention-vs-price lead-lag on aligned periods.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
from typing import Any

import httpx

from .leadlag import cross_correlation, granger
from .providers.base import ProviderError

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


# ---------------------------------------------------------------------------
# analytics
# ---------------------------------------------------------------------------
def spike(values: list[float], window: int = 12) -> dict[str, Any]:
    """z-score of the latest value vs the previous ``window`` values; momentum = last / mean(prev 4) − 1."""
    if len(values) < window + 1:
        return {"z": None, "momentum": None}
    hist = values[-window - 1:-1]
    m = sum(hist) / len(hist)
    sd = math.sqrt(sum((v - m) ** 2 for v in hist) / (len(hist) - 1)) if len(hist) > 1 else 0.0
    prev4 = values[-5:-1]
    base = sum(prev4) / len(prev4) if prev4 else 0
    return {"z": (values[-1] - m) / sd if sd > 0 else None, "momentum": (values[-1] / base - 1) if base else None,
            "spike": bool(sd > 0 and (values[-1] - m) / sd > 2)}


BULL = ["bull", "bullish", "moon", "buy", "long", "calls", "beat", "beats", "upgrade", "breakout", "rally", "ath",
        "強気", "買い", "上昇", "最高値", "上方修正", "好決算", "増益", "爆上げ", "買い増し", "反発", "ストップ高", "急騰"]
BEAR = ["bear", "bearish", "sell", "short", "puts", "miss", "misses", "downgrade", "crash", "dump", "overvalued",
        "弱気", "売り", "下落", "暴落", "下方修正", "減益", "空売り", "利確", "ストップ安", "急落", "損切り"]
_WORD = re.compile(r"[a-z]+|[぀-ヿ一-鿿]+")


def lexicon_score(text: str) -> float | None:
    """(bull − bear) / (bull + bear) using a small EN/JA finance lexicon; None when no signal words."""
    t = text.lower()
    tokens = set(_WORD.findall(t))
    b = sum(1 for w in BULL if (w in tokens if w.isascii() else w in t))
    s = sum(1 for w in BEAR if (w in tokens if w.isascii() else w in t))
    return (b - s) / (b + s) if b + s else None


def aggregate_sentiment(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """posts: [{text, label?: 'Bullish'|'Bearish', weight?}] → bullish share & weighted score."""
    bull = bear = 0.0
    scored = []
    for p in posts:
        w = 1.0 + math.log1p(max(p.get("weight") or 0, 0))
        if p.get("label") in ("Bullish", "Bearish"):
            sc = 1.0 if p["label"] == "Bullish" else -1.0
        else:
            sc = lexicon_score(p.get("text") or "")
        if sc is None:
            continue
        scored.append(sc)
        if sc > 0:
            bull += w
        elif sc < 0:
            bear += w
    tot = bull + bear
    return {"posts": len(posts), "with_signal": len(scored), "bullish_share": bull / tot * 100 if tot else None,
            "score": (bull - bear) / tot if tot else None}


def attention_vs_price(att: list[dict[str, Any]], closes: dict[str, float], max_lag: int = 4) -> dict[str, Any]:
    """att: [{date, value}] (weekly or daily). Price is sampled on/before each attention date.
    Correlates Δattention with returns; positive lag = attention leads price."""
    dates = sorted(closes)

    def px(d: str) -> float | None:
        prior = [x for x in dates if x <= d]
        return closes[prior[-1]] if prior else None

    pts = [(a["date"], a["value"], px(a["date"])) for a in att]
    pts = [p for p in pts if p[2] is not None]
    if len(pts) < 12:
        return {"error": f"only {len(pts)} aligned periods"}
    da = [pts[i][1] - pts[i - 1][1] for i in range(1, len(pts))]
    rp = [math.log(pts[i][2] / pts[i - 1][2]) for i in range(1, len(pts)) if pts[i - 1][2] > 0]
    n = min(len(da), len(rp))
    da, rp = da[:n], rp[:n]
    cc = cross_correlation(da, rp, max_lag)
    lead = [r for r in cc["lags"] if r["lag"] > 0 and r["corr"] is not None]
    best = max(lead, key=lambda r: abs(r["corr"])) if lead else None
    return {"periods": n, "ccf": cc, "best_lead": best,
            "granger_attention_to_price": granger(da, rp, 1), "granger_price_to_attention": granger(rp, da, 1),
            "contemporaneous": next((r["corr"] for r in cc["lags"] if r["lag"] == 0), None)}


# ---------------------------------------------------------------------------
# Google Trends (unofficial)
# ---------------------------------------------------------------------------
GT = "https://trends.google.com"


def _strip_xssi(text: str) -> Any:
    i = text.find("{")
    return json.loads(text[i:]) if i >= 0 else {}


class GoogleTrends:
    def __init__(self, http: httpx.AsyncClient | None = None, hl: str = "en-US", tz: int = -540) -> None:
        self.http = http or httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}, follow_redirects=True)
        self.hl, self.tz = hl, tz

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            r = await self.http.get(GT + path, params=params)
            if r.status_code == 429:
                await self.http.get(GT + "/", params={"geo": "US"})  # obtain NID cookie, retry once
                r = await self.http.get(GT + path, params=params)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"google trends {path}: {e}") from e
        return _strip_xssi(r.text)

    async def interest(self, keywords: list[str], geo: str = "", timeframe: str = "today 12-m",
                       related: bool = True) -> dict[str, Any]:
        kws = keywords[:5]
        req = {"comparisonItem": [{"keyword": k, "geo": geo, "time": timeframe} for k in kws], "category": 0, "property": ""}
        exp = await self._get("/trends/api/explore", {"hl": self.hl, "tz": self.tz, "req": json.dumps(req)})
        widgets = exp.get("widgets", [])
        ts = next((w for w in widgets if w.get("id") == "TIMESERIES"), None)
        if ts is None:
            raise ProviderError("google trends: TIMESERIES widget not found (format changed?)")
        data = await self._get("/trends/api/widgetdata/multiline",
                               {"hl": self.hl, "tz": self.tz, "req": json.dumps(ts["request"]), "token": ts["token"]})
        series: dict[str, list[dict[str, Any]]] = {k: [] for k in kws}
        for row in (data.get("default") or {}).get("timelineData", []):
            d = dt.datetime.fromtimestamp(int(row["time"]), tz=dt.timezone.utc).strftime("%Y-%m-%d")
            for k, v in zip(kws, row.get("value", [])):
                series[k].append({"date": d, "time": int(row["time"]), "value": v, "partial": bool(row.get("isPartial"))})
        out: dict[str, Any] = {"keywords": kws, "geo": geo, "timeframe": timeframe, "series": series,
                               "spikes": {k: spike([p["value"] for p in s if not p["partial"]]) for k, s in series.items()}}
        if related:
            rel: dict[str, Any] = {}
            for w in (x for x in widgets if x.get("id", "").startswith("RELATED_QUERIES")):
                kw = (w.get("request", {}).get("restriction", {}).get("complexKeywordsRestriction", {})
                      .get("keyword", [{}])[0].get("value"))
                try:
                    d = await self._get("/trends/api/widgetdata/relatedsearches",
                                        {"hl": self.hl, "tz": self.tz, "req": json.dumps(w["request"]), "token": w["token"]})
                except ProviderError:
                    continue
                lists = (d.get("default") or {}).get("rankedList", [])
                pick = lambda i: [{"query": x.get("query"), "value": x.get("formattedValue") or x.get("value")}  # noqa: E731
                                  for x in (lists[i].get("rankedKeyword", []) if len(lists) > i else [])][:15]
                rel[kw or "?"] = {"top": pick(0), "rising": pick(1)}
            out["related"] = rel
        return out


# ---------------------------------------------------------------------------
# X (Twitter) API v2 — official, bearer token
# ---------------------------------------------------------------------------
class XClient:
    BASE = "https://api.twitter.com/2"

    def __init__(self, token: str | None = None, http: httpx.AsyncClient | None = None) -> None:
        self.token = token if token is not None else os.environ.get("X_BEARER_TOKEN", "")
        self.http = http or httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise ProviderError("X_BEARER_TOKEN is not set (X API v2; counts/search need a paid tier) — docs/ATTENTION.md")
        try:
            r = await self.http.get(self.BASE + path, params=params, headers={"Authorization": f"Bearer {self.token}"})
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ProviderError(f"X API {path}: HTTP {e.response.status_code} {e.response.text[:200]}") from e
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"X API {path}: {e}") from e
        return r.json()

    async def analyze(self, query: str, lang: str | None = None) -> dict[str, Any]:
        q = query + (f" lang:{lang}" if lang else "") + " -is:retweet"
        counts = await self._get("/tweets/counts/recent", {"query": q, "granularity": "day"})
        series = [{"date": c["start"][:10], "value": c["tweet_count"]} for c in counts.get("data", [])]
        search = await self._get("/tweets/search/recent", {"query": q, "max_results": 100,
                                                            "tweet.fields": "created_at,public_metrics,lang"})
        posts = [{"text": t.get("text", ""), "weight": (t.get("public_metrics") or {}).get("like_count", 0),
                  "created_at": t.get("created_at")} for t in search.get("data", [])]
        top = sorted(posts, key=lambda p: -(p["weight"] or 0))[:10]
        return {"query": query, "series": series, "spike": spike([p["value"] for p in series], min(5, max(len(series) - 1, 1))),
                "sentiment": aggregate_sentiment(posts), "top_posts": top,
                "note": "lexicon-based sentiment (EN/JA finance words); counts = last 7 days (recent endpoint)"}


# ---------------------------------------------------------------------------
# StockTwits — public symbol stream
# ---------------------------------------------------------------------------
class StockTwits:
    BASE = "https://api.stocktwits.com/api/2"

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=20, headers={"User-Agent": UA})

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            r = await self.http.get(self.BASE + path)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"stocktwits {path}: {e}") from e
        return r.json()

    async def symbol(self, ticker: str) -> dict[str, Any]:
        d = await self._get(f"/streams/symbol/{ticker}.json")
        msgs = d.get("messages", [])
        posts = [{"text": m.get("body", ""), "label": ((m.get("entities") or {}).get("sentiment") or {}).get("basic"),
                  "created_at": m.get("created_at"), "weight": (m.get("likes") or {}).get("total", 0)} for m in msgs]
        by_day: dict[str, dict[str, int]] = {}
        for p in posts:
            day = (p["created_at"] or "")[:10]
            b = by_day.setdefault(day, {"posts": 0, "bullish": 0, "bearish": 0})
            b["posts"] += 1
            if p["label"] == "Bullish":
                b["bullish"] += 1
            elif p["label"] == "Bearish":
                b["bearish"] += 1
        return {"symbol": ticker, "watchers": (d.get("symbol") or {}).get("watchlist_count"),
                "sentiment": aggregate_sentiment(posts), "by_day": [{"date": k, **v} for k, v in sorted(by_day.items())],
                "recent": posts[:20]}

    async def trending(self) -> list[dict[str, Any]]:
        d = await self._get("/trending/symbols.json")
        return [{"symbol": s.get("symbol"), "title": s.get("title"), "watchers": s.get("watchlist_count")}
                for s in d.get("symbols", [])]
