# FORECAST HARNESS — 業績予想ハーネス

## なぜ作るのか

AI に業績予想や投資判断を直接任せると、次の問題が起きます。

1. **ハルシネーション**：もっともらしいロジックで、根拠のない数値を出す
2. **再現性がない**：同じ質問をしても、実行するたびに数値が変わる
3. **監査できない**：どの数値が、どの前提と式から出たのかを追えない

そこで役割を分けます。

| 担当 | やってよいこと |
|---|---|
| **AI／アナリスト** | spec（JSON）に、前提（成長率、マージン、ドライバーの予想など）と、その**出典（`source`）**を書く |
| **ハーネス（このエンジン）** | spec から決まった手順で計算し、数値の出所と検証チェックを付け、ハッシュで再現性を保証する |

同じ spec からは、ビット単位で同じ結果（`meta.output_hash`）が出ます。シードなしの乱数や現在時刻は使いません。

## MECE カタログ（`GET /api/harness/catalog`、`backend/app/harness/__init__.py`）

業績予想に必要な作業を、重複も漏れもない 7 つの層に分けています。

| 層 | 問い | 内容 |
|---|---|---|
| **A. 統計推定** | データから関係をどう推定するか | OLS（係数、標準誤差、t 値、p 値、R²、調整済み R²、F 値、ダービン・ワトソン比、予測区間）、log-log 弾性値、時間トレンド（線形・対数線形）、時系列（CAGR、YoY、季節指数、Holt、AR(1)、naive、季節 naive）、ローリング検証による精度評価（MAPE、RMSE、バイアス） |
| **B. 売上の組み立て方** | 売上をどう積み上げるか（明細行ごとに 1 つ選ぶ） | 成長率、価格 × 数量、セグメントの合計、市場規模 × シェア、顧客数 × ARPU、受注残の消化、生産能力 × 稼働率 × 単価、既存店 + 新店、マクロ・業界ドライバーへの回帰、統計的な外挿 |
| **C. 費用構造** | 費用をどう置くか | 他の行に対する %、過去の平均比率、固定費 + 変動費（営業レバレッジを OLS で推定）、前年の基準値に対する %（減価償却など）、会社計画などの値をそのまま入力 |
| **D. 3 表の連動** | P&L → CF をどうつなぐか | 粗利 → 営業利益 → EBITDA → 税引前利益 → 税 → 少数株主持分 → 純利益 → EPS、運転資本（DSO、DIO、DPO）→ 運転資本の増減、FCFF = NOPAT + 減価償却 − 設備投資 − 運転資本の増加、配当と純資産の推移 |
| **E. バリュエーション** | 価値をどう出すか | WACC／CAPM、DCF（ゴードン成長モデル、EV/EBITDA のエグジットマルチプル）、倍率法（PER、EV/EBITDA、PBR）、DDM、残余利益モデル、現在株価との差 |
| **F. 不確実性** | 幅をどう示すか | シナリオ（確率で加重）、2 次元の感応度表、モンテカルロ（分布は正規、一様、三角、対数正規。シード固定） |
| **G. ガバナンス** | 数値をどう信用するか | 検証チェック、数値の出所、入力と出力の SHA-256、エンジンのバージョン、出典のない前提への警告 |

**会社ごとの「モデル」は、B と C から明細行ごとに作り方を選び、A で推定し、D と E は自動、F は任意で付け、G が常に検査する**、という組み合わせで表現します。

## spec の形式（JSON）

完全な例は [`models/examples/sample_manufacturer.json`](../models/examples/sample_manufacturer.json) にあります（数値は架空です）。

```jsonc
{
  "company": {"symbol": "TSE:7203", "name": "…", "currency": "JPY", "unit": "bn"},
  "history": {                       // 実績。各リストの長さは years と同じにする
    "years": ["FY2020", "FY2021", …],
    "revenue": […], "cogs": […], "sga": […], "da": […], "capex": […], "non_operating": […],
    "units": […], "industry_production": […]      // 任意の KPI やドライバー
  },
  "forecast_years": ["FY2025E", …],
  "lines": {                         // 明細行の作り方。依存関係は自動で解決（循環はエラー）
    "units":   {"method": "growth", "params": {"rates": [0.03, …], "source": "業界団体の見通し 2026/10"}},
    "price":   {"method": "growth", "params": {"base": 2.2, "rates": 0.01, "source": "…"}},
    "revenue": {"method": "price_volume", "params": {"volume": {"line": "units"}, "price": {"line": "price"}}},
    "cogs":    {"method": "fixed_variable", "params": {"of": "revenue"}},       // 固定費と変動費を OLS で推定
    "sga":     {"method": "hist_avg_pct_of", "params": {"of": "revenue", "years": 3}},
    "capex":   {"method": "pct_of", "params": {"of": "revenue", "pct": 0.054, "source": "中期経営計画"}},
    "da":      {"method": "pct_of_prior", "params": {"of": "capex", "pct": 0.75, "source": "…"}}
  },
  "assumptions": {"tax_rate": 0.30, "minority_pct": 0.02, "payout_ratio": 0.35,
                  "dso": 60, "dio": 50, "dpo": 45, "shares": 400, "per_share_factor": 1000},
  "valuation": {
    "wacc": {"rf": 0.01, "beta": 1.1, "erp": 0.06, "cost_of_debt": 0.012, "tax_rate": 0.3, "debt_weight": 0.2},
    "terminal_growth": 0.01, "exit_ev_ebitda": 7.0, "net_debt": 120, "book_equity": 900,
    "multiples": {"per": 13, "ev_ebitda": 7, "pbr": 1.1, "year_index": 0}, "current_price": 2000
  },
  "scenarios":   {"bull": {"lines.units.params.rates": [0.05, …], "probability": 0.25}, "base": {"probability": 0.5}, "bear": {…}},
  "sensitivity": {"x": {"path": "valuation.wacc.erp", "values": […]}, "y": {"path": "valuation.terminal_growth", "values": […]},
                  "output": "valuation.dcf.price_per_share"},
  "monte_carlo": {"n": 500, "seed": 7, "output": "valuation.dcf.price_per_share",
                  "drivers": {"lines.units.params.rates": {"dist": "normal", "mean": 0.025, "sd": 0.02}}},
  "checks": {"segments_sum_to": {"total": "revenue", "items": ["seg_a", "seg_b"]}},
  "report_outputs": ["valuation.dcf.price_per_share", "projection.derived.eps[0]"]
}
```

