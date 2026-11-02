# AGENTS.md — AI エージェント（ChatGPT / Codex / Claude など）向けの作業ルール

このリポジトリは、複数の AI と人間が交代で開発します。**作業を始める前に、必ず次の 3 つを読んでください。**

1. [`docs/HANDOFF.md`](docs/HANDOFF.md)：現状、ファイル構成、既知の課題、次にやること
2. [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md)：ユーザーの要望（原文に沿った記録）と、実装との対応
3. [`docs/WORKLOG.md`](docs/WORKLOG.md)：時系列の作業記録

## 必ず守ること

- **記録を残す**：作業が終わったら、`docs/WORKLOG.md` に追記します（日付、担当 AI／人、やったこと、未解決事項）。仕様を変えたら、該当する docs も同じコミットで更新します。
- **データを捏造しない**：データを取得できないときはエラーを表示します。SIM（疑似データ）は `source="sim"` と DEMO 表示で必ず区別し、本物の市場データとして見せてはいけません。
- **業績予想の数値は、AI が直接書かない**：AI が触ってよいのは spec（JSON）の前提値と `source`（出典）だけです。数値は `backend/app/harness` のエンジンが計算します（[`docs/FORECAST_HARNESS.md`](docs/FORECAST_HARNESS.md)）。
- **Excel を劣化させない**：HTML からの編集は、Windows では xlwings（Excel 本体）経由で行います。openpyxl での直接書き込みは、グラフやマクロなど失われる要素がないファイルに限り、必ずバックアップを取ってから行います。この制約を緩めないでください（[`docs/EXCEL.md`](docs/EXCEL.md)）。
- **決定性を保つ**：ハーネスや分析のコードで、現在時刻やシードなしの乱数を結果に混ぜてはいけません。
- **コミット前に `scripts/test.sh` を実行し、すべて通すこと**：テストを消したりスキップしたりして通すのは禁止です。

## 規約

- バックエンドは Python 3.11 以上、FastAPI です。依存を増やすときは慎重に判断します（分析コードはあえて numpy を使わない純 Python です）。
- フロントエンドは React 19、TypeScript（strict）、Vite、lightweight-charts v5 です。色はすべて `frontend/src/styles.css` の CSS 変数で管理します。
- 銘柄記号は TradingView 形式の `EXCHANGE:TICKER`（例：`NASDAQ:AAPL`, `TSE:7203`, `FX:USDJPY`）に統一します。Yahoo 向けには `providers/yahoo.py::to_yahoo` で変換します。
- 新しいデータソースを追加するときは、`backend/app/providers/base.py` の `Provider` を継承し、`providers/__init__.py` に登録します。
- 新しい画面機能を追加するときは、`frontend/src/lib/commands.ts` の `FUNCTIONS` に追加し、`App.tsx` の `FunctionBody` で表示コンポーネントを割り当て、`docs/COMMANDS.md` に追記します。

## よく使うコマンド

```bash
scripts/setup.sh
```

```bash
scripts/dev.sh
```

```bash
scripts/test.sh
```

```bash
cd backend && TERMINAL_PROVIDER=sim .venv/bin/uvicorn app.main:app --port 8000
```

それぞれ、初回セットアップ、開発サーバー起動（:8000 と :5173）、全テスト、オフラインでの動作確認に使います。
