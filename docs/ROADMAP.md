# ROADMAP

優先度の高い順です。完了したら WORKLOG に記録し、ここから削除してください。

## P0 — 次のセッションでやる
- [ ] TradingView と Yahoo の実データでの接続確認と修正（HANDOFF §6）
- [ ] 未検証の記号の確認（DATA_SOURCES の「未検証の記号」）
- [ ] Windows 実機で、XLS の xlwings 経由の編集と、実際の Excel フォルダでの表示（忠実度、速度）を確認

## P1 — アナリストの業務に直結
- [ ] XLS：範囲の貼り付け（Excel や TSV からの複数セル）、コピー、オートフィル、行・列の挿入（xlwings 経由）
- [ ] XLS：xlwings で開いているブックから値を直接読む（保存しなくても最新の値を表示）
- [ ] ハーネス：会社ごとの spec のテンプレート（製造業、小売、SaaS、銀行、商社）と、`models/companies/` の運用
- [ ] ハーネス：Excel のセルから history と前提を読み込む（`{"excel": "<file_id>", "range": "Model!B4:G4"}`）
- [ ] ハーネス：コンセンサス予想との比較、予想の改訂履歴（spec のバージョン管理と差分）
- [ ] 決算カレンダー、決算短信と開示資料へのリンク（EDINET / TDnet / SEC EDGAR）
- [ ] ファクター：日本の TOPIX スタイル指数やバリュー・グロースの ETF、Fama-French 型の回帰（銘柄 × ファクターのエクスポージャー）
- [ ] リード・ラグ：日中足での分析（米国の引け → 日本の寄り付き）、イベントスタディ（決算・指標発表の前後のリターン）
- [ ] スクリーナー：任意条件のフィルタ UI（スキャナーの filter を組み立てる）
- [ ] Binance 公式 websocket の Provider（暗号資産を無料でリアルタイムに）

## P2 — TradingView との差を埋める
- [ ] チャート：ストキャス、ATR、一目均衡表、出来高プロファイルの表示、平行チャネル、テキスト、計測ツール、画像保存
- [ ] インジケーター条件でのアラートと Webhook 通知
- [ ] バーリプレイ
- [ ] 平均足以外の足種（Renko など）

## P3 — 基盤
- [ ] 認証と複数ユーザー、DB（SQLite → Postgres）
- [ ] 正式なデータ契約に対応した Provider（Polygon, J-Quants, Refinitiv, Bloomberg など）
- [ ] デスクトップアプリ化（Tauri／Electron）。Excel の起動とファイル監視がローカルで確実に動く
- [ ] E2E テスト（Playwright）を CI で実行