- 単位：金額は spec 内で揃えます（例：十億円）。`per_share_factor` は 1 株あたりの値に直す係数です（十億円 ÷ 百万株なら 1000）。
- パス記法：`lines.revenue.params.rates[0]`。リストの位置に数値を 1 つだけ入れると、全年度に同じ値が使われます。

### 明細行の作り方（18 種）と主なパラメータ

| method | params |
|---|---|
| values | values（会社計画などをそのまま入力） |
| growth | rates、base（省略時は実績の最終値） |
| cagr_trend | years |
| trend | kind = loglinear または linear |
| holt | alpha, beta |
| ar1 | — |
| pct_of | of, pct |
| hist_avg_pct_of | of, years |
| fixed_variable | of、fixed と variable_ratio（省略時は OLS で推定）、fixed_growth |
| pct_of_prior | of, pct |
| price_volume | volume, price（パス形式）、unit_factor |
| sum | items, signs |
| market_share | market_size, share |
| customers_arpu | customers, arpu, periods_per_year |
| backlog | orders, burn_rate, in_period_rate, backlog_start |
| capacity | capacity, utilization, price |
| stores | same_store_growth, new_stores, sales_per_new_store, first_year_ramp, base |
| driver_regression | drivers_history, drivers_future, transform = level、log、growth |

パス形式は `{"values": [...]}`、`{"start": x, "growth": g}`、`{"line": "他の行の名前"}` のいずれかです。

## 検証チェック（`harness/checks.py`）

| id | 内容 | 結果 |
|---|---|---|
| history_length | 実績の期数（5 期以上を推奨） | 3 期未満で FAIL |
| assumption_sources | 判断が入る前提に `source` がない | WARN |
| revenue_non_negative | 売上がマイナス | FAIL |
| segments_sum | セグメントの合計 ≠ 全体 | FAIL |
| *_margin_range | 予想マージンが、実績の平均 ± max(2σ, 3pp) を外れる | WARN |
| revenue_growth_outlier | 成長率が ±max(20%, 実績の最大値の 1.5 倍) を超える | WARN |
| tax_rate_bounds | 税率が 0〜50% の範囲外 | FAIL |
| regression_* | 小さいサンプル、残差の自己相関（DW）、見せかけの回帰の疑い | WARN |
| terminal_growth | 4% を超える | WARN |
| terminal_value_share | ターミナルバリューが EV の 85% を超える | WARN |
| ev_positive / valuation_* | EV ≤ 0、または計算エラー（g ≥ WACC など） | FAIL / WARN |

## AI と一緒に使うときの手順（ChatGPT などに渡す指示の例）

```
あなたの役割は spec(JSON) の作成・修正のみです。数値の計算は行わないでください。
1. GET /api/harness/catalog で利用可能な method を確認する
2. 会社の開示資料から history を転記し、各数値の出典をコメントで残す
3. 各 line の method を選び、判断を伴う params には必ず "source" を付ける
4. POST /api/harness/run を実行し、checks の WARN/FAIL を確認して spec を直す
5. 結論は result の数値と meta.input_hash を引用して書く(自分で計算した数値を書かない)
```

## 会社ごとのモデルを追加するには

1. `models/companies/<EXCHANGE>_<TICKER>.json` を作る（またはターミナルの MODEL 画面で SAVE する。保存先は data/store.json）
2. 実績は開示資料から転記する。将来は Excel のセルから読み込む機能を追加予定（ROADMAP）
3. 共通の明細行の作り方で表せない会社固有のロジックが必要になった場合は、`harness/lines.py` に新しい method を**汎用的な形で**追加し、テストと CATALOG と本ドキュメントを更新する。特定の会社名を含むコードは書かない
