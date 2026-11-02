"""INFO hub: feed formats, tagging, EDINET / SEC parsing, the update flow with alerts, filings, key settings."""
import asyncio
import io
import time
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from app import api_info as AI
from app.info import feeds as FD
from app.info import filings as FL

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>NHK</title>
<item><title>日銀が利上げを決定</title><link>https://example.jp/a</link><pubDate>Fri, 31 Oct 2026 03:00:00 +0900</pubDate>
<description><![CDATA[<p>政策金利を 0.75% に</p>]]></description><guid>a1</guid></item>
<item><title>アドバンテスト、上方修正</title><link>https://example.jp/b</link><pubDate>Fri, 31 Oct 2026 15:30:00 +0900</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>METI</title>
<entry><title>半導体の支援策</title><link rel="alternate" href="https://example.jp/meti/1"/><updated>2026-10-30T10:00:00+09:00</updated>
<id>tag:meti,1</id><summary>補助金</summary></entry></feed>"""
RDF = """<?xml version="1.0" encoding="UTF-8"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><channel rdf:about="x"><title>内閣府</title></channel>
<item rdf:about="https://example.jp/cao/1"><title>月例経済報告</title><link>https://example.jp/cao/1</link><dc:date>2026-10-29T17:00:00+09:00</dc:date></item>
</rdf:RDF>"""


def test_feed_formats_and_tagging():
    r = FD.parse_feed(RSS)
    assert [x["title"] for x in r] == ["日銀が利上げを決定", "アドバンテスト、上方修正"]
    assert r[0]["published"] == "2026-10-30T18:00:00Z" and r[0]["summary"] == "政策金利を 0.75% に"
    a = FD.parse_feed(ATOM)[0]
    assert a["link"] == "https://example.jp/meti/1" and a["published"] == "2026-10-30T01:00:00Z"
    d = FD.parse_feed(RDF)[0]
    assert d["link"] == "https://example.jp/cao/1" and d["published"].startswith("2026-10-29T08:00")
    with pytest.raises(ValueError):
        FD.parse_feed("<html><body>not a feed</body></html>")
    cov = [{"ticker": "6857", "name": "アドバンテスト"}, {"ticker": "3436", "name": "SUMCO"}]
    t = FD.tag_item(r[1], cov, ["上方修正"])
    assert t["tickers"] == ["6857"] and t["keywords"] == ["上方修正"]
    assert FD.tag_item({"title": "コード 3436 の開示", "summary": ""}, cov, [])["tickers"] == ["3436"]
    assert FD.tag_item({"title": "2026年の見通し", "summary": ""}, cov, [])["tickers"] == []
    tick = lambda title, c=cov: FD.tag_item({"title": title, "summary": ""}, c, [])["tickers"]       # noqa: E731
    assert tick("＜６８５７＞急伸") == tick("決算（東証プライム：6857）") == tick("【6857】") == tick("6857.T rises") == ["6857"]
    assert tick("売上高は6857億円") == tick("6857人が参加") == []                                    # numbers are not codes
    us = [{"ticker": "AAPL", "name": "Apple Inc."}, {"ticker": "META", "name": "Meta Platforms, Inc."}, {"ticker": "AI", "name": "C3.ai"}]
    assert tick("Apple shares rise", us) == tick("$AAPL up", us) == tick("(NASDAQ: AAPL)", us) == ["AAPL"]
    assert tick("Metallica tour", us) == [] and tick("Meta Platforms beats", us) == ["META"]
    assert tick("artificial intelligence (AI) boom", us) == [] and tick("NYSE: AI falls", us) == ["AI"]
    assert FD.short_name("株式会社アドバンテスト") == "アドバンテスト" and FD.short_name("ソニーグループ株式会社") == "ソニーグループ"
    assert FD.tag_item({"title": "ＦＯＭＣ声明", "summary": ""}, [], ["FOMC"])["keywords"] == ["FOMC"]     # full-width text
    assert "news.google.com/rss/search?q=" in FD.google_news_url("アドバンテスト")


def codes_zip() -> bytes:
    text = "ダウンロード実行日,2026年11月02日現在,件数,3\nＥＤＩＮＥＴコード,提出者種別,上場区分,提出者名,証券コード\n" \
           "E01234,内国法人,上場,株式会社アドバンテスト,68570\nE09999,内国法人,非上場,某投資顧問,\n"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("EdinetcodeDlInfo.csv", text.encode("cp932"))
    return b.getvalue()


EDINET_LIST = {"metadata": {"status": "200", "message": "OK"}, "results": [
    {"docID": "S100AAAA", "secCode": None, "filerName": "某投資顧問", "docDescription": "変更報告書", "docTypeCode": "350",
     "submitDateTime": "2026-11-02 15:00", "edinetCode": "E09999", "issuerEdinetCode": None, "subjectEdinetCode": "E01234", "withdrawalStatus": "0"},
    {"docID": "S100BBBB", "secCode": "68570", "filerName": "株式会社アドバンテスト", "docDescription": "自己株券買付状況報告書", "docTypeCode": "220",
     "submitDateTime": "2026-11-02 09:00", "edinetCode": "E01234", "withdrawalStatus": "0"},
    {"docID": "S100CCCC", "secCode": "68570", "filerName": "株式会社アドバンテスト", "docDescription": "有価証券報告書", "docTypeCode": "120",
     "submitDateTime": "2026-11-01 09:00", "edinetCode": "E01234", "withdrawalStatus": "1"}]}


def test_edinet_and_sec_parsers():
    docs = FL.parse_edinet_list(EDINET_LIST)
    assert [d["doc_id"] for d in docs] == ["S100AAAA", "S100BBBB"]                  # withdrawn skipped
    assert [d["kind"] for d in docs] == ["大量保有", "自己株買い"]
    codes = FL.parse_edinet_codes(codes_zip())
    assert codes == {"E01234": "6857"}
    assert FL.edinet_ticker(docs[0], codes) == "6857" and FL.edinet_ticker(docs[1], codes) == "6857"   # the subject, not the filer
    with pytest.raises(ValueError):
        FL.parse_edinet_list({"metadata": {"status": "401", "message": "Access denied"}})
    assert FL.parse_sec_tickers({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}) == {"AAPL": 320193}
    sub = {"cik": "320193", "filings": {"recent": {"form": ["8-K", "4"], "filingDate": ["2026-10-30", "2026-10-29"],
                                                   "accessionNumber": ["0000320193-26-000101", "0000320193-26-000099"],
                                                   "primaryDocument": ["a8k.htm", "x4.xml"], "primaryDocDescription": ["8-K", ""]}}}
    f = FL.parse_sec_submissions(sub)
    assert f[0]["kind"] == "臨時報告" and f[0]["url"].endswith("/320193/000032019326000101/a8k.htm") and f[1]["kind"] == "インサイダー取引"


def test_update_feeds_alerts_filings_and_stock(tmp_path, monkeypatch):
    from app.main import app

    test_feeds = [{"id": "t_nhk", "name": "テスト NHK", "url": "https://feeds.test/nhk", "category": "ニュース", "region": "JP", "enabled": True},
                  {"id": "t_meti", "name": "テスト METI", "url": "https://feeds.test/meti", "category": "政府・統計", "region": "JP", "enabled": True}]
    monkeypatch.setattr(AI, "feeds", lambda: test_feeds)
    info_dir = tmp_path / "info"
    info_dir.mkdir()
    monkeypatch.setattr(AI, "idir", lambda: info_dir)                # never the shared data/info of other tests
    state = {"rss": RSS}

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u.endswith("/nhk"):
            return httpx.Response(200, text=state["rss"])
        if u.endswith("/meti"):
            return httpx.Response(200, text=ATOM)
        if "codelist" in u:
            return httpx.Response(200, content=codes_zip())
        if "documents.json" in u:
            if req.url.params["date"] != state.get("edinet_day"):
                return httpx.Response(200, json={"metadata": {"status": "200"}, "results": []})
            return httpx.Response(200, json={**EDINET_LIST, "results": EDINET_LIST["results"] + state.get("edinet_new", [])})
        return httpx.Response(404)

    mk = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: E731
    with TestClient(app) as c:
        items = [{"ticker": "6857", "symbol": "TSE:6857", "name": "アドバンテスト", "fye_month": 3}]
        c.put("/api/store/coverage", json={"value": {"items": items, "pages": {}, "config": {"layout": "sector", "root": str(tmp_path / "Cov")}}})
        AI._write("items.json", [])
        AI._write("feed_status.json", {})
        r1 = asyncio.run(AI.update_feeds(mk))
        assert r1["new"] == 3 and r1["alerts"] == 0                                        # the first load never alerts
        assert asyncio.run(AI.update_feeds(mk))["new"] == 0                                 # nothing new
        state["rss"] = RSS.replace("</channel>", "<item><title>アドバンテストが自社株買い</title><link>https://example.jp/c</link>"
                                                   "<pubDate>Sat, 01 Nov 2026 10:00:00 +0900</pubDate></item></channel>")
        r3 = asyncio.run(AI.update_feeds(mk))
        assert r3["new"] == 1 and r3["alerts"] == 1
        hits = c.get("/api/info/items", params={"hits_only": True, "days": 3650}).json()["rows"]
        assert {h["title"] for h in hits} >= {"アドバンテストが自社株買い", "日銀が利上げを決定"}
        st = c.get("/api/info/stock/TSE:6857", params={"news": False}).json()
        assert {x["title"] for x in st["items"]} == {"アドバンテストが自社株買い", "アドバンテスト、上方修正"}
        # EDINET needs a key; with one, coverage filings are mapped through the subject company
        assert asyncio.run(AI.update_edinet(mk))["skipped"]
        monkeypatch.setenv("EDINET_API_KEY", "0123456789abcdef0123456789abcdef")
        import datetime as dt
        state["edinet_day"] = dt.date.today().isoformat()
        first = asyncio.run(AI.update_edinet(mk))
        assert first["dates"] == 7 and first["alerts"] == 0                                 # history: no alerts
        state["edinet_new"] = [{**EDINET_LIST["results"][1], "docID": "S100DDDD", "docDescription": "臨時報告書", "submitDateTime": f"{state['edinet_day']} 16:00"}]
        assert asyncio.run(AI.update_edinet(mk))["alerts"] == 1                             # a new coverage filing today
        fil = c.get("/api/info/filings").json()
        assert [(x["ticker"], x["kind"]) for x in fil["rows"]] == [("6857", "臨時報告書"), ("6857", "大量保有"), ("6857", "自己株買い")]
        assert fil["rows"][1]["pdf"] == "/api/info/edinet/S100AAAA/pdf" and fil["keys"]["EDINET_API_KEY"]
        assert [x["doc_id"] for x in c.get("/api/info/stock/TSE:6857", params={"news": False}).json()["filings"]] == ["S100DDDD", "S100AAAA", "S100BBBB"]
        # keywords and feeds management
        assert c.put("/api/info/keywords", json={"words": ["利上げ", " ", "半導体"]}).json()["words"] == ["利上げ", "半導体"]
    monkeypatch.undo()                                                       # the real feed list again
    with TestClient(app) as c:
        a = c.post("/api/info/feeds", json={"name": "日経 マーケット", "url": "https://example.jp/a.rss"}).json()["id"]
        b = c.post("/api/info/feeds", json={"name": "日経 企業", "url": "https://example.jp/b.rss"}).json()["id"]
        assert a != b and c.post("/api/info/feeds", json={"name": "x", "url": "ftp://x"}).status_code == 400
        assert c.put(f"/api/info/feeds/{a}", json={"enabled": False}).json()["ok"]
        fs = {f["id"]: f for f in c.get("/api/info/feeds").json()["rows"]}
        assert fs[a]["enabled"] is False and fs[b]["enabled"] is True and fs[b]["custom"] and len(fs) == len(FD.DEFAULT_FEEDS) + 2
        c.delete(f"/api/info/feeds/{a}"), c.delete(f"/api/info/feeds/{b}"), c.put(f"/api/info/feeds/{a}", json={"enabled": True})
        assert len(c.get("/api/info/feeds").json()["rows"]) == len(FD.DEFAULT_FEEDS)


def test_key_settings_write_the_local_env(monkeypatch):
    import os
    from pathlib import Path
    from app.main import app

    p = Path(os.environ["TERMINAL_ENV_FILE"])
    p.write_text("# local settings\nNOTION_TOKEN=keep-me\n", encoding="utf-8")
    with TestClient(app) as c:
        assert c.put("/api/settings/keys", json={"key": "ESTAT_APP_ID", "value": "someone@example.com"}).status_code == 400
        r = c.put("/api/settings/keys", json={"key": "ESTAT_APP_ID", "value": "0123456789abcdef0123456789abcdef01234567"}).json()
        assert r["keys"]["ESTAT_APP_ID"]["set"] and r["keys"]["ESTAT_APP_ID"]["masked"] == "0123…4567"
        text = p.read_text(encoding="utf-8")
        assert "ESTAT_APP_ID=0123456789abcdef0123456789abcdef01234567" in text and "NOTION_TOKEN=keep-me" in text
        assert os.environ["ESTAT_APP_ID"].startswith("0123")                                 # applied without a restart
        assert c.get("/api/econ/status").json()["keys"]["ESTAT_APP_ID"] is True
        c.put("/api/settings/keys", json={"key": "ESTAT_APP_ID", "value": ""})
        assert "ESTAT_APP_ID" not in p.read_text(encoding="utf-8") and "ESTAT_APP_ID" not in os.environ
        assert c.put("/api/settings/keys", json={"key": "SEC_USER_AGENT", "value": "no-contact"}).status_code == 400
        assert c.put("/api/settings/keys", json={"key": "OTHER", "value": "x"}).status_code == 400
        # what the keys screen writes is read back unchanged at the next start (config.load_dotenv)
        ua = "Taro Yamada #2 taro@example.com"
        assert c.put("/api/settings/keys", json={"key": "SEC_USER_AGENT", "value": ua}).status_code == 200
    from app.config import load_dotenv
    os.environ.pop("SEC_USER_AGENT")
    had_notion = "NOTION_TOKEN" in os.environ
    monkeypatch.delenv("TERMINAL_NO_DOTENV", raising=False)
    try:
        assert "SEC_USER_AGENT" in load_dotenv(p) and os.environ["SEC_USER_AGENT"] == ua
    finally:                                     # plain pops: monkeypatch would restore these values after the test
        os.environ.pop("SEC_USER_AGENT", None)
        if not had_notion:
            os.environ.pop("NOTION_TOKEN", None)
    time.sleep(0)
