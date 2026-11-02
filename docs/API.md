# API リファレンス

ベース URL は `http://localhost:8000` です。OpenAPI の自動ドキュメントは `/docs` にあります。
`source=` パラメータ（tradingview | yahoo | sim）を付けると、そのリクエストだけデータ取得元を変えられます（省略時はアクティブなソース）。

## データ形式

```jsonc
// Quote
{"symbol":"NASDAQ:AAPL","name":"Apple","exchange":"NASDAQ","currency":"USD","type":"stock",
 "last":230.8,"change":0.8,"change_pct":0.36,"open":230.2,"high":231.1,"low":229.9,"prev_close":230.0,
 "volume":4.6e6,"bid":230.78,"ask":230.87,"market_cap":null,"pe":null,"eps":null,"div_yield":null,
 "time":1793550463,"delay_sec":900,"source":"tradingview","error":null}
// Bar
{"time":1793491200,"open":227.3,"high":231.8,"low":226.3,"close":230.9,"volume":8482465}
```

`delay_sec` の意味：0 はリアルタイム、900 は 15 分遅延、null は不明です。`source` が `sim` のときは疑似データです。

## メタ情報・データソース

| Method | Path | 説明 |
|---|---|---|
| GET | /api/health | アクティブな provider の状態 |
| GET | /api/providers | 全 provider の一覧と状態 |
| POST | /api/providers/active `{"name":"yahoo"}` | 手動で切り替え（store.settings に保存） |
| GET | /api/universe | 銘柄リスト、テープ、時間足、戦略、アラート条件、ファクターセット、テーマ |

## 市場データ

| Method | Path | 説明 |
|---|---|---|
| GET | /api/quotes?symbols=A,B | 最新値（スナップショット） |
| GET | /api/history?symbol&interval=1D&bars=300 | OHLCV |
| GET | /api/history.csv?... | CSV ダウンロード |
| GET | /api/search?q=toyota | 銘柄検索 |
| GET | /api/screener?market=america&preset=most_active\|gainers\|losers\|largest&limit | スクリーナー |
| GET | /api/fundamentals?symbol | スキャナーの項目と、日足から計算したパフォーマンス |
| GET | /api/news?symbol= | ニュース（TradingView、失敗時は Yahoo RSS） |
| GET | /api/calendar?countries=US,JP&days_back&days_ahead | 経済指標カレンダー |

時間足の値は `1,5,15,30,60,240,1D,1W,1M` です（`1h`、`4h`、`d`、`w` などの別名も使えます）。

## 分析（/api/analytics）

| Method | Path | 説明 |
|---|---|---|
| GET | /technicals?symbol&interval | MA とオシレーターの投票による判定 |
| GET | /correlation?symbols&interval&bars | 対数リターンの相関行列とボラティリティ |
| GET | /performance?symbols | 1D〜1Y、YTD、ボラティリティ、52 週高値・安値 |
| POST | /backtest `{symbol, interval, bars, strategy, params, allow_short, fee_bps}` | 戦略は sma_cross, ema_cross, rsi_reversion, breakout, buy_hold |
| GET | /factors/etf?set=US\|JP\|SECTORS_US&bars | ベンチマーク対比の超過リターンと RS カーブ |
| GET | /factors/cross_section?market=america&limit=500&min_mcap&quantiles | 上位と下位の差、IC、セクター（TradingView のスキャナーが必要） |
| GET | /leadlag/themes | テーマのプリセット一覧 |
| GET | /leadlag/theme/{id}?residualize&max_lag&bars | テーマのスキャン |
| GET | /leadlag/scan?leader&followers=A,B&market&max_lag | 任意の組み合わせでのスキャン |
| GET | /leadlag/pair?leader&follower&market&max_lag&window | CCF、グレンジャー（両方向）、ローリング相関 |

### クオンツ系（/api/analytics）

