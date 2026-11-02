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

## アラートと保存

| Method | Path | 説明 |
|---|---|---|
| GET/POST | /api/alerts | 条件は above, below, cross_up, cross_down, change_pct_above, change_pct_below |
| PATCH/DELETE | /api/alerts/{id} | 有効・無効の切替、値やメモの変更、削除 |
| GET/PUT | /api/store/{key} `{"value":...}` | キーは watchlists, portfolio, notes, layout, settings, excel_links, harness_models |

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
