# CONFIG — 環境変数

| 変数 | 既定値 | 説明 |
|---|---|---|
| `TERMINAL_PROVIDER` | `tradingview` | 起動時のデータソース（tradingview, yahoo, sim）。未設定なら、最後に UI で選んだもの（store.settings.provider）を復元する |
| `X_BEARER_TOKEN` | （空） | X API v2 の Bearer Token（`TRND` の X 分析。counts/search は有料プラン）。**秘密情報。コミットしないこと** |
| `TV_AUTH_TOKEN` | `unauthorized_user_token` | TradingView の auth token（ログインしていればリアルタイム）。**秘密情報。コミットしないこと** |
| `YAHOO_POLL_SEC` | `5` | Yahoo のポーリング間隔（秒） |
| `SIM_TICK_SEC` | `1` | SIM のティック間隔（秒） |
| `PUSH_INTERVAL_SEC` | `0.25` | ブラウザへまとめて送る間隔（秒） |
| `TERMINAL_DATA_DIR` | `<repo>/data` | store.json と workbooks の保存先 |
| `TERMINAL_EXCEL_DIRS` | `<DATA_DIR>/workbooks` | Excel ライブラリのルート（OS のパス区切り文字で区切る） |
| `TERMINAL_EXCEL_WRITE` | `auto` | auto（xlwings が使えればそれ、なければ劣化しないファイルだけ openpyxl）, xlwings, openpyxl, off（[EXCEL.md](EXCEL.md)） |
| `TERMINAL_STATIC_DIR` | `<repo>/frontend/dist` | 本番でビルド済みの UI を配信する場所 |
| `TERMINAL_CORS` | `http://localhost:5173,http://127.0.0.1:5173` | 開発サーバーの CORS |
| `LOG_LEVEL` | `INFO` | |

サンプルは [`.env.example`](../.env.example) にあります。リポジトリ直下に `.env` としてコピーすると起動時に自動で読み込みます（`backend/app/config.py` の `load_dotenv`。すでに環境変数で設定されている値は上書きしません。`.env` は `.gitignore` 済み）。

**セキュリティ**：サーバーは既定で `127.0.0.1` だけで待ち受けます（`scripts/start.sh`）。認証がないので、LAN や外部に公開しないでください（Excel のファイルを開いたり書き込んだりする API があります）。
