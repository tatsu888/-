# COVERAGE — Notion の銘柄マスタと連動するカバレッジ（COV）

Notion から読むのは銘柄リストだけ。決算日と四半期はターミナルの決算カレンダーが正本（[EARNINGS.md](EARNINGS.md)）。

## できること
- **SYNC FROM NOTION**：`ATLAS / MICRO / 銘柄マスタ`（Ticker・社名・GICS 産業グループ／サブグループ・旧セクター（TOPIX17）・決算期末月）を読み込み、`ATLAS / MICRO / <GICS> / <ticker> | <社名>` の個社ページを探して紐付ける。
- **決算日を更新**：ターミナルの決算カレンダー（**正本。Notion ではない**）を機械的に埋める：手入力 > JPX 決算発表予定日一覧（確定）> TradingView（予定・発表済）> 推定（前年同期 + 364 日、四半期末 + 通常の日数）。次回決算の列に状態のバッジ（確定／予定／推定／手入力）と出所。詳細は [EARNINGS.md](EARNINGS.md)。
- **JPX 取り込み**：JPX の決算発表予定日一覧（xlsx）を手動でアップロード（ダウンロードが使えないとき）。**決算ログ**：機械的な更新・手入力・Notion との不一致の記録。
- **四半期ページは個社ごと**に STK（個別銘柄ページ）の「四半期」で管理：決算日の固定・メモ・チェックリスト・四半期フォルダ（`<銘柄フォルダ>/quarters/FY2027_2Q/`）。
- Notion への決算の書き出し（銘柄マスタの「次回決算日」「次回決算期」、個社ページの下の四半期ページ）は**任意・非推奨**（SETTINGS → 「任意: Notion へ書き出す」、PREVIEW → APPLY）。書き出す値は決算カレンダーのもの。
- **フォルダ**（PREVIEW → APPLY）：`セクター/銘柄`（Notion と同じ）または `ティッカー` のレイアウトで作成・移動。各銘柄フォルダに `reports/` と `.coverage.json`（目印）。
- 銘柄ごと：**XLS**（ターミナル内で表示・編集）、**Excel**（紐付いたファイルを Excel で開く。無ければ `<ticker>_<社名>_model.xlsx` を作成）、**📁**（フォルダを開く）、**N**（Notion の個社ページ）、**REPORT**（ルールベースのファンダメンタル・レポート → `reports/YYYY-MM-DD_<ticker>_ファンダメンタル.md`、任意で Notion の個社ページの子ページ「ターミナル・レポート YYYY-MM-DD」）。
- AUTO 三位一体のユニバースに Notion のカバレッジを使う（`trinity_config.sources` に `coverage`）。XRAY・AUTO のセクター ETF は銘柄マスタの旧セクター（TOPIX17）から正確に対応、PFND のグループは GICS 産業サブグループ。

## 四半期ラベル（[EARNINGS.md](EARNINGS.md)）
- 既定は**標準の決算期の呼び方**（FY = 決算期が終わる年）：2027年3月期 = FY2027、2026年12月期 = FY2026。
- Notion の ATLAS ページの付け方（FY = 開始年 + 1。12月決算だけ 1 年ずれる：SUMCO の Notion の `FY2026 4Q ■` は標準では FY2025 4Q）は、`PUT /api/earnings/config {"convention": "start_plus_1"}` で選べる。
- 決算発表日の 7 日以上前に終わった直近の四半期を「報告される四半期」とする（JPX の種別があればそれに合わせる）。Notion に書き出すときは、終わった期に ` ■` を付ける。

## 初回設定（Windows）
1. https://www.notion.so/my-integrations で内部インテグレーションを作成し、トークンを `.env` の `NOTION_TOKEN` に書く（**秘密情報。コミットしない**。`.env` は `.gitignore` 済み）。
2. Notion で「銘柄マスタ」データベースと「ATLAS / MICRO」ページを開き、… → コネクト → 作ったインテグレーションを追加。
3. `NOTION_COVERAGE_DB`（銘柄マスタのデータベース ID）と `NOTION_MICRO_PAGE`（MICRO ページ ID）を `.env` か COV の SETTINGS に設定。
4. COV → SYNC FROM NOTION → 決算日を更新（JPX のダウンロードが失敗したら「JPX 取り込み」）→ フォルダ（PREVIEW → APPLY）。以後、決算日は AUTO が 1 日 1 回更新する。

## フォルダの中身
```
<ルート>\
├─ _terminal\earnings\calendar.json        決算カレンダー（決算日・四半期のメモ・チェックリスト・ログ）
└─ GICS4530_半導体・半導体製造装置\6857_アドバンテスト\
   ├─ 6857_アドバンテスト_model.xlsx         Excel（COV の Excel で作成）
   ├─ reports\                              REPORT の保存先
   ├─ quarters\FY2027_2Q\notes.md           四半期フォルダ（STK の「📁 四半期フォルダ」。メモと双方向に同期）
   └─ .coverage.json                         ティッカーの目印
```
既定のルートは `<最初の Excel フォルダ>\Coverage`（`TERMINAL_EXCEL_DIRS` を設定していなければ `<リポジトリ>\data\workbooks\Coverage`）。COV の上部に表示。

## OneDrive に移すとき
- **COV → SETTINGS →「ルートごと移す」**：移動先（例 `C:\Users\<you>\OneDrive\Coverage`）を入れて PREVIEW（ファイル数・容量・衝突）→ APPLY。
  - **コピー → 全ファイルのサイズを確認 → ルートを切り替え**。元のフォルダは消さない（確認してから手で削除。削除するまで XLS に同じファイルが見えることがある）。
  - 決算カレンダー（`_terminal`）も一緒に移る。手で紐付けた Excel のリンクも新しい場所に付け替える。
  - Office のロック・ファイル（`~$…`）はコピーしない。移動先に内容の違う同名ファイルがあれば中止（409）。コピーできないファイル（Excel で開いている等）があればルートは切り替えず、閉じて再実行すればコピー済みのものは飛ばす。
- 手で移す場合は、フォルダ一式（`_terminal` を含む）を移してから SETTINGS のルート（または `.env` の `COVERAGE_DIR`）を変える。保存しているのはルートからの相対パスと `.coverage.json` なので、リンクは切れない。
- フォルダ名は Windows / OneDrive で使えない文字（`\ / : * ? " < > |`）を `_` に置換。セクター・フォルダは `GICS4530_…` のように接頭辞を付け、4桁コードが同じティッカー（例 4530 = 久光製薬）に誤って紐付かないようにしている。
- OneDrive の「オンラインのみ」のファイルは、開くときにダウンロードされる。Excel で開いている間は XLS からの書き込みは xlwings 経由になる（EXCEL.md）。
- 2 台の PC で同時に使うと、`calendar.json` が OneDrive で競合することがある（1 台ずつ使う）。

## API
決算カレンダーは `/api/earnings/*`（[EARNINGS.md](EARNINGS.md)）。COV：`GET /api/coverage`、`PUT /api/coverage/config`、`POST /api/coverage/sync`、`POST /api/coverage/earnings/refresh`、`PUT /api/coverage/{ticker}/earnings`、`GET /api/coverage/calendar`、`POST /api/coverage/notion/earnings {apply, create_pages, update_master, add_properties, days_ahead, tickers}`、`POST /api/coverage/folders {apply, layout, tickers}`、`POST /api/coverage/move_root {to, apply}`、`POST /api/coverage/{ticker}/excel`、`POST /api/coverage/{ticker}/open_folder`、`POST /api/coverage/{ticker}/report {save, to_notion}`。
