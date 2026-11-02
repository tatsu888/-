// ECO (economic calendar), ALRT (alerts), PORT (portfolio), SRC (data source), HELP.
import { useEffect, useState } from 'react';
import { api, store } from '../lib/api';
import { FUNCTIONS } from '../lib/commands';
import { useFeedMessages, useQuotes } from '../lib/feed';
import { cls, fmtNum, fmtPct, fmtPrice, fmtTime, heat, shortSym } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

export function ECO() {
  const [countries, setCountries] = useState('US,JP,EU,GB,CN,DE');
  const [minImp, setMinImp] = useState(0);
  const r = useAsync(() => api.get<any>('/calendar', { countries, days_back: 1, days_ahead: 10 }), [countries]);
  let lastDay = '';
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">COUNTRIES</span>
        <input className="inp" value={countries} onChange={(e) => setCountries(e.target.value.toUpperCase())} />
        <span className="lbl">IMPORTANCE ≥</span>
        {[-1, 0, 1].map((i) => (
          <button key={i} className={`tb ${minImp === i ? 'on' : ''}`} onClick={() => setMinImp(i)}>{['LOW', 'MED', 'HIGH'][i + 1]}</button>
        ))}
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {r.data?.errors?.length > 0 && <div className="note">{r.data.errors.join(' | ')}</div>}
      <table className="t">
        <thead><tr><th className="l">TIME</th><th className="l">CTRY</th><th className="l">EVENT</th><th className="l">PERIOD</th><th>ACTUAL</th><th>FORECAST</th><th>PRIOR</th><th className="l">IMP</th></tr></thead>
        <tbody>
          {(r.data?.items ?? []).filter((e: any) => (e.importance ?? 0) >= minImp).flatMap((e: any) => {
            const d = new Date(e.date);
            const day = d.toDateString();
            const rows = [];
            if (day !== lastDay) {
              lastDay = day;
              rows.push(<tr key={`d${day}`} className="group"><td colSpan={8}>{day}</td></tr>);
            }
            const beat = e.actual != null && e.forecast != null ? e.actual - e.forecast : null;
            rows.push(
              <tr key={e.id}>
                <td className="l muted">{d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</td>
                <td className="l amber">{e.country}</td>
                <td className="l">{e.title}</td>
                <td className="l muted">{e.period}</td>
                <td className={cls(beat)}>{e.actual ?? ''}{e.unit && e.actual != null ? e.unit : ''}</td>
                <td>{e.forecast ?? ''}</td>
                <td className="muted">{e.previous ?? ''}</td>
                <td className="l yellow">{'★'.repeat((e.importance ?? -1) + 2)}</td>
              </tr>,
            );
            return rows;
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ALRT({ symbol }: { symbol: string }) {
  const { universe, toast } = useTerminal();
  const [list, setList] = useState<any[]>([]);
  const [form, setForm] = useState({ symbol, condition: 'cross_up', value: '', note: '', interval: '1D' });
  const IND: Record<string, [string, string]> = {
    rsi_above: ['RSI(14) ≥', '70'], rsi_below: ['RSI(14) ≤', '30'], price_cross_sma_up: ['SMA period', '50'], price_cross_sma_down: ['SMA period', '50'],
    golden_cross: ['(SMA50/200)', '0'], dead_cross: ['(SMA50/200)', '0'], macd_cross_up: ['(12,26,9)', '0'], macd_cross_down: ['(12,26,9)', '0'],
    volume_spike: ['× 20-bar avg', '3'], breakout_high: ['N-bar high', '20'], breakout_low: ['N-bar low', '20'],
  };
  const isInd = form.condition in IND;
  const load = () => api.get<any[]>('/alerts').then(setList);
  useEffect(() => void load(), []);
  useEffect(() => setForm((f) => ({ ...f, symbol })), [symbol]);
  useFeedMessages((m) => m.type === 'alert' && load());
  const quotes = useQuotes([...new Set(list.map((a) => a.symbol))]);
  async function create() {
    try {
      await api.post('/alerts', { ...form, value: parseFloat(form.value || (isInd ? IND[form.condition][1] : '')) });
      setForm((f) => ({ ...f, value: '', note: '' }));
      load();
    } catch (e: any) {
      toast(e.message);
    }
  }
  return (
    <div>
      <div className="toolbar">
        <input className="inp" style={{ width: 130 }} value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })} />
        <select className="inp" value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value, value: '' })}>
          <optgroup label="price (every tick)">{(universe?.alert_conditions ?? []).filter((c) => !(c in IND)).map((c) => <option key={c}>{c}</option>)}</optgroup>
          <optgroup label="indicator (checked every minute)">{(universe?.alert_conditions ?? []).filter((c) => c in IND).map((c) => <option key={c}>{c}</option>)}</optgroup>
        </select>
        {isInd && <span className="lbl">{IND[form.condition][0]}</span>}
        <input className="inp" style={{ width: 90 }} value={form.value} placeholder={isInd ? IND[form.condition][1] : 'value'} onChange={(e) => setForm({ ...form, value: e.target.value })} />
        {isInd && (
          <select className="inp" value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })}>
            {['60', '240', '1D', '1W'].map((x) => <option key={x}>{x}</option>)}
          </select>
        )}
        <input className="inp" style={{ width: 160 }} value={form.note} placeholder="note" onChange={(e) => setForm({ ...form, note: e.target.value })} />
        <button className="tb green" onClick={create} disabled={!form.value && !isInd}>CREATE</button>
        <button className="tb" onClick={() => Notification?.requestPermission?.()}>ENABLE DESKTOP NOTIFY</button>
      </div>
      <table className="t">
        <thead><tr><th className="l">SECURITY</th><th className="l">CONDITION</th><th>VALUE</th><th>LAST</th><th className="l">NOTE</th><th className="l">STATUS</th><th className="l">TRIGGERED</th><th /></tr></thead>
        <tbody>
          {list.map((a) => (
            <tr key={a.id}>
              <td className="l sym">{a.symbol}</td>
              <td className="l">{a.condition}{a.kind === 'indicator' ? <span className="muted"> [{a.interval}]</span> : ''}</td>
              <td>{fmtNum(a.value, 4)}</td>
              <td>{fmtPrice(quotes.get(a.symbol)?.last)}</td>
              <td className="l muted">{a.note}</td>
              <td className="l">
                <button className={`tb ${a.active ? 'green' : ''}`} onClick={() => api.patch(`/alerts/${a.id}`, { active: !a.active }).then(load)}>{a.active ? 'ACTIVE' : 'OFF'}</button>
              </td>
              <td className="l muted">{a.triggered_at ? `${fmtTime(a.triggered_at, true)} @ ${fmtPrice(a.trigger_price)}` : ''}</td>
              <td><button className="tb red" onClick={() => api.del(`/alerts/${a.id}`).then(load)}>DEL</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {!list.length && <div className="note">no alerts. Alerts are evaluated server-side on every tick and pushed to all open terminals.</div>}
    </div>
  );
}

interface Pos { id: string; symbol: string; qty: number; cost: number; note?: string }

export function PORT() {
  const { setSecurity, security } = useTerminal();
  const [pos, setPos] = useState<Pos[] | null>(null);
  const [f, setF] = useState({ symbol: security, qty: '', cost: '' });
  useEffect(() => void store.get<Pos[]>('portfolio', []).then(setPos), []);
  useEffect(() => setF((x) => ({ ...x, symbol: security })), [security]);
  const quotes = useQuotes((pos ?? []).map((p) => p.symbol));
  const [tab, setTab] = useState<'pos' | 'risk' | 'blotter'>('pos');
  if (!pos) return <Loading />;
  const save = (p: Pos[]) => (setPos(p), store.set('portfolio', p));
  const rows = pos.map((p) => {
    const q = quotes.get(p.symbol);
    const mv = q?.last != null ? q.last * p.qty : null;
    const pnl = mv != null ? mv - p.cost * p.qty : null;
    const day = q?.change != null ? q.change * p.qty : null;
    return { p, q, mv, pnl, day };
  });
  const tot = rows.reduce((a, r) => ({ mv: a.mv + (r.mv ?? 0), pnl: a.pnl + (r.pnl ?? 0), day: a.day + (r.day ?? 0) }), { mv: 0, pnl: 0, day: 0 });
  return (
    <div>
      <div className="toolbar">
        <input className="inp" style={{ width: 130 }} value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} />
        <input className="inp" style={{ width: 80 }} placeholder="qty (−=short)" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} />
        <input className="inp" style={{ width: 80 }} placeholder="avg cost" value={f.cost} onChange={(e) => setF({ ...f, cost: e.target.value })} />
        <button className="tb green" disabled={!f.qty || !f.cost} onClick={() => save([...pos, { id: Math.random().toString(36).slice(2, 10), symbol: f.symbol, qty: +f.qty, cost: +f.cost }])}>ADD</button>
        <span className="muted">P&L in each security's own currency (no FX conversion)</span>
        <span style={{ flex: 1 }} />
        <button className={`tb ${tab === 'pos' ? 'on' : ''}`} onClick={() => setTab('pos')}>POSITIONS</button>
        <button className={`tb ${tab === 'risk' ? 'on' : ''}`} onClick={() => setTab('risk')} disabled={!pos.length}>RISK</button>
        <button className={`tb ${tab === 'blotter' ? 'on' : ''}`} onClick={() => setTab('blotter')}>BLOTTER</button>
      </div>
      {tab === 'risk' && <PortRisk positions={pos} />}
      {tab === 'blotter' && <Blotter onSync={(p) => (save(p), setTab('pos'))} />}
      {tab === 'pos' && (
      <table className="t">
        <thead><tr><th className="l">SECURITY</th><th>QTY</th><th>AVG COST</th><th>LAST</th><th>%CHG</th><th>MKT VAL</th><th>WEIGHT</th><th>DAY P&L</th><th>UNREAL P&L</th><th>P&L %</th><th /></tr></thead>
        <tbody>
          {rows.map(({ p, q, mv, pnl, day }) => (
            <tr key={p.id} className="click" onClick={() => setSecurity(p.symbol)}>
              <td className="l sym">{shortSym(p.symbol)}</td>
              <td>{fmtNum(p.qty, 0)}</td>
              <td>{fmtPrice(p.cost)}</td>
              <td>{fmtPrice(q?.last)}</td>
              <td className={cls(q?.change_pct)}>{fmtPct(q?.change_pct)}</td>
              <td>{fmtNum(mv, 0)}</td>
              <td>{mv != null && tot.mv ? fmtPct((mv / tot.mv) * 100, 1, false) : '--'}</td>
              <td className={cls(day)}>{fmtNum(day, 0)}</td>
              <td className={cls(pnl)}>{fmtNum(pnl, 0)}</td>
              <td className={cls(pnl)}>{pnl != null ? fmtPct((pnl / Math.abs(p.cost * p.qty)) * 100) : '--'}</td>
              <td><span className="muted" style={{ cursor: 'pointer' }} onClick={(e) => (e.stopPropagation(), save(pos.filter((x) => x.id !== p.id)))}>✕</span></td>
            </tr>
          ))}
          <tr className="group">
            <td>TOTAL</td><td /><td /><td /><td /><td style={{ textAlign: 'right' }}>{fmtNum(tot.mv, 0)}</td><td /><td style={{ textAlign: 'right' }} className={cls(tot.day)}>{fmtNum(tot.day, 0)}</td><td style={{ textAlign: 'right' }} className={cls(tot.pnl)}>{fmtNum(tot.pnl, 0)}</td><td /><td />
          </tr>
        </tbody>
      </table>
      )}
    </div>
  );
}

