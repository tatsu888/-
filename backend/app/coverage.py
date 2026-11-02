"""COV — coverage from the Notion 銘柄マスタ: fiscal quarters, folder layout, fundamental report (pure helpers).

Fiscal-quarter labels: the system of record is the terminal's earnings calendar (earnings.py / api_earnings.py).
    Default convention "end" (standard 決算期 naming): FY = the year in which the fiscal year ENDS
        3月決算: Apr 2026–Mar 2027 = FY2027 ／ 12月決算: Jan–Dec 2025 = FY2025 ／ 1月決算: Feb 2026–Jan 2027 = FY2027
    Option "start_plus_1" reproduces the labels found on the ATLAS Notion pages (differs only for 12月決算),
    which the user says may be wrong. "■" is appended once the quarter has ended.

Folders (local; designed to be moved to OneDrive later — everything is stored RELATIVE to the root):
    layout "sector": <root>/GICS4530_半導体・半導体製造装置/6857_アドバンテスト/
    layout "ticker": <root>/6857_アドバンテスト/
    Each stock folder gets reports/ and a .coverage.json marker (ticker, name) so folders can be found
    again after a rename or a layout change. Sector folders are prefixed "GICS" so the 4-digit GICS code
    can never be auto-linked to a stock with the same ticker (e.g. 4530 = 久光製薬).
    Names are sanitised for Windows/OneDrive (\\ / : * ? " < > | and control chars, trailing dot/space,
    reserved names such as CON / NUL / COM1).
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from pathlib import Path, PurePosixPath
from typing import Any

TOPIX17_ETF = {
    "食品": "TSE:1617", "エネルギー資源": "TSE:1618", "建設・資材": "TSE:1619", "素材・化学": "TSE:1620",
    "医薬品": "TSE:1621", "自動車・輸送機": "TSE:1622", "鉄鋼・非鉄": "TSE:1623", "機械": "TSE:1624",
    "電機・精密": "TSE:1625", "情報通信・サービスその他": "TSE:1626", "電気・ガス": "TSE:1627", "電力・ガス": "TSE:1627",
    "運輸・物流": "TSE:1628", "商社・卸売": "TSE:1629", "小売": "TSE:1630", "銀行": "TSE:1631",
    "金融（除く銀行）": "TSE:1632", "不動産": "TSE:1633",
}
_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


# ---------------------------------------------------------------------------
# fiscal quarters
# ---------------------------------------------------------------------------
def _month_end(y: int, m: int) -> dt.date:
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def quarter_of(quarter_end: dt.date, fye_month: int, convention: str = "end") -> tuple[int, int]:
    """(FY label, quarter n) — delegates to earnings.fy_of (one implementation of the fiscal calendar)."""
    from .earnings import fy_of
    return fy_of(quarter_end, fye_month, convention)


def label(fy: int, n: int, ended: bool) -> str:
    return f"FY{fy} {n}Q" + (" ■" if ended else "")


def last_quarter_end(before: dt.date, fye_month: int, min_gap_days: int = 7) -> dt.date:
    """Most recent fiscal-quarter end at least ``min_gap_days`` before ``before``."""
    y, m = before.year, before.month
    for _ in range(15):
        if (m - fye_month) % 3 == 0:
            e = _month_end(y, m)
            if (before - e).days >= min_gap_days:
                return e
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    raise ValueError("no quarter end found")


def reported_quarter(earnings_date: dt.date, fye_month: int, today: dt.date | None = None,
                     convention: str = "end") -> dict[str, Any]:
    """Which quarter an earnings release reports. convention "end" = standard 決算期 naming (FY = year the
    fiscal year ends); "start_plus_1" = the labels found on the ATLAS pages (differs for 12月決算)."""
    e = last_quarter_end(earnings_date, fye_month)
    fy, n = quarter_of(e, fye_month, convention)
    today = today or dt.date.today()
    return {"fy": fy, "q": n, "quarter_end": e.isoformat(), "title": label(fy, n, e < today),
            "title_base": label(fy, n, False)}


def to_date(v: Any) -> dt.date | None:
    """Scanner timestamps (s or ms), ISO strings or dates → date."""
    if v in (None, ""):
        return None
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)):
        x = float(v) / (1000 if float(v) > 1e12 else 1)
        return dt.datetime.fromtimestamp(x, tz=dt.timezone.utc).date()
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# folders
# ---------------------------------------------------------------------------
def safe_name(s: str, limit: int = 80) -> str:
    s = _INVALID.sub("_", (s or "").replace("|", " ")).strip()
    s = re.sub(r"\s+", " ", s).replace(" ", "_")
    s = re.sub(r"_+", "_", s).strip("._ ")
    if s.upper().split(".")[0] in _RESERVED:
        s = f"_{s}"
    return s[:limit] or "_"


def stock_folder_name(ticker: str, name: str | None) -> str:
    return safe_name(f"{ticker} {name or ''}")


def group_folder_name(group: str | None) -> str:
    """"4530 | 半導体・半導体製造装置" → "GICS4530_半導体・半導体製造装置"; unknown → "GICS_未分類"."""
    if not group:
        return "GICS_未分類"
    m = re.match(r"\s*(\d{4})\s*\|\s*(.+)", group)
    return safe_name(f"GICS{m.group(1)} {m.group(2)}") if m else safe_name(f"GICS {group}")


def rel_stock_dir(item: dict[str, Any], layout: str) -> str:
    """Relative POSIX path (stored in the coverage list; independent of the root → survives a OneDrive move)."""
    stock = stock_folder_name(item["ticker"], item.get("name"))
    if layout == "sector":
        return str(PurePosixPath(group_folder_name(item.get("gics_group"))) / stock)
    return stock


def plan_folders(items: list[dict[str, Any]], root: Path, layout: str,
                 existing: dict[str, Path] | None = None) -> list[dict[str, Any]]:
    """What ``apply_folders`` would do. existing = {ticker: current absolute folder} found via markers."""
    out = []
    for it in items:
        target = root / rel_stock_dir(it, layout)
        cur = (existing or {}).get(it["ticker"])
        if cur and Path(cur).resolve() == target.resolve():
            action = "ok"
        elif cur:
            action = "move"
        elif target.exists():
            action = "adopt"          # folder already there (made by hand) → only add the marker / reports/
        else:
            action = "create"
        out.append({"ticker": it["ticker"], "name": it.get("name"), "action": action,
                    "from": str(cur) if cur else None, "to": str(target), "rel": rel_stock_dir(it, layout)})
    return out


# ---------------------------------------------------------------------------
# fundamental report (rule-based; every number from terminal data, blanks are left for the analyst)
# ---------------------------------------------------------------------------
FRAMEWORK_SECTIONS = [
    ("Ⅰ. 業界分析（7項目）", ["市場規模 — 業界の天井（TAM）", "市場規模 — 発展段階（Sカーブ）", "産業発展 — 歴史・競争・道筋",
                         "海外ベンチマーク", "ランドスケープ — シェア、CR5／CR10", "参入障壁と撤退障壁", "今後の動向"]),
    ("Ⅱ. 企業分析", ["基礎（沿革・製品・チャネル）", "ビジネスモデル（製品・キャッシュ・情報の3フロー）",
                   "ガバナンス（株主構成・経営・インセンティブ・大株主の体外利益）", "競争力（3.5句）",
                   "指標（リテンション・利回り・R&D）", "サプライチェーン（川上・川下・交渉力）",
                   "今後の動向（主要セグメントの数量・ASP・マージン）", "財務予想", "トラッキング手法と先行指標",
                   "他の投資家の見方（MF・HF・個人）との差分", "リスク（崩れる経路と下落幅）", "株価の振り返り"]),
]


def _f(v: Any, d: int = 2, pct: bool = False) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{x:,.{d}f}%" if pct else f"{x:,.{d}f}"


def build_report(ctx: dict[str, Any]) -> dict[str, Any]:
    """ctx: item, quote/scan, perf, earnings, auto_row, scorecard, xray, chip, peers, transcript, themes, generated_at, source.
    Returns {"title", "sections": [{"heading", "lines": [str]}], "markdown"}."""
    it = ctx["item"]
    sc = ctx.get("scan") or {}
    secs: list[dict[str, Any]] = []
    head = [f"Ticker: {it['ticker']}（{it.get('symbol')}）　社名: {it.get('name') or '—'}",
            f"GICS: {it.get('gics_group') or '—'} ／ {it.get('gics_sub') or '—'}　旧セクター: {it.get('topix17') or '—'}",
            f"決算期末月: {it.get('fye_month') or '—'}月{'（未確定）' if it.get('fye_uncertain') else ''}",
            f"生成: {ctx.get('generated_at')}　データ: {ctx.get('source')}（ルールベース、AIなし）"]
    if ctx.get("source") == "sim":
        head.append("⚠ SIM（疑似データ）— 数値は市場データではない")
    secs.append({"heading": "概要", "lines": head})
    perf = ctx.get("perf") or {}
    secs.append({"heading": "株価・バリュエーション", "lines": [
        f"株価 {_f(sc.get('close'))}　時価総額 {_f((sc.get('market_cap_basic') or 0) / 1e8, 0) + '億' if sc.get('market_cap_basic') else '—'}",
        f"PER {_f(sc.get('price_earnings_ttm'), 1)}　PBR {_f(sc.get('price_book_ratio'), 2)}　EV/EBITDA {_f(sc.get('enterprise_value_ebitda_ttm'), 1)}　配当利回り {_f(sc.get('dividend_yield_recent'), 2, True)}",
        f"ROE {_f(sc.get('return_on_equity'), 1, True)}　営業利益率 {_f(sc.get('operating_margin'), 1, True)}　売上成長 {_f(sc.get('total_revenue_yoy_growth_ttm'), 1, True)}",
        f"騰落 1M {_f(perf.get('1M'), 1, True)}　3M {_f(perf.get('3M'), 1, True)}　1Y {_f(perf.get('1Y'), 1, True)}　ボラ(1Y) {_f(perf.get('vol_1y'), 1, True)}"]})
    er = ctx.get("earnings") or {}
    secs.append({"heading": "カタリスト（決算）", "lines": [
        f"次回決算 {er.get('next') or '—'}（{er.get('next_title') or '—'}）　あと {er.get('days') if er.get('days') is not None else '—'} 日",
        f"前回決算 {er.get('last') or '—'}（{er.get('last_title') or '—'}）"] + [f"テーマ: {t}" for t in ctx.get("themes") or []]})
    a = ctx.get("auto_row")
    if a:
        lines = [f"判定 {a['direction']}　確信 {a['conviction']}/3　サイズ {_f(a['size_pct'], 2, True)}",
                 f"F {_f(a['f']['score'])}（{a['f']['source']}）／ M {a['m'].get('reason', '')} ／ 需給 {a['l'].get('zone', '')}"]
        if a.get("sector_rrg"):
            lines.append(f"セクター回転 {a['sector_rrg'].get('label')}: {a['sector_rrg'].get('quadrant')}")
        lines += [f"・{f}" for f in a.get("flags", [])]
        secs.append({"heading": "三位一体（AUTO・ルールベース）", "lines": lines})
    card = ctx.get("scorecard")
    if card:
        r = card.get("result", {})
        sh = card.get("sheet", {})
        lines = [f"評点 {_f(r.get('total'))} → {r.get('direction')}（前回 {_f(r.get('prev_total'))}）　長期 {_f((r.get('groups') or {}).get('Long-term', {}).get('score'))} ／ 短期 {_f((r.get('groups') or {}).get('Short-term', {}).get('score'))}",
                 f"3.5句 {_f((r.get('moat') or {}).get('score'))} / 3.5（{'・'.join((r.get('moat') or {}).get('matched') or []) or '該当なし'}）"]
        if sh.get("reason"):
            lines.append(f"Reason: {sh['reason']}")
        for k, v in (sh.get("text") or {}).items():
            if v:
                lines.append(f"{k}: {v}")
        secs.append({"heading": "評点表（SCORE）", "lines": lines})
    x = ctx.get("xray")
    if x:
        s = x.get("shares", {})
        secs.append({"heading": "リターン分解（XRAY）", "lines": [
            f"マーケット {_f(s.get('market', 0) * 100, 0, True)} ／ スタイル・マクロ {_f(s.get('style', 0) * 100, 0, True)} ／ セクター {_f(s.get('sector', 0) * 100, 0, True)} ／ 個別 {_f(s.get('idio', 0) * 100, 0, True)}",
            f"→ {x.get('verdict')}"] + [f"・{c['factor']}: β {_f(c['beta'], 3)}（t {_f(c['t'], 1)}）" for c in (x.get("coefficients") or [])[:5]]})
    mg = ctx.get("margin")
    if mg and mg.get("latest"):
        L = mg["latest"]
        secs.append({"heading": "信用残（JPX 週次）", "lines": [
            f"{L.get('date')}: 信用倍率 {_f(L.get('ratio'))}（自己の過去 {mg.get('weeks')} 週で {_f(mg.get('ratio_percentile'), 0)} pctl）",
            f"買残 {_f(L.get('long'), 0)} ／ 売残 {_f(L.get('short'), 0)}　買残÷20日出来高 {_f(mg.get('buy_days'), 1)} 日"]})
    ch = ctx.get("chip")
    if ch:
        secs.append({"heading": "需給（CHIP）", "lines": [f"ゾーン: {ch.get('zone')}"] + [f"・{s['signal']}" for s in ch.get("top", []) + ch.get("bottom", []) if s.get("on")]})
    peers = ctx.get("peers") or []
    if peers:
        lines = [f"同じサブグループ（{it.get('gics_sub')}）のカバレッジ {len(peers)} 社"]
        for p in peers[:12]:
            lines.append(f"・{p['ticker']} {p.get('name') or ''}: PER {_f(p.get('pe'), 1)} PBR {_f(p.get('pb'), 2)} 1M {_f(p.get('ret_1m'), 1, True)} 判定 {p.get('verdict') or '—'}")
        secs.append({"heading": "同業比較（カバレッジ内）", "lines": lines})
    tr = ctx.get("transcript")
    if tr:
        secs.append({"heading": "書き起こし（TXT）", "lines": [
            f"{tr.get('period')}: net tone {_f(tr.get('net_tone'))}、言語変化 {_f(tr.get('change_score'), 3)}、Q&A 回避度 {_f(tr.get('evasiveness'))}"]})
    for title, items in FRAMEWORK_SECTIONS:
        secs.append({"heading": title, "lines": [f"□ {i}: " for i in items], "blank": True})
    secs.append({"heading": "結論（取引可能な命題）", "lines": ["誤価格の内容: ", "大きさ: ", "収束の日付（カタリスト）: ", "スプレッド分類（A-1 か）: "], "blank": True})
    title = f"{it['ticker']} {it.get('name') or ''} — ファンダメンタル・レポート {str(ctx.get('generated_at'))[:10]}"
    md = [f"# {title}", ""]
    for s in secs:
        md += [f"## {s['heading']}", ""] + [f"- {ln}" for ln in s["lines"]] + [""]
    return {"title": title, "sections": secs, "markdown": "\n".join(md)}


def notion_blocks(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Report → Notion blocks (heading_2 + bulleted / to-do items)."""
    def rt(text: str) -> list[dict[str, Any]]:
        return [{"type": "text", "text": {"content": text[:1900]}}]

    blocks: list[dict[str, Any]] = [{"object": "block", "type": "callout", "callout": {
        "rich_text": rt("ターミナルが自動生成（ルールベース・AIなし）。数値は生成時点のデータ。□ の項目はアナリストが記入。"),
        "icon": {"type": "emoji", "emoji": "🧾"}}}]
    for s in report["sections"]:
        blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": rt(s["heading"])}})
        for ln in s["lines"]:
            if s.get("blank") and ln.startswith("□ "):
                blocks.append({"object": "block", "type": "to_do", "to_do": {"rich_text": rt(ln[2:]), "checked": False}})
            else:
                blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rt(ln)}})
    return blocks
