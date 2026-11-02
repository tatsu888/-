# HANDOFF — 引き継ぎ資料（最初に読む）

最終更新：2026-11-02（Claude Code / クラウドセッション）。決算・四半期の正本はターミナルの決算カレンダー（[`EARNINGS.md`](EARNINGS.md)）で、Notion ではない
次の担当者（ChatGPT など）は、このファイル → [`REQUIREMENTS.md`](REQUIREMENTS.md) → [`WORKLOG.md`](WORKLOG.md) の順に読んでください。

---

## 1. 目的

ヘッジファンドのアナリストが日常的に使う分析ツールを作ります。第 1 段階は、**TradingView の機能を模したプラットフォーム**を、**ブルームバーグターミナル風のデザイン・操作感**で作ることです。

- TradingView / Yahoo の数値をリアルタイムに近い形で取得し、データ取得元は**手動で切り替え**られるようにする
- 市場分析：どのファクターが効いているか、タイムラグ（原油→株、米国のテーマ→日本株）を調べる
- Excel 連携：銘柄を選んだら、その銘柄の Excel をフォルダから探さずに HTML 上で参照し、**HTML から編集もする**（ユーザーは Windows）。**Excel の機能は劣化させない**
- 業績予想ハーネス：AI のハルシネーションや、実行ごとに結果がぶれることを防ぐため、**会社に依存しない計算式と財務モデルを MECE に網羅した、決定的なエンジン**を用意する
- マクロ・マーケットタイミング：**資産クラス別の認識伝播**（ニッチ → マクロ投資家 → 日本の個別株投資家）を毎日見る（`PROP`）
- **ユーザーと会社（Pinpoint）のフレームワーク「投資の三位一体」（Notion）どおりに分析できること**（`TRIN` ほか）。中身と対応表は [`FRAMEWORK.md`](FRAMEWORK.md)

ユーザーの発言は [`REQUIREMENTS.md`](REQUIREMENTS.md) に時系列で記録しています。

## 2. 現状（何ができて、何が未検証か）

