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
