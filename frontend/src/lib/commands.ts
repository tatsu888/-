// Terminal command-line grammar (Bloomberg-like):
//   <SECURITY> <FUNCTION> [args]     e.g. "AAPL GP", "TSE:7203 DES", "7203 XLS"
//   <FUNCTION> [args]                e.g. "WEI", "LAG oil_energy", "FACT JP"
//   <SECURITY>                       load security into focused panel's current function
export interface FnDef {
  code: string;
  name: string;
  desc: string;
  needsSecurity?: boolean;
  group: string;
}

export const FUNCTIONS: FnDef[] = [
  { code: 'GP', name: 'Graph Price', desc: 'チャート (足種/時間足/インジ/描画/比較)', needsSecurity: true, group: 'Security' },
  { code: 'DES', name: 'Description', desc: '銘柄概要・ファンダメンタルズ・パフォーマンス', needsSecurity: true, group: 'Security' },
  { code: 'TA', name: 'Technical Analysis', desc: 'テクニカル判定 (MA/オシレーター投票)', needsSecurity: true, group: 'Security' },
  { code: 'N', name: 'News', desc: 'ニュース (銘柄 or 全体)', group: 'Security' },
  { code: 'XLS', name: 'Excel Models', desc: '銘柄に紐づくExcelを表示 / Excelで開く / What-if', group: 'Security' },
  { code: 'NOTE', name: 'Notes', desc: '銘柄メモ', needsSecurity: true, group: 'Security' },
  { code: 'BT', name: 'Backtest', desc: '戦略バックテスト (SMA/EMA/RSI/ブレイクアウト)', needsSecurity: true, group: 'Analytics' },
  { code: 'BETA', name: 'Beta', desc: '回帰ベータ (raw/adjusted β, α, R², 散布図)', needsSecurity: true, group: 'Analytics' },
  { code: 'SPRD', name: 'Pair Spread', desc: 'ペアスプレッド (ヘッジ比率, z-score, 半減期, 共和分検定)', needsSecurity: true, group: 'Analytics' },
  { code: 'SEAS', name: 'Seasonality', desc: '季節性 (年×月リターン, 月別平均/勝率)', needsSecurity: true, group: 'Analytics' },
  { code: 'EVT', name: 'Event Study', desc: 'イベントスタディ (決算等の前後の異常リターン CAR)', needsSecurity: true, group: 'Analytics' },
  { code: 'RV', name: 'Relative Value', desc: '同業他社比較 (バリュエーション/収益性/パフォーマンスのパーセンタイル)', needsSecurity: true, group: 'Analytics' },
  { code: 'CYCL', name: 'Cycles / Fourier', desc: 'フーリエ変換: 支配的な周期・調和回帰予測・ナイーブ予測とのバックテスト', needsSecurity: true, group: 'Analytics' },
  { code: 'OV', name: 'Option Valuation', desc: 'オプション計算 (Black-Scholes, Greeks, IV)', needsSecurity: true, group: 'Analytics' },
  { code: 'EARN', name: 'Earnings Calendar', desc: '決算カレンダー (次回決算日, EPS予想)', group: 'Macro' },
  { code: 'W', name: 'Watchlist', desc: 'ウォッチリスト (複数・編集可)', group: 'Monitor' },
  { code: 'WEI', name: 'World Equity Indices', desc: '世界株価指数', group: 'Monitor' },
  { code: 'FX', name: 'Currencies', desc: '為替', group: 'Monitor' },
  { code: 'RATES', name: 'Govt Yields', desc: '国債利回り', group: 'Monitor' },
  { code: 'CMDTY', name: 'Commodities', desc: 'コモディティ', group: 'Monitor' },
  { code: 'CRYP', name: 'Crypto', desc: '暗号資産', group: 'Monitor' },
  { code: 'SCRN', name: 'Screen Builder', desc: '条件を組み立てるスクリーナー (PER/ROE/モメンタム…・保存可)', group: 'Monitor' },
  { code: 'TEAR', name: 'Tear Sheet', desc: '銘柄1枚サマリー (印刷/PDF)', needsSecurity: true, group: 'Security' },
  { code: 'MOST', name: 'Screener', desc: '値上がり/値下がり/出来高/時価総額 (TradingView scanner)', group: 'Monitor' },
  { code: 'HMAP', name: 'Heatmap', desc: 'マーケットヒートマップ (時価総額×騰落)', group: 'Monitor' },
  { code: 'PROP', name: 'Propagation Map', desc: '認識伝播マップ: ニッチ→マクロ投資家→日本株への伝播・未波及チェック・先行指標', group: 'Macro' },
  { code: 'MACRO', name: 'Macro Dashboard', desc: 'マクロ: 金利・カーブ・BEI・クレジット・ボラ・景気局面 (成長×インフレ)', group: 'Macro' },
  { code: 'FACT', name: 'Factor Analysis', desc: 'ファクター/スタイル分析 (ETF・クロスセクション・セクター)', group: 'Analytics' },
  { code: 'LAG', name: 'Lead-Lag', desc: 'タイムラグ分析 (原油→株, 米国テーマ→日本 等)', group: 'Analytics' },
  { code: 'CORR', name: 'Correlation', desc: '相関行列', group: 'Analytics' },
  { code: 'MODEL', name: 'Forecast Harness', desc: '業績予想ハーネス (決定的・検証付き)', group: 'Analytics' },
  { code: 'MRGN', name: 'Margin (信用残)', desc: '信用倍率・買残/売残の推移・出来高比・ランキング (JPX 週末残高)', group: 'Security' },
  { code: 'STK', name: 'Stock Page', desc: '個別銘柄ページ: 株価の要因分解（個社要因 vs ファクター・スタイル）・信用残・需給・三位一体・決算／書き起こし・ファイル・同業', needsSecurity: true, group: 'Security' },
  { code: 'FCTR', name: 'Factor Monitor', desc: 'ファクターの計測（Notion 04.4: スタイル・マクロ・セクター）— どのファクターが強いか、時点スライダー付き', group: 'Macro' },
  { code: 'FLOW', name: 'Global Flows', desc: 'グローバル資金フロー: アセットクラス／カントリー／セクター（米国・TOPIX-17）／スタイル（ETF）— CMF・OBV・売買代金・相対強度・設定解約、ルールによる読み', group: 'Macro' },
  { code: 'BRIEF', name: 'Morning Brief', desc: '朝のブリーフ（ルールベース）: 市場・マクロ局面・スタイル・三位一体 AUTO の変化・決算（今日/明日/今週/直近の反応）・ポートフォリオの決算リスク・信用残・データの状態。毎朝 AUTO が作成し .md で保存', group: 'Security' },
  { code: 'COV', name: 'Coverage (Notion)', desc: 'Notion の銘柄マスタからカバレッジを読み込み: 次回決算日→Notion の四半期ページ、セクター/ティッカー別フォルダ（OneDrive 可）、銘柄ごとに XLS・Excel・フォルダ・Notion・ファンダメンタル・レポート', group: 'Security' },
  { code: 'TRIN', name: 'Trinity Framework', desc: '投資の三位一体: AUTO（ルールベースで自動更新する全銘柄の判定）・パイプライン・裁定ルール（全タブのハブ）', group: 'Framework' },
  { code: 'SCORE', name: 'Scoring Sheet', desc: '評点表 (Weight×Score/AI/Prev → 3.4 ロング / 2.7 ショート) + 3.5句', needsSecurity: true, group: 'Framework' },
  { code: 'KELLY', name: 'Kelly Sizing', desc: '期待値・ケリー F=E/(XW×XL)・六つの原則・評点差→サイズ', group: 'Framework' },
  { code: 'RULE', name: 'Exposure Rules', desc: '六層のエクスポージャー規律 (L1 3%/2% … L6 グロス150–300%) 自動チェック', group: 'Framework' },
  { code: 'PAIR', name: 'Pair Check', desc: 'Pair Sigma・相関・Beta調整Net÷Gross・20日スプレッド入場ルール・ペア適性・A-1宣言', needsSecurity: true, group: 'Framework' },
  { code: 'SHRT', name: 'Short Models', desc: '空売り8モデル判定 (増速放緩・基金放棄・無利潤成長・シェア減少…)', needsSecurity: true, group: 'Framework' },
  { code: 'CHIP', name: 'Top/Bottom & Crowding', desc: '天井・底シグナル (回転率・信用残・配当利回り) と混雑度', needsSecurity: true, group: 'Framework' },
  { code: 'GATE', name: 'Idea Gates', desc: '関門チェックリスト ①〜⑤ + 四半期点検 Ⅰ〜Ⅳ・毎月リセット', group: 'Framework' },
  { code: 'GLQ', name: 'Growth × Liquidity', desc: '成長×流動性 4象限 (時計回り 4→1→2→3)・軌跡・次の象限・象限別リターン', group: 'Framework' },
  { code: 'XRAY', name: 'Factor X-ray', desc: 'リターン分解（マーケット/スタイル・マクロ/セクター/個別）と、ブックの意図しないファクター・ベット検知', needsSecurity: true, group: 'Framework' },
  { code: 'RRG', name: 'Relative Rotation', desc: 'セクター・ローテーション（TOPIX-17 / 米国セクター / カバレッジ）と売買代金による資金フローの代理', group: 'Framework' },
  { code: 'THEME', name: 'Theme Baskets', desc: 'テーマ・バスケット（事実→理由→バスケット）: 反応ラグのフェーズ、β中立スプレッド、バスケット買いの検出', group: 'Framework' },
  { code: 'PFND', name: 'Pair Finder', desc: 'サブセクター内のペア候補を自動スクリーニング（Pair Sigma・β調整・入場ルール・評点差→サイズ）', group: 'Framework' },
  { code: 'TRAK', name: 'Track Record', desc: '約定からの実績: ベイズ更新した勝率・平均勝ち/負け・ケリー・損益の形・週次/月次勝率', group: 'Framework' },
  { code: 'TXT', name: 'Transcripts', desc: '決算説明会の書き起こし: トーン・Lazy Prices差分・Q&A回避度・数字抽出・出典必須AIブリーフ検証', needsSecurity: true, group: 'Research' },
  { code: 'TRND', name: 'Attention Trends', desc: 'Google Trends (急騰・関連クエリ・株価との先行性) / X / StockTwits', needsSecurity: true, group: 'Research' },
  { code: 'PORT', name: 'Portfolio', desc: 'ポジション・損益・リスク (VaR, β, リスク寄与, ストレス)', group: 'Trading' },
  { code: 'ALRT', name: 'Alerts', desc: '価格アラート', group: 'Trading' },
  { code: 'ECO', name: 'Economic Calendar', desc: '経済指標カレンダー', group: 'Macro' },
  { code: 'SRC', name: 'Data Source', desc: 'データ取得元の切替 (TradingView / Yahoo / SIM)', group: 'System' },
  { code: 'HELP', name: 'Help', desc: 'コマンド一覧', group: 'System' },
];

