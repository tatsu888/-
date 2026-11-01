// ECO (economic calendar), ALRT (alerts), PORT (portfolio), SRC (data source), HELP.
import { useEffect, useState } from 'react';
import { api, store } from '../lib/api';
import { FUNCTIONS } from '../lib/commands';
import { useFeedMessages, useQuotes } from '../lib/feed';
import { cls, fmtNum, fmtPct, fmtPrice, fmtTime, shortSym } from '../lib/format';
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
  const [form, setForm] = useState({ symbol, condition: 'cross_up', value: '', note: '' });
  const load = () => api.get<any[]>('/alerts').then(setList);
  useEffect(() => void load(), []);
  useEffect(() => setForm((f) => ({ ...f, symbol })), [symbol]);
  useFeedMessages((m) => m.type === 'alert' && load());
  const quotes = useQuotes([...new Set(list.map((a) => a.symbol))]);
  async function create() {
    try {
      await api.post('/alerts', { ...form, value: parseFloat(form.value) });
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
        <select className="inp" value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })}>
          {(universe?.alert_conditions ?? []).map((c) => <option key={c}>{c}</option>)}
        </select>
        <input className="inp" style={{ width: 90 }} value={form.value} placeholder="value" onChange={(e) => setForm({ ...form, value: e.target.value })} />
        <input className="inp" style={{ width: 160 }} value={form.note} placeholder="note" onChange={(e) => setForm({ ...form, note: e.target.value })} />
        <button className="tb green" onClick={create} disabled={!form.value}>CREATE</button>
        <button className="tb" onClick={() => Notification?.requestPermission?.()}>ENABLE DESKTOP NOTIFY</button>
      </div>
      <table className="t">
        <thead><tr><th className="l">SECURITY</th><th className="l">CONDITION</th><th>VALUE</th><th>LAST</th><th className="l">NOTE</th><th className="l">STATUS</th><th className="l">TRIGGERED</th><th /></tr></thead>
        <tbody>
          {list.map((a) => (
            <tr key={a.id}>
              <td className="l sym">{a.symbol}</td>
              <td className="l">{a.condition}</td>
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
      </div>
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
