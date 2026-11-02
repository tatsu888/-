# COMMANDS — ターミナル機能一覧

## 入力の文法

```
<SECURITY> <FUNCTION> [args] <GO>    AAPL GP · 7203 DES · NASDAQ:NVDA TA · USDJPY GP · 7203 JP Equity DES
<FUNCTION> [args] <GO>               WEI · MOST JP · LAG oil_energy · FACT JP · FACT xs
<SECURITY> <GO>                      読み込み中の銘柄を変更（固定されていないパネルが追随する）
```

- 銘柄の解釈：`EXCH:TICKER` はそのまま使います。4 桁の数字は `TSE:`、`USDJPY` のような通貨ペアは `FX:`、`BTCUSDT` は `BINANCE:` と解釈します。それ以外は検索 API の最初の候補を使います。
- 「Equity」「Index」「JP」「US」などのブルームバーグ式の補助語は無視します。
- キー操作：どこで入力してもコマンドラインに入ります。↑↓ で候補を選び、Tab で補完、Enter で実行（GO）、Esc で取り消し（CANCEL）です。
- パネル：クリックでフォーカスします（オレンジの枠）。コマンドはフォーカス中のパネルに表示されます。🔗 は読み込み中の銘柄に追随、📌 は固定です。ヘッダーのプルダウンでも機能を切り替えられます。
- 表の行：クリックで銘柄を読み込み、ダブルクリックでチャート（GP）を開きます。
- レイアウト：1 / 2 / 3 / 4 / 6 分割です。配置、銘柄、各機能の状態は localStorage に保存されます。

## 機能一覧

| コード | 名前 | 内容 |
|---|---|---|
| **GP** | チャート | 時間足 1m〜M、CANDLE / BAR / LINE / AREA / HA、LOG、VOL、SMA20/50/200、EMA20、BB、VWAP、RSI、MACD、描画（HLINE / TREND / FIB / CLEAR）、ALERT@（クリックした価格でアラート）、COMPARE（% 比較）、CSV |
| **DES** | 銘柄概要 | クォート、パフォーマンス（1D〜1Y、YTD、ボラティリティ、52 週レンジ）、ファンダメンタルズ（スキャナー）、紐付いた Excel |
| **TA** | テクニカル判定 | 1H, 4H, D, W のゲージと各指標の投票 |
| **N** | ニュース | 銘柄ニュースと TOP NEWS |
| **XLS** | Excel モデル | 紐付け、表示、**EDIT（HTML から編集し、Excel に保存）**、WHAT-IF（ファイルを変えずに試算）、UNDO、LIVE、Excel で開く、ダウンロード、アップロード。キー操作：矢印・Tab で移動、入力で上書き、Enter・F2 で編集、Delete で消去、Ctrl+Z で元に戻す、Esc で取り消し。[EXCEL.md](EXCEL.md) |
| **NOTE** | メモ | 銘柄ごとのメモ（自動保存） |
| **BT** | バックテスト | sma_cross, ema_cross, rsi_reversion, breakout, buy_hold、手数料、ロング／ショート |
| **W** | ウォッチリスト | 複数のリスト、追加と削除、並べ替え、点滅表示 |
| **WEI** | 世界株価指数 | 地域別 |
| **FX / RATES / CMDTY / CRYP** | 為替、金利、商品、暗号資産 | |
| **MOST** | スクリーナー | MOST_ACTIVE / GAINERS / LOSERS / LARGEST × 市場 |
| **HMAP** | ヒートマップ | 大きさは時価総額、色は騰落率 |
| **FACT** | ファクター分析 | ETF PROXY（US / JP / SECTORS_US）、CROSS-SECTION（市場別） |
| **LAG** | リード・ラグ | テーマのプリセットまたは任意指定、RESIDUAL、MAX LAG、行をクリックするとペアの詳細 |
| **CORR** | 相関行列 | 銘柄リスト、時間足、期間 |
| **MODEL** | 業績予想ハーネス | LOAD / RUN / SAVE / EXPORT XLSX、RESULT / SPEC / CATALOG。[FORECAST_HARNESS.md](FORECAST_HARNESS.md) |
| **PORT** | ポートフォリオ | ポジション、評価額、ウェイト、当日損益、含み損益 |
| **ALRT** | アラート | 条件 6 種、サーバー側で評価、トーストとデスクトップ通知 |
| **ECO** | 経済指標 | 国、重要度、実績と予想の比較 |
| **SRC** | データソース | TradingView / Yahoo / SIM の状態と切替 |
| **HELP** | ヘルプ | 機能一覧 |

分析系の画面には `SOURCE` 選択欄があり、その分析だけデータ取得元を変えられます（例：長期の日足は Yahoo で取る）。
