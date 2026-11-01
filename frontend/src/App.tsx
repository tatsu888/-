// Terminal shell: command line, function keys, ticker tape, panel grid, status bar.
import { useCallback, useEffect, useState } from 'react';
import { CommandLine } from './components/CommandLine';
import { Clocks, FKeys, StatusBar, TickerTape } from './components/Chrome';
import { Ctx } from './ctx';
import { api } from './lib/api';
import { FUNCTIONS } from './lib/commands';
import { feed, useFeedMessages } from './lib/feed';
import { shortSym } from './lib/format';
import { PanelBoundary } from './components/ui';
import type { PanelState, Universe } from './lib/types';
import GP from './functions/GP';
import { BT, CORR, FACT, LAG } from './functions/Analytics';
import { ALRT, ECO, HELP, PORT, SRC } from './functions/Misc';
import { ListMonitor, Watchlist } from './functions/Monitor';
import { MODEL } from './functions/MODEL';
import { HMAP, MOST } from './functions/Screener';
import { DES, NEWS, NOTE, TA } from './functions/Security';
import { XLS } from './functions/XLS';

const DEFAULT_PANELS: PanelState[] = [
  { id: 'p1', fn: 'GP' },
  { id: 'p2', fn: 'W' },
  { id: 'p3', fn: 'WEI' },
  { id: 'p4', fn: 'DES' },
  { id: 'p5', fn: 'FX' },
  { id: 'p6', fn: 'N' },
];

function load<T>(k: string, d: T): T {
  try {
    const v = localStorage.getItem(k);
    return v ? (JSON.parse(v) as T) : d;
  } catch {
    return d;
  }
}
function save(k: string, v: unknown) {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* private mode etc. */
  }
}

feed.connect();

