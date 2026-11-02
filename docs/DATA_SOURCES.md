# DATA SOURCES — データ取得元

## 利用規約について（必読）

TradingView と Yahoo Finance への接続は、どちらも**公開 API ではなく、ウェブサイトが内部で使っているエンドポイント**を利用しています。

- 仕様は予告なく変わります。壊れたら、ブラウザの DevTools → Network → WS／Fetch で実際の通信を確認して直してください。
- 各社の利用規約で、自動取得や再配布が制限されている場合があります。**個人の調査用途の範囲**にとどめ、業務で本格的に使う場合は正式なデータ契約を検討してください。Provider 層を差し替えるだけで移行できます。
- 未ログインの TradingView は、多くの取引所で遅延データ（`update_mode=delayed_streaming_900`、つまり 15 分遅延。画面では `D15`）です。

## 銘柄記号

TradingView 形式の `EXCHANGE:TICKER` に統一しています。

| 種別 | 例 |
|---|---|
| 米国株 | `NASDAQ:AAPL`, `NYSE:JPM`, `AMEX:SPY` |
| 日本株 | `TSE:7203`（コマンドで `7203` と入力すると自動で TSE と解釈） |
| 指数 | `SP:SPX`, `NASDAQ:NDX`, `DJ:DJI`, `TVC:NI225`, `TVC:VIX` |
| FX | `FX:USDJPY`（`USDJPY` と入力しても解釈） |
| 暗号資産 | `BINANCE:BTCUSDT`（`BTCUSDT` と入力しても解釈） |
| 先物・CFD | `TVC:USOIL`, `TVC:GOLD`, `COMEX:HG1!` |
| 金利 | `TVC:US10Y`, `TVC:JP10Y` |

Yahoo への変換は `backend/app/providers/yahoo.py` の `to_yahoo()` で行います。`TSE:7203` → `7203.T`、`FX:USDJPY` → `USDJPY=X`、`BINANCE:BTCUSDT` → `BTC-USD`、主要指数は対応表で変換します。US02Y、DE10Y、GB10Y、JP10Y は Yahoo に確実な記号がないため、対応していません。

### 未検証の記号（実データで要確認）

- ファクター ETF の取引所プレフィックス：`BATS:MTUM`, `BATS:VLUE`, `BATS:QUAL`, `BATS:USMV`, `AMEX:SPHB`, `AMEX:SPLV`, `AMEX:RSP` など。TradingView 上で別の取引所名になっている可能性があります。Yahoo では取引所名を無視するので影響しません。
- `TVC:TOPIX`, `TVC:KOSPI`, `TVC:CAC40`, `TVC:RUT`
- 日本の ETF：`TSE:1306`, `TSE:1321`, `TSE:1489`, `TSE:1591`, `TSE:2516`
- リード・ラグのテーマに使う銘柄（`NASDAQ:SOX`, `TSE:3350` など）
- スクリーナーの列名：決算カレンダー（`earnings_release_next_date`, `earnings_release_date`, `earnings_per_share_forecast_next_fq`, `earnings_per_share_fq`, `revenue_forecast_next_fq`）と、RV の `enterprise_value_ebitda_ttm`, `net_margin`。失敗した場合は、少ない列で再試行します（`api_analysis.py` の `EARN_*`, `RV_*`）

修正先は `universe.py`、`factors.py`、`leadlag.py` です。

## TradingView

### WebSocket（`providers/tradingview.py`, `tv_protocol.py`）

- URL は `wss://data.tradingview.com/socket.io/websocket?from=chart%2F&type=chart`、ヘッダーに `Origin: https://www.tradingview.com` が必要です。
- フレームは `~m~<len>~m~<payload>` 形式です。payload は `{"m": method, "p": [params]}` か、ハートビート `~h~N` です。ハートビートは、受け取った内容をそのまま同じ形式で送り返す必要があります。
- **クォートセッション**（常時接続）の流れ：
  1. `set_auth_token ["unauthorized_user_token" | <token>]`
  2. `quote_create_session [qs]`
  3. `quote_set_fields [qs, "lp","ch","chp","volume","bid","ask","open_price","high_price","low_price","prev_close_price","description","exchange","currency_code","type","market_cap_basic","price_earnings_ttm","earnings_per_share_basic_ttm","dividends_yield","lp_time","update_mode","short_name","pro_name"]`
  4. `quote_add_symbols [qs, sym...]`、`quote_remove_symbols`、`quote_fast_symbols`
  5. 受信する `qsd [qs, {"n": sym, "s": "ok"|"error", "v": {差分の項目}}]` を、銘柄ごとに `_quotes` へマージします。
