// Terminal shell: command line, function keys, ticker tape, panel grid, status bar.
import { useCallback, useEffect, useState } from 'react';
import { CommandLine } from './components/CommandLine';
import { Clocks, FKeys, StatusBar, TickerTape } from './components/Chrome';
import { Ctx, useTerminal } from './ctx';
import { api, store } from './lib/api';
import { FUNCTIONS } from './lib/commands';
import { feed, useFeedMessages } from './lib/feed';
import { shortSym } from './lib/format';
import { PanelBoundary } from './components/ui';
import type { PanelState, Universe } from './lib/types';
import GP from './functions/GP';
import { BT, CORR, FACT, LAG } from './functions/Analytics';
import { ALRT, ECO, HELP, PORT, SRC } from './functions/Misc';
import { BETA, EARN, EVT, OV, RV, SEAS, SPRD } from './functions/Quant';
import { ListMonitor, Watchlist } from './functions/Monitor';
import { MODEL } from './functions/MODEL';
import { HMAP, MOST } from './functions/Screener';
import { DES, NEWS, NOTE, TA } from './functions/Security';
import { XLS } from './functions/XLS';
import { SCRN, TEAR } from './functions/Reports';
import { CYCL, MACRO, MRGN, PROP, TRND, TXT } from './functions/Research';
import { GLQ, TRIN } from './functions/Trinity';
import { PFND, RRG, THEME, TRAK, XRAY } from './functions/Insight';
import { COV } from './functions/Coverage';
import { FCTR, STK } from './functions/Stock';
import { FLOW } from './functions/Flows';
import { BRIEF } from './functions/Brief';
import { ECST } from './functions/Econ';
import { TOP } from './functions/Info';

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
  const [maxed, setMaxed] = useState<string | null>(null); // maximized panel id (double-click header)
  const [toasts, setToasts] = useState<{ id: number; msg: string }[]>([]);
  const [provider, setProvider] = useState('');
  const [workspaces, setWorkspaces] = useState<Record<string, { panels: PanelState[]; layout: number; security: string }>>({});

  useEffect(() => {
    api.get<Universe>('/universe').then(setUniverse).catch(() => setUniverse(null));
    api.get<{ active: string }>('/providers').then((r) => setProvider(r.active)).catch(() => undefined);
  }, []);
  useEffect(() => {
    store.get<Record<string, any>>('workspaces', {}).then(setWorkspaces);
  }, []);
  const wsApi = {
    names: Object.keys(workspaces),
    save: (name: string) => {
      const w = { ...workspaces, [name]: { panels, layout, security } };
      setWorkspaces(w);
      store.set('workspaces', w);
      toast(`workspace saved: ${name}`);
    },
    load: (name: string) => {
      const w = workspaces[name];
      if (!w) return;
      setPanels(w.panels);
      setLayout(w.layout);
      setSecurityRaw(w.security);
    },
    remove: (name: string) => {
      const w = { ...workspaces };
      delete w[name];
      setWorkspaces(w);
      store.set('workspaces', w);
    },
  };
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
    if (m.type === 'trinity') {
      const msg = `TRIN AUTO: ${m.changes.slice(0, 4).map((c: any) => `${c.symbol} ${c.from ?? ''}→${c.to}`).join(' · ')}${m.changes.length > 4 ? ` (+${m.changes.length - 4})` : ''}`;
      toast(msg);
    }
    if (m.type === 'earnings' && m.changes?.length) {
      toast(`決算日の更新: ${m.changes.slice(0, 3).map((c: any) => `${c.ticker} ${c.qid ?? ''} → ${c.to}`).join(' · ')}${m.changes.length > 3 ? ` (+${m.changes.length - 3})` : ''}`);
    }
    if (m.type === 'earnings_alert' && m.items?.length) {
      const msg = m.items.slice(0, 4).map((x: any) => x.kind === '明日決算'
        ? `明日決算 ${x.ticker} ${x.name ?? ''} ${x.label}（${x.status}${x.typical ? `、通常 ±${(x.typical * 100).toFixed(1)}%` : ''}）`
        : `決算反応 ${x.ticker} ${x.move >= 0 ? '+' : ''}${(x.move * 100).toFixed(1)}%（通常の ${x.times.toFixed(1)} 倍）`).join(' · ');
      toast(msg);
      try {
        if (Notification?.permission === 'granted') new Notification('Analyst Terminal — 決算', { body: msg });
      } catch {
        /* ignore */
      }
    }
    if (m.type === 'brief') toast(`朝のブリーフ ${m.date} を作成しました（BRIEF）`);
    if (m.type === 'info_alert' && m.items?.length) {
      const msg = m.items.slice(0, 3).map((x: any) => `${x.tickers?.length ? `[${x.tickers.join(',')}] ` : ''}${x.title}`).join(' · ');
      toast(`ニュース・開示: ${msg}${m.items.length > 3 ? ` (+${m.items.length - 3})` : ''}`);
      try {
        if (Notification?.permission === 'granted') new Notification('Analyst Terminal — ニュース・開示', { body: msg });
      } catch {
        /* ignore */
      }
    }
    if (m.type === 'econ_release' && m.items?.length) {
      toast(`統計の発表: ${m.items.slice(0, 4).map((x: any) => `${x.country} ${x.name} ${x.value?.toFixed?.(2) ?? x.value}${x.surprise != null && Math.abs(x.surprise) >= 1.5 ? `（サプライズ ${x.surprise > 0 ? '+' : ''}${x.surprise.toFixed(1)}）` : ''}`).join(' · ')}${m.items.length > 4 ? ` (+${m.items.length - 4})` : ''}`);
    }
  });

  const setSecurity = useCallback((s: string) => setSecurityRaw(s), []);
  const visible = maxed ? panels.filter((p) => p.id === maxed) : panels.slice(0, layout);

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
        <FKeys layout={layout} setLayout={setLayout} ws={wsApi} />
        <TickerTape />
        <div className={`grid l${maxed ? 1 : layout}`}>
          {visible.map((p) => (
            <PanelView
              key={p.id}
              p={p}
              focused={p.id === focus}
              onFocus={() => setFocus(p.id)}
              security={p.symbol ?? security}
              onPin={() => setPanels((ps) => ps.map((x) => (x.id === p.id ? { ...x, symbol: x.symbol ? undefined : security } : x)))}
              onFn={(fn) => setPanels((ps) => ps.map((x) => (x.id === p.id ? { ...x, fn, args: undefined } : x)))}
              maxed={maxed === p.id}
              onMax={() => setMaxed(maxed === p.id ? null : p.id)}
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

function PanelView({ p, focused, onFocus, security, onPin, onFn, switchProvider, maxed, onMax }: {
  p: PanelState; focused: boolean; onFocus: () => void; security: string; onPin: () => void; onFn: (fn: string) => void; switchProvider: (n: string) => void;
  maxed: boolean; onMax: () => void;
}) {
  const def = FUNCTIONS.find((f) => f.code === p.fn);
  const usesSec = def?.needsSecurity || ['N', 'XLS', 'ALRT', 'LAG'].includes(p.fn);
  return (
    <div className={`panel ${focused ? 'focused' : ''}`} onMouseDown={onFocus}>
      <div className="phead" onDoubleClick={(e) => (e.target as HTMLElement).tagName !== 'SELECT' && onMax()} title="double-click: maximize / restore">
        <select className="inp" value={p.fn} onChange={(e) => onFn(e.target.value)} style={{ background: '#ffa028', color: '#000', fontWeight: 700, border: 0 }}>
          {FUNCTIONS.map((f) => (
            <option key={f.code} value={f.code}>{f.code}</option>
          ))}
        </select>
        {usesSec && <span className="sec">{shortSym(security)}</span>}
        <span className="title">{def?.name}</span>
        <span className="sp" />
        <span className="pin" onClick={onMax} title={maxed ? 'restore layout' : 'maximize panel'}>{maxed ? '🗗' : '⤢'}</span>
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
  const { run, setSecurity } = useTerminal();
  switch (fn) {
    case 'GP': return <GP key={symbol} symbol={symbol} />;
    case 'DES': return <DES symbol={symbol} />;
    case 'TA': return <TA symbol={symbol} />;
    case 'N': return <NEWS symbol={symbol} all={args === 'all'} />;
    case 'XLS': return <XLS key={symbol} symbol={symbol} args={args} />;
    case 'NOTE': return <NOTE symbol={symbol} />;
    case 'BT': return <BT symbol={symbol} />;
    case 'BETA': return <BETA symbol={symbol} />;
    case 'SPRD': return <SPRD symbol={symbol} args={args} />;
    case 'SEAS': return <SEAS symbol={symbol} />;
    case 'EVT': return <EVT symbol={symbol} />;
    case 'RV': return <RV symbol={symbol} args={args} />;
    case 'OV': return <OV symbol={symbol} />;
    case 'EARN': return <EARN />;
    case 'TEAR': return <TEAR symbol={symbol} />;
    case 'CYCL': return <CYCL symbol={symbol} />;
    case 'PROP': return <PROP onChart={(s) => run('GP', s)} />;
    case 'MACRO': return <MACRO />;
    case 'MRGN': return <MRGN symbol={symbol} onPick={(s) => setSecurity(s)} />;
    case 'SCRN': return <SCRN />;
    case 'TRIN': return <TRIN symbol={symbol} tab={args?.toUpperCase() || 'AUTO'} onPick={(s) => setSecurity(s)} />;
    case 'SCORE': case 'KELLY': case 'RULE': case 'PAIR': case 'SHRT': case 'CHIP': case 'GATE':
      return <TRIN symbol={symbol} tab={fn} onPick={(s) => setSecurity(s)} />;
    case 'GLQ': return <GLQ />;
    case 'XRAY': return <XRAY symbol={symbol} />;
    case 'RRG': return <RRG args={args} />;
    case 'THEME': return <THEME />;
    case 'PFND': return <PFND />;
    case 'TRAK': return <TRAK />;
    case 'BRIEF': return <BRIEF />;
    case 'ECST': return <ECST args={args} />;
    case 'TOP': return <TOP args={args} />;
    case 'COV': return <COV />;
    case 'STK': return <STK key={symbol} symbol={symbol} />;
    case 'FCTR': return <FCTR />;
    case 'FLOW': return <FLOW args={args} />;
    case 'TXT': return <TXT symbol={symbol} />;
    case 'TRND': return <TRND symbol={symbol} />;
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
