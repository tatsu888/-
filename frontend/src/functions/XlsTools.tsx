// XLS helpers: format toolbar, history (backups → diff → restore), quick chart, find bar, selection stats.
import { useState } from 'react';
import { api } from '../lib/api';
import { fmtNum } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';

export const NUMBER_FORMATS: [string, string][] = [
  ['General', 'GEN'], ['#,##0', '#,##0'], ['#,##0.0', '#,##0.0'], ['#,##0.00', '.00'], ['0.0%', '0.0%'],
  ['0.00%', '0.00%'], ['0.0"x"', '0.0x'], ['#,##0;(#,##0)', '(acct)'], ['yyyy-mm-dd', 'date'],
];
export const FILLS: [string | null, string][] = [[null, 'none'], ['FFF2CC', 'yellow'], ['DDEBF7', 'blue'], ['E2EFDA', 'green'], ['EDEDED', 'gray'], ['FCE4D6', 'orange']];

export function FormatBar({ disabled, apply }: { disabled: boolean; apply: (fmt: Record<string, any>, label: string) => void }) {
  return (
    <div className="toolbar">
      <span className="lbl">FORMAT</span>
      <button className="tb" disabled={disabled} style={{ fontWeight: 700 }} onClick={() => apply({ bold: true }, 'bold')} title="Ctrl+B">B</button>
      <button className="tb" disabled={disabled} onClick={() => apply({ bold: false }, 'unbold')}>b</button>
      <button className="tb" disabled={disabled} style={{ fontStyle: 'italic' }} onClick={() => apply({ italic: true }, 'italic')}>I</button>
      <button className="tb" disabled={disabled} style={{ color: '#5ea9ff' }} onClick={() => apply({ font_color: '0000FF' }, 'input style')} title="アナリストの慣行: 入力値は青字">INPUT</button>
      <button className="tb" disabled={disabled} onClick={() => apply({ font_color: null }, 'black font')} title="数式は黒字">CALC</button>
      <span className="lbl">NUM</span>
      {NUMBER_FORMATS.map(([f, l]) => (
        <button key={f} className="tb" disabled={disabled} onClick={() => apply({ number_format: f }, `format ${l}`)} title={f}>{l}</button>
      ))}
      <span className="lbl">FILL</span>
      {FILLS.map(([c, l]) => (
        <button key={l} className="tb" disabled={disabled} title={l} onClick={() => apply({ fill: c }, `fill ${l}`)}
          style={{ background: c ? `#${c}` : undefined, color: c ? '#000' : undefined, minWidth: 22 }}>{c ? ' ' : '∅'}</button>
      ))}
      <span className="lbl">ALIGN</span>
      {(['left', 'center', 'right'] as const).map((a) => (
        <button key={a} className="tb" disabled={disabled} onClick={() => apply({ align: a }, `align ${a}`)}>{a[0].toUpperCase()}</button>
      ))}
    </div>
  );
}

