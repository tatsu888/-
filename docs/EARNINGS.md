# EARNINGS — 決算カレンダーと四半期ページ（正本はターミナル。Notion ではない）

## 方針
- Notion の決算ページ（四半期ページの FY の付け方、決算期末月など）は**誤っている可能性がある**ため、決算日と四半期はターミナルの独立したシステム（`data/earnings/calendar.json`）で管理する。Notion から読むのは銘柄リスト（ティッカー・社名・GICS・決算期末月の初期値）だけ。
- 次回決算日は**機械的に埋める**。人が固定した日付は、機械が上書きしない。
- 候補はすべて出所と取得時刻つきで残し、変更はすべてログに記録する（COV →「決算ログ」）。

## 機械的に埋める順序（`earnings.resolve`）

| 優先 | 状態 | 出所 | 内容 |
|---|---|---|---|
| 1 | 手入力 | STK の四半期ページで固定 | 機械は上書きしない。「固定を解除」で自動に戻る |
| 2 | 確定 | JPX 決算発表予定日一覧（xlsx） | 公式。COV「決算日を更新」でダウンロード、または「JPX 取り込み」で手動。日付が過ぎたら「発表済」 |
| 2 | 発表済 | TradingView の前回決算日（`earnings_release_date`） | 実際に発表した日。報告した四半期に付く。同じ順位では新しい取得、同じ取得なら JPX を優先 |
| 3 | 予定 | TradingView の次回決算日（`earnings_release_next_date`） | 会社が公表した予定（TradingView 経由） |
| 4 | 推定 | 前年同期の発表日 + 364 日 | 同じ曜日になる |
| 5 | 推定 | 四半期末 + その会社の通常の日数 | 過去の実績の中央値（2 件以上ある場合）。無ければ 40 日（本決算は 45 日）。土日は翌月曜 |

- 「今回の取得で見つかった候補」だけを使い、古い候補は履歴として残す。TradingView を参照しない更新（JPX 取り込みの直後など）では、TradingView の最後の値を使い続ける（「予定」が「推定」にぶれない）。
- 状態：`未到来`（期が始まっていない）、`期中`、`決算待ち`（期は終わったが未発表）、`発表済`。

## どの四半期の決算か（`quarter_for_release`）
- 発表日の 7 日以上前に終わった直近の四半期末を「報告される四半期」とする（120 日を超えるものは対応させない）。
- JPX の「種別」（第１四半期・第２四半期・第３四半期・本決算）があれば、その四半期に合わせる。

## 決算期末月
- 優先順位：**手入力 > JPX（「決算期末」列）> Notion 銘柄マスタ**。
- JPX と Notion が違うときは JPX を使い、ログに「決算期末月（Notion と不一致）」を記録する。COV の「決算月」の列に `≠N` を表示（マウスを乗せると出所）。
- 決算期末月や FY の表記が変わったときは、四半期ページを**期間で付け替える**（メモ・チェックリスト・固定した日付は残る）。四半期末が合わなくなったページ（例：3月 → 2月）は `archive` に退避し、削除しない。

## FY の表記（`config.convention`）
- 既定 `end`（**標準の決算期の呼び方**）：決算期が終わる年。2026年12月期 = FY2026（2026年1〜12月）、2027年3月期 = FY2027（2026年4月〜2027年3月）。
- 任意 `start_plus_1`（Notion の ATLAS ページの付け方）：開始年 + 1。違いが出るのは 12月決算だけ（2026年12月期が FY2027 になる。SUMCO の Notion の `FY2026 4Q ■`（2026-02-17 発表）は、標準の表記では FY2025 4Q＝2025年12月期 本決算）。
- 画面の表示：`FY2027 2Q` と `2027年3月期 第2四半期`。切替は `PUT /api/earnings/config {"convention": "end" | "start_plus_1"}`。

