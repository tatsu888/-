# EXCEL — 銘柄に紐付いた Excel モデルの参照（XLS）

## 目的（ユーザー要件 R13、R14、R16、R18）

> 銘柄を HTML から選んだときに、いちいち Excel をフォルダから探さずに HTML 上で参照できると便利。**Excel の機能の劣化はしたくない**。
> 普段は Windows を使っている。**編集も HTML から行えるほうがやりやすい**。

## 設計：「HTML で表示・編集し、保存は Excel 本体に任せる」

| 操作 | 方法 | ファイルへの影響 |
|---|---|---|
| 表示 | Excel が保存時に計算した値と、書式（太字、斜体、下線、文字色、背景色、配置、インデント、罫線、数値書式、列幅、行高、非表示、結合セル、シートの色、目盛線）を表示 | なし |
| **編集（EDIT モード、既定）** | セルを選んで入力すると、そのまま保存されます。**Windows では xlwings 経由で Excel 本体が書き込み、再計算して保存する**ため、グラフ、マクロ、ピボットなどはすべて残ります。そのブックを Excel で開いている場合は、その Excel の画面にもすぐ反映されます | あり（Excel 本体による保存） |
| 元に戻す（UNDO、Ctrl+Z） | 書き込み前の値や数式をサーバーが返すので、それを書き戻します（最大 50 回） | あり |
| What-if（WHAT-IF モード） | 入力した値をメモリ上だけで再計算し、影響を受けたセルを黄色で表示します。`APPLY TO FILE` でまとめて保存することもできます | なし（APPLY するまで） |
| `=TV("NASDAQ:AAPL","last")` | 市場データ関数。LIVE ボタンで 3 秒ごとに更新 | なし |
| Excel で開く | サーバー機で Excel を起動 | Excel 上で普通に編集 |
| 保存を検知して自動再読込 | Excel 側で保存すると、HTML の表示が自動で更新されます（ターミナルからの書き込みは除く） | — |

### キー操作（Excel と同じ）

| キー | 動作 |
|---|---|
| 矢印キー、Tab、Shift+Tab | セルの移動 |
| 文字を入力 | 上書きで編集を開始 |
| Enter、F2、ダブルクリック | 今の内容を編集 |
| 編集中に Enter | 確定して下へ（Tab なら右へ） |
| Esc | 編集を取り消し |
| Delete、Backspace | セルの内容を消去 |
| Ctrl+Z | 元に戻す |
| 数式バー（fx） | 長い数式を編集し、Enter で確定 |

入力値の解釈も Excel と同じです。`1,234` は 1234、`5%` は 0.05、`TRUE` は真偽値、`=` で始まれば数式になります。

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

### 書き込みモード（`TERMINAL_EXCEL_WRITE`）

| モード | 仕組み | 劣化 | 条件 |
|---|---|---|---|
| `auto`（既定） | xlwings が使えれば xlwings、使えなければ openpyxl。ただし openpyxl では劣化しないファイルに限る | なし | — |
| `xlwings`（Windows の推奨） | **Excel 本体**を操作します。開いているブックにはそのまま接続し、開いていなければ非表示の Excel で開いて書き込み、保存して閉じます。COM の呼び出しは専用スレッドで行います | **なし** | Windows（または macOS）、デスクトップ版 Excel、`pip install xlwings`（`scripts\setup.ps1` で自動インストール） |
| `openpyxl` | ファイルを直接書き換えます | グラフ、画像、ピボット、マクロ、外部リンク、スライサー、Power Query などを含むファイルは**書き込みを拒否**（`lossy_parts` で検出）。含まない場合でも、数式の計算結果は消えます（ターミナルのエンジンで計算して表示し、次に Excel で開くと再計算されます） | 書き込む前に `.terminal_backups/` へ自動でバックアップ |
| `off` | 読み取り専用（What-if のみ） | なし | — |

画面上部には、そのファイルで実際に使える方式が表示されます（「Excel 本体経由で保存」または「直接保存（自動バックアップ）」）。編集できない場合は理由が表示されます。

**注意（xlwings）**：開いているブックに書き込むときは `Save` が実行されるため、その Excel で保存していなかった変更も一緒に保存されます。

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
- 「Excel で開く」と xlwings での編集は、**サーバーが動いている PC**の Excel を使います。ローカル（Windows PC でサーバーを起動）での利用が前提です。
- 行や列の挿入・削除、シートの追加、書式の変更は HTML からはできません（値と数式の編集のみ）。必要な場合は「Excel で開く」を使ってください（ROADMAP）。
