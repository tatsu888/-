// Security-level functions: DES, TA, N (news), NOTE.
import { useEffect, useState } from 'react';
import { api, store } from '../lib/api';
import { useQuotes } from '../lib/feed';
import { cls, fmtBig, fmtNum, fmtPct, fmtPrice, fmtTime } from '../lib/format';
import { DelayBadge, ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

const FIELD_LABELS: [string, string, (v: any) => string][] = [
  ['sector', 'Sector', String], ['industry', 'Industry', String], ['market_cap_basic', 'Market Cap', fmtBig],
  ['price_earnings_ttm', 'P/E (TTM)', (v) => fmtNum(v, 1)], ['earnings_per_share_basic_ttm', 'EPS (TTM)', (v) => fmtNum(v, 2)],
  ['price_book_ratio', 'P/B', (v) => fmtNum(v, 2)], ['dividend_yield_recent', 'Div Yield %', (v) => fmtNum(v, 2)],
  ['beta_1_year', 'Beta 1Y', (v) => fmtNum(v, 2)], ['return_on_equity', 'ROE %', (v) => fmtNum(v, 1)],
  ['gross_margin', 'Gross Margin %', (v) => fmtNum(v, 1)], ['operating_margin', 'Op Margin %', (v) => fmtNum(v, 1)],
  ['debt_to_equity', 'Debt/Equity', (v) => fmtNum(v, 2)], ['total_revenue', 'Revenue', fmtBig], ['net_income', 'Net Income', fmtBig],
  ['number_of_employees', 'Employees', fmtBig], ['average_volume_10d_calc', 'Avg Vol 10D', fmtBig],
  ['price_52_week_high', '52W High', fmtPrice], ['price_52_week_low', '52W Low', fmtPrice],
  ['Recommend.All', 'TV Tech Rating', (v) => fmtNum(v, 2)], ['RSI', 'RSI(14)', (v) => fmtNum(v, 1)],
];

export function DES({ symbol }: { symbol: string }) {
  const { run } = useTerminal();
  const q = useQuotes([symbol]).get(symbol);
  const f = useAsync(() => api.get<any>('/fundamentals', { symbol }), [symbol]);
  const xls = useAsync(() => api.get<any[]>('/excel/for_symbol', { symbol }), [symbol]);
  const perf = f.data?.performance ?? {};
  const fields = f.data?.fields ?? {};
  return (
    <div>
      <div className="pad">
        <span className="amber" style={{ fontSize: 16 }}>{symbol}</span> <span className="yellow" style={{ fontSize: 14 }}>{q?.name ?? fields.description ?? ''}</span>{' '}
        <DelayBadge q={q} />
        <div style={{ fontSize: 22, marginTop: 4 }}>
          {fmtPrice(q?.last)} <span className={cls(q?.change)} style={{ fontSize: 16 }}>{q?.change != null ? (q.change > 0 ? '+' : '') + fmtPrice(q.change, q.last) : ''} {fmtPct(q?.change_pct)}</span>
        </div>
        <div className="muted">
          {q?.exchange} · {q?.currency} · {q?.type ?? fields.type ?? ''} · last update {fmtTime(q?.time, true)}
        </div>
      </div>
      {f.loading && <Loading />}
      <div className="cols">
        <div className="box">
          <h4>QUOTE</h4>
          <div className="kv">
            <span>Open</span><span>{fmtPrice(q?.open)}</span>
            <span>High</span><span>{fmtPrice(q?.high)}</span>
            <span>Low</span><span>{fmtPrice(q?.low)}</span>
            <span>Prev Close</span><span>{fmtPrice(q?.prev_close)}</span>
            <span>Bid / Ask</span><span>{fmtPrice(q?.bid)} / {fmtPrice(q?.ask)}</span>
            <span>Volume</span><span>{fmtBig(q?.volume)}</span>
          </div>
        </div>
        <div className="box">
          <h4>PERFORMANCE (from daily history)</h4>
          <table className="t">
            <tbody>
              {['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y'].map((k) => (
                <tr key={k}>
                  <td className="l amber">{k}</td>
                  <td className={cls(perf[k])}>{fmtPct(perf[k])}</td>
                </tr>
              ))}
              <tr><td className="l amber">Vol 1Y (ann.)</td><td>{fmtPct(perf.VOL_1Y, 1, false)}</td></tr>
              <tr><td className="l amber">52W Range</td><td>{fmtPrice(perf.LOW_52W)} – {fmtPrice(perf.HIGH_52W)}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="box">
          <h4>FUNDAMENTALS (TradingView scanner)</h4>
          <div className="kv">
            {FIELD_LABELS.filter(([k]) => fields[k] != null).map(([k, l, fmt]) => [<span key={k + 'l'}>{l}</span>, <span key={k}>{fmt(fields[k])}</span>])}
          </div>
          {!Object.keys(fields).length && <div className="note">no fundamentals (source unavailable or not an equity)</div>}
        </div>
        <div className="box">
          <h4>LINKED EXCEL MODELS</h4>
          {(xls.data ?? []).map((x) => (
            <div key={x.id} className="pad blue" style={{ cursor: 'pointer' }} onClick={() => run('XLS', symbol, x.id)}>
              {x.link === 'manual' ? '★' : '·'} {x.path}
            </div>
          ))}
          {xls.data && !xls.data.length && <div className="note">none — use XLS to link a workbook</div>}
        </div>
      </div>
      {f.data?.errors?.length > 0 && <div className="note">notes: {f.data.errors.join(' | ')}</div>}
    </div>
  );
}

export function TA({ symbol }: { symbol: string }) {
  const ivs = ['60', '240', '1D', '1W'];
  const res = useAsync(() => Promise.all(ivs.map((iv) => api.get<any>('/analytics/technicals', { symbol, interval: iv }).catch((e) => ({ error: e.message })))), [symbol]);
  if (res.loading) return <Loading />;
  return (
    <div className="cols">
      {ivs.map((iv, i) => {
        const r = res.data?.[i];
        if (!r || r.error) return <div key={iv} className="box"><h4>{iv}</h4><div className="err">{r?.error}</div></div>;
        return (
          <div key={iv} className="box">
            <h4>
              {iv === '60' ? '1 HOUR' : iv === '240' ? '4 HOURS' : iv === '1D' ? 'DAILY' : 'WEEKLY'} — <b className={r.summary.score > 0.1 ? 'up' : r.summary.score < -0.1 ? 'down' : 'yellow'}>{r.summary.label}</b>
            </h4>
            <Gauge score={r.summary.score} />
            <table className="t">
              <thead><tr><th className="l">INDICATOR</th><th>VALUE</th><th>VOTE</th></tr></thead>
              <tbody>
                {[...r.oscillators.items, ...r.moving_averages.items].map((it: any) => (
                  <tr key={it.name}>
                    <td className="l">{it.name}</td>
                    <td>{fmtNum(it.value, 2)}</td>
                    <td className={it.vote > 0 ? 'up' : it.vote < 0 ? 'down' : 'muted'}>{it.vote > 0 ? 'BUY' : it.vote < 0 ? 'SELL' : 'NEUTRAL'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

function Gauge({ score }: { score: number }) {
  const x = ((score + 1) / 2) * 100;
  return (
    <div style={{ margin: '6px 8px', height: 10, background: 'linear-gradient(90deg,#ff4545,#555 50%,#2fd17a)', position: 'relative' }}>
      <div style={{ position: 'absolute', left: `calc(${x}% - 2px)`, top: -3, width: 4, height: 16, background: '#ffd84a' }} />
    </div>
  );
}

export function NEWS({ symbol, all }: { symbol: string; all?: boolean }) {
  const [scope, setScope] = useState<'sec' | 'all'>(all ? 'all' : 'sec');
  const r = useAsync(() => api.get<any>('/news', { symbol: scope === 'sec' ? symbol : undefined, limit: 80 }), [symbol, scope]);
  return (
    <div>
      <div className="toolbar">
        <button className={`tb ${scope === 'sec' ? 'on' : ''}`} onClick={() => setScope('sec')}>{symbol}</button>
        <button className={`tb ${scope === 'all' ? 'on' : ''}`} onClick={() => setScope('all')}>TOP NEWS</button>
        <button className="tb" onClick={r.reload}>REFRESH</button>
        <span className="muted">{r.data?.source ? `source: ${r.data.source}` : ''}</span>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {r.data?.errors?.length > 0 && <div className="note">{r.data.errors.join(' | ')}</div>}
      <table className="t">
        <tbody>
          {(r.data?.items ?? []).map((n: any, i: number) => (
            <tr key={n.id ?? i}>
              <td className="l muted" style={{ width: 120 }}>{fmtTime(n.published, true)}</td>
              <td className="l" style={{ whiteSpace: 'normal' }}>
                {n.urgency === 1 && <span className="badge fail">HOT</span>}{' '}
                {n.url ? <a className="blue" href={n.url} target="_blank" rel="noreferrer">{n.title}</a> : n.title}
              </td>
              <td className="l muted">{n.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function NOTE({ symbol }: { symbol: string }) {
  const [notes, setNotes] = useState<Record<string, string> | null>(null);
  const [text, setText] = useState('');
  const [saved, setSaved] = useState(true);
  useEffect(() => {
    store.get<Record<string, string>>('notes', {}).then((n) => {
      setNotes(n);
      setText(n[symbol] ?? '');
    });
  }, [symbol]);
  useEffect(() => {
    if (saved || !notes) return;
    const h = setTimeout(() => {
      const n = { ...notes, [symbol]: text };
      setNotes(n);
      store.set('notes', n).then(() => setSaved(true));
    }, 600);
    return () => clearTimeout(h);
  }, [text, saved]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!notes) return <Loading />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="toolbar">
        <span className="amber">{symbol}</span>
        <span className="muted">{saved ? 'saved' : 'editing…'}</span>
        <span className="lbl">other notes:</span>
        {Object.keys(notes).filter((k) => k !== symbol && notes[k]).slice(0, 12).map((k) => <span key={k} className="muted">{k}</span>)}
      </div>
      <textarea className="inp" style={{ flex: 1, resize: 'none' }} value={text} onChange={(e) => (setText(e.target.value), setSaved(false))} placeholder="投資メモ / thesis / catalysts / risks …" />
    </div>
  );
}
