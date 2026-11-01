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

const KEYS = ['GP', 'DES', 'TA', 'N', 'XLS', '|', 'W', 'WEI', 'FX', 'RATES', 'CMDTY', 'CRYP', 'MOST', 'HMAP', '|', 'FACT', 'LAG', 'CORR', 'BT', 'MODEL', '|', 'PORT', 'ALRT', 'ECO', 'NOTE', 'SRC', 'HELP'];

export function FKeys({ layout, setLayout }: { layout: number; setLayout: (n: number) => void }) {
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
