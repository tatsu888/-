// Ticker tape, function-key strip, clocks and status bar (data-source switch lives here).
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useFeedStatus, useQuotes } from '../lib/feed';
import { cls, fmtPct, fmtPrice, shortSym } from '../lib/format';
import { useTerminal } from '../ctx';

export function TickerTape() {
  const { universe, run } = useTerminal();
  const syms = universe?.tape ?? [];
  const quotes = useQuotes(syms);
  const items = syms.map((s) => quotes.get(s));
  return (
    <div className="tape">
      <div className="tape-inner">
        {syms.map((s, i) => (
          <span className="item" key={s} onClick={() => run('GP', s)}>
            <span className="sym">{shortSym(s)}</span>
            <span>{fmtPrice(items[i]?.last)}</span> <span className={cls(items[i]?.change_pct)}>{fmtPct(items[i]?.change_pct)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

const KEYS = ['BRIEF', 'COV', 'STK', 'GP', 'DES', 'TA', 'N', 'XLS', 'RV', 'MRGN', 'TEAR', '|', 'W', 'WEI', 'FX', 'RATES', 'CMDTY', 'CRYP', 'MOST', 'SCRN', 'HMAP', '|', 'TRIN', 'SCORE', 'RULE', 'GATE', 'GLQ', 'THEME', 'RRG', 'XRAY', 'PFND', 'TRAK', '|', 'PROP', 'MACRO', 'FCTR', 'FLOW', 'TRND', 'TXT', 'FACT', 'LAG', 'CORR', 'BETA', 'SPRD', 'SEAS', 'EVT', 'BT', 'OV', 'MODEL', '|', 'PORT', 'ALRT', 'ECO', 'EARN', 'NOTE', 'SRC', 'HELP'];

export interface WorkspaceApi {
  names: string[];
  save: (name: string) => void;
  load: (name: string) => void;
  remove: (name: string) => void;
}

/** Manual refresh of the rule-based AUTO Trinity run (also runs on a schedule on the server). */
function TrinityRefresh() {
  const { toast } = useTerminal();
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const r = await api.post<any>('/trinity/run', {});
      toast(`三位一体を更新: ${r.universe}銘柄 · L${r.book.longs}/S${r.book.shorts} · 変化 ${r.changes.length}件 (${r.seconds}s)`);
      window.dispatchEvent(new CustomEvent('trinity-updated'));
    } catch (e: any) {
      toast(`三位一体の更新に失敗: ${e.message}`);
    }
    setBusy(false);
  };
  return (
    <button className={`fkey ${busy ? 'y' : ''}`} onClick={go} disabled={busy} title="三位一体（AUTO）を今すぐ更新（通常は自動で定期実行）">
      {busy ? '⟳ 更新中…' : '⟳ 三位一体を更新'}
    </button>
  );
}

export function FKeys({ layout, setLayout, ws }: { layout: number; setLayout: (n: number) => void; ws: WorkspaceApi }) {
  const { run } = useTerminal();
  return (
    <div className="fkeys">
      {KEYS.map((k, i) =>
        k === '|' ? (
          <span key={i} className="fkey sep">
            │
          </span>
        ) : (
          <button key={k} className="fkey" onClick={() => run(k)}>
            {k}
          </button>
        ),
      )}
      <span className="fkey sep">│</span>
      {[1, 2, 3, 4, 6].map((n) => (
        <button key={n} className={`fkey ${layout === n ? 'y' : ''}`} onClick={() => setLayout(n)} title="panel layout">
          {n}▦
        </button>
      ))}
      <span className="fkey sep">│</span>
      <select
        className="fkey"
        value=""
        title="workspaces: saved panel layouts"
        onChange={(e) => {
          const v = e.target.value;
          if (v === '__save') {
            const n = prompt('workspace name (例: Morning, JP Semis, Earnings)');
            if (n) ws.save(n);
          } else if (v.startsWith('del:')) {
            if (confirm(`delete workspace ${v.slice(4)}?`)) ws.remove(v.slice(4));
          } else if (v) ws.load(v);
        }}
      >
        <option value="">WORKSPACE ▾</option>
        {ws.names.map((n) => <option key={n} value={n}>{n}</option>)}
        <option value="__save">+ SAVE CURRENT…</option>
        {ws.names.map((n) => <option key={'d' + n} value={`del:${n}`}>✕ delete {n}</option>)}
      </select>
      <span className="fkey sep">│</span>
      <TrinityRefresh />
    </div>
  );
}

function zoneTime(tz: string) {
  return new Date().toLocaleTimeString('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

export function Clocks() {
  const [, setT] = useState(0);
  useEffect(() => {
    const h = setInterval(() => setT((x) => x + 1), 1000);
    return () => clearInterval(h);
  }, []);
  return (
    <span className="clock">
      NY <b>{zoneTime('America/New_York')}</b> LDN <b>{zoneTime('Europe/London')}</b> TKY <b>{zoneTime('Asia/Tokyo')}</b>
    </span>
  );
}

export function StatusBar({ onSwitch }: { onSwitch: (p: string) => void }) {
  const { connected, health } = useFeedStatus();
  const { provider, security } = useTerminal();
  const [h, setH] = useState<any>(null);
  useEffect(() => {
    const load = () => api.get('/health').then(setH).catch(() => setH(null));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [provider]);
  const st = h?.status ?? health?.status;
  const color = !connected ? '#ff4545' : st === 'connected' ? '#2fd17a' : st === 'error' ? '#ff4545' : '#ffd84a';
  return (
    <div className="status">
      <span>
        <span className="dot" style={{ background: color }} />
        {connected ? 'WS OK' : 'WS DOWN'}
      </span>
      <span className="lbl">DATA SOURCE</span>
      <span className="src">
        {['tradingview', 'yahoo', 'sim'].map((p) => (
          <button key={p} className={`tb ${provider === p ? 'on' : ''}`} onClick={() => onSwitch(p)} title={`switch data source to ${p}`}>
            {p === 'tradingview' ? 'TRADINGVIEW' : p.toUpperCase()}
          </button>
        ))}
      </span>
      {provider === 'sim' && <span className="badge demo">SIMULATED DEMO DATA — NOT MARKET DATA</span>}
      <span className="muted">
        {st}
        {h?.detail ? ` · ${String(h.detail).slice(0, 90)}` : ''}
      </span>
      <span style={{ flex: 1 }} />
      <span className="yellow">{security}</span>
      <Clocks />
    </div>
  );
}