| 領域 | 状態 | 備考 |
|---|---|---|
| ブルームバーグ風 UI（コマンドライン、ファンクションキー、ティッカーテープ、マルチパネル、ステータスバー） | ✅ 実装・画面確認済み | SIM モードで Playwright のスクリーンショットを撮って確認 |
| データ取得元の手動切替（TradingView / Yahoo / SIM） | ✅ | ステータスバーまたは `SRC`。`POST /api/providers/active` |
| TradingView 接続（websocket のクォート・足、検索、スクリーナー、ニュース、経済指標、ファンダメンタルズ） | ⚠️ **実装済み・実データでは未検証** | 開発したクラウド環境では tradingview.com への通信がブロックされていた。下記 §6 を参照 |
| Yahoo 接続（チャート、検索、RSS ニュース） | ⚠️ **実装済み・実データでは未検証** | 同上 |
| チャート GP（足種 5 種、時間足 9 種、インジケーター 9 種、描画、比較、対数軸、CSV、アラート） | ✅ | lightweight-charts v5 |
| モニター（W / WEI / FX / RATES / CMDTY / CRYP）、MOST、HMAP | ✅ | MOST と HMAP は TradingView のスクリーナーに依存（SIM では簡易版） |
| DES / TA / N / ECO / NOTE / PORT / ALRT | ✅ | アラートはサーバー側で毎ティック評価し、websocket で通知 |
| ファクター分析 FACT（ETF プロキシ、クロスセクション、セクターローテーション） | ✅ ロジックはテスト済み | ETF の取引所プレフィックスの一部は未検証（§6） |
| リード・ラグ分析 LAG（ラグ相関、グレンジャー検定、ローリング相関、リーダースキャン、市場ベータ除去、テーマのプリセット 8 種） | ✅ ロジックはテスト済み | |
| 相関 CORR、バックテスト BT | ✅ | |
| クオンツ系：BETA、SPRD、SEAS、EVT、RV、OV、EARN、PORT の RISK（基準通貨への換算あり） | ✅ ロジックはテスト済み、SIM で画面確認済み | EARN と RV のスクリーナー列名は未検証 |
| ワークスペース（画面配置の保存）、コマンド履歴、XLS の範囲選択・コピー・貼り付け | ✅ | |
| Excel 連携 XLS（自動・手動の紐付け、劣化なしの表示、**HTML からの編集（EDIT）**、UNDO、Excel と同じキー操作、What-if、`=TV()`、Excel で開く、保存の検知と自動再読込） | ✅ | 編集は既定で有効（`auto`）。Windows では xlwings（Excel 本体）経由。**xlwings の実機（Windows + Excel）は未検証**で、制御の流れは偽のモジュールを使ったテストで確認済み。openpyxl 経由はブラウザでの操作まで確認済み |
| 業績予想ハーネス MODEL（A〜G の 7 層、明細行の作り方 18 種、3 表、DCF／倍率法／DDM／RIM、シナリオ、感応度、モンテカルロ、検証チェック、ハッシュ） | ✅ テスト済み | サンプルの JSON は架空の数値 |
| チャートの追加指標（一目・ストキャス・ATR・PNG）、指標アラート、ペアトレードのバックテスト、約定記録、TEAR、SCRN | ✅ | |
| CYCL（フーリエ）、MACRO（景気局面）、PROP（認識伝播マップ）、MRGN（信用残の取り込み） | ✅ ロジックはテスト済み、SIM で画面確認済み | マクロ系の記号の一部は未検証。MRGN は JPX のファイルを手で取り込む |
| **STK**（個別銘柄ページ：要因分解・信用残・需給・三位一体・決算・ファイル）、**FCTR**（Notion 04.4 のファクター計測）、**FLOW**（グローバル資金フロー）、全分析の**時間ウィンドウのスライダー** | ✅ テスト済み、SIM で画面確認済み | FLOW の ETF・発行済口数は未検証。スタイル・ファクターはカバレッジが 15 銘柄以上で計算 |
| **COV**（Notion の銘柄マスタ → カバレッジ、セクター／ティッカー別フォルダ（OneDrive 可）、銘柄ごとの Excel・レポート） | ✅ テスト済み（Notion API はモック）、SIM で画面確認済み | **実 Notion API は未検証**（トークン未設定）。Notion への決算の書き出しは任意・非推奨 |
| **決算カレンダーと四半期ページ**（Notion から独立した正本。JPX 確定 → TradingView → 出来高からの検出 → 推定で機械的に埋める、手入力の固定、決算期末月の検証、個社ごとの四半期ページ：メモ（notes.md と双方向同期）・チェックリスト・フォルダ、AUTO で 1 日 1 回更新、.ics 書き出し）[EARNINGS.md](EARNINGS.md) | ✅ テスト済み、SIM で画面確認済み | **JPX のダウンロードは未検証**（この環境では通信拒否）。手動の「JPX 取り込み」で代替可。TradingView の決算日の列も実データでは未検証 |
| **決算時の株価反応**（反応日・対市場・ドリフト・出来高、通常の値動き。日付が推定の期は出来高の急増から検出） | ✅ テスト済み（合成データ）、SIM で画面確認済み | 実データでの検出精度は未確認（しきい値 2 倍・±10 日）。検出は実データのときだけ保存 |
| **ECST 世界経済統計**（日本＋海外 514 系列：FRED・e-Stat・中国国家統計局・ONS・BoE・ECB・Eurostat・カナダ統計局・ブラジル中銀・世界銀行・市場。Bloomberg 風の番号メニューと主要指標マトリクス。自動更新、発表とサプライズ、国別の合成指数・統計版の成長×流動性・ヒートマップ、資金フロー、局面別リターンと先行性、ファイル取り込み）[ECON.md](ECON.md) | ✅ テスト済み（各提供元の応答の形の解析、取得はスタブ）、画面確認（スクラッチの試験データ） | **実データでの取得は未検証**（この環境は全データ源が 403）。**e-Stat は `ESTAT_APP_ID` が必要**。コードの一部は廃止・変更の可能性 → ユーザーの PC の初回の取得で SOURCES に出る |
| **BRIEF 朝のブリーフ**（市場・マクロ局面・セクター回転・スタイル・AUTO の前日からの変化・決算・ポートフォリオの決算リスク・信用残・データの状態。毎朝 AUTO が作成し .md で保存）[BRIEF.md](BRIEF.md) | ✅ テスト済み、SIM で画面確認済み | 実データでの見え方は未確認。既定の時刻 07:30 |
| **TOP 情報ハブ**（中銀・政府・規制当局・ニュースの RSS 17、EDINET・SEC EDGAR の開示、会社ごとの Google ニュース、カバレッジ・キーワードの当たりと通知。STK・BRIEF に欄。API キーの画面 → その PC の `.env`）[INFO.md](INFO.md) | ✅ テスト済み（各形式の解析・当たりの判定・巡回と通知・開示の結び付け・キーの保存）、SIM で画面確認 | **実データでの取得は未検証**（この環境は 403）。EDINET は `EDINET_API_KEY`、EDGAR は `SEC_USER_AGENT` が必要。日銀の RSS の URL は未確認 |
| **決算アラート・カレンダーのバックアップ・四半期フォルダの資料**（明日決算・大きな反応の通知、毎日のバックアップと復元、資料の一覧と書き起こしの取り込み） | ✅ テスト済み、SIM で画面確認済み（明日決算の通知を AUTO の実行で確認） | 大きな反応の通知は実データのみ |
| **OneDrive への移行**（COV の「ルートごと移す」：コピー → 確認 → 切り替え。決算カレンダーもルートの中） | ✅ テスト済み、SIM で画面確認済み | Windows + OneDrive の実機では未確認（開いている Excel はコピーできず、その場合は切り替えない） |
| **分析の拡張**：XRAY（リターン分解・意図しないベット）、RRG（セクター回転）、THEME（テーマ・バスケット）、PFND（ペア候補）、TRAK（ベイズ勝率） | ✅ テスト済み、SIM で画面確認済み | 業種 ETF の記号は未検証。テーマのテンプレートは業種 ETF による代用 |
| **AUTO 三位一体**（ルールベース・自動更新、TRIN の既定タブ） | ✅ テスト済み、SIM で自動実行を確認 | スキャナーが使えないと F のルール採点は N/A |
| **投資の三位一体**：TRIN / SCORE / KELLY / RULE / PAIR / SHRT / CHIP / GATE / GLQ | ✅ テスト済み（Notion の数字を再現）、SIM で画面確認済み | 評点表の Weight はプレースホルダー、成長×流動性は代理指標（[FRAMEWORK.md](FRAMEWORK.md) §7） |
| TXT（書き起こし：Lazy Prices 差分、トーン、Q&A 回避度、出典必須の AI ブリーフ検証） | ✅ | 外部通信なし |
| TRND（Google Trends、X、StockTwits） | ⚠️ 実装済み・実通信は未検証 | X は `X_BEARER_TOKEN`（有料）が必要 |
| 自己診断（`python -m app.diagnose`、SRC の RUN DIAGNOSTICS） | ✅ | 実ネットワーク環境で最初に実行する |
| テスト | ✅ backend 194 件、frontend 10 件、型チェック、ビルド | `scripts/test.sh` |

