# EXCEL — 銘柄に紐付いた Excel モデルの参照（XLS）

## 目的（ユーザー要件 R13、R14、R16）

> 銘柄を HTML から選んだときに、いちいち Excel をフォルダから探さずに HTML 上で参照できると便利。**Excel の機能の劣化はしたくない**。

## 設計：「表示は劣化なし、編集は本物の Excel」

| 操作 | 方法 | ファイルへの影響 |
|---|---|---|
| 表示 | Excel が保存時に計算した値と、書式（太字、斜体、下線、文字色、背景色、配置、インデント、罫線、数値書式、列幅、行高、非表示、結合セル、シートの色、目盛線）を表示 | なし（読み取りのみ） |
| 数式の確認 | セルを選ぶと、数式バーに数式を表示 | なし |
| **Excel で開く** | サーバー機の OS で、既定のアプリ（Excel）を起動 | Excel 上で普通に編集 |
| 保存を検知して自動再読込 | 表示中のファイルの更新時刻を 1.5 秒ごとに監視し、websocket で通知 | — |
| **What-if** | セルをダブルクリックして値や数式を入力 → サーバーの数式エンジンで再計算 → 影響を受けたセルを黄色で表示 | **なし**（メモリ上だけで計算） |
| `=TV("NASDAQ:AAPL","last")` | 市場データ関数。LIVE ボタンで 3 秒ごとに更新 | なし |
| 書き戻し | `TERMINAL_EXCEL_WRITE` で明示的に有効化（下記） | あり |

### 銘柄との紐付け

- **自動**：ファイル名またはフォルダ名に、ティッカーが独立した語として含まれていれば紐付きます（例：`TSE:7203` → `7203_トヨタ_model.xlsx`, `JP/7203/…`、`NASDAQ:AAPL` → `AAPL_model.xlsx`）。
- **手動**：XLS 画面の `LINK→…` ボタン。`data/store.json` の `excel_links` に保存されます。
- DES 画面にも、紐付いたモデルの一覧が出ます。

### 設定

```bash
TERMINAL_EXCEL_DIRS="/Users/me/Models:/Volumes/Share/Models"
```

```powershell
$env:TERMINAL_EXCEL_DIRS="C:\Users\me\Models;D:\Share\Models"
```

1 つ目が macOS／Linux（`:` 区切り）、2 つ目が Windows（`;` 区切り）です。未設定のときは `data/workbooks/`（アップロード先）を使います。

### 書き戻しのモード（`TERMINAL_EXCEL_WRITE`）

| モード | 仕組み | 劣化 | 条件 |
|---|---|---|---|
| `off`（既定） | 読み取り専用 | なし | — |
| `xlwings`（推奨） | 起動中の **Excel 本体** を操作して値や数式を設定し、保存 | **なし**（Excel 自身が保存するため） | Windows／macOS、デスクトップ版 Excel、`pip install xlwings` |
| `openpyxl` | ファイルを直接書き換え | グラフ、画像、ピボット、マクロ、外部リンク、スライサー、Power Query などを含むファイルは**書き込みを拒否**（`lossy_parts` で検出）。含まない場合でも、数式の計算結果は消える（次に Excel で開くと再計算される） | 書き込む前に `.terminal_backups/` へ自動でバックアップ |

## 数式エンジン（`backend/app/formula.py`）

- 対応：四則演算、べき乗、`&`、比較、`%`、単項マイナス（Excel と同じく `-2^2 = 4`）、シートをまたぐ参照（`'My Sheet'!A1:B9`）、範囲。
- 対応関数：SUM, AVERAGE, MIN, MAX, PRODUCT, MEDIAN, STDEV(.S/.P), VAR(.S/.P), COUNT, COUNTA, IF, IFERROR, IFNA, AND, OR, NOT, ROUND, ROUNDUP, ROUNDDOWN, ABS, SQRT, LN, LOG, LOG10, EXP, POWER, MOD, INT, PI, CONCAT, CONCATENATE, LEN, UPPER, LOWER, TRIM, LEFT, RIGHT, MID, TODAY, NOW, VLOOKUP, MATCH, INDEX, SUMPRODUCT, SUMIF, COUNTIF, AVERAGEIF, TV
- **非対応の関数**（XLOOKUP、OFFSET、INDIRECT、配列数式、データテーブルなど）を使ったセルは、**Excel が保存した値をそのまま使い**、`stale` として表示します（What-if の結果に反映されない可能性がある、という警告）。
- エラー値：#DIV/0!、#VALUE!、#REF!、#NAME?、#N/A、#NUM!、循環参照は #CIRC!
- Excel 以外のツールで保存されたファイル（計算結果を持たないもの）は、エンジンで値を補い、点線の下線と「engine-computed」バッジで明示します。

## 制限

- 表示は最大 3000 行 × 120 列です（それを超える部分は Excel で開いてください）。
- 条件付き書式、グラフ、図形、コメント、ウィンドウ枠の固定の再現は未対応です（ROADMAP）。
- `.xls` と `.xlsb` は一覧に出ますが、表示はできません（Excel で開くことはできます）。
- 「Excel で開く」は**サーバーが動いている PC**で Excel を起動します。ローカルで使う前提で、クラウドで動かした場合は機能しません。
