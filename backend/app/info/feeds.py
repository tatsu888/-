"""Feeds (RSS 2.0 / Atom / RSS 1.0 RDF) — parsing, the default list of public sources, tagging. Pure functions."""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any

# category: 中銀 / 政府・統計 / 規制・取引所 / ニュース / 国際機関; region: JP / US / EU / UK / GLOBAL
DEFAULT_FEEDS: list[dict[str, Any]] = [
    {"id": "fed_press", "name": "FRB プレスリリース", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "category": "中銀", "region": "US"},
    {"id": "fed_speech", "name": "FRB 講演", "url": "https://www.federalreserve.gov/feeds/speeches.xml", "category": "中銀", "region": "US"},
    {"id": "ecb_press", "name": "ECB プレス", "url": "https://www.ecb.europa.eu/rss/press.html", "category": "中銀", "region": "EU"},
    {"id": "boe_news", "name": "イングランド銀行 ニュース", "url": "https://www.bankofengland.co.uk/rss/news", "category": "中銀", "region": "UK"},
    {"id": "boj_new", "name": "日本銀行 新着情報", "url": "https://www.boj.or.jp/rss/whatsnew.xml", "category": "中銀", "region": "JP"},
    {"id": "bis_speech", "name": "BIS 各国中銀の講演", "url": "https://www.bis.org/doclist/cbspeeches.rss", "category": "中銀", "region": "GLOBAL"},
    {"id": "meti", "name": "経済産業省 ニュースリリース", "url": "https://www.meti.go.jp/ml_index_release_atom.xml", "category": "政府・統計", "region": "JP"},
    {"id": "cao", "name": "内閣府 新着", "url": "https://www.cao.go.jp/rss/news.rdf", "category": "政府・統計", "region": "JP"},
    {"id": "kantei", "name": "首相官邸 新着", "url": "https://www.kantei.go.jp/index-jnews.rdf", "category": "政府・統計", "region": "JP"},
    {"id": "fsa", "name": "金融庁 新着", "url": "https://www.fsa.go.jp/fsaNewsListAll_rss2.xml", "category": "規制・取引所", "region": "JP"},
    {"id": "sec_press", "name": "米 SEC プレスリリース", "url": "https://www.sec.gov/news/pressreleases.rss", "category": "規制・取引所", "region": "US"},
    {"id": "nhk_main", "name": "NHK 主要ニュース", "url": "https://www.nhk.or.jp/rss/news/cat0.xml", "category": "ニュース", "region": "JP"},
    {"id": "nhk_econ", "name": "NHK 経済", "url": "https://www.nhk.or.jp/rss/news/cat5.xml", "category": "ニュース", "region": "JP"},
    {"id": "nhk_intl", "name": "NHK 国際", "url": "https://www.nhk.or.jp/rss/news/cat6.xml", "category": "ニュース", "region": "GLOBAL"},
    {"id": "yahoo_biz", "name": "Yahoo!ニュース 経済", "url": "https://news.yahoo.co.jp/rss/categories/business.xml", "category": "ニュース", "region": "JP"},
    {"id": "cnbc_top", "name": "CNBC Top News", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
     "category": "ニュース", "region": "US"},
    {"id": "mw_top", "name": "MarketWatch Top Stories", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "category": "ニュース", "region": "US"},
]
# words that make an item worth a look even without a coverage hit (editable on screen)
DEFAULT_KEYWORDS = ["利上げ", "利下げ", "政策金利", "金融政策", "為替介入", "FOMC", "日銀", "ECB", "決算", "上方修正", "下方修正",
                    "自社株買い", "TOB", "公開買付", "M&A", "増資", "関税", "rate hike", "rate cut", "tariff", "guidance"]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def parse_date(s: str | None) -> str | None:
    """RFC 822 / ISO 8601 → ISO (UTC)."""
    t = (s or "").strip()
    if not t:
        return None
    try:
        d = email.utils.parsedate_to_datetime(t)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError:
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
            if not m:
                return None
            d = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean(s: str, n: int = 400) -> str:
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """Items: {title, link, published, summary, guid} from RSS 2.0, Atom or RSS 1.0 (RDF)."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as e:
        raise ValueError(f"フィードを読めない（XML ではない）: {e}") from e
    kind = _local(root.tag)
    if kind == "feed":                                                    # Atom
        entries = [e for e in root if _local(e.tag) == "entry"]
    elif kind == "rss":
        ch = _child(root, "channel")
        entries = [e for e in (ch if ch is not None else root) if _local(e.tag) == "item"]
    elif kind == "rdf":
        entries = [e for e in root if _local(e.tag) == "item"]
    else:
        raise ValueError(f"フィードではない（{kind}）")
    out = []
    for e in entries:
        title = _clean(_text(_child(e, "title")), 300)
        link = ""
        if kind == "feed":
            ls = [c for c in e if _local(c.tag) == "link"]
            alt = next((c for c in ls if c.get("rel", "alternate") == "alternate"), ls[0] if ls else None)
            link = alt.get("href", "") if alt is not None else ""
        else:
            link = _text(_child(e, "link")) or (e.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or "")
        pub = parse_date(_text(_child(e, "pubdate", "published", "updated", "date", "issued")))
        summary = _clean(_text(_child(e, "description", "summary", "content", "encoded")))
        guid = _text(_child(e, "guid", "id")) or link or title
        if title or link:
            out.append({"title": title, "link": link.strip(), "published": pub, "summary": summary,
                        "guid": hashlib.sha1(guid.encode("utf-8")).hexdigest()[:16]})
    return out


_SUFFIX = re.compile(r"(株式会社|\(株\)|ホールディングス|グループ本社|\bHoldings?\b|\bHD\b|\bInc\.?|\bCorporation\b|\bCorp\.?|"
                     r"\bCo\.,? ?Ltd\.?|\bLtd\.?|\bplc\b|\bN\.V\.|\bS\.A\.|\bAG\b)", re.I)


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def short_name(name: str) -> str:
    """The name without the corporate suffix (株式会社, ホールディングス, Inc. …) — how news usually writes it."""
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", _nfkc(name))).strip(" ・,.")


def code_hit(ticker: str, text: str) -> bool:
    """A ticker only where it is written as a code — （6857）＜6857＞【6857】 6857.T コード6857 TSE:6857 / (AAPL) $AAPL NASDAQ:AAPL —
    so that 「6857億円」 or 「2026年」 never tag a stock."""
    t, e = _nfkc(ticker).upper(), re.escape(_nfkc(ticker).upper())
    if not t:
        return False
    if re.fullmatch(r"[0-9][0-9A-Z]{3}", t):                       # Japanese securities code (incl. 130A)
        pats = [rf"[(\[【「<]\s*(?:[^\s()\[\]<>]{{1,12}}[:]\s*)?{e}\s*[)\]】」>]", rf"(?<![0-9A-Z]){e}\.T(?![A-Za-z])",
                rf"コード\s*:?\s*{e}(?![0-9A-Z])", rf"TSE\s*:\s*{e}(?![0-9A-Z])"]
    else:                                                            # US and other letter tickers
        pats = [rf"\${e}(?![A-Za-z])", rf"(?:NASDAQ|NYSE|AMEX|Nasdaq|Nyse)\s*:\s*{e}(?![A-Za-z])"]
        if len(t) >= 3:
            pats.append(rf"\(\s*{e}\s*\)")
    return any(re.search(p, text) for p in pats)


def name_hit(name: str, text: str) -> bool:
    for nm in {_nfkc(name).strip(), short_name(name)}:
        if len(nm) < 3:
            continue
        if re.fullmatch(r"[\x00-\x7f]+", nm):                      # Latin names as whole words (Meta ≠ Metallica)
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(nm)}(?![A-Za-z0-9])", text):
                return True
        elif nm in text:
            return True
    return False


def tag_item(item: dict[str, Any], coverage: list[dict[str, Any]], keywords: list[str]) -> dict[str, Any]:
    """Coverage hits (the ticker written as a code, or the company name) and keyword hits in title + summary."""
    text = _nfkc(f"{item.get('title', '')} {item.get('summary', '')}")
    hits = [c["ticker"] for c in coverage if c.get("ticker") and (code_hit(c["ticker"], text) or name_hit(c.get("name") or "", text))]
    low = text.lower()
    words = [w for w in keywords if w and _nfkc(w).lower() in low]
    return {**item, "tickers": sorted(set(hits)), "keywords": words}


def google_news_url(q: str, lang: str = "ja") -> str:
    from urllib.parse import quote
    if lang == "ja":
        return f"https://news.google.com/rss/search?q={quote(q)}&hl=ja&gl=JP&ceid=JP:ja"
    return f"https://news.google.com/rss/search?q={quote(q)}&hl=en-US&gl=US&ceid=US:en"