## 3. 起動方法

```bash
scripts/setup.sh
```

```bash
scripts/start.sh
```

ブラウザで http://localhost:8000 を開きます。

```bash
TERMINAL_PROVIDER=sim scripts/start.sh
```

こちらはオフラインで試す場合です。Windows では `scripts\setup.ps1` と `scripts\start.ps1` を使います。環境変数の一覧は [`CONFIG.md`](CONFIG.md) にあります。

## 4. ファイル構成（どこに何があるか）

```
backend/app/
  main.py            FastAPI のアプリ本体、websocket、静的配信、Excel 監視ループ
  state.py           シングルトン（provider registry, store, alerts, excel, hub, history cache）
  config.py          環境変数
  hub.py             購読の集約・配信（ブラウザ ↔ provider）。250ms 間隔でまとめて送る。アラート評価
  models.py          Quote / Bar の正規化した形
  intervals.py       時間足の正規化（1,5,15,30,60,240,1D,1W,1M）
  universe.py        WEI/FX/RATES/CMDTY/CRYP/W の銘柄リストとティッカーテープ
  api_market.py      /api/health, providers, quotes, history, search, screener, fundamentals, news, calendar, alerts, store
  api_analysis.py    /api/analytics/*（technicals, correlation, performance, backtest, factors/*, leadlag/*）
  api_excel.py       /api/excel/*
  api_harness.py     /api/harness/*
  api_macro.py       /api/macro/*（認識伝播マップ、ダッシュボード、成長×流動性）
  api_research.py    /api/margin/*, /api/trends/*, /api/social/*, /api/transcripts/*
  api_framework.py   /api/framework/*（投資の三位一体）
  api_trinity.py     /api/trinity/*（AUTO 三位一体の実行・スケジューラ・保存）
  trinity_auto.py    AUTO 三位一体のルール（純関数）
  api_factors.py     /api/factors/*, /api/stock/*/page, /api/flows（FCTR・STK・FLOW）
  factorlib.py       ファクター・ライブラリ（マクロ・セクター・スタイル）と要因分解
  flows.py           資金フローの代理（CMF・OBV・売買代金・相対強度）と設定・解約
  window.py          時間ウィンドウ（as-of で全系列を同じ日付で切る）
  api_coverage.py    /api/coverage/*（COV。ルートごとの移動 move_root を含む）
  coverage.py        フォルダ名・レイアウト、ルールベースのレポート（四半期の計算は earnings.py に委譲）
  earnings.py        決算カレンダーの純関数：FY・四半期（標準／ATLAS 表記）、JPX xlsx の読み取り、機械的な日付の決定、付け替え
  earnings_reaction.py 決算時の株価反応の純関数：反応日（既知／出来高から検出）、対市場、ドリフト、まとめ
  econ/              マクロ統計：catalog.py（514 系列の一覧と主要指標マトリクス）、sources.py（FRED・e-Stat・中国国家統計局・ONS・BoE・ECB・Eurostat・
                     カナダ統計局・ブラジル中銀・世界銀行・DBnomics の取得と解析）、
                     analysis.py（変換・指標・合成指数・象限・サプライズ・局面・フロー）
  api_econ.py        /api/econ/*（保存、自動更新、発表の検出、合成系列、ダッシュボード、フロー、取り込み、コード修正）
  brief.py           朝のブリーフの純関数（各区分の組み立てと Markdown）
  info/              情報ハブ：feeds.py（既定の取得元とキーワード、RSS / Atom / RDF の解析、当たりの判定、Google ニュースの URL）、
                     filings.py（EDINET の一覧・コード一覧・種類・対象の会社への結び付け、SEC EDGAR の解析）
  api_info.py        /api/info/*（TOP：取得と保存、巡回、通知、開示、会社ごとのニュース）
  api_settings.py    /api/settings/keys（API キーをその PC の .env に書き込み、すぐ有効にする）
  api_brief.py       /api/brief/*（データ集め、_terminal/briefs/ への保存、AUTO からの毎朝の作成）
  api_earnings.py    /api/earnings/*（正本 <カバレッジのルート>/_terminal/earnings/calendar.json、JPX、四半期ページ、
                     notes.md との双方向同期、反応、.ics）
  notion_api.py      Notion REST クライアント（銘柄マスタ、MICRO の個社ページ、ページ作成）
  api_insight.py     /api/insight/*（XRAY / RRG / THEME / PFND / TRAK）
  xray.py rrg.py themes.py pairscreen.py trackrecord.py   分析の拡張（純関数）
  framework.py       評点表・3.5句・ケリー・六層規律・ペア・空売り8モデル・天井/底・関門（純関数）
  macro.py           認識伝播マップ、景気局面、成長×流動性
  margin.py          JPX 信用残の取り込みと分析
  attention.py       Google Trends、X、StockTwits、センチメント
  transcripts.py     書き起こしのトーン・差分・回避度・数字・出典検証
  fourier.py         FFT、調和回帰、ローリング・バックテスト
  screener.py        SCRN の条件組み立て
  diagnose.py        接続の自己診断（CLI と API）
  analytics.py       指標、テクニカル判定、相関、パフォーマンス、バックテスト（純 Python）
  quant.py           BETA、SPRD（共和分）、SEAS、EVT、ポートフォリオリスク（VaR、為替換算）、RV
  factors.py         ファクター分析（ETF プロキシ、クロスセクション）
  leadlag.py         リード・ラグ分析とテーマのプリセット
  stats.py           OLS、F 分布、順位、スピアマン相関
  alerts.py          アラートエンジン
  store.py           JSON ファイルへの保存（data/store.json）
  excel.py           Excel ライブラリ（紐付け、表示、What-if、書き戻し、監視）
  formula.py         Excel 数式エンジン（主要関数＋ TV()）
  providers/
    base.py          Provider インターフェース
    __init__.py      ProviderRegistry（実行中の切替、source= の指定）
    tradingview.py   TradingView websocket とスキャナー
    tv_protocol.py   TradingView の通信フレーム（純関数、テスト済み）
    tv_web.py        ニュース、経済指標、ファンダメンタルズ、ユニバーススキャン、Yahoo RSS
    yahoo.py         Yahoo のチャート・検索と記号変換
    sim.py           疑似データ（DEMO）
  harness/
    __init__.py      CATALOG（MECE の一覧）
    regression.py    OLS（t, p, R², DW, 予測区間）、弾性値、トレンド、ドライバー回帰
    timeseries.py    CAGR、YoY、季節性、Holt、AR(1)、naive、精度評価、ローリング検証
    lines.py         明細行の作り方 18 種と依存関係の解決
    model.py         3 表の連動（P&L → FCF）
    valuation.py     WACC、DCF、倍率法、DDM、RIM
    uncertainty.py   シナリオ、感応度、モンテカルロ（シード固定）
    checks.py        検証チェック
    runner.py        実行、ハッシュ、入力検証
    paths.py         "a.b[0]" 形式のパス操作
backend/tests/       pytest
frontend/src/
  App.tsx            画面全体の骨組み（パネル、レイアウト、機能の割り当て）
  ctx.tsx            アプリ全体で共有する状態
  styles.css         ブルームバーグ風テーマ（CSS 変数）
  lib/               api, feed（websocket と hooks）, commands, indicators, format, xlsfmt, treemap, types
  components/        CommandLine, Chrome（テープ・キー・ステータス）, LineChart, ui
  functions/         GP, Monitor（W/WEI…）, Screener（MOST/HMAP）, Security（DES/TA/N/NOTE）,
                     Misc（ECO/ALRT/PORT+RISK+BLOTTER/SRC/HELP）, Analytics（FACT/LAG/CORR/BT）, Quant（BETA/SPRD/SEAS/EVT/RV/EARN/OV）,
                     XLS + XlsTools, MODEL + ModelTools, Reports（TEAR/SCRN）, Research（CYCL/PROP/MACRO/MRGN/TXT/TRND）,
                     Trinity（TRIN/SCORE/KELLY/RULE/PAIR/SHRT/CHIP/GATE/GLQ）, Insight（XRAY/RRG/THEME/PFND/TRAK）, Coverage（COV）, Stock（STK/FCTR）, Flows（FLOW）, Brief（BRIEF）, Econ（ECST）, Info（TOP・KeysPanel）, components/WindowSlider
models/examples/     ハーネスのサンプル spec
scripts/             setup / start / dev / test（sh と ps1）
docs/                本資料群
```

