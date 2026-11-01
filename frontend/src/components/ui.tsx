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
