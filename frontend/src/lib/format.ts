// Number / time formatting helpers used across panels.
export function fmtPrice(v: number | null | undefined, ref?: number | null): string {
  if (v == null || !isFinite(v)) return '--';
  const a = Math.abs(ref ?? v);
  const d = a >= 1000 ? 2 : a >= 10 ? 2 : a >= 1 ? 4 : 5;
  return v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function fmtNum(v: number | null | undefined, d = 2): string {
  if (v == null || !isFinite(v)) return '--';
  return v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function fmtPct(v: number | null | undefined, d = 2, sign = true): string {
  if (v == null || !isFinite(v)) return '--';
  return `${sign && v > 0 ? '+' : ''}${v.toFixed(d)}%`;
}

export function fmtChg(v: number | null | undefined, ref?: number | null): string {
  if (v == null || !isFinite(v)) return '--';
  return `${v > 0 ? '+' : ''}${fmtPrice(v, ref)}`;
}

export function fmtBig(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '--';
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + 'T';
  if (a >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return v.toFixed(0);
}

export function fmtTime(epoch: number | null | undefined, withDate = false): string {
  if (!epoch) return '--';
  const d = new Date(epoch * 1000);
  const t = d.toLocaleTimeString('en-GB', { hour12: false });
  return withDate ? `${d.toLocaleDateString('en-CA')} ${t}` : t;
}

export function cls(v: number | null | undefined): string {
  if (v == null || !isFinite(v) || v === 0) return 'flat';
  return v > 0 ? 'up' : 'down';
}

/** Background colour for heatmaps: green for positive, red for negative, scaled by |v|/scale. */
export function heat(v: number | null | undefined, scale = 3): string {
  if (v == null || !isFinite(v)) return 'transparent';
  const a = Math.min(Math.abs(v) / scale, 1);
  return v >= 0 ? `rgba(0, 190, 90, ${0.15 + a * 0.65})` : `rgba(230, 40, 40, ${0.15 + a * 0.65})`;
}

export function shortSym(s: string): string {
  return s.includes(':') ? s.split(':')[1] : s;
}