## 5. 主な設計判断とその理由

1. **バックエンドを Python にした**：将来の定量分析（回帰、ファクター、バックテスト）や Excel 処理（openpyxl、xlwings）との相性を優先しました。
2. **分析コードは numpy を使わない純 Python**：インストールが軽く、読みやすく、決定的になるためです。速度が問題になったら numpy に置き換えます（計算式は docs にあるので置き換えやすいです）。
3. **銘柄記号は TradingView 形式に統一**：Yahoo 向けは変換表で対応します。
4. **データソースはレジストリで遅延起動し、ストリーミングはアクティブな 1 つだけ**：分析 API は `source=` で個別に指定できるので、「長期の日足は Yahoo、ライブは TradingView」のような使い分けができます。
5. **SIM は常に DEMO と表示**：疑似データを本物と取り違えないためです。
6. **Excel の編集は「HTML で入力し、保存は Excel 本体」**：openpyxl で書き込むと、グラフ、画像、ピボット、マクロ、数式の計算結果が失われます。ユーザーの要望は「劣化させたくない」「HTML から編集したい」「Windows を使う」の 3 つです。そこで Windows では xlwings で Excel 本体に書き込ませ（劣化なし）、xlwings が使えない環境では、劣化しないファイルに限って openpyxl で書き込みます（バックアップ必須）。What-if（ファイルを変えない試算）は別モードとして残しました。
7. **ハーネスは「AI は spec を書く、数値はエンジンが出す」**：結果の再現性はハッシュで保証し、数値の出所は明細行ごとの method／formula／source で追えるようにし、もっともらしいだけの数値は検証チェックで警告します。
8. **リード・ラグは日付（UTC）で揃えた日次データで分析**：東京市場は NY より先に引けるので、米国→日本の効果はラグ +1 に現れます。
9. **フレームワークの実装は「Notion の数字をそのまま、無い数字は作らない」**：閾値・上限は Notion の値をコードに写し、テストで再現しています。Notion に数字がない箇所はプレースホルダーと画面・docs に明記し、取得できないデータは「不明」のまま評価します（推測で埋めると、ハーネスで避けたかった「もっともらしい誤り」を自分で作ることになるため）。
10. **AI が書く文章は機械で検証する**：`TXT` の BRIEF と `MODEL` の AI ブリーフは、出典の番号と数字の一致をコードで確認します。AI の採点は `SCORE` の AI Score 列に分けて記録し、人の採点との乖離だけを表示します。

