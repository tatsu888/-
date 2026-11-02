"""AI brief — a self-contained markdown prompt for ChatGPT / Claude that lets the assistant improve a
harness spec WITHOUT computing numbers itself. Its answer must be a JSON list of changes that the
terminal validates and applies (POST /api/harness/apply_changes)."""
from __future__ import annotations

import json
from typing import Any

from . import CATALOG
from .lines import METHOD_PARAMS
from .runner import ENGINE_VERSION

RULES = """\
## ルール（必ず守ること）
1. あなたは数値を計算しない。売上・利益・株価などの予想値をあなたが書いてはいけない。計算はハーネスが行う。
2. あなたが変更できるのは前提（lines の method / params、assumptions、valuation、scenarios、sensitivity、monte_carlo）だけ。
   history（実績）は変更禁止（開示資料や Excel から入れる）。
3. 判断を伴う前提（成長率・マージン・単価・シェア等）には必ず "source"（出典：資料名・日付・ページ、または根拠）を付ける。
   根拠が無い場合は変更を提案せず、「必要な情報」として列挙する。
4. 回答は下記 JSON だけを ```json ブロックで返す（説明は "rationale" に書く）。
"""

ANSWER_FORMAT = """\
## 回答形式
```json
{
  "changes": [
    {"path": "lines.units.params.rates", "value": [0.03, 0.03, 0.02, 0.02, 0.02],
     "source": "業界団体 2026/10 見通し p.4", "rationale": "…"}
  ],
  "questions": ["確認が必要な事項 …"],
  "missing_data": ["追加で必要な実績データ …"]
}
```
path は spec 内のドット記法（例: lines.cogs.params.pct, valuation.terminal_growth, assumptions.tax_rate）。
"""


def method_table() -> str:
    rows = ["| method | required params | optional | meaning |", "|---|---|---|---|"]
    for m, meta in METHOD_PARAMS.items():
        rows.append(f"| {m} | {', '.join(f'{k}:{v}' for k, v in meta['required'].items()) or '—'} | "
                    f"{', '.join(meta['optional']) or '—'} | {meta['desc']} |")
    return "\n".join(rows)


def make_brief(spec: dict[str, Any], result: dict[str, Any] | None = None, task: str = "") -> str:
    company = spec.get("company", {})
    parts = [
        f"# 業績予想ハーネス レビュー依頼 — {company.get('name', '')} ({company.get('symbol', '')})",
        f"engine: {ENGINE_VERSION}",
        "",
        "あなたは株式アナリストのアシスタントです。以下の決定的な財務モデル（ハーネス）の spec を点検し、"
        "前提の改善案を JSON で返してください。",
        "",
        f"## 依頼内容\n{task or '前提の妥当性を点検し、出典の無い前提・過去実績から乖離した前提・警告(WARN/FAIL)を解消する変更を提案してください。'}",
        "",
        RULES,
        ANSWER_FORMAT,
        "## 利用できる line method",
        method_table(),
        "",
        "## MECE カタログ（層）",
        "\n".join(f"- {layer['layer']}: " + ", ".join(i['id'] for i in layer['items']) for layer in CATALOG),
        "",
        "## 現在の spec",
        "```json",
        json.dumps(spec, ensure_ascii=False, indent=1),
        "```",
    ]
    if result:
        d = result.get("projection", {}).get("derived", {})
        years = result.get("projection", {}).get("years", [])
        val = (result.get("valuation") or {}).get("dcf", {})
        parts += [
            "",
            "## 直近の実行結果（ハーネスが計算。あなたはこれを再計算しないこと）",
            f"- input_hash: {result.get('meta', {}).get('input_hash')}",
            f"- years: {years}",
            f"- operating_profit: {d.get('operating_profit')}",
            f"- eps: {d.get('eps')}",
            f"- operating_margin: {d.get('operating_margin')}",
            f"- DCF price per share: {val.get('price_per_share')}",
            "",
            "### 検証チェック",
        ]
        parts += [f"- [{c['status']}] {c['id']}: {c['message']}" for c in result.get("checks", [])]
    return "\n".join(parts)
