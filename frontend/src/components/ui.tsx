// Small shared UI pieces.
import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import { cls, fmtChg, fmtPct, fmtPrice } from '../lib/format';
import type { Quote } from '../lib/types';

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): { data?: T; error?: string; loading: boolean; reload: () => void } {
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true });
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    fn().then(
      (data) => alive && setState({ data, loading: false }),
      (e) => alive && setState({ error: String(e.message ?? e), loading: false }),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { ...state, reload: () => setN((x) => x + 1) };
}

/** Price cell that flashes green/red when the value ticks. */
export function Flash({ value, children, className }: { value: number | null | undefined; children: React.ReactNode; className?: string }) {
  const prev = useRef(value);
  const [f, setF] = useState('');
  useEffect(() => {
    if (value != null && prev.current != null && value !== prev.current) {
      setF(value > prev.current ? 'flash-up' : 'flash-down');
      const t = setTimeout(() => setF(''), 800);
      prev.current = value;
      return () => clearTimeout(t);
    }
    prev.current = value;
  }, [value]);
  return <td className={`${className ?? ''} ${f}`}>{children}</td>;
}

export function QuoteCells({ q }: { q?: Quote }) {
  return (
    <>
      <Flash value={q?.last}>{fmtPrice(q?.last)}</Flash>
      <td className={cls(q?.change)}>{fmtChg(q?.change, q?.last)}</td>
      <td className={cls(q?.change_pct)}>{fmtPct(q?.change_pct)}</td>
    </>
  );
}

export function Loading({ what = 'LOADING' }: { what?: string }) {
  return <div className="note">{what}…</div>;
}

export function ErrorBox({ error }: { error?: string }) {
  if (!error) return null;
  return <div className="err">ERROR: {error}</div>;
}

export function DelayBadge({ q }: { q?: Quote }) {
  if (!q) return null;
  if (q.source === 'sim') return <span className="badge demo">DEMO</span>;
  if (q.delay_sec === 0) return <span className="badge live">RT</span>;
  if (q.delay_sec) return <span className="badge delay">D{Math.round(q.delay_sec / 60)}</span>;
  return <span className="badge delay">?</span>;
}

export function Bars({ values, labels, height = 120, band }: { values: (number | null)[]; labels: string[]; height?: number; band?: number }) {
  // simple SVG bar chart centred at zero (used for CCF / factor spreads)
  const w = Math.max(values.length * 26, 200);
  const max = Math.max(1e-9, ...values.map((v) => Math.abs(v ?? 0)), band ?? 0);
  const mid = height / 2;
  return (
    <svg width={w} height={height + 14} style={{ display: 'block' }}>
      <line x1={0} x2={w} y1={mid} y2={mid} stroke="#444" />
      {band != null && (
        <>
          <line x1={0} x2={w} y1={mid - (band / max) * (mid - 4)} y2={mid - (band / max) * (mid - 4)} stroke="#5ea9ff" strokeDasharray="3 3" />
          <line x1={0} x2={w} y1={mid + (band / max) * (mid - 4)} y2={mid + (band / max) * (mid - 4)} stroke="#5ea9ff" strokeDasharray="3 3" />
        </>
      )}
      {values.map((v, i) => {
        const h = ((v ?? 0) / max) * (mid - 4);
        return (
          <g key={i}>
            <rect x={i * 26 + 4} width={18} y={h >= 0 ? mid - h : mid} height={Math.abs(h)} fill={(v ?? 0) >= 0 ? '#2fd17a' : '#ff4545'}>
              <title>{`${labels[i]}: ${v?.toFixed(4)}`}</title>
            </rect>
            <text x={i * 26 + 13} y={height + 11} fill="#8a8a8a" fontSize={9} textAnchor="middle">
              {labels[i]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Keeps one broken panel from taking down the whole terminal. */
export class PanelBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null; key: string }> {
  state = { error: null as Error | null, key: this.props.resetKey };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  static getDerivedStateFromProps(props: { resetKey: string }, state: { error: Error | null; key: string }) {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }
  render() {
    if (this.state.error)
      return (
        <div className="err">
          PANEL ERROR: {this.state.error.message}
          <br />
          <button className="tb" onClick={() => this.setState({ error: null })}>RETRY</button>
        </div>
      );
    return this.props.children;
  }
}

/** Small SVG x/y chart: scatter points and/or a line, optional fitted line y = a + b·x, zero axes. */
export function XYChart({ points, line, fit, height = 220, xLabel, yLabel, fmt = (v: number) => v.toFixed(2) }: {
  points?: { x: number; y: number }[]; line?: { x: number; y: number }[]; fit?: { a: number; b: number };
  height?: number; xLabel?: string; yLabel?: string; fmt?: (v: number) => string;
}) {
  const all = [...(points ?? []), ...(line ?? [])];
  if (!all.length) return null;
  const W = 520, H = height, P = 34;
  let x0 = Math.min(...all.map((p) => p.x)), x1 = Math.max(...all.map((p) => p.x));
  let y0 = Math.min(...all.map((p) => p.y)), y1 = Math.max(...all.map((p) => p.y));
  if (x0 === x1) (x0 -= 1), (x1 += 1);
  if (y0 === y1) (y0 -= 1), (y1 += 1);
  const sx = (x: number) => P + ((x - x0) / (x1 - x0)) * (W - 2 * P);
  const sy = (y: number) => H - P + -((y - y0) / (y1 - y0)) * (H - 2 * P);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: 720, height: 'auto', display: 'block' }}>
      <rect x={P} y={P} width={W - 2 * P} height={H - 2 * P} fill="none" stroke="#2a2a2a" />
      {x0 < 0 && x1 > 0 && <line x1={sx(0)} x2={sx(0)} y1={P} y2={H - P} stroke="#444" />}
      {y0 < 0 && y1 > 0 && <line x1={P} x2={W - P} y1={sy(0)} y2={sy(0)} stroke="#444" />}
      {(points ?? []).map((p, i) => <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={1.8} fill="#ffa028" opacity={0.6} />)}
      {line && <polyline fill="none" stroke="#59e3ff" strokeWidth={2} points={line.map((p) => `${sx(p.x)},${sy(p.y)}`).join(' ')} />}
      {fit && <line x1={sx(x0)} y1={sy(fit.a + fit.b * x0)} x2={sx(x1)} y2={sy(fit.a + fit.b * x1)} stroke="#ff6ad5" strokeWidth={2} />}
      <text x={P} y={H - 8} fill="#8a8a8a" fontSize={10}>{fmt(x0)}</text>
      <text x={W - P} y={H - 8} fill="#8a8a8a" fontSize={10} textAnchor="end">{fmt(x1)}</text>
      <text x={4} y={P + 4} fill="#8a8a8a" fontSize={10}>{fmt(y1)}</text>
      <text x={4} y={H - P} fill="#8a8a8a" fontSize={10}>{fmt(y0)}</text>
      {xLabel && <text x={W / 2} y={H - 8} fill="#ffa028" fontSize={10} textAnchor="middle">{xLabel}</text>}
      {yLabel && <text x={P + 4} y={P - 8} fill="#ffa028" fontSize={10}>{yLabel}</text>}
    </svg>
  );
}