| Method | Path | 説明 |
|---|---|---|
| GET | /beta?symbol&benchmark=SP:SPX&interval=1D&bars=500 | 回帰ベータ |
| GET | /spread?a&b&window=60&entry_z=2 | ペアスプレッドと共和分検定（series.spread, z, ratio を含む） |
| GET | /seasonality?symbol | 年 × 月のリターン表と月別統計 |
| POST | /event_study `{symbol, benchmark, events:["YYYY-MM-DD"], pre, post, est_window}` | 日付が空なら大きな値動きの日を自動検出 |
| POST | /portfolio_risk `{positions:[{symbol, qty}], benchmark, lookback, base_currency}` | VaR・ES、ボラティリティ、ベータ、リスク寄与度、ストレステスト、為替換算 |
| GET | /relative_value?symbol&peers=A,B | 同業他社のスクリーナー項目、パフォーマンス、中央値、パーセンタイル |
| GET | /earnings?symbols=A,B | 次回・前回の決算日と予想（SIM では無効） |
| POST | /pair_backtest `{a, b, hedge_window, z_window, entry_z, exit_z, stop_z, ...}` | ペアトレードのバックテスト（ローリング・ヘッジ比率） |
| GET | /blotter | 約定記録（store.trades）から平均取得単価・実現損益・ポジション |
| GET | /fourier?symbol&interval&k&horizon&bars&detrend | ピリオドグラム、調和回帰予測、ナイーブ比のローリング・バックテスト |

## マクロ（/api/macro）

| Method | Path | 説明 |
|---|---|---|
| GET/PUT/DELETE | /map | 認識伝播マップの定義（DELETE で既定に戻す） |
| GET | /propagation?bars&z_window&gap&max_lag&source | 資産クラス × 段のシグナル、段の合成、段間ラグ、未波及、先行指標 |
| GET | /dashboard?bars&source | 金利・カーブ・クレジット・ボラ・コモディティ、景気局面（成長×インフレ）、成長×流動性 |
| GET | /growth_liquidity?bars&horizon=63&z_window=756&source | 成長×流動性 4 象限（現在地、軌跡、回転、次の象限、象限別の翌月リターン） |

## リサーチ（/api）

| Method | Path | 説明 |
|---|---|---|
| POST | /margin/import (multipart: file, date?) | JPX 信用残ファイル（CSV / XLSX）の取り込み |
| POST | /margin/import_url `{url, date?}` | URL から取り込み（https のみ） |
| GET | /margin/dates, /margin/ranking?date&min_long, /margin/stock?symbol | 取り込み済みの日付、ランキング、銘柄の推移と株価との関係 |
| GET | /trends/google?keywords=a,b&geo=JP&timeframe&symbol | Google Trends（非公式）、急騰、関連クエリ、株価との先行性 |
| GET | /social/x?query&lang | X API v2（要 `X_BEARER_TOKEN`） |
| GET | /social/stocktwits?symbol | StockTwits（symbol なしならトレンド） |
| GET/POST | /transcripts/{symbol} `{period, date?, title?, text}` | 書き起こしの一覧・保存（同じ期は上書き） |
| DELETE | /transcripts/{symbol}/{id} | 削除 |
| GET | /transcripts/{symbol}/analyze?id | トーン、前期との差分、Q&A 回避度、数字、期ごとの変化スコアの履歴 |
| POST | /transcript_text/analyze `{text, prev?}` | 保存せずに分析 |
| GET | /transcripts/{symbol}/brief_pack?id | 出典番号つき SOURCE と規則を含む AI 用プロンプト |
| POST | /transcripts/{symbol}/validate_brief `{brief, id?}` | AI の回答の出典・数字を検証 |

## ファクター・個別銘柄・資金フロー（/api）

| Method | Path | 説明 |
|---|---|---|
| POST | /factors/build | スタイル・ファクターをいま再計算（通常は AUTO 実行時） |
| GET | /factors/library?end_offset | スタイル・マクロ・セクター・ファクターの成績（1D〜6M、z） |
| GET | /factors/attribution/{symbol}?window&est&end_offset | 株価の要因分解（寄与、個社要因、判定、累積系列） |
| GET | /stock/{symbol}/page | 個別銘柄ページ（信用残・需給・AUTO・評点・テーマ・書き起こし・ファイル・同業） |
| GET | /stock/{symbol}/report_file?name | 保存済みレポートの本文 |
| GET | /flows?lens=ASSET\|COUNTRY\|SECTOR_US\|SECTOR_JP\|STYLE_US\|STYLE_JP&window&end_offset | 資金フローの代理・設定解約・読み |
| POST | /flows/record | ETF の発行済口数を記録（AUTO 実行時にも記録） |

時点（as-of）のパラメータ：`end_offset`（営業日）を `/analytics/beta`・`/analytics/correlation`・`/insight/xray`・`/insight/xray/book`・`/insight/themes/{id}/analyze`（＋`lookback`）・`/insight/pairs/screen`（＋`lookback`）・`/framework/pair`（＋`sigma_window`・`corr_window`）・`/macro/growth_liquidity` に、`end_weeks`（週）と `n`（平滑化）を `/insight/rrg` に追加。

