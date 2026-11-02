# CONFIG — 環境変数

| 変数 | 既定値 | 説明 |
|---|---|---|
| `TERMINAL_PROVIDER` | `tradingview` | 起動時のデータソース（tradingview, yahoo, sim）。未設定なら、最後に UI で選んだもの（store.settings.provider）を復元する |
| `TERMINAL_TRINITY_AUTO` | `1` | `0` で AUTO 三位一体の自動実行を止める（間隔は TRIN の AUTO タブで設定） |
| `TERMINAL_TRINITY_FIRST_DELAY` | `20` | 起動から初回の自動実行までの秒数 |
| `FRED_API_KEY` | （空） | FRED の API キー（任意）。無くても CSV で取得できる。検索（ECST → SOURCES）に必要。https://fred.stlouisfed.org で無料登録 |
| `ESTAT_APP_ID` | （空） | **e-Stat のアプリケーション ID**（ログインのメールアドレスではない。マイページ →「API 機能（アプリケーション ID 発行）」で発行する英数字）。日本の公式統計（労働力調査・CPI・賃金・貿易統計・法人企業統計など）に必要。https://www.e-stat.go.jp で無料登録 |
| `TERMINAL_ECON_AUTO` | `1` | `0` でマクロ統計（ECST）の自動更新を止める（間隔・ON/OFF は画面でも変更可） |
| `EDINET_API_KEY` | （空） | EDINET API v2 の Subscription-Key。情報ハブ（TOP）の開示（大量保有・自己株買い・公開買付・有報…）に必要。EDINET の「API 利用登録」で無料で発行。**秘密情報。コミットしないこと** |
| `SEC_USER_AGENT` | （空） | SEC EDGAR に送る連絡先（「名前 メールアドレス」。SEC の規則）。米国株の開示に必要 |
| `TERMINAL_INFO_AUTO` | `1` | `0` で情報ハブ（TOP）の自動取得を止める（間隔・ON/OFF は画面でも変更可） |
| `TERMINAL_ENV_FILE` | `<リポジトリ>/.env` | API キーの画面が書き込む `.env` の場所（テストで使う） |
| `NOTION_TOKEN` | （空） | COV が Notion API を使うためのインテグレーション・トークン。**秘密情報。コミットしないこと**（[COVERAGE.md](COVERAGE.md)） |
| `NOTION_COVERAGE_DB` / `NOTION_MICRO_PAGE` | （空） | 銘柄マスタのデータベース ID と ATLAS / MICRO のページ ID（COV の SETTINGS でも可） |
| `COVERAGE_DIR` | `<最初の Excel フォルダ>/Coverage` | カバレッジ・フォルダのルート。決算カレンダー（`_terminal/earnings/calendar.json`）もここに入る。OneDrive に移すときは COV の「ルートごと移す」を使う（SETTINGS のルートが `.env` より優先） |
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

**API キーは画面からも設定できます**：TOP → 7) KEYS（または ECST → SOURCES）に `ESTAT_APP_ID`・`FRED_API_KEY`・`EDINET_API_KEY`・`SEC_USER_AGENT` を貼って保存すると、その PC の `.env` に書き込まれ、再起動なしで有効になります（形式を確かめ、画面には伏せ字だけを出す。[INFO.md](INFO.md) §8）。Windows の環境変数に同じ名前があると、次の起動ではそちらが優先されます。

サンプルは [`.env.example`](../.env.example) にあります。リポジトリ直下に `.env` としてコピーすると起動時に自動で読み込みます（`backend/app/config.py` の `load_dotenv`。すでに環境変数で設定されている値は上書きしません。`.env` は `.gitignore` 済み）。

**セキュリティ**：サーバーは既定で `127.0.0.1` だけで待ち受けます（`scripts/start.sh`）。認証がないので、LAN や外部に公開しないでください（Excel のファイルを開いたり書き込んだりする API があります）。
