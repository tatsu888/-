# WORKLOG — 作業記録（追記していく）

書式：`## 日付 — 担当 (AI名/人)` → やったこと / 確認したこと / 未解決 / 次の人へ

---

## 2026-11-01 — Claude Code（クラウドセッション、branch `claude/optimistic-bohr-9gt9hh`）

### やったこと
- 空のリポジトリから全体を作成：backend（FastAPI）、frontend（React + Vite + lightweight-charts）、docs、scripts
- データ取得：TradingView（websocket のクォートとチャートセッション、スキャナー、検索、ニュース、経済指標、ファンダメンタルズ）、Yahoo（チャート、検索、RSS）、SIM（DEMO 表示つき）
- 実行中のデータソース切替（UI と API）と、リクエスト単位の `source=` 指定
- ブルームバーグ風 UI と 24 の機能（`docs/COMMANDS.md`）
- 分析：テクニカル判定、相関、パフォーマンス、バックテスト（5 戦略）、ファクター分析（ETF プロキシ、クロスセクション）、リード・ラグ分析（CCF、グレンジャー、ローリング、スキャン、残差化）
- Excel：紐付け、劣化なしの表示（計算結果と書式）、What-if、`=TV()`、Excel で開く、保存の監視、書き戻し（モード制）、アップロード
- 業績予想ハーネス：7 層の MECE、明細行の作り方 18 種、DCF・倍率法・DDM・RIM、シナリオ、感応度、モンテカルロ、検証チェック、ハッシュ、xlsx 出力
- テスト：backend 38 件、frontend 6 件。SIM モードで Playwright のスクリーンショットを撮り、全主要画面を目視確認

### 確認できなかったこと
- **TradingView と Yahoo の実データでの動作**：このクラウド環境から外部への通信が 403 で拒否された（ユーザーが許可設定をしたが、このセッションには反映されなかった）
- xlwings モード（Windows／Mac で、デスクトップ版 Excel が必要）

### 途中で見つけて直したバグ
- LineChart のアンマウント時に、削除済みのチャートへ `removeSeries` を呼んで落ちていた → チャートの参照を null にしてから判定するよう修正。さらに `PanelBoundary` を追加し、1 つのパネルのエラーでアプリ全体が落ちないようにした
- openpyxl で保存した xlsx は数式の計算結果を持たない → エンジンで補完し、補完した値であることを明示するよう変更
- What-if 計算で、変更前と変更後の計算が同じデータを共有していた → deepcopy で分離

### 次の人へ
- HANDOFF §7 の 1 番（実データでの接続確認）から着手してください

## 2026-11-02 — Claude Code（同じセッションの続き）

### ユーザーからの回答と要望
- 普段は Windows。Excel は HTML からも編集したい（R17、R18）

### やったこと
- `backend/app/excel.py`：書き込みモードを `auto`（既定）、`xlwings`、`openpyxl`、`off` に整理
  - xlwings：開いているブックがあれば接続し、なければ非表示の Excel で開いて書き込み、保存して閉じる。COM の呼び出しは専用スレッドで行う
  - openpyxl：グラフやマクロなど失われる要素を含むファイルは拒否し、それ以外はバックアップを取ってから書き込む
  - 書き込み前の内容（`before`）を返すようにし、UNDO に使う
  - ターミナル自身の書き込みは「外部での保存」として通知しない
  - 入力値の解釈を Excel に合わせた（%, 桁区切り, TRUE/FALSE, 整数）
  - `=TV()` は初回表示から、手元にあるライブ価格で値を埋める
- `api_excel.py`：`POST /write` が `before` と更新後の `view` を返すようにした。処理はスレッドで実行
- `frontend/src/functions/XLS.tsx`：EDIT と WHAT-IF のモード、Excel と同じキー操作、数式バーでの編集、UNDO（Ctrl+Z）、What-if の結果をファイルへ反映（APPLY TO FILE）、保存中の表示。グリッド上の入力がコマンドラインに取られないよう `data-own-keys` を追加
- テスト：openpyxl での編集と UNDO、グラフを含むファイルの拒否、off モード、偽の xlwings による「非表示の Excel で開く場合」と「開いているブックに接続する場合」の流れ（計 39 件、全件成功）
- ブラウザ（Playwright）で、`5%` の入力 → 保存 → 再計算、Ctrl+Z、数式バーからの `=D4/C4-1` の入力を確認