export const FN_CODES = new Set(FUNCTIONS.map((f) => f.code));

export interface ParsedCommand {
  security?: string; // raw token, resolved later
  fn?: string;
  args?: string;
}

export function parseCommand(input: string): ParsedCommand {
  const toks = input.trim().replace(/<GO>$/i, '').trim().split(/\s+/).filter(Boolean);
  if (!toks.length) return {};
  const up = toks.map((t) => t.toUpperCase());
  if (FN_CODES.has(up[0])) return { fn: up[0], args: toks.slice(1).join(' ') || undefined };
  // Bloomberg style "7203 JP Equity GP": drop yellow-key words
  const yellow = new Set(['EQUITY', 'INDEX', 'CURNCY', 'CMDTY', 'CORP', 'GOVT', 'US', 'JP', 'LN', 'GY', 'HK']);
  const fnIdx = up.findIndex((t, i) => i > 0 && FN_CODES.has(t));
  const secToks = (fnIdx < 0 ? toks : toks.slice(0, fnIdx)).filter((t, i) => i === 0 || !yellow.has(t.toUpperCase()));
  return {
    security: secToks[0],
    fn: fnIdx < 0 ? undefined : up[fnIdx],
    args: fnIdx < 0 ? undefined : toks.slice(fnIdx + 1).join(' ') || undefined,
  };
}

/** Deterministic resolution without network: EXCH:TICKER kept, 4-digit -> TSE, 6 letters FX pair -> FX:. */
export function quickResolve(token: string): string | null {
  const t = token.trim().toUpperCase();
  if (t.includes(':')) return t;
  if (/^\d{4}$/.test(t) || /^\d{3}[A-Z]$/.test(t)) return `TSE:${t}`;
  if (/^(USD|EUR|JPY|GBP|AUD|CHF|CAD|NZD|CNH)(USD|EUR|JPY|GBP|AUD|CHF|CAD|NZD|CNH)$/.test(t)) return `FX:${t}`;
  if (/^[A-Z]{2,6}USDT$/.test(t)) return `BINANCE:${t}`;
  return null;
}