## カバレッジ（/api/coverage）— [COVERAGE.md](COVERAGE.md)

書き込み系（`/notion/earnings`、`/folders`）は `apply: false` で計画だけを返す（dry run）。

## 分析の拡張（/api/insight）

| Method | Path | 説明 |
|---|---|---|
| GET | /xray?symbol&lookback&sector_etf&source | リターン分解（shares, coefficients, verdict） |
| POST | /xray/book `{positions?, lookback, source}` | ブックの因子露出・分散寄与・警告（positions 省略時は RULE のブック） |
| GET | /rrg?universe=JP17\|US11\|COVER\|CUSTOM&symbols&bench&tail&source | 相対回転グラフ |
| GET/POST | /themes | テーマ一覧・保存（id があれば更新） |
| POST | /themes/from_template `{name}` | Notion のテーマをテンプレートから作成 |
| DELETE | /themes/{id} | 削除 |
| GET | /themes/{id}/analyze?source | フェーズ、スプレッド、ドライバー、バスケット買い、構成銘柄 |
| POST | /pairs/screen `{groups?, by, max_per_group, source}` | ペア候補（groups 省略時は AUTO のユニバースを業種別に） |
| GET | /track?a0&b0 | 往復取引・ベイズ勝率・ケリー・期間別勝率 |

## AUTO 三位一体（/api/trinity）

| Method | Path | 説明 |
|---|---|---|
| GET | /latest | 最新のスナップショット、実行状態（最終・次回・エラー）、設定 |
| POST | /run?source | 今すぐ実行（実行中なら 409） |
| GET/PUT | /config `{enabled, interval_min, extra, exclude, max_symbols, sources}` | 対象ユニバースと間隔 |
| GET | /history/{symbol}?days | 日次の判定の推移 |
| GET | /changes?limit | 判定・象限の変化のログ |

WebSocket：判定が変わると `{"type":"trinity","changes":[...],"at":...}` を配信。

## 投資の三位一体（/api/framework）— [FRAMEWORK.md](FRAMEWORK.md)

| Method | Path | 説明 |
|---|---|---|
| GET | /meta | 評点表の項目、閾値、上限、ショートの型、関門、裁定ルール、ペア適性表 |
| POST | /score/evaluate `{rows, moat, reason, text}` | 評点表の評価（保存しない） |
| GET | /scorecards | 保存済み評点表の最新版の一覧 |
| GET/POST/DELETE | /scorecards/{symbol} | 版の履歴・保存（Previous Score は前版から自動）・削除 |
| POST | /score_gap `{long_score, short_score, cap}` | 評点差 → サイズ |
| GET | /pairs_from_scores | サブセクターごとの最高×最低のペア候補 |
| POST | /kelly `{pw, xw, xl, side, ruin_prob, fraction, cap_pct}` | 期待値・ケリー・成長曲線・六つの原則 |
| GET/PUT | /book | 六層チェック用のブック（positions, level, nav, drawdown_pct） |
| POST | /book/from_portfolio `{nav, base_currency}` | PORT のポジションから重み・セクター・時価総額・βを作る |
| POST | /exposure `{positions, level, drawdown_pct, compute_pairs}` | L1〜L6 と DD ルールのチェック、ペアの Pair Sigma など |
| POST | /pair `{long, short, w_long, w_short, bench?, earnings_dirs?, borrow_ok?, spread_class?}` | Pair Sigma、相関分布、β、固有分散、20日スプレッド、ペア適性 |
| POST | /short_models `{symbol?, inputs}` | 空売り8モデル（symbol があれば一部を自動取得） |
| GET | /top_bottom/{symbol}?scope&shares&holding_value&inst_ownership_pct | 天井／底シグナル、回転率、信用残、混雑度 |
| GET/POST | /ideas, DELETE /ideas/{id}, POST /ideas/monthly_reset, GET /ideas/archive/{month} | 関門チェックリストのアイデア管理と毎月リセット |
| POST | /gates `{"macro:0":"yes", ...}` | 関門の通過状況 |
| GET | /overview/{symbol} | ファンダ（評点表）× マクロ（4 象限）× 需給（天井/底）の一覧 |

## アラートと保存

