# HANDOFF — 引き継ぎ資料（最初に読む）

最終更新：2026-11-02（Claude Code / クラウドセッション）
次の担当者（ChatGPT など）は、このファイル → [`REQUIREMENTS.md`](REQUIREMENTS.md) → [`WORKLOG.md`](WORKLOG.md) の順に読んでください。

---

## 1. 目的

ヘッジファンドのアナリストが日常的に使う分析ツールを作ります。第 1 段階は、**TradingView の機能を模したプラットフォーム**を、**ブルームバーグターミナル風のデザイン・操作感**で作ることです。

- TradingView / Yahoo の数値をリアルタイムに近い形で取得し、データ取得元は**手動で切り替え**られるようにする
- 市場分析：どのファクターが効いているか、タイムラグ（原油→株、米国のテーマ→日本株）を調べる
- Excel 連携：銘柄を選んだら、その銘柄の Excel をフォルダから探さずに HTML 上で参照し、**HTML から編集もする**（ユーザーは Windows）。**Excel の機能は劣化させない**
- 業績予想ハーネス：AI のハルシネーションや、実行ごとに結果がぶれることを防ぐため、**会社に依存しない計算式と財務モデルを MECE に網羅した、決定的なエンジン**を用意する

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
| テスト | ✅ backend 48 件、frontend 7 件、型チェック、ビルド | `scripts/test.sh` |

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
                     Misc（ECO/ALRT/PORT+RISK/SRC/HELP）, Analytics（FACT/LAG/CORR/BT）, Quant（BETA/SPRD/SEAS/EVT/RV/EARN/OV）, XLS, MODEL
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

## 7. 次にやること（優先順）

1. 実ネットワーク環境で TradingView と Yahoo の接続を確認・修正する（§6）
2. **Windows 実機で XLS の編集を確認する**（`scripts\setup.ps1` で xlwings を入れる → `TERMINAL_EXCEL_DIRS` にモデルのフォルダを設定 → 開いているブックと閉じているブックの両方で、入力、UNDO、数式の編集を試す）。あわせて、実際のファイルで表示の再現度と速度を確認する
3. 会社ごとのハーネス spec を作る（`models/companies/<symbol>.json`）。必要なら、Excel のセルから history を読み込む機能（`excel:` 参照）を追加する
4. ファクター ETF の記号を検証し、日本向けファクターを充実させる（TOPIX スタイル指数など）
5. 暗号資産のリアルタイム配信（Binance 公式 websocket）の Provider を追加する
6. ユーザー認証、DB 化、複数ユーザーでのウォッチリスト共有
7. ROADMAP の残り（[`ROADMAP.md`](ROADMAP.md)）

## 8. ユーザーに確認したいこと（未回答）

回答済み：普段使う PC は **Windows**（2026-11-02）。

- TradingView の有料プランでログイン済みか（リアルタイム化のため `TV_AUTH_TOKEN` を使うかどうか）
- Excel モデルの置き場所と、ファイル名の付け方（自動紐付けのルールを合わせるため）
- 業績予想ハーネスで最初に扱う会社と、使いたい売上の組み立て方
