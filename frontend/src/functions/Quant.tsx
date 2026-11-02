// Quant tools: BETA, SPRD (pair spread), SEAS (seasonality), EVT (event study), RV (relative value),
// EARN (earnings calendar), OV (option valuation). Formulas: docs/ANALYTICS.md §6-§12.
import { useMemo, useState } from 'react';
import { api } from '../lib/api';
import { useQuotes } from '../lib/feed';
import { cls, fmtBig, fmtNum, fmtPct, heat, shortSym } from '../lib/format';
import { bs, impliedVol, type OptType } from '../lib/options';
import { ErrorBox, Loading, useAsync, XYChart } from '../components/ui';
import { WindowSlider, type WindowValue } from '../components/WindowSlider';
import { LineChart } from '../components/LineChart';
import { useTerminal } from '../ctx';

const BENCHES = ['SP:SPX', 'NASDAQ:NDX', 'TVC:NI225', 'TVC:TOPIX', 'TVC:SX5E'];
const pct = (v: number | null | undefined, d = 2) => fmtPct(v == null ? null : v * 100, d);

function BenchPick({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <>
      <span className="lbl">VS</span>
      <input className="inp" style={{ width: 110 }} list="bench-list" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} />
      <datalist id="bench-list">{BENCHES.map((b) => <option key={b} value={b} />)}</datalist>
    </>
  );
}

const defaultBench = (s: string) => (s.startsWith('TSE:') ? 'TVC:TOPIX' : 'SP:SPX');