## 6. 既知の課題・リスク（重要）

- **実データでの接続確認ができていません。** このクラウドセッションでは、tradingview.com、yahoo.com、binance などへの外向き通信が 403 で拒否されました。ユーザーはネットワーク許可を設定しましたが、このコンテナには反映されませんでした（新しいセッションから反映されると思われます）。**次の担当者が最初にやること**：実ネットワークのある環境で `TERMINAL_PROVIDER=tradingview` と `yahoo` を指定して起動し、W・GP・DES・MOST・N・ECO・FACT が動くか確認する。動かない場合は、`providers/tv_protocol.py` と `tradingview.py` のメッセージ名とフィールド名を、ブラウザの DevTools（WS タブ）で見える実際の通信と照らし合わせて直す。
- TradingView の websocket やスキャナーなどは**非公式**です。仕様は予告なく変わり、利用規約上の制約もあります（[`DATA_SOURCES.md`](DATA_SOURCES.md)）。商用・業務で本格的に使う場合は、正式なデータ契約（例：Bloomberg B-PIPE、Refinitiv、Polygon、J-Quants など）への切替を検討してください。Provider 層を差し替えるだけで済む設計にしてあります。
- 一部の記号は未検証です（例：`BATS:MTUM` などの ETF の取引所プレフィックス、`TVC:TOPIX`、`TVC:KOSPI`、`TSE:1591` など）。未ログインの TradingView では遅延データです。
- クロスセクションのファクター分析は「現時点の特性 × 過去のリターン」で計算しているため、バックテストではありません（スタイル要因の説明に使うものです）。
- 保存は単一ユーザー向けの JSON ファイルです。複数人で使うには DB と認証が必要です。
- Excel ビューは最大 3000 行 × 120 列までです。条件付き書式、グラフ、図形は表示しません（Excel で開けば見られます）。
- Windows では、Excel が開いているファイルはロックされ、openpyxl での書き込みは失敗します（423 を返す）。xlwings なら、開いているブックにそのまま書き込めます。
- xlwings で開いているブックに書き込むと `Save` するため、ユーザーが Excel で保存していなかった変更も一緒に保存されます。
- HTML から編集できるのは値と数式だけです（行・列の挿入、シートの追加、書式の変更は不可）。
- 決算時の株価反応の「検出」は出来高の急増からの推定です（推定日 ±10 日、20 日中央値の 2 倍以上、引け後の発表と仮定）。決算以外のニュースで出来高が増えた日を拾う可能性があるため、「検出」と明示し、実データのときだけ保存し、JPX・TradingView・手入力の日付があればそちらが優先されます。
- 決算カレンダーはカバレッジのルート（OneDrive に置くことを想定）の中にあります。2 台の PC で同時に使うと OneDrive で競合することがあります。
- 決算カレンダー：JPX の一覧ページの URL と xlsx の形式は実際には未確認です（見出しを文字で探すので多少の変更には耐えます）。ダウンロードに失敗しても前回分を使い続け、COV の「JPX 取り込み」で手動アップロードできます。推定（前年同期 + 364 日、四半期末 + 通常の日数）は「推定」と明示しています。