### 未確認
- Windows 実機 + Excel での xlwings 経由の書き込み（HANDOFF §7-2）

## 2026-11-02 — Claude Code（機能追加：R19）

### やったこと
- `backend/app/quant.py`（新規、純 Python）：回帰ベータ、ペアスプレッド（OLS によるヘッジ比率、エングル・グレンジャー検定、半減期、z スコア）、季節性、イベントスタディ（マーケットモデル、CAR、t 値、大きな値動きの日の自動検出）、ポートフォリオリスク（VaR・ES、リスク寄与度、ベータ、ストレステスト、為替換算）、同業他社の統計、通貨の判定と FX ペアの慣行
- `api_analysis.py`：/beta, /spread, /seasonality, /event_study, /portfolio_risk, /relative_value, /earnings を追加。`tv_web.scan_symbols`（複数銘柄・任意の列、失敗時は少ない列で再試行）
- フロントエンド：`functions/Quant.tsx`（BETA, SPRD, SEAS, EVT, RV, EARN, OV）、PORT の RISK タブ、`lib/options.ts`（ブラック・ショールズ、IV）、`XYChart`（SVG の散布図と折れ線）、ワークスペース、コマンド履歴、XLS の範囲選択・コピー・貼り付け・範囲消去
- テスト：backend 48 件（quant の真値の再現、共和分の検出、FX の換算と慣行、エンドポイント）、frontend 7 件（ブラック・ショールズは Hull の例題の値とプットコールパリティで確認）

### 途中で見つけて直した問題
- ポートフォリオリスクで円とドルを混ぜて合算し、ウェイトが歪んでいた → 基準通貨（USD / JPY / EUR）への換算を追加
- 換算の通貨ペアの向きが逆だった（JPYUSD を探していた）→ 市場慣行の順序（EURUSD, USDJPY, EURJPY …）を優先するよう修正

### 未確認
- EARN と RV で使うスクリーナーの列名（実データ）

## 2026-11-02 — Claude Code（機能追加：R20〜R25）

### やったこと（コミット順）
- `e370fe6` TradingView 通信：偽の websocket サーバーによる E2E テスト（再接続を含む）、HTTP のパーサーのテスト、自己診断（`python -m app.diagnose`、`/api/diagnose`、SRC の RUN DIAGNOSTICS）
- `8495637` ハーネス：パラメータの契約と JSON Schema、Excel セル参照、版の履歴と差分、AI ブリーフ → 変更提案の検証と適用（過去実績の変更禁止・出典必須）、業種テンプレート 6 種、前提のフォーム編集
- `a51a186` `cec16aa` Excel（R20）：フィル／貼り付け（相対参照）、参照元・参照先、検索、名前ボックス、統計、枠の固定、書式、行列の挿入・削除、新規シート／ブック、書き込み前のスナップショットと差分・復元、クイックチャート、未保存の値の同期、条件付き書式・入力規則・コメント・リンクの表示（コメントの VML は劣化扱いにしない）
- `6c6dfeb` チャート：一目・ストキャス・ATR・PNG 保存。指標アラート（サーバーで毎分評価）
- `a4dcdfc` ペアトレードのバックテスト、約定記録（平均取得単価・実現損益・ポジションへの同期）、為替変動込みのポートフォリオリスク
- `55feee5` TEAR（印刷用ティアシート）、SCRN（スクリーンビルダー）、パネル最大化、`Start-Terminal.bat`
- `d8d1d81` CYCL（フーリエ）とハーネスの `fourier` メソッド
- `543744d` PROP（認識伝播マップ）と MACRO（金利・カーブ・クレジット・ボラ・景気局面）
- `aa2e2fc` MRGN（JPX 信用残の取り込みと分析）
- `f68c9ea` TRND のバックエンド（Google Trends、X API v2、StockTwits、辞書によるセンチメント、急騰、関心と株価の先行性）
- `f521a78` **投資の三位一体**のバックエンド：`framework.py`（評点表、3.5句、評点差→サイズ、ケリー、六層規律、Pair Sigma・ペア適性、空売り8モデル、天井/底、混雑度、関門）、`api_framework.py`、成長×流動性（`macro.growth_liquidity`）、書き起こし分析（`transcripts.py`）
- `fa05d5b` フロントエンド：`TRIN` とタブ（SCORE / KELLY / RULE / PAIR / SHRT / CHIP / GATE / GLQ）、`TXT`、`TRND`、MACRO に 4 象限
- 本コミット：docs 一式（FRAMEWORK.md・ATTENTION.md 新規、COMMANDS / API / ANALYTICS / DATA_SOURCES / CONFIG / HANDOFF / REQUIREMENTS / ROADMAP 更新）、`.env` の自動読み込み（`config.load_dotenv`）と `.gitignore` への `.env` 追加、`POST /transcripts/analyze_text` が `/{symbol}` に隠れていたのを `/transcript_text/analyze` に変更