// ---------------------------------------------------------------- BETA
export function BETA({ symbol }: { symbol: string }) {
  const [bench, setBench] = useState(defaultBench(symbol));
  const [iv, setIv] = useState('1D');
  const [w, setW] = useState<WindowValue>({ length: 500, offset: 0 });
  const r = useAsync(() => api.get<any>('/analytics/beta', { symbol, benchmark: bench, interval: iv, bars: w.length, end_offset: w.offset }), [symbol, bench, iv, w.length, w.offset]);
  const d = r.data;
  return (
    <div>
      <div className="toolbar">
        <BenchPick value={bench} onChange={setBench} />
        {['1D', '1W', '1M'].map((x) => <button key={x} className={`tb ${iv === x ? 'on' : ''}`} onClick={() => setIv(x)}>{x}</button>)}
      </div>
      <WindowSlider label="BARS" value={w} onChange={setW} min={60} max={2000} step={10} maxOffset={1000} />
      {r.loading && <Loading />}
      <ErrorBox error={r.error || d?.error} />
      {d && !d.error && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>Raw beta</span><span className="yellow">{fmtNum(d.beta, 3)}</span>
            <span>Adjusted β</span><span>{fmtNum(d.adjusted_beta, 3)}</span>
            <span>β std err</span><span>{fmtNum(d.beta_se, 3)} (t {fmtNum(d.beta_t, 1)})</span>
            <span>R²</span><span>{fmtNum(d.r2, 3)}</span>
            <span>Alpha (ann.)</span><span className={cls(d.alpha_annualized)}>{pct(d.alpha_annualized)}</span>
            <span>Alpha p-value</span><span>{fmtNum(d.alpha_p, 3)}</span>
            <span>Vol sec / bmk</span><span>{pct(d.vol_security, 1)} / {pct(d.vol_benchmark, 1)}</span>
            <span>Residual vol</span><span>{pct(d.residual_vol, 1)}</span>
          </div>
          <div className="note">{d.start} → {d.end} · N={d.observations} · adjusted β = 0.67·raw + 0.33 (Bloomberg/Blume)</div>
          <div className="pad">
            <XYChart points={d.points} fit={{ a: d.alpha_per_period, b: d.beta }} xLabel={`${shortSym(bench)} return`} yLabel={`${shortSym(symbol)} return`} fmt={(v) => (v * 100).toFixed(1) + '%'} />
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- SPRD
export function SPRD({ symbol, args }: { symbol: string; args?: string }) {
  const [a, setA] = useState(symbol);
  const [b, setB] = useState(args?.toUpperCase() || (symbol.startsWith('TSE:') ? 'TVC:TOPIX' : 'SP:SPX'));
  const [win, setWin] = useState(60);
  const [ez, setEz] = useState(2);
  const r = useAsync(() => api.get<any>('/analytics/spread', { a, b, window: win, entry_z: ez }), [a, b, win, ez]);
  const d = r.data;
  const lines = useMemo(() => (d?.series ? [{ name: 'z-score', data: d.series.z }] : []), [d]);
  const ratio = useMemo(() => (d?.series ? [{ name: `${shortSym(a)}/${shortSym(b)}`, data: d.series.ratio, color: '#ffa028' }] : []), [d, a, b]);
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">A</span><input className="inp" style={{ width: 120 }} value={a} onChange={(e) => setA(e.target.value.toUpperCase())} />
        <span className="lbl">B</span><input className="inp" style={{ width: 120 }} value={b} onChange={(e) => setB(e.target.value.toUpperCase())} />
        <span className="lbl">Z WINDOW</span><select className="inp" value={win} onChange={(e) => setWin(+e.target.value)}>{[20, 40, 60, 120, 250].map((x) => <option key={x}>{x}</option>)}</select>
        <span className="lbl">ENTRY |z|</span><select className="inp" value={ez} onChange={(e) => setEz(+e.target.value)}>{[1.5, 2, 2.5, 3].map((x) => <option key={x}>{x}</option>)}</select>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error || d?.error} />
      {d && !d.error && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>Hedge ratio</span><span className="yellow">{fmtNum(d.hedge_ratio, 3)}</span>
            <span>ADF t (EG)</span><span>{fmtNum(d.adf.t_stat, 2)}</span>
            <span>Cointegrated</span><span className={d.cointegrated_at ? 'up' : 'down'}>{d.cointegrated_at ? `YES (${d.cointegrated_at})` : 'NO'}</span>
            <span>Half-life</span><span>{d.half_life != null ? `${fmtNum(d.half_life, 1)} days` : 'n/a (not mean-reverting)'}</span>
            <span>z (last)</span><span className={cls(-(d.z_last ?? 0))}>{fmtNum(d.z_last, 2)}</span>
            <span>Signal</span><span className="amber">{d.signal}</span>
            <span>Return corr</span><span>{fmtNum(d.correlation_returns, 2)}</span>
            <span>N</span><span>{d.observations}</span>
          </div>
          <div className="note">spread = ln A − h·ln B − c (OLS) · EG critical: 1% {d.eg_critical['1%']}, 5% {d.eg_critical['5%']}, 10% {d.eg_critical['10%']} · signal is mechanical (|z| ≥ entry), not advice</div>
          <div className="note">Z-SCORE ({win}d rolling)</div>
          <LineChart lines={lines} height={200} baseline={0} />
          <div className="note">PRICE RATIO A/B</div>
          <LineChart lines={ratio} height={160} />
          <PairBacktest a={a} b={b} entryZ={ez} zWindow={win} />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- SEAS
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function SEAS({ symbol }: { symbol: string }) {
  const r = useAsync(() => api.get<any>('/analytics/seasonality', { symbol }), [symbol]);
  const d = r.data;
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorBox error={r.error} />;
  return (
    <div>
      <div className="note">Monthly returns (%) of {symbol} — month-end close to month-end close · last row: average / % positive</div>
      <table className="t">
        <thead><tr><th className="l">YEAR</th>{MONTHS.map((m) => <th key={m}>{m}</th>)}<th>YEAR</th></tr></thead>
        <tbody>
          {[...(d.years as number[])].reverse().map((y) => (
            <tr key={y}>
              <td className="l amber">{y}</td>
              {MONTHS.map((_, i) => {
                const v = d.table[String(y)]?.[String(i + 1)];
                return <td key={i} style={{ background: heat(v, 8) }}>{fmtNum(v, 1)}</td>;
              })}
              <td style={{ background: heat(d.yearly[String(y)], 25) }}>{fmtNum(d.yearly[String(y)], 1)}</td>
            </tr>
          ))}
          <tr className="group"><td colSpan={14}>STATISTICS</td></tr>
          <tr><td className="l amber">Average</td>{d.month_stats.map((m: any) => <td key={m.month} style={{ background: heat(m.mean, 4) }}>{fmtNum(m.mean, 2)}</td>)}<td /></tr>
          <tr><td className="l amber">Median</td>{d.month_stats.map((m: any) => <td key={m.month}>{fmtNum(m.median, 2)}</td>)}<td /></tr>
          <tr><td className="l amber">% Positive</td>{d.month_stats.map((m: any) => <td key={m.month} className={m.pct_positive >= 60 ? 'up' : m.pct_positive <= 40 ? 'down' : ''}>{fmtNum(m.pct_positive, 0)}</td>)}<td /></tr>
          <tr><td className="l amber">N</td>{d.month_stats.map((m: any) => <td key={m.month} className="muted">{m.n}</td>)}<td /></tr>
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- EVT
export function EVT({ symbol }: { symbol: string }) {
  const [bench, setBench] = useState(defaultBench(symbol));
  const [dates, setDates] = useState('');
  const [pre, setPre] = useState(5);
  const [post, setPost] = useState(10);
  const [run, setRun] = useState(0);
  const events = dates.split(/[\s,;]+/).filter((x) => /^\d{4}-\d{2}-\d{2}$/.test(x));
  const r = useAsync(() => api.post<any>('/analytics/event_study', { symbol, benchmark: bench, events, pre, post }), [symbol, bench, pre, post, run]);
  const d = r.data;
  const line = d?.mean_car ? d.relative_days.map((x: number, i: number) => ({ x, y: d.mean_car[i] })) : undefined;
  return (
    <div>
      <div className="toolbar">
        <BenchPick value={bench} onChange={setBench} />
        <span className="lbl">PRE</span><input className="inp" style={{ width: 36 }} value={pre} onChange={(e) => setPre(+e.target.value || 0)} />
        <span className="lbl">POST</span><input className="inp" style={{ width: 36 }} value={post} onChange={(e) => setPost(+e.target.value || 1)} />
        <span className="lbl">EVENT DATES</span>
        <input className="inp" style={{ flex: 1, minWidth: 200 }} value={dates} placeholder="2025-01-30, 2025-04-30 … (空欄 = 大きな値動きの日を自動検出)" onChange={(e) => setDates(e.target.value)} />
        <button className="tb green" onClick={() => setRun((x) => x + 1)}>RUN</button>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error || d?.error} />
      {d && !d.error && (
        <>
          <div className="note">
            {d.auto_events ? 'AUTO: days with |return| > 2.5σ (proxy for news/earnings). ' : ''}Market model vs {d.benchmark} · {d.n_events} events ·
            CAR[{-pre},+{post}] = <span className={cls(d.mean_car[d.mean_car.length - 1])}>{pct(d.mean_car[d.mean_car.length - 1])}</span>
            {' '}(t {fmtNum(d.t_car[d.t_car.length - 1], 2)}, p {fmtNum(d.p_final, 3)}) · positive {fmtNum(d.pct_positive_final, 0)}%
          </div>
          <div className="pad"><XYChart line={line} xLabel="days relative to event" yLabel="mean CAR" fmt={(v) => (Math.abs(v) < 1 && !Number.isInteger(v) ? (v * 100).toFixed(1) + '%' : v.toFixed(0))} /></div>
          <table className="t">
            <thead><tr><th className="l">EVENT</th><th className="l">DAY 0</th><th>β</th><th>AR day0</th><th>CAR pre</th><th>CAR post</th><th>CAR total</th><th>t</th></tr></thead>
            <tbody>
              {d.events.map((e: any) => (
                <tr key={e.event}>
                  <td className="l amber">{e.event}</td>
                  {e.error ? <td colSpan={7} className="l down">{e.error}</td> : (
                    <>
                      <td className="l muted">{e.day0}</td><td>{fmtNum(e.beta, 2)}</td>
                      <td className={cls(e.ar_day0)}>{pct(e.ar_day0)}</td><td className={cls(e.car_pre)}>{pct(e.car_pre)}</td>
                      <td className={cls(e.car_post)}>{pct(e.car_post)}</td><td className={cls(e.car_total)}>{pct(e.car_total)}</td>
                      <td>{fmtNum(e.t_car_total, 2)}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- RV
const RV_COLS: [string, string, (v: any) => string, boolean][] = [
  ['market_cap_basic', 'MKT CAP', fmtBig, true], ['price_earnings_ttm', 'P/E', (v) => fmtNum(v, 1), false],
  ['price_book_ratio', 'P/B', (v) => fmtNum(v, 2), false], ['enterprise_value_ebitda_ttm', 'EV/EBITDA', (v) => fmtNum(v, 1), false],
  ['dividend_yield_recent', 'DIV %', (v) => fmtNum(v, 2), true], ['return_on_equity', 'ROE %', (v) => fmtNum(v, 1), true],
  ['operating_margin', 'OPM %', (v) => fmtNum(v, 1), true], ['debt_to_equity', 'D/E', (v) => fmtNum(v, 2), false],
  ['beta_1_year', 'β', (v) => fmtNum(v, 2), false], ['hist_1M', '1M %', (v) => fmtNum(v, 1), true],
  ['hist_YTD', 'YTD %', (v) => fmtNum(v, 1), true], ['hist_1Y', '1Y %', (v) => fmtNum(v, 1), true], ['vol_1Y', 'VOL %', (v) => fmtNum(v, 1), false],
];
export function RV({ symbol, args }: { symbol: string; args?: string }) {
  const { universe, setSecurity } = useTerminal();
  const def = args || (universe?.lists.W ?? []).map((i) => i.symbol).filter((s) => s !== symbol && s.split(':')[0] === symbol.split(':')[0]).slice(0, 8).join(',');
  const [peers, setPeers] = useState(def);
  const [input, setInput] = useState(def);
  const r = useAsync(() => (peers ? api.get<any>('/analytics/relative_value', { symbol, peers }) : Promise.resolve(null)), [symbol, peers]);
  const d = r.data;
  const cols = RV_COLS.filter(([k]) => d && Object.values(d.rows).some((row: any) => row[k] != null));
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">PEERS</span>
        <input className="inp" style={{ flex: 1, minWidth: 200 }} value={input} onChange={(e) => setInput(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === 'Enter' && setPeers(input)} placeholder="NASDAQ:MSFT,NASDAQ:GOOGL …" />
        <button className="tb" onClick={() => setPeers(input)}>RUN</button>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <>
          <table className="t">
            <thead><tr><th className="l">SECURITY</th><th className="l">NAME</th>{cols.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
            <tbody>
              {d.peers.map((s: string) => (
                <tr key={s} className={`click ${s === symbol ? 'sel' : ''}`} onClick={() => setSecurity(s)}>
                  <td className="l sym">{shortSym(s)}</td>
                  <td className="l name">{d.rows[s]?.description ?? ''}</td>
                  {cols.map(([k, , f]) => <td key={k}>{d.rows[s]?.[k] != null ? f(d.rows[s][k]) : '--'}</td>)}
                </tr>
              ))}
              <tr className="group"><td colSpan={2 + cols.length}>PEER MEDIAN · {shortSym(symbol)} PERCENTILE (0 = lowest, 100 = highest)</td></tr>
              <tr><td className="l amber">Median</td><td />{cols.map(([k, , f]) => <td key={k}>{d.stats[k] ? f(d.stats[k].median) : '--'}</td>)}</tr>
              <tr>
                <td className="l amber">Percentile</td><td />
                {cols.map(([k, , , higherBetter]) => {
                  const p = d.stats[k]?.percentile;
                  return <td key={k} style={{ background: heat(p == null ? null : (higherBetter ? p - 50 : 50 - p), 50) }}>{fmtNum(p, 0)}</td>;
                })}
              </tr>
              <tr><td className="l amber">vs median</td><td />{cols.map(([k]) => <td key={k} className={cls(d.stats[k]?.vs_median_pct)}>{fmtPct(d.stats[k]?.vs_median_pct, 0)}</td>)}</tr>
            </tbody>
          </table>
          <div className="note">colour: green = favourable vs peers (cheap valuation / high return & quality). Fundamentals: TradingView scanner; performance: daily history.</div>
          {Object.keys(d.errors ?? {}).length > 0 && <div className="note">unavailable: {Object.entries(d.errors).map(([k, v]) => `${k}: ${v}`).join(' | ')}</div>}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- EARN
export function EARN() {
  const { universe, setSecurity } = useTerminal();
  const def = (universe?.lists.W ?? []).map((i) => i.symbol).join(',');
  const [syms, setSyms] = useState(def);
  const [input, setInput] = useState(def);
  const r = useAsync(() => (syms ? api.get<any>('/analytics/earnings', { symbols: syms }) : Promise.resolve(null)), [syms]);
  const day = (t: number | null | undefined) => (t ? new Date(t * 1000).toISOString().slice(0, 10) : '--');
  const now = Date.now() / 1000;
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">SYMBOLS</span>
        <input className="inp" style={{ flex: 1, minWidth: 200 }} value={input} onChange={(e) => setInput(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === 'Enter' && setSyms(input)} />
        <button className="tb" onClick={() => setSyms(input)}>RUN</button>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {r.data?.errors?.length > 0 && <div className="note">{r.data.errors.join(' | ')}</div>}
      <table className="t">
        <thead><tr><th className="l">NEXT REPORT</th><th className="l">DAYS</th><th className="l">SECURITY</th><th className="l">NAME</th><th>EPS EST (next)</th><th>EPS (last)</th><th>REV EST (next)</th><th className="l">LAST REPORT</th></tr></thead>
        <tbody>
          {(r.data?.rows ?? []).map((x: any) => {
            const days = x.earnings_release_next_date ? Math.round((x.earnings_release_next_date - now) / 86400) : null;
            return (
              <tr key={x.symbol} className="click" onClick={() => setSecurity(x.symbol)}>
                <td className="l amber">{day(x.earnings_release_next_date)}</td>
                <td className={`l ${days != null && days <= 7 ? 'yellow' : 'muted'}`}>{days != null ? `${days}d` : ''}</td>
                <td className="l sym">{shortSym(x.symbol)}</td>
                <td className="l name">{x.description}</td>
                <td>{fmtNum(x.earnings_per_share_forecast_next_fq, 2)}</td>
                <td>{fmtNum(x.earnings_per_share_fq, 2)}</td>
                <td>{fmtBig(x.revenue_forecast_next_fq)}</td>
                <td className="l muted">{day(x.earnings_release_date)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="note">source: TradingView scanner (column names unverified — see docs/DATA_SOURCES.md). Use EVT with these dates to study post-earnings drift.</div>
    </div>
  );
}

// ---------------------------------------------------------------- OV
export function OV({ symbol }: { symbol: string }) {
  const [p, setP] = useState({ S: 100, K: 100, days: 30, r: 4.0, q: 0.0, vol: 25, type: 'call' as OptType, mkt: '' });
  const last = useQuotes([symbol]).get(symbol)?.last;
  const T = p.days / 365;
  const base = { S: p.S, K: p.K, T, r: p.r / 100, q: p.q / 100, type: p.type };
  const out = bs({ ...base, sigma: p.vol / 100 });
  const iv = p.mkt ? impliedVol(+p.mkt, base) : null;
  const strikes = [0.8, 0.9, 0.95, 1, 1.05, 1.1, 1.2].map((m) => Math.round(p.S * m * 100) / 100);
  const num = (k: keyof typeof p) => (
    <input className="inp" style={{ width: 70 }} value={p[k] as any} onChange={(e) => setP({ ...p, [k]: k === 'mkt' ? e.target.value : +e.target.value || 0 })} />
  );
  return (
    <div>
      <div className="toolbar">
        <button className={`tb ${p.type === 'call' ? 'on' : ''}`} onClick={() => setP({ ...p, type: 'call' })}>CALL</button>
        <button className={`tb ${p.type === 'put' ? 'on' : ''}`} onClick={() => setP({ ...p, type: 'put' })}>PUT</button>
        <span className="lbl">SPOT</span>{num('S')}<span className="lbl">STRIKE</span>{num('K')}<span className="lbl">DAYS</span>{num('days')}
        <span className="lbl">VOL %</span>{num('vol')}<span className="lbl">RATE %</span>{num('r')}<span className="lbl">DIV %</span>{num('q')}
        <span className="lbl">MKT PRICE→IV</span>{num('mkt')}
        <button className="tb" disabled={last == null} onClick={() => last != null && setP({ ...p, S: +last.toPrecision(6), K: +last.toPrecision(3) })}>
          SPOT = {shortSym(symbol)} {last != null ? fmtNum(last, 2) : ''}
        </button>
      </div>
      <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
        <span>Price</span><span className="yellow">{fmtNum(out.price, 4)}</span>
        <span>Delta</span><span>{fmtNum(out.delta, 4)}</span>
        <span>Gamma</span><span>{fmtNum(out.gamma, 5)}</span>
        <span>Vega (/1vol)</span><span>{fmtNum(out.vega, 4)}</span>
        <span>Theta (/day)</span><span>{fmtNum(out.theta, 4)}</span>
        <span>Rho (/1%)</span><span>{fmtNum(out.rho, 4)}</span>
        <span>d1 / d2</span><span>{fmtNum(out.d1, 3)} / {fmtNum(out.d2, 3)}</span>
        <span>Implied vol</span><span className="amber">{p.mkt ? (iv != null ? fmtPct(iv * 100, 2, false) : 'no solution') : '—'}</span>
      </div>
      <div className="note">STRIKE LADDER (same expiry / vol)</div>
      <table className="t">
        <thead><tr><th>STRIKE</th><th>CALL</th><th>Δ CALL</th><th>PUT</th><th>Δ PUT</th><th>GAMMA</th><th>VEGA</th></tr></thead>
        <tbody>
          {strikes.map((k) => {
            const c = bs({ ...base, K: k, sigma: p.vol / 100, type: 'call' });
            const pu = bs({ ...base, K: k, sigma: p.vol / 100, type: 'put' });
            return (
              <tr key={k} className={k === p.K ? 'sel' : ''}>
                <td className="amber">{fmtNum(k, 2)}</td><td>{fmtNum(c.price, 3)}</td><td>{fmtNum(c.delta, 3)}</td>
                <td>{fmtNum(pu.price, 3)}</td><td>{fmtNum(pu.delta, 3)}</td><td>{fmtNum(c.gamma, 4)}</td><td>{fmtNum(c.vega, 3)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="note">Black-Scholes-Merton (European, continuous dividend yield). Not suitable for American early exercise.</div>
    </div>
  );
}

function PairBacktest({ a, b, entryZ, zWindow }: { a: string; b: string; entryZ: number; zWindow: number }) {
  const [p, setP] = useState({ hedge_window: 120, exit_z: 0.5, stop_z: 4, fee_bps: 5 });
  const [run, setRun] = useState(0);
  const r = useAsync(() => (run ? api.post<any>('/analytics/pair_backtest', { a, b, z_window: zWindow, entry_z: entryZ, ...p }) : Promise.resolve(null)), [run, a, b, entryZ, zWindow]);
  const d = r.data;
  const lines = useMemo(() => (d?.equity ? [{ name: 'pair strategy', data: d.equity }] : []), [d]);
  const hedge = useMemo(() => (d?.hedge ? [{ name: 'rolling hedge ratio', data: d.hedge, color: '#a98bff' }] : []), [d]);
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>PAIR TRADE BACKTEST — rolling hedge (no look-ahead)</h4>
      <div className="toolbar">
        {(Object.keys(p) as (keyof typeof p)[]).map((k) => (
          <span key={k}><span className="lbl">{k}</span><input className="inp" style={{ width: 48 }} value={p[k]} onChange={(e) => setP({ ...p, [k]: +e.target.value || 0 })} /></span>
        ))}
        <span className="muted">entry |z| {entryZ}, z window {zWindow} (from above)</span>
        <button className="tb green" onClick={() => setRun((x) => x + 1)}>RUN BACKTEST</button>
      </div>
      {r.loading && run > 0 && <Loading />}
      <ErrorBox error={r.error || d?.error} />
      {d?.stats && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>Total return</span><span className={cls(d.stats.total_return_pct)}>{fmtPct(d.stats.total_return_pct)}</span>
            <span>Sharpe</span><span>{fmtNum(d.stats.sharpe, 2)}</span>
            <span>Max DD</span><span className="down">{fmtPct(d.stats.max_drawdown_pct)}</span>
            <span>Trades</span><span>{d.stats.trades} ({d.stats.stops} stops)</span>
            <span>Win rate</span><span>{fmtPct(d.stats.win_rate_pct, 0, false)}</span>
            <span>Avg holding</span><span>{fmtNum(d.stats.avg_holding_days, 1)} days</span>
          </div>
          <LineChart lines={lines} height={180} baseline={1} />
          <LineChart lines={hedge} height={120} />
          <table className="t">
            <thead><tr><th className="l">SIDE</th><th className="l">ENTRY</th><th>z</th><th>HEDGE</th><th className="l">EXIT</th><th>z</th><th className="l">REASON</th><th>RETURN</th></tr></thead>
            <tbody>
              {[...d.trades].reverse().slice(0, 40).map((t: any, i: number) => (
                <tr key={i}>
                  <td className="l">{t.side}</td><td className="l muted">{t.entry}</td><td>{fmtNum(t.entry_z, 2)}</td><td>{fmtNum(t.hedge, 2)}</td>
                  <td className="l muted">{t.exit ?? 'open'}</td><td>{fmtNum(t.exit_z, 2)}</td><td className={`l ${t.reason === 'stop' ? 'down' : ''}`}>{t.reason}</td>
                  <td className={cls(t.return_pct)}>{fmtPct(t.return_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="note">{d.note}. Equity is per unit of gross exposure; fees on both legs at entry and exit.</div>
        </>
      )}
    </div>
  );
}