function PortRisk({ positions }: { positions: Pos[] }) {
  const [bench, setBench] = useState('SP:SPX');
  const [lookback, setLookback] = useState(252);
  const [base, setBase] = useState('USD');
  const [fxOn, setFxOn] = useState(true);
  const r = useAsync(() => api.post<any>('/analytics/portfolio_risk', { positions: positions.map((p) => ({ symbol: p.symbol, qty: p.qty })), benchmark: bench, lookback, base_currency: base, include_fx: fxOn }), [JSON.stringify(positions), bench, lookback, base, fxOn]);
  const d = r.data;
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">BENCHMARK</span>
        <input className="inp" style={{ width: 110 }} value={bench} onChange={(e) => setBench(e.target.value.toUpperCase())} />
        <span className="lbl">LOOKBACK</span>
        <select className="inp" value={lookback} onChange={(e) => setLookback(+e.target.value)}>{[60, 126, 252, 504].map((x) => <option key={x}>{x}</option>)}</select>
        <span className="lbl">BASE CCY</span>
        {['USD', 'JPY', 'EUR'].map((c) => <button key={c} className={`tb ${base === c ? 'on' : ''}`} onClick={() => setBase(c)}>{c}</button>)}
        <button className={`tb ${fxOn ? 'on' : ''}`} onClick={() => setFxOn(!fxOn)} title="include FX moves of non-base-currency positions in returns">FX RISK</button>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error || d?.error} />
      {d && !d.error && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>Gross / Net ({d.base_currency})</span><span>{fmtNum(d.gross_exposure, 0)} / {fmtNum(d.net_exposure, 0)} ({fmtPct(d.net_pct_of_gross, 0, false)})</span>
            <span>Vol (ann.)</span><span className="yellow">{fmtPct(d.vol_annual * 100, 1, false)}</span>
            <span>VaR 95% 1d</span><span className="down">{fmtPct(d.var_95_1d_pct, 2, false)} ({fmtNum(d.var_95_1d_amount, 0)})</span>
            <span>VaR 99% 1d</span><span className="down">{fmtPct(d.var_99_1d_pct, 2, false)} ({fmtNum(d.var_99_1d_amount, 0)})</span>
            <span>ES 95% / 99%</span><span className="down">{fmtPct(d.es_95_1d_pct, 2, false)} / {fmtPct(d.es_99_1d_pct, 2, false)}</span>
            <span>Beta</span><span>{fmtNum(d.beta, 2)}</span>
            <span>Max DD (hist.)</span><span className="down">{fmtPct(d.max_drawdown_pct, 1)}</span>
            <span>Window</span><span className="muted">{d.start} → {d.end} ({d.observations}d)</span>
          </div>
          <table className="t">
            <thead><tr><th className="l">SECURITY</th><th>WEIGHT</th><th>MKT VAL ({d.base_currency})</th><th>VOL</th><th>MARGINAL</th><th>RISK CONTRIB</th></tr></thead>
            <tbody>
              {Object.entries(d.positions).sort((a: any, b: any) => b[1].contribution_pct - a[1].contribution_pct).map(([s, x]: any) => (
                <tr key={s}>
                  <td className="l sym">{shortSym(s)}</td><td className={cls(x.weight)}>{fmtPct(x.weight * 100, 1)}</td>
                  <td>{fmtNum(x.market_value, 0)}</td><td>{fmtPct(x.vol_ann * 100, 1, false)}</td>
                  <td>{fmtPct(x.marginal * 100, 1, false)}</td>
                  <td style={{ background: heat(x.contribution_pct - 100 / Object.keys(d.positions).length, 30) }}>{fmtPct(x.contribution_pct, 1, false)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.stress_worst_benchmark_days && (
            <>
              <div className="note">STRESS — portfolio on the 5 worst benchmark days in the window</div>
              <table className="t">
                <thead><tr><th className="l">DATE</th><th>BENCHMARK</th><th>PORTFOLIO</th><th>P&L</th></tr></thead>
                <tbody>
                  {d.stress_worst_benchmark_days.map((x: any) => (
                    <tr key={x.date}><td className="l amber">{x.date}</td><td className="down">{fmtPct(x.benchmark_pct)}</td><td className={cls(x.portfolio_pct)}>{fmtPct(x.portfolio_pct)}</td><td className={cls(x.portfolio_amount)}>{fmtNum(x.portfolio_amount, 0)}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <div className="note">{d.note}</div>
          {Object.keys(d.errors ?? {}).length > 0 && <div className="note">⚠ {Object.entries(d.errors).map(([k, v]) => `${k}: ${v}`).join(' | ')}</div>}
        </>
      )}
    </div>
  );
}

export function SRC({ onSwitch }: { onSwitch: (p: string) => void }) {
  const r = useAsync(() => api.get<any>('/providers'), []);
  useEffect(() => {
    const t = setInterval(r.reload, 4000);
    return () => clearInterval(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!r.data) return <Loading />;
  return (
    <div className="pad">
      <p className="muted">
        データ取得元を手動で切り替えます。ストリーミング (W/WEI/GP のライブ更新) はアクティブなソースから配信されます。分析系 API は <span className="yellow">source=</span> パラメータで個別指定も可能です。
      </p>
      <table className="t">
        <thead><tr><th className="l">SOURCE</th><th className="l">DESCRIPTION</th><th className="l">STATUS</th><th className="l">DETAIL</th><th /></tr></thead>
        <tbody>
          {r.data.providers.map((p: any) => (
            <tr key={p.name}>
              <td className="l amber">{p.name}</td>
              <td className="l">{p.description}</td>
              <td className="l">{p.started ? p.status : 'not started'}</td>
              <td className="l muted" style={{ whiteSpace: 'normal' }}>{p.detail}</td>
              <td>{p.active ? <span className="badge live">ACTIVE</span> : <button className="tb" onClick={() => onSwitch(p.name)}>USE</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Diagnostics />
      <p className="muted">
        TradingView / Yahoo は非公式エンドポイントです。利用規約を確認のうえ、個人の調査用途で使用してください (docs/DATA_SOURCES.md)。未ログインの TradingView は多くの取引所で遅延データ (D15 等) です。
      </p>
    </div>
  );
}

export function HELP() {
  const { run } = useTerminal();
  const groups = [...new Set(FUNCTIONS.map((f) => f.group))];
  return (
    <div className="pad">
      <div className="yellow">COMMAND SYNTAX</div>
      <pre className="muted" style={{ margin: '4px 0 10px' }}>{`<SECURITY> <FUNCTION> <GO>     AAPL GP  ·  7203 DES  ·  NASDAQ:NVDA TA  ·  USDJPY GP
<FUNCTION> [args] <GO>         WEI  ·  MOST JP  ·  LAG oil_energy  ·  FACT JP
<SECURITY> <GO>                load security into the focused panel
Click a row = load security · Double-click = chart · Typing anywhere focuses the command line
Panels without 📌 follow the loaded security; 📌 pins a panel to its security.`}</pre>
      {groups.map((g) => (
        <div key={g} className="box" style={{ marginBottom: 6 }}>
          <h4>{g}</h4>
          <table className="t">
            <tbody>
              {FUNCTIONS.filter((f) => f.group === g).map((f) => (
                <tr key={f.code} className="click" onClick={() => run(f.code)}>
                  <td className="l amber" style={{ width: 70 }}>{f.code}</td>
                  <td className="l" style={{ width: 200 }}>{f.name}</td>
                  <td className="l muted">{f.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function Diagnostics() {
  const { toast } = useTerminal();
  const [rep, setRep] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  async function run() {
    setBusy(true);
    setErr(undefined);
    try {
      setRep(await api.get('/diagnose', { symbols: true }));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function copy() {
    const md = await fetch(api.url('/diagnose', { symbols: false, format: 'markdown' })).then((r) => r.text());
    try {
      await navigator.clipboard.writeText(md);
      toast('diagnostics report copied — paste it to your AI assistant');
    } catch {
      toast('clipboard unavailable');
    }
  }
  return (
    <div className="box" style={{ margin: '8px 0' }}>
      <h4>CONNECTIVITY DIAGNOSTICS（接続の自己診断）</h4>
      <div className="toolbar">
        <button className="tb green" onClick={run} disabled={busy}>{busy ? 'RUNNING… (~30s)' : 'RUN DIAGNOSTICS'}</button>
        <button className="tb" onClick={copy}>COPY REPORT FOR AI</button>
        <span className="muted">TradingView / Yahoo の各エンドポイントと、設定済みの全シンボルの実在を確認します</span>
      </div>
      <ErrorBox error={err} />
      {rep && (
        <table className="t">
          <thead><tr><th className="l">STATUS</th><th className="l">CHECK</th><th>MS</th><th className="l">DETAIL</th><th className="l">HINT</th></tr></thead>
          <tbody>
            {rep.checks.map((c: any) => (
              <tr key={c.check}>
                <td className="l"><span className={`badge ${c.status.toLowerCase()}`}>{c.status}</span></td>
                <td className="l amber">{c.check}</td>
                <td className="muted">{c.ms}</td>
                <td className="l" style={{ whiteSpace: 'normal' }}>{c.detail}</td>
                <td className="l muted" style={{ whiteSpace: 'normal' }}>{c.hint}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

interface Trade { id: string; time: string; symbol: string; side: 'buy' | 'sell'; qty: number; price: number; fee: number; note?: string }

function Blotter({ onSync }: { onSync: (p: Pos[]) => void }) {
  const { security, toast } = useTerminal();
  const [trades, setTrades] = useState<Trade[] | null>(null);
  const [f, setF] = useState({ time: new Date().toISOString().slice(0, 10), symbol: security, side: 'buy' as 'buy' | 'sell', qty: '', price: '', fee: '0', note: '' });
  const pnl = useAsync(() => api.get<any>('/analytics/blotter'), [trades?.length, JSON.stringify(trades)]);
  useEffect(() => void store.get<Trade[]>('trades', []).then(setTrades), []);
  useEffect(() => setF((x) => ({ ...x, symbol: security })), [security]);
  const quotes = useQuotes(Object.keys(pnl.data?.positions ?? {}));
  if (!trades) return <Loading />;
  const save = async (t: Trade[]) => {
    setTrades(t);
    await store.set('trades', t);
    pnl.reload();
  };
  const add = () => {
    if (!f.qty || !f.price) return;
    save([...trades, { id: Math.random().toString(36).slice(2, 10), time: f.time, symbol: f.symbol, side: f.side, qty: +f.qty, price: +f.price, fee: +f.fee || 0, note: f.note }]);
    setF({ ...f, qty: '', price: '', note: '' });
  };
  const positions = Object.entries<any>(pnl.data?.positions ?? {});
  return (
    <div>
      <div className="toolbar">
        <input className="inp" type="date" value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} />
        <input className="inp" style={{ width: 120 }} value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} />
        <button className={`tb ${f.side === 'buy' ? 'green' : ''}`} onClick={() => setF({ ...f, side: 'buy' })}>BUY</button>
        <button className={`tb ${f.side === 'sell' ? 'red' : ''}`} onClick={() => setF({ ...f, side: 'sell' })}>SELL</button>
        <input className="inp" style={{ width: 70 }} placeholder="qty" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} />
        <input className="inp" style={{ width: 80 }} placeholder="price" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} />
        <input className="inp" style={{ width: 60 }} placeholder="fee" value={f.fee} onChange={(e) => setF({ ...f, fee: e.target.value })} />
        <input className="inp" style={{ width: 160 }} placeholder="note / rationale" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        <button className="tb green" onClick={add}>ADD TRADE</button>
        <button className="tb" disabled={!positions.length} onClick={() => {
          const p: Pos[] = positions.filter(([, x]) => x.qty).map(([s, x]) => ({ id: s, symbol: s, qty: x.qty, cost: x.avg_cost }));
          if (confirm(`replace POSITIONS with ${p.length} positions from the blotter?`)) (onSync(p), toast('positions synced from blotter'));
        }}>SYNC → POSITIONS</button>
      </div>
      <div className="note">average-cost accounting · shorts supported · realized P&L net of fees: <span className={cls(pnl.data?.total_realized_net)}>{fmtNum(pnl.data?.total_realized_net, 0)}</span></div>
      <table className="t">
        <thead><tr><th className="l">SECURITY</th><th>QTY</th><th>AVG COST</th><th>LAST</th><th>UNREALIZED</th><th>REALIZED</th><th>FEES</th></tr></thead>
        <tbody>
          {positions.map(([s, x]) => {
            const last = quotes.get(s)?.last;
            const unreal = last != null && x.qty ? (last - x.avg_cost) * x.qty : null;
            return (
              <tr key={s}>
                <td className="l sym">{shortSym(s)}</td><td className={cls(x.qty)}>{fmtNum(x.qty, 0)}</td><td>{fmtPrice(x.avg_cost)}</td><td>{fmtPrice(last)}</td>
                <td className={cls(unreal)}>{fmtNum(unreal, 0)}</td><td className={cls(x.realized)}>{fmtNum(x.realized, 0)}</td><td className="muted">{fmtNum(x.fees, 0)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="note">TRADES</div>
      <table className="t">
        <thead><tr><th className="l">DATE</th><th className="l">SECURITY</th><th className="l">SIDE</th><th>QTY</th><th>PRICE</th><th>FEE</th><th className="l">NOTE</th><th /></tr></thead>
        <tbody>
          {[...trades].reverse().map((t) => (
            <tr key={t.id}>
              <td className="l muted">{t.time}</td><td className="l sym">{shortSym(t.symbol)}</td>
              <td className={`l ${t.side === 'buy' ? 'up' : 'down'}`}>{t.side.toUpperCase()}</td>
              <td>{fmtNum(t.qty, 0)}</td><td>{fmtPrice(t.price)}</td><td className="muted">{fmtNum(t.fee, 0)}</td>
              <td className="l muted">{t.note}</td>
              <td><span className="muted" style={{ cursor: 'pointer' }} onClick={() => confirm('delete trade?') && save(trades.filter((x) => x.id !== t.id))}>✕</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