## 7. 次にやること（優先順）

1. **TOP → 7) KEYS に e-Stat のアプリケーション ID（`ESTAT_APP_ID`。ユーザーは発行済み）・EDINET の API キー・SEC の連絡先を貼って保存し、ECST → ⟳ 更新 → SOURCES と TOP → 5) FEEDS でエラー・更新停止のものを確認・修正する**（コードは開発環境から取得を確認できていない）。あわせて、実ネットワーク環境で `python -m app.diagnose` を実行し、TradingView と Yahoo の接続、記号、スキャナーの列名を確認・修正する（§6）
2. **Windows 実機で XLS の編集を確認する**（`scripts\setup.ps1` で xlwings を入れる → `TERMINAL_EXCEL_DIRS` にモデルのフォルダを設定 → 開いているブックと閉じているブックの両方で、入力、UNDO、数式の編集を試す）。あわせて、実際のファイルで表示の再現度と速度を確認する
3. **ユーザーと一緒に評点表の Weight（Notion に数値なし）と、成長×流動性の独自指標の定義を確定する**（[FRAMEWORK.md](FRAMEWORK.md) §7）。Notion の未読ページ（WORKLOG 参照）に差分があれば反映する
4. 会社ごとのハーネス spec を作る（`models/companies/<symbol>.json`）。必要なら、Excel のセルから history を読み込む機能（`excel:` 参照）を追加する
5. ファクター ETF の記号を検証し、日本向けファクターを充実させる（TOPIX スタイル指数など）
6. 暗号資産のリアルタイム配信（Binance 公式 websocket）の Provider を追加する
7. ユーザー認証、DB 化、複数ユーザーでのウォッチリスト共有
8. ROADMAP の残り（[`ROADMAP.md`](ROADMAP.md)）

