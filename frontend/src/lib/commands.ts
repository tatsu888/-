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
  { code: 'W', name: 'Watchlist', desc: 'ウォッチリスト (複数・編集可)', group: 'Monitor' },
  { code: 'WEI', name: 'World Equity Indices', desc: '世界株価指数', group: 'Monitor' },
  { code: 'FX', name: 'Currencies', desc: '為替', group: 'Monitor' },
  { code: 'RATES', name: 'Govt Yields', desc: '国債利回り', group: 'Monitor' },
  { code: 'CMDTY', name: 'Commodities', desc: 'コモディティ', group: 'Monitor' },
  { code: 'CRYP', name: 'Crypto', desc: '暗号資産', group: 'Monitor' },
  { code: 'MOST', name: 'Screener', desc: '値上がり/値下がり/出来高/時価総額 (TradingView scanner)', group: 'Monitor' },
  { code: 'HMAP', name: 'Heatmap', desc: 'マーケットヒートマップ (時価総額×騰落)', group: 'Monitor' },
  { code: 'FACT', name: 'Factor Analysis', desc: 'ファクター/スタイル分析 (ETF・クロスセクション・セクター)', group: 'Analytics' },
  { code: 'LAG', name: 'Lead-Lag', desc: 'タイムラグ分析 (原油→株, 米国テーマ→日本 等)', group: 'Analytics' },
  { code: 'CORR', name: 'Correlation', desc: '相関行列', group: 'Analytics' },
  { code: 'MODEL', name: 'Forecast Harness', desc: '業績予想ハーネス (決定的・検証付き)', group: 'Analytics' },
  { code: 'PORT', name: 'Portfolio', desc: 'ポジション・損益', group: 'Trading' },
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