## 四半期ページ（個社ごと）
- **STK（個別銘柄ページ）の「四半期」**：過去 8 四半期・今期・先 4 四半期を自動で作る（古いページも残る）。
- 各四半期：FY・期間・状態・決算発表日（状態のバッジと出所）・候補の一覧・メモ・チェックリスト
  - 決算前：会社計画・コンセンサスの確認／注目点（数量・ASP・マージン）／前回からの変化点
  - 決算後：結果 vs 予想（サプライズ）／ガイダンスの変化／株価の反応（翌日）／評点表（SCORE）を更新
- 「📁 四半期フォルダ」：`<銘柄フォルダ>/quarters/FY2027_2Q/`（`notes.md` を作成）。短信・説明資料・メモを置く。銘柄フォルダは COV のレイアウト（セクター別／ティッカー別）に従い、OneDrive に移しても動く。
- 決算期末月の修正も STK から（「決算期末月を修正」＝手入力）。

## 自動更新
- AUTO 三位一体の実行時に **1 日 1 回**（`config.auto` が true のとき）決算カレンダーを更新する（JPX のダウンロード → TradingView → 推定）。変化があれば websocket の `earnings` で通知。
- AUTO の「決算までの日数」もこのカレンダーを優先する（無い銘柄は TradingView）。
- 手動：COV の「決算日を更新」、または `POST /api/earnings/refresh`。

## JPX のファイル
- 一覧ページ（`config.jpx_index`、既定 `https://www.jpx.co.jp/listing/event-schedules/financial-announcement/index.html`）から xlsx のリンクをすべてたどって読む。見出し行は文字で探す（「決算発表予定日」「コード」「会社名」「決算期末」「種別」など）ので、列の順や表題の行が変わっても読める。英字を含むコード（例 `456A`）にも対応。
- **このクラウド環境では JPX への通信が拒否されたため、ダウンロードは未検証**。失敗しても前回分を使い続け（エラーは更新結果に表示）、COV の「JPX 取り込み」で手動アップロードできる。
- 手動取り込みでは、同じ会社の 75 日以内の古い記録を新しいファイルの記録で置き換える（会社が発表日を変更した場合）。ダウンロードは全件を置き換える。

## データ（`data/earnings/calendar.json`）
- `config`：convention、jpx_index、auto、last_refresh
- `companies`：ticker → fye_month、fye_source、name
- `quarters`：ticker → qid（`FY2027-2Q`）→ fy、q、period_start、period_end、label、label_ja、earnings（date・status・source）、candidates、notes、checklist、state
- `jpx`：records、fetched、files、source（download / upload）
- `log`（最新 1000 件）、`archive`（付け替えできなかったページ）

## API（`/api/earnings`）

| Method | Path | 説明 |
|---|---|---|
| POST | /refresh `{jpx, tradingview, tickers}` | 機械的に埋める（カバレッジ全体、または指定銘柄） |
| POST | /jpx/import（multipart `file`） | JPX の xlsx を手動で取り込み、続けて更新 |
| GET | /calendar?days | 今後の決算（-3 日〜days 日、発表済を除く） |
| GET | /log?limit | 変更・手入力・不一致の記録（新しい順） |
| GET / PUT | /config | convention、jpx_index、auto |
| GET | /{ticker} | 会社と四半期ページの一覧、次回・前回 |
| PUT | /{ticker}/fye `{month}` | 決算期末月を手入力（ページは付け替え） |
| PUT | /{ticker}/{qid} `{earnings_date, notes, checklist}` | 日付の固定（`""` で解除）、メモ、チェックリスト |
| POST | /{ticker}/{qid}/folder | 四半期フォルダを作成して開く |

COV 側の互換：`POST /api/coverage/earnings/refresh`（= /refresh）、`PUT /api/coverage/{ticker}/earnings {next}`（日付から四半期を求めて固定）、`GET /api/coverage/calendar`（= /calendar）。

## Notion について
- Notion への書き出し（銘柄マスタの「次回決算日」「次回決算期」、個社ページの下の四半期ページ）は**任意・非推奨**。COV の SETTINGS →「任意: Notion へ書き出す」から PREVIEW → APPLY。書き出す値はこのカレンダーのもので、Notion を正本にはしない。