- **チャートセッション**（足の取得とライブ更新）の流れ：
  1. `chart_create_session [cs, ""]`
  2. `resolve_symbol [cs, "sds_sym_1", "={\"symbol\":\"NASDAQ:AAPL\",\"adjustment\":\"splits\",\"session\":\"regular\"}"]`
  3. `create_series [cs, "sds_1", "s1", "sds_sym_1", "D", 300, ""]`（時間足は 1, 5, 15, 30, 60, 240, D, W, M）
  4. 受信：`timescale_update [cs, {"sds_1": {"s": [{"i":0,"v":[t,o,h,l,c,v]}, ...]}}]` → `series_completed`。以降の更新は `du`。
  5. エラー：`symbol_error`, `series_error`, `critical_error`, `protocol_error`
- 履歴の取得には、リクエストごとに短時間だけ使う接続を開きます。ライブの足は常時接続上のチャートセッションで受け取ります。
- 接続が切れた場合は、1 秒から最大 60 秒まで間隔を倍にしながら再接続し、購読とチャートセッションを作り直します。

### HTTP（`providers/tv_web.py`）

| 用途 | エンドポイント |
|---|---|
| 銘柄検索 | `GET https://symbol-search.tradingview.com/symbol_search/v3/?text=…`（Origin ヘッダーが必要。`<em>` タグを除去） |
| スクリーナー・ファンダメンタルズ・ユニバース | `POST https://scanner.tradingview.com/{market}/scan`。市場は america, japan, crypto, forex, cfd, futures など |
| ニュース | `GET https://news-headlines.tradingview.com/v2/headlines?client=web&lang=en&symbol=…` |
| 経済指標 | `GET https://economic-calendar.tradingview.com/events?from=ISO&to=ISO&countries=US,JP` |

スキャナーは、存在しない列を 1 つでも指定するとエラーになります。そのためファンダメンタルズの取得では、失敗したら最小限の列で再試行します。

### ログイン（リアルタイム化）

`TV_AUTH_TOKEN` に、ログイン済みセッションの auth token を設定すると、契約プランの範囲でリアルタイムになります。取得方法：ログインした状態の DevTools の WS タブで、`set_auth_token` の引数を確認します。**token は秘密情報です。コミットしたり、共有したりしないでください。**

## Yahoo Finance（`providers/yahoo.py`）

- チャート：`GET https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=5m&range=1mo`。4 時間足（240）は 60 分足から作ります。
- クォート：上記の `meta`（regularMarketPrice, chartPreviousClose, …）を `YAHOO_POLL_SEC` 秒ごとにポーリングします。
- 検索：`GET https://query1.finance.yahoo.com/v1/finance/search?q=`
- ニュース（予備）：`https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL`
- 遅延の有無は不明（`delay_sec=null`）として扱います。

## SIM（`providers/sim.py`）

- 銘柄ごとにシードを固定した幾何ランダムウォークで、`source="sim"` を付けます。UI には常に DEMO と表示し、ニュースと経済指標は無効です。
- 用途はオフラインでの開発、UI の確認、テストです。**分析結果に意味はありません。**

## ネットワーク環境のメモ

開発に使ったクラウドコンテナでは、外向き通信がポリシーで制限されていました（パッケージレジストリのみ許可）。TradingView と Yahoo のホストを許可する場合は、環境設定の Network access で、次のドメインを Allowed domains に追加します（https://code.claude.com/docs/en/cloud-environments#network-access）。

`*.tradingview.com`（data, scanner, symbol-search, news-headlines, economic-calendar）、`query1.finance.yahoo.com`、`query2.finance.yahoo.com`、`feeds.finance.yahoo.com`