### Notion の読み取り（R23、R24）
- `ATLAS / STRATEGY / 投資の三位一体` の第1〜5部、`ファンダメンタル戦略`、`Framework of Pinpoint`、`見るべき統計` を読んだ。数字は Notion の値をそのまま実装し、Notion に数字がない箇所はプレースホルダーと明記（FRAMEWORK.md §7）
- 未読：`マクロ戦略 加筆版`、`クオンツ戦略`、`TRADING`、`Valuation`、`ストックレビューの仕方`、`ファンダメンタルズ L/S MN戦略と限界`、`AI 指示`（三位一体と重複が多いと判断。次回、差分があれば反映）

### 途中で見つけて直した問題
- 成長×流動性の結果で、象限のラベル（`growth`）が数値の z を上書きしていた → ラベルを `growth_label` / `liq_label` に改名
- 空売りモデル①の「二階微分」を、成長率の系列の二階差分で計算していた → 成長率＝利益の一階微分なので、その変化（一階差分）が二階微分（Notion の例 30→20→10% で成立）
- SCORE と PAIR の画面で、パネル幅が狭いと表が右側の列と重なった → 最小幅を設けて折り返し
- `.env.example` はあったが読み込む処理がなく、`.env` も `.gitignore` に入っていなかった

### テスト
- backend 116 件（framework 13、transcripts 5、config 1 を追加）、frontend 10 件、型チェック、ビルド
- Playwright（SIM）で TRIN / SCORE / KELLY / RULE / PAIR / SHRT / CHIP / GATE / GLQ / TXT / MACRO / TRND を操作して画面確認。StockTwits はこの環境では外部通信が拒否されエラー表示（想定どおり）

### 未確認
- 実データでの成長×流動性の記号（`COMEX:HG1!`、`TVC:DXY`、`TVC:US02Y`、`AMEX:HYG` など）、スキャナーの列（`float_shares_outstanding`、`total_revenue_yoy_growth_ttm`、`free_cash_flow`、`enterprise_value_ebitda_ttm`）
- Google Trends・X・StockTwits の実通信

## 2026-11-02 — Claude Code（R26：AUTO 三位一体）

### やったこと
- `backend/app/trinity_auto.py`（純関数）：ルール採点（同ユニバース内の順位 → Notion の分布で 1〜5 点）、成長×流動性の象限とセクターの優劣、天井/底と混雑、確信度（1＋一致−逆行）、ルールによるサイズ、裁定ルールのフラグ、自動関門、空売りモデルの自動判定、スナップショットの差分
- `backend/app/api_trinity.py`：ユニバースの組み立て、データ取得、`data/trinity/` への保存（latest・日次履歴・変化ログ）、起動時と一定間隔の自動実行（`main.py` の lifespan）、変化を websocket で通知、`/api/trinity/*`
- フロントエンド：TRIN の既定タブを AUTO に（一覧、根拠、変化ログ、UNIVERSE と間隔の設定、RUN NOW）。変化はトーストで通知
- テスト：`test_trinity_auto.py` 7 件（分布の写像、ルール採点、象限、確信度と裁定、混雑の検出、差分、API）。テスト中は自動実行を止める（`TERMINAL_TRINITY_AUTO=0`）
- SIM で自動実行（起動数秒後）と画面を確認。この環境ではスキャナーがプロキシで拒否されるため、ルール採点の F は N/A（評点表を保存した銘柄のみ判定）

### 未確認
- 実データでのスキャナー列（`return_on_equity`、`gross_margin`、`debt_to_equity` など）と、セクター名の対応（`SECTOR_BUCKET`）
- （R27）上部バーに手動更新ボタン「⟳ 三位一体を更新」を追加。押すと `POST /api/trinity/run` → トースト → 開いている AUTO タブを再読込（`trinity-updated` イベント）。ブラウザで動作確認