## 8. ユーザーに確認したいこと（未回答）

回答済み：普段使う PC は **Windows**（2026-11-02）。

- TradingView の有料プランでログイン済みか（リアルタイム化のため `TV_AUTH_TOKEN` を使うかどうか）
- Excel モデルの置き場所と、ファイル名の付け方（自動紐付けのルールを合わせるため）
- 業績予想ハーネスで最初に扱う会社と、使いたい売上の組み立て方
- **評点表の各 Weight**（Notion には「配点あり・合計100」のみ）と、**成長×流動性の独自指標の定義**（FRAMEWORK.md §7）
- 回転率の閾値「市場全体 70%×1か月、個別 10%×1か月」の単位（日次か月次か）。現在は個別＝1日平均、市場＝月合計と解釈
- 四半期の FY 表記：標準（決算期が終わる年。2026年12月期 = FY2026）を既定にした。Notion の ATLAS の付け方（開始年 + 1）に合わせたいか（`PUT /api/earnings/config`、[EARNINGS.md](EARNINGS.md)）
- 四半期ページのチェックリスト（決算前・決算後）の項目を、普段の決算対応に合わせて変えたいか
- マクロ統計で、ほかに必ず見たい統計（社内で見ている 400 の一覧があれば、その名前）。AUTO の M（マクロ）を統計版の成長×流動性に切り替えたいか
- 三位一体の分析の追加（ALIGN：全銘柄の三位の一致と裁定ルールの地図／CHECK：発注前の一括チェック／EVAL：AUTO の判定の答え合わせ）— 設計まで済み、未実装（R44）
- PR を作るための `main` ブランチを作成してよいか（現在リポジトリには作業ブランチしかなく、PR を作れない）