| Method | Path | 説明 |
|---|---|---|
| GET/POST | /api/alerts | 条件は above, below, cross_up, cross_down, change_pct_above, change_pct_below |
| PATCH/DELETE | /api/alerts/{id} | 有効・無効の切替、値やメモの変更、削除 |
| GET/PUT | /api/store/{key} `{"value":...}` | キーは watchlists, portfolio, notes, layout, settings, excel_links, harness_models, workspaces, harness_versions, macro_map, screens, trades, scorecards, fw_book, fw_ideas, fw_ideas_archive, transcripts, themes, trinity_config |
| GET | /api/diagnose | 接続の自己診断（`python -m app.diagnose` と同じ） |
| GET | /api/screener/fields, POST /api/screener/custom | SCRN 用の項目一覧とカスタム条件のスキャン |

## Excel（/api/excel）

| Method | Path | 説明 |
|---|---|---|
| GET | /files | ライブラリ内のファイル一覧と書き込みモード |
| GET | /for_symbol?symbol | 紐付いたファイル（manual が先、auto が後） |
| POST | /link `{symbol, file_id, linked}` | 手動での紐付けと解除 |
| GET | /view?id | シート、セル（v, f, nf, s, calc）、スタイル、結合、列幅、行高、lossy_parts、write_mode（このファイルで実際に使える書き込み方式。off なら編集不可）、write_reason |
| POST | /whatif `{id, overrides:{"Sheet!B5": 1.2}}` | 変わったセル（changed）、ライブ値（live）、エンジン非対応のセル（stale）。ファイルは変更しない |
| POST | /open `{id}` | サーバー機で Excel を起動（ローカル利用時のみ有効） |
| POST | /write `{id, sheet, updates:{"B5":"5%","C7":"=C6/B6-1"}}` | セルの編集（値または数式）。返り値は `mode`（xlwings／openpyxl）、`before`（UNDO 用の変更前の内容）、`view`（更新後の表示） |
| POST | /upload (multipart) | data/workbooks/uploads へ保存 |
| GET | /download?id | ファイルのダウンロード |
| POST | /format, /structure, /fill | 書式の変更、行・列の挿入／削除（Excel 経由のみ）、数式のフィル（相対参照） |
| GET | /trace?id&sheet&cell | 参照元・参照先 |
| GET | /backups?id, /diff?id&backup, POST /restore | 書き込み前のスナップショット一覧、差分、復元 |
| GET | /live?id | Excel で開いている未保存の値（xlwings） |
| POST | /new | 新しいシート・ブックの作成 |

## ハーネス（/api/harness）

| Method | Path | 説明 |
|---|---|---|
| GET | /catalog | MECE カタログ |
| GET | /models | 保存済みモデルとサンプルの一覧 |
| GET/PUT | /models/{name}[?example=true] | spec の取得と保存 |
| POST | /run[?uncertainty=false] | spec を実行し、全結果を返す |
| POST | /regression `{y, drivers, future?, transform}` | OLS の結果、またはドライバー回帰による予測 |
| POST | /timeseries `{values, horizon, period}` | 各種の時系列予測と、ローリング検証による手法比較 |
| POST | /export.xlsx | 結果を xlsx で出力（Projection、Checks、Meta の各シート） |
| GET | /schema, /templates, /templates/{name} | spec の JSON Schema、業種テンプレート |
| GET | /models/{name}/versions[/{version}], /models/{name}/diff | 版の履歴と差分 |
| POST | /brief, /apply_changes | AI 用ブリーフの生成、AI が提案した変更の検証と適用（過去実績の変更禁止・出典必須） |
| GET | /for_symbol?symbol | 銘柄に紐づくモデル |

## WebSocket `/ws`

ブラウザ → サーバー：

```jsonc
{"op":"set_symbols","symbols":["NASDAQ:AAPL","FX:USDJPY"]}   // 購読の全置換（feed.ts が使う）
{"op":"subscribe","symbols":[...]} / {"op":"unsubscribe","symbols":[...]}
{"op":"subscribe_bars","symbol":"NASDAQ:AAPL","interval":"5"} / {"op":"unsubscribe_bars",...}
{"op":"ping","t":123}
```

サーバー → ブラウザ：

```jsonc
{"type":"hello", "provider":"tradingview", "status":"connected", ...}
{"type":"quotes","data":[Quote, ...]}                 // 250ms ごとにまとめて送る
{"type":"bar","symbol":"...","interval":"5","bar":Bar}
{"type":"alert","alert":{...}}                        // 全クライアントに送る
{"type":"provider", ...health}                        // データソースが切り替わった
{"type":"excel_changed","id":"0/7203_model.xlsx","mtime":...}
{"type":"error","message":"..."} / {"type":"pong","t":123}
```