export function HistoryPanel({ fileId, canWrite, onRestored, onJump }: { fileId: string; canWrite: boolean; onRestored: () => void; onJump: (sheet: string, addr: string) => void }) {
  const list = useAsync(() => api.get<any[]>('/excel/backups', { id: fileId }), [fileId]);
  const [sel, setSel] = useState<string | null>(null);
  const diff = useAsync(() => (sel ? api.get<any>('/excel/diff', { id: fileId, backup: sel }) : Promise.resolve(null)), [sel, fileId]);
  const [err, setErr] = useState<string>();
  if (list.loading) return <Loading />;
  const fmtTaken = (t: string) => `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)} ${t.slice(9, 11)}:${t.slice(11, 13)}:${t.slice(13, 15)}`;
  return (
    <div className="box" style={{ margin: 4, maxHeight: 320, overflow: 'auto', background: '#050505' }}>
      <h4>HISTORY — 書き込み前の自動スナップショット (.terminal_backups)。選択すると「その時点 → 現在」の変更セルを表示</h4>
      <ErrorBox error={list.error || err} />
      {!list.data?.length && <div className="note">no snapshots yet — they are created automatically before every edit from the terminal</div>}
      <div style={{ display: 'flex', gap: 8 }}>
        <table className="t" style={{ width: 260 }}>
          <tbody>
            {(list.data ?? []).map((b) => (
              <tr key={b.name} className={`click ${sel === b.name ? 'sel' : ''}`} onClick={() => setSel(b.name)}>
                <td className="l amber">{fmtTaken(b.taken)}{b.seq ? ` #${b.seq}` : ''}</td>
                <td className="muted">{fmtNum(b.size / 1024, 0)} KB</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ flex: 1 }}>
          {diff.loading && sel && <Loading />}
          {diff.data && (
            <>
              <div className="toolbar">
                <span>{diff.data.changes.length} changed cell(s){diff.data.truncated ? ' (truncated)' : ''}</span>
                {diff.data.sheets_added.length > 0 && <span className="up">+sheets: {diff.data.sheets_added.join(', ')}</span>}
                {diff.data.sheets_removed.length > 0 && <span className="down">−sheets: {diff.data.sheets_removed.join(', ')}</span>}
                <span style={{ flex: 1 }} />
                <button className="tb red" disabled={!canWrite} onClick={async () => {
                  if (!confirm(`${sel} の状態に戻しますか? (現在の状態もスナップショットとして保存されます)`)) return;
                  try {
                    await api.post('/excel/restore', { id: fileId, backup: sel });
                    list.reload();
                    onRestored();
                  } catch (e: any) {
                    setErr(e.message);
                  }
                }}>RESTORE THIS SNAPSHOT</button>
              </div>
              <table className="t">
                <thead><tr><th className="l">CELL</th><th className="l">BEFORE (snapshot)</th><th className="l">AFTER (now)</th></tr></thead>
                <tbody>
                  {diff.data.changes.slice(0, 500).map((c: any) => (
                    <tr key={c.sheet + c.addr} className="click" onClick={() => onJump(c.sheet, c.addr)}>
                      <td className="l amber">{c.sheet}!{c.addr}</td>
                      <td className="l muted">{c.before_f ?? ''} {c.before != null ? `= ${c.before}` : ''}</td>
                      <td className="l yellow">{c.after_f ?? ''} {c.after != null ? `= ${c.after}` : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const COLORS = ['#ffa028', '#59e3ff', '#ff6ad5', '#2fd17a', '#ffd84a', '#a98bff', '#ff4545', '#5ea9ff'];

/** Rows of the selection = series (first text cell of a row = series name). */
export function QuickChart({ block, kind, onClose }: { block: any[][]; kind: 'line' | 'bar'; onClose: () => void }) {
  const series = block
    .map((row, i) => {
      const name = typeof row[0] === 'string' ? row[0] : `row ${i + 1}`;
      const vals = (typeof row[0] === 'string' ? row.slice(1) : row).map((v) => (typeof v === 'number' ? v : null));
      return { name, vals };
    })
    .filter((s) => s.vals.some((v) => v != null));
  if (!series.length) return <div className="note">select a numeric range (rows = series; a text first column names each series) <button className="tb" onClick={onClose}>✕</button></div>;
  const n = Math.max(...series.map((s) => s.vals.length));
  const all = series.flatMap((s) => s.vals.filter((v): v is number => v != null));
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const W = 640, H = 220, P = 36;
  const x = (i: number) => P + (n <= 1 ? (W - 2 * P) / 2 : (i / (n - 1)) * (W - 2 * P));
  const y = (v: number) => H - P - ((v - lo) / (hi - lo || 1)) * (H - 2 * P);
  const bw = Math.max(2, (W - 2 * P) / n / (series.length + 1));
  return (
    <div className="box" style={{ margin: 4, background: '#050505' }}>
      <h4>QUICK CHART <button className="tb" onClick={onClose} style={{ float: 'right' }}>✕</button></h4>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: 820, display: 'block' }}>
        <line x1={P} x2={W - P} y1={y(0)} y2={y(0)} stroke="#444" />
        <text x={4} y={P} fill="#8a8a8a" fontSize={10}>{fmtNum(hi, 1)}</text>
        <text x={4} y={H - P} fill="#8a8a8a" fontSize={10}>{fmtNum(lo, 1)}</text>
        {series.map((s, si) =>
          kind === 'line' ? (
            <polyline key={s.name} fill="none" stroke={COLORS[si % COLORS.length]} strokeWidth={2}
              points={s.vals.map((v, i) => (v == null ? '' : `${x(i)},${y(v)}`)).filter(Boolean).join(' ')} />
          ) : (
            s.vals.map((v, i) => v == null ? null : (
              <rect key={`${s.name}${i}`} x={P + (i / n) * (W - 2 * P) + bw * si + bw / 2} width={bw} y={Math.min(y(v), y(0))} height={Math.abs(y(v) - y(0))} fill={COLORS[si % COLORS.length]}>
                <title>{`${s.name} [${i + 1}]: ${v}`}</title>
              </rect>
            ))
          ),
        )}
      </svg>
      <div className="toolbar">{series.map((s, i) => <span key={s.name} style={{ color: COLORS[i % COLORS.length] }}>■ {s.name}</span>)}</div>
    </div>
  );
}

export function selectionStats(values: unknown[]): { count: number; nums: number; sum: number; avg: number | null; min: number | null; max: number | null } {
  const nums = values.filter((v): v is number => typeof v === 'number' && isFinite(v));
  const sum = nums.reduce((a, b) => a + b, 0);
  return {
    count: values.filter((v) => v != null && v !== '').length, nums: nums.length, sum,
    avg: nums.length ? sum / nums.length : null, min: nums.length ? Math.min(...nums) : null, max: nums.length ? Math.max(...nums) : null,
  };
}

// ---------------------------------------------------------------- conditional formatting
export interface CfRule { ranges: string[]; type: string; operator?: string; values?: (number | null)[]; fill?: string; font?: string; bold?: boolean; cfvo?: { type: string; val: number | null }[]; colors?: string[]; color?: string; stop?: boolean }
export interface CfStyle { bg?: string; color?: string; bold?: boolean; bar?: { pct: number; color: string } }

function rangeCells(r: string, parse: (a: string) => [number, number], col: (n: number) => string): string[] {
  const [a, b] = r.split(':');
  const [r1, c1] = parse(a), [r2, c2] = parse(b ?? a);
  const out: string[] = [];
  for (let i = Math.min(r1, r2); i <= Math.max(r1, r2) && out.length < 20000; i++) for (let j = Math.min(c1, c2); j <= Math.max(c1, c2); j++) out.push(`${col(j)}${i}`);
  return out;
}

function mix(c1: string, c2: string, t: number): string {
  const a = [0, 2, 4].map((i) => parseInt(c1.slice(i, i + 2), 16)), b = [0, 2, 4].map((i) => parseInt(c2.slice(i, i + 2), 16));
  return '#' + a.map((v, i) => Math.round(v + (b[i] - v) * t).toString(16).padStart(2, '0')).join('');
}

/** Evaluate cellIs / colorScale / dataBar rules for a sheet → per-cell style overrides. */
export function buildConditionalFormats(rules: CfRule[] | undefined, value: (addr: string) => unknown, parse: (a: string) => [number, number], col: (n: number) => string): Record<string, CfStyle> {
  const out: Record<string, CfStyle> = {};
  for (const rule of [...(rules ?? [])].sort((x: any, y: any) => (x.priority ?? 0) - (y.priority ?? 0))) {
    const cells = rule.ranges.flatMap((r) => rangeCells(r, parse, col));
    const nums = cells.map((a) => value(a)).filter((v): v is number => typeof v === 'number');
    if (rule.type === 'cellIs') {
      const [x, y] = rule.values ?? [];
      const test = (v: number) => {
        switch (rule.operator) {
          case 'greaterThan': return x != null && v > x;
          case 'greaterThanOrEqual': return x != null && v >= x;
          case 'lessThan': return x != null && v < x;
          case 'lessThanOrEqual': return x != null && v <= x;
          case 'equal': return x != null && v === x;
          case 'notEqual': return x != null && v !== x;
          case 'between': return x != null && y != null && v >= Math.min(x, y) && v <= Math.max(x, y);
          case 'notBetween': return x != null && y != null && (v < Math.min(x, y) || v > Math.max(x, y));
          default: return false;
        }
      };
      for (const a of cells) {
        const v = value(a);
        if (typeof v === 'number' && test(v) && !out[a]?.bg) out[a] = { ...out[a], ...(rule.fill ? { bg: `#${rule.fill}` } : {}), ...(rule.font ? { color: `#${rule.font}` } : {}), ...(rule.bold ? { bold: true } : {}) };
      }
    } else if ((rule.type === 'colorScale' || rule.type === 'dataBar') && nums.length) {
      const sorted = [...nums].sort((p, q) => p - q);
      const lo = sorted[0], hi = sorted[sorted.length - 1];
      const point = (c?: { type: string; val: number | null }, fallback = lo) => {
        if (!c) return fallback;
        if (c.type === 'min') return lo;
        if (c.type === 'max') return hi;
        if (c.type === 'num' && c.val != null) return c.val;
        if (c.type === 'percent' && c.val != null) return lo + ((hi - lo) * c.val) / 100;
        if (c.type === 'percentile' && c.val != null) return sorted[Math.min(sorted.length - 1, Math.round(((sorted.length - 1) * c.val) / 100))];
        return fallback;
      };
      for (const a of cells) {
        const v = value(a);
        if (typeof v !== 'number') continue;
        if (rule.type === 'dataBar') {
          out[a] = { ...out[a], bar: { pct: hi === lo ? 100 : Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)), color: `#${rule.color ?? '638EC6'}` } };
        } else if (rule.colors && rule.colors.length >= 2 && !out[a]?.bg) {
          const cs = rule.colors;
          const p0 = point(rule.cfvo?.[0], lo), pN = point(rule.cfvo?.[cs.length - 1], hi);
          if (cs.length === 2) out[a] = { ...out[a], bg: mix(cs[0], cs[1], pN === p0 ? 0.5 : Math.max(0, Math.min(1, (v - p0) / (pN - p0)))) };
          else {
            const pm = point(rule.cfvo?.[1], (p0 + pN) / 2);
            out[a] = { ...out[a], bg: v <= pm ? mix(cs[0], cs[1], pm === p0 ? 1 : Math.max(0, Math.min(1, (v - p0) / (pm - p0)))) : mix(cs[1], cs[2], pN === pm ? 1 : Math.max(0, Math.min(1, (v - pm) / (pN - pm)))) };
          }
        }
      }
    }
  }
  return out;
}

/** {addr: options} for list data-validation (dropdown) cells. */
export function buildValidations(vals: { ranges: string[]; options: unknown[] }[] | undefined, parse: (a: string) => [number, number], col: (n: number) => string): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const v of vals ?? []) for (const r of v.ranges) for (const a of rangeCells(r, parse, col)) out[a] = v.options.map(String);
  return out;
}
