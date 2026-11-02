# COVERAGE — Notion の銘柄マスタと連動するカバレッジ（COV）

## できること
- **SYNC FROM NOTION**：`ATLAS / MICRO / 銘柄マスタ`（Ticker・社名・GICS 産業グループ／サブグループ・旧セクター（TOPIX17）・決算期末月）を読み込み、`ATLAS / MICRO / <GICS> / <ticker> | <社名>` の個社ページを探して紐付ける。
- **決算日を更新**：TradingView スキャナーの次回・前回決算日（取れない銘柄は手入力 `PUT /api/coverage/<ticker>/earnings`）。報告される四半期を ATLAS の規則で計算。
- **NOTION 決算書き込み**（PREVIEW → APPLY）：銘柄マスタの「次回決算日」「次回決算期」を更新（無ければプロパティ追加を選べる）し、個社ページの下に四半期ページ（例 `FY2027 3Q`、終わった期は ` ■`）を作る。同じ四半期のページが既にあれば作らない。
- **フォルダ**（PREVIEW → APPLY）：`セクター/銘柄`（Notion と同じ）または `ティッカー` のレイアウトで作成・移動。各銘柄フォルダに `reports/` と `.coverage.json`（目印）。
- 銘柄ごと：**XLS**（ターミナル内で表示・編集）、**Excel**（紐付いたファイルを Excel で開く。無ければ `<ticker>_<社名>_model.xlsx` を作成）、**📁**（フォルダを開く）、**N**（Notion の個社ページ）、**REPORT**（ルールベースのファンダメンタル・レポート → `reports/YYYY-MM-DD_<ticker>_ファンダメンタル.md`、任意で Notion の個社ページの子ページ「ターミナル・レポート YYYY-MM-DD」）。
- AUTO 三位一体のユニバースに Notion のカバレッジを使う（`trinity_config.sources` に `coverage`）。XRAY・AUTO のセクター ETF は銘柄マスタの旧セクター（TOPIX17）から正確に対応、PFND のグループは GICS 産業サブグループ。

## 四半期ラベル（ATLAS の既存ページで確認した規則）
- **FY ラベル = 会計年度の開始年 + 1**。3月決算：2026年4月〜2027年3月 = FY2027。12月決算：2025年1〜12月 = FY2026（SUMCO の `FY2026 4Q ■` は 2026-02-17 の決算）。1月決算：2026年2月〜2027年1月 = FY2027。
- 決算発表日の 7 日以上前に終わった直近の四半期を「報告される四半期」とする。四半期末が今日より前なら ` ■`。

## 初回設定（Windows）
1. https://www.notion.so/my-integrations で内部インテグレーションを作成し、トークンを `.env` の `NOTION_TOKEN` に書く（**秘密情報。コミットしない**。`.env` は `.gitignore` 済み）。
2. Notion で「銘柄マスタ」データベースと「ATLAS / MICRO」ページを開き、… → コネクト → 作ったインテグレーションを追加。
3. `NOTION_COVERAGE_DB`（銘柄マスタのデータベース ID）と `NOTION_MICRO_PAGE`（MICRO ページ ID）を `.env` か COV の SETTINGS に設定。
4. COV → SYNC FROM NOTION → 決算日を更新 → フォルダ（PREVIEW → APPLY）。

## OneDrive に移すとき
- フォルダ一式を OneDrive に移動し、COV の SETTINGS のルート（または `.env` の `COVERAGE_DIR`）を新しい場所に変えるだけ。保存しているのはルートからの相対パスと `.coverage.json` なので、リンクは切れない。
- フォルダ名は Windows / OneDrive で使えない文字（`\ / : * ? " < > |`）を `_` に置換。セクター・フォルダは `GICS4530_…` のように接頭辞を付け、4桁コードが同じティッカー（例 4530 = 久光製薬）に誤って紐付かないようにしている。
- OneDrive の「オンラインのみ」のファイルは、開くときにダウンロードされる。Excel で開いている間は XLS からの書き込みは xlwings 経由になる（EXCEL.md）。

## API
`GET /api/coverage`、`PUT /api/coverage/config`、`POST /api/coverage/sync`、`POST /api/coverage/earnings/refresh`、`PUT /api/coverage/{ticker}/earnings`、`GET /api/coverage/calendar`、`POST /api/coverage/notion/earnings {apply, create_pages, update_master, add_properties, days_ahead, tickers}`、`POST /api/coverage/folders {apply, layout, tickers}`、`POST /api/coverage/{ticker}/excel`、`POST /api/coverage/{ticker}/open_folder`、`POST /api/coverage/{ticker}/report {save, to_notion}`。