export default function App() {
  const [universe, setUniverse] = useState<Universe | null>(null);
  const [security, setSecurityRaw] = useState<string>(() => load('term.security', 'NASDAQ:AAPL'));
  const [panels, setPanels] = useState<PanelState[]>(() => load('term.panels', DEFAULT_PANELS));
  const [layout, setLayout] = useState<number>(() => load('term.layout', 4));
  const [focus, setFocus] = useState<string>('p1');
  const [toasts, setToasts] = useState<{ id: number; msg: string }[]>([]);
  const [provider, setProvider] = useState('');

  useEffect(() => {
    api.get<Universe>('/universe').then(setUniverse).catch(() => setUniverse(null));
    api.get<{ active: string }>('/providers').then((r) => setProvider(r.active)).catch(() => undefined);
  }, []);
  useEffect(() => save('term.security', security), [security]);
  useEffect(() => save('term.panels', panels), [panels]);
  useEffect(() => save('term.layout', layout), [layout]);

  const toast = useCallback((msg: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  useFeedMessages((m) => {
    if (m.type === 'alert') {
      const a = m.alert;
      const msg = `ALERT ${a.symbol} ${a.condition} ${a.value} @ ${a.trigger_price}${a.note ? ' — ' + a.note : ''}`;
      toast(msg);
      try {
        if (Notification?.permission === 'granted') new Notification('Analyst Terminal', { body: msg });
      } catch {
        /* ignore */
      }
    }
    if (m.type === 'provider') setProvider(m.provider);
  });

  const setSecurity = useCallback((s: string) => setSecurityRaw(s), []);
  const visible = panels.slice(0, layout);

  const run = useCallback(
    (fn: string, sec?: string, args?: string) => {
      if (sec) setSecurityRaw(sec);
      if (!fn) return;
      setPanels((ps) => ps.map((p) => (p.id === focus ? { ...p, fn, args, symbol: p.symbol && sec ? sec : p.symbol } : p)));
    },
    [focus],
  );

  async function switchProvider(name: string) {
    try {
      await api.post('/providers/active', { name });
      setProvider(name);
      toast(`DATA SOURCE → ${name.toUpperCase()}`);
    } catch (e: any) {
      toast(e.message);
    }
  }

  return (
    <Ctx.Provider value={{ universe, security, setSecurity, run, toast, provider }}>
      <div className="app">
        <div className="topbar">
          <span className="brand">ANALYST TERMINAL</span>
          <CommandLine />
          <Clocks />
        </div>
        <FKeys layout={layout} setLayout={setLayout} />
        <TickerTape />
        <div className={`grid l${layout}`}>
          {visible.map((p) => (
            <PanelView
              key={p.id}
              p={p}
              focused={p.id === focus}
              onFocus={() => setFocus(p.id)}
              security={p.symbol ?? security}
              onPin={() => setPanels((ps) => ps.map((x) => (x.id === p.id ? { ...x, symbol: x.symbol ? undefined : security } : x)))}
              onFn={(fn) => setPanels((ps) => ps.map((x) => (x.id === p.id ? { ...x, fn, args: undefined } : x)))}
              switchProvider={switchProvider}
            />
          ))}
        </div>
        <StatusBar onSwitch={switchProvider} />
        <div className="toast">
          {toasts.map((t) => (
            <div key={t.id}>{t.msg}</div>
          ))}
        </div>
      </div>
    </Ctx.Provider>
  );
}

function PanelView({ p, focused, onFocus, security, onPin, onFn, switchProvider }: {
  p: PanelState; focused: boolean; onFocus: () => void; security: string; onPin: () => void; onFn: (fn: string) => void; switchProvider: (n: string) => void;
}) {
  const def = FUNCTIONS.find((f) => f.code === p.fn);
  const usesSec = def?.needsSecurity || ['N', 'XLS', 'ALRT', 'LAG'].includes(p.fn);
  return (
    <div className={`panel ${focused ? 'focused' : ''}`} onMouseDown={onFocus}>
      <div className="phead">
        <select className="inp" value={p.fn} onChange={(e) => onFn(e.target.value)} style={{ background: '#ffa028', color: '#000', fontWeight: 700, border: 0 }}>
          {FUNCTIONS.map((f) => (
            <option key={f.code} value={f.code}>{f.code}</option>
          ))}
        </select>
        {usesSec && <span className="sec">{shortSym(security)}</span>}
        <span className="title">{def?.name}</span>
        <span className="sp" />
        {usesSec && (
          <span className={`pin ${p.symbol ? 'on' : ''}`} onClick={onPin} title={p.symbol ? 'pinned — click to follow the loaded security' : 'click to pin this panel to the current security'}>
            {p.symbol ? '📌' : '🔗'}
          </span>
        )}
      </div>
      <div className="pbody">
        <PanelBoundary resetKey={`${p.fn}|${security}|${p.args ?? ''}`}>
          <FunctionBody fn={p.fn} symbol={security} args={p.args} switchProvider={switchProvider} />
        </PanelBoundary>
      </div>
    </div>
  );
}

function FunctionBody({ fn, symbol, args, switchProvider }: { fn: string; symbol: string; args?: string; switchProvider: (n: string) => void }) {
  switch (fn) {
    case 'GP': return <GP key={symbol} symbol={symbol} />;
    case 'DES': return <DES symbol={symbol} />;
    case 'TA': return <TA symbol={symbol} />;
    case 'N': return <NEWS symbol={symbol} all={args === 'all'} />;
    case 'XLS': return <XLS key={symbol} symbol={symbol} args={args} />;
    case 'NOTE': return <NOTE symbol={symbol} />;
    case 'BT': return <BT symbol={symbol} />;
    case 'W': return <Watchlist />;
    case 'WEI': case 'FX': case 'RATES': case 'CMDTY': case 'CRYP': return <ListMonitor list={fn} />;
    case 'MOST': return <MOST args={args} />;
    case 'HMAP': return <HMAP />;
    case 'FACT': return <FACT args={args} />;
    case 'LAG': return <LAG args={args} symbol={symbol} />;
    case 'CORR': return <CORR args={args} />;
    case 'MODEL': return <MODEL />;
    case 'PORT': return <PORT />;
    case 'ALRT': return <ALRT symbol={symbol} />;
    case 'ECO': return <ECO />;
    case 'SRC': return <SRC onSwitch={switchProvider} />;
    default: return <HELP />;
  }
}
