# ARCHITECTURE

```
 Browser (React)                          Backend (FastAPI, single process)                 Upstream
 ───────────────                          ─────────────────────────────────                 ────────
 CommandLine ──REST /api/*──────────────▶ api_market / api_analysis / api_excel / api_harness
 Panels (GP,W,…)                                │            │             │           │
   useQuotes / useBars ◀──WS /ws── Hub ◀────────┤            │             │           │
        ▲   (quotes coalesced 250ms)   │  ▲     │            │             │           │
        │                              │  │ emit_quote/bar   │             │           │
        │                    set_quote_symbols / set_bar_subscriptions     │           │
        │                              ▼  │                  │             │           │
        │                    ProviderRegistry ── active ──▶ TradingViewProvider ──wss──▶ data.tradingview.com
        │                              │                     YahooProvider ─────https──▶ query1.finance.yahoo.com
        │                              │                     SimProvider (local GBM)
        │                              └─ source= (pull) ──▶ any provider
        │                    TVWeb ──https──▶ scanner / news-headlines / economic-calendar / symbol-search
        │                    AlertEngine (evaluated on every quote) ──▶ Hub.broadcast {"type":"alert"}
        │                    ExcelLibrary (openpyxl read, formula engine, mtime watcher) ──▶ {"type":"excel_changed"}
        │                    Harness (pure functions, deterministic)
        │                    Store (data/store.json)
```

## データの流れ

1. **ストリーミング**：パネルが `useQuotes([...])` を呼ぶ → `feed` が参照カウントで購読をまとめ、`set_symbols` を送る → Hub が全ブラウザの購読の和集合をアクティブな Provider に渡す → Provider が `emit_quote` を呼ぶ → Hub はブラウザごとに更新をまとめ、250ms ごとに `{"type":"quotes"}` として送る。
2. **足（バー）**：GP が `useBars(symbol, interval)` を呼ぶ → `subscribe_bars` → TradingView では銘柄と時間足ごとにチャートセッションを作り、`du` メッセージで更新を受ける。SIM はティックから足を組み立て、Yahoo はポーリングで取得する。
3. **履歴**：`GET /api/history` → `S.history()`（TTL キャッシュ：日中足は 15 秒、日足以上は 120 秒）→ `provider.get_history()`。TradingView は、リクエストごとに短時間だけ使う websocket で取得する。
4. **分析**：分析 API は履歴をまとめて取得し、純 Python の関数で計算する。
5. **データソースの切替**：`POST /api/providers/active` → `registry.get(name)`（必要なら遅延起動）→ `hub.set_provider()`（旧 Provider の購読を空にし、新 Provider につなぎ替えて再購読）→ ブラウザに `{"type":"provider"}` を送る。

## 実行時の状態

- `state.S`：プロセス全体で 1 つだけのインスタンス（registry, store, alerts, excel, web, hub, hist_cache）
- アプリのライフサイクル（`main.lifespan`）：保存済みの provider を復元 → Hub を作成 → アラート対象の銘柄を購読 → Excel の監視タスクを開始

## フロントエンドの状態

- グローバル：`security`（読み込み中の銘柄）、`panels`（最大 6 つ。fn, symbol（固定時）, args）、`layout`、`focus`。localStorage に保存する。
- サーバー保存（`/api/store/*`）：watchlists, portfolio, notes, excel_links, harness_models, settings
- 色：`styles.css` の CSS 変数

## 拡張ポイント

| 追加したいもの | 触る場所 |
|---|---|
| 新しいデータソース | `providers/base.py` を継承し、`providers/__init__.py` の `PROVIDERS` と `create_provider` に登録 |
| 新しい画面機能 | `frontend/src/lib/commands.ts` の `FUNCTIONS`、`App.tsx` の `FunctionBody`、`docs/COMMANDS.md` |
| 新しい分析 API | `api_analysis.py`（ロジックは純関数のモジュールに書き、テストを付ける） |
| 明細行の新しい作り方 | `harness/lines.py` の `METHODS`、`harness/__init__.py` の `CATALOG`、`docs/FORECAST_HARNESS.md` |
| 新しい検証チェック | `harness/checks.py` |
| 銘柄リスト | `backend/app/universe.py` |
| リード・ラグのテーマ | `backend/app/leadlag.py` の `THEMES` |
| ファクターの ETF | `backend/app/factors.py` の `FACTOR_SETS` |
