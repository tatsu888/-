// TEAR (printable one-page tear sheet) and SCRN (custom screener builder).
import { useEffect, useMemo, useState } from 'react';
import { api, store } from '../lib/api';
import { useQuotes } from '../lib/feed';
import { cls, fmtBig, fmtNum, fmtPct, fmtPrice, shortSym } from '../lib/format';
import type { Bar } from '../lib/types';
import { DelayBadge, ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { useTerminal } from '../ctx';

// ---------------------------------------------------------------- TEAR
export function TEAR({ symbol }: { symbol: string }) {
  const { provider } = useTerminal();
  const q = useQuotes([symbol]).get(symbol);
  const bench = symbol.startsWith('TSE:') ? 'TVC:TOPIX' : 'SP:SPX';
  const hist = useAsync(() => api.get<{ bars: Bar[] }>('/history', { symbol, interval: '1D', bars: 260 }), [symbol]);
  const f = useAsync(() => api.get<any>('/fundamentals', { symbol }), [symbol]);
  const ta = useAsync(() => api.get<any>('/analytics/technicals', { symbol, interval: '1D' }).catch(() => null), [symbol]);
  const beta = useAsync(() => api.get<any>('/analytics/beta', { symbol, benchmark: bench, bars: 260 }).catch(() => null), [symbol]);
  const models = useAsync(() => api.get<any[]>('/harness/for_symbol', { symbol }).catch(() => []), [symbol]);
  const xls = useAsync(() => api.get<any[]>('/excel/for_symbol', { symbol }).catch(() => []), [symbol]);
  const [note, setNote] = useState('');
  useEffect(() => void store.get<Record<string, string>>('notes', {}).then((n) => setNote(n[symbol] ?? '')), [symbol]);
  const lines = useMemo(() => {
    const b = hist.data?.bars ?? [];
    const sma = b.map((_, i) => (i >= 49 ? b.slice(i - 49, i + 1).reduce((a, x) => a + x.close, 0) / 50 : null));
    return [
      { name: shortSym(symbol), data: b.map((x) => ({ time: x.time, value: x.close })), color: '#ffa028' },
      { name: 'SMA50', data: b.map((x, i) => ({ time: x.time, value: sma[i] as number })).filter((p) => p.value != null), color: '#5ea9ff' },
    ];
  }, [hist.data, symbol]);
  const perf = f.data?.performance ?? {};
  const fl = f.data?.fields ?? {};
  function print() {
    document.body.classList.add('printing');
    setTimeout(() => {
      window.print();
      document.body.classList.remove('printing');
    }, 300);
  }
  const KV = ({ items }: { items: [string, React.ReactNode][] }) => (
    <div className="kv">{items.map(([k, v]) => [<span key={k}>{k}</span>, <span key={k + 'v'}>{v}</span>])}</div>
  );
  return (
    <div>
      <div className="toolbar no-print">
        <button className="tb green" onClick={print}>PRINT / SAVE AS PDF</button>
        <span className="muted">1 枚サマリー。ブラウザの印刷ダイアログで「PDF に保存」を選択できます。</span>
      </div>
      <div className="print-area pad">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: '2px solid var(--amber)', paddingBottom: 4 }}>
          <div>
            <span className="amber" style={{ fontSize: 18, fontWeight: 700 }}>{q?.name ?? fl.description ?? symbol}</span>{' '}
            <span className="muted">{symbol} · {q?.currency ?? fl.currency ?? ''} · {fl.sector ?? ''} {fl.industry ? `/ ${fl.industry}` : ''}</span>
          </div>
          <div style={{ fontSize: 18 }}>
            {fmtPrice(q?.last)} <span className={cls(q?.change_pct)}>{fmtPct(q?.change_pct)}</span> <DelayBadge q={q} />
          </div>
        </div>
        {(hist.loading || f.loading) && <Loading />}
        <ErrorBox error={hist.error} />
        <LineChart lines={lines} height={220} />
        <div className="cols">
          <div className="box">
            <h4>PERFORMANCE</h4>
            <KV items={[['1M', fmtPct(perf['1M'])], ['3M', fmtPct(perf['3M'])], ['YTD', fmtPct(perf.YTD)], ['1Y', fmtPct(perf['1Y'])],
              ['Vol 1Y', fmtPct(perf.VOL_1Y, 1, false)], ['52W range', `${fmtPrice(perf.LOW_52W)} – ${fmtPrice(perf.HIGH_52W)}`]]} />
          </div>
          <div className="box">
            <h4>VALUATION & QUALITY</h4>
            <KV items={[['Mkt cap', fmtBig(fl.market_cap_basic)], ['P/E', fmtNum(fl.price_earnings_ttm, 1)], ['P/B', fmtNum(fl.price_book_ratio, 2)],
              ['Div yield', fmtPct(fl.dividend_yield_recent, 2, false)], ['ROE', fmtPct(fl.return_on_equity, 1, false)], ['Op margin', fmtPct(fl.operating_margin, 1, false)]]} />
          </div>
          <div className="box">
            <h4>RISK & TECHNICALS</h4>
            <KV items={[[`β vs ${shortSym(bench)}`, fmtNum(beta.data?.beta, 2)], ['Adj. β', fmtNum(beta.data?.adjusted_beta, 2)], ['R²', fmtNum(beta.data?.r2, 2)],
              ['TA (daily)', ta.data?.summary ? <b className={ta.data.summary.score > 0.1 ? 'up' : ta.data.summary.score < -0.1 ? 'down' : 'yellow'}>{ta.data.summary.label}</b> : '--'],
              ['RSI(14)', fmtNum(ta.data?.oscillators?.items?.find((x: any) => x.name === 'RSI14')?.value, 1)]]} />
          </div>
        </div>
        <div className="box" style={{ margin: '6px 0' }}>
          <h4>FORECAST HARNESS MODELS ({(models.data ?? []).length})</h4>
          {(models.data ?? []).length === 0 && <div className="note">no saved model with company.symbol = {symbol} (MODEL → SAVE)</div>}
          <table className="t">
            <tbody>
              {(models.data ?? []).map((m: any) => (
                <tr key={m.name}>
                  <td className="l amber">{m.name} v{m.version}</td>
                  <td className="l muted">{m.saved_at}</td>
                  <td>EPS {(m.summary?.eps ?? []).slice(0, 3).map((x: number) => fmtNum(x, 1)).join(' / ')}</td>
                  <td>DCF {fmtNum(m.summary?.dcf_price, 0)}</td>
                  <td className="muted">checks {m.summary?.checks ? `${m.summary.checks.PASS}/${m.summary.checks.WARN}/${m.summary.checks.FAIL}` : '--'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="cols">
          <div className="box"><h4>NOTES / THESIS</h4><div className="pad" style={{ whiteSpace: 'pre-wrap', minHeight: 40 }}>{note || <span className="muted">(NOTE)</span>}</div></div>
          <div className="box"><h4>LINKED EXCEL</h4>{(xls.data ?? []).map((x: any) => <div key={x.id} className="pad">{x.path}</div>)}{!xls.data?.length && <div className="note">none</div>}</div>
        </div>
        <div className="note">
          Generated {new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC · data source: {provider || '?'}{provider === 'sim' ? ' (SIMULATED DEMO — NOT MARKET DATA)' : ''} ·
          fundamentals: TradingView scanner · not investment advice
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- SCRN
interface Filter { left: string; operation: string; right: any }
const DEFAULT_COLS = ['close', 'change', 'market_cap_basic', 'price_earnings_ttm', 'return_on_equity', 'Perf.6M', 'sector'];

export function SCRN() {
  const { setSecurity, run, toast } = useTerminal();
  const meta = useAsync(() => api.get<any>('/screener/fields'), []);
  const [market, setMarket] = useState('america');
  const [filters, setFilters] = useState<Filter[]>([{ left: 'market_cap_basic', operation: 'greater', right: 1e9 }]);
  const [cols, setCols] = useState<string[]>(DEFAULT_COLS);
  const [sort, setSort] = useState({ by: 'market_cap_basic', order: 'desc' });
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<Record<string, any>>({});
  useEffect(() => void store.get<Record<string, any>>('screens', {}).then(setSaved), []);
  const fields: Record<string, { label: string; group: string; unit: string }> = meta.data?.fields ?? {};
  async function go() {
    setBusy(true);
    setErr(undefined);
    try {
      setRes(await api.post('/screener/custom', { market, filters, columns: cols, sort_by: sort.by, order: sort.order, limit: 200 }));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }
  const fmtCell = (k: string, v: any) => (v == null ? '--' : fields[k]?.unit === 'text' ? String(v) : k === 'market_cap_basic' || k === 'volume' ? fmtBig(v) : fmtNum(v, Math.abs(v) >= 100 ? 0 : 2));
  if (meta.loading) return <Loading />;
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">PRESET</span>
        <select className="inp" value="" onChange={(e) => {
          const pr = meta.data.presets[e.target.value] ?? saved[e.target.value];
          if (!pr) return;
          setFilters(pr.filters);
          setSort({ by: pr.sort ?? 'market_cap_basic', order: pr.order ?? 'desc' });
          if (pr.columns) setCols(pr.columns);
        }}>
          <option value="">choose…</option>
          {Object.entries<any>(meta.data.presets).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          {Object.keys(saved).map((k) => <option key={'s' + k} value={k}>★ {k}</option>)}
        </select>
        <span className="lbl">MARKET</span>
        <select className="inp" value={market} onChange={(e) => setMarket(e.target.value)}>{['america', 'japan', 'uk', 'germany', 'hongkong', 'china', 'india', 'korea', 'taiwan'].map((m) => <option key={m}>{m}</option>)}</select>
        <span className="lbl">SORT</span>
        <select className="inp" value={sort.by} onChange={(e) => setSort({ ...sort, by: e.target.value })}>{Object.entries(fields).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <button className="tb" onClick={() => setSort({ ...sort, order: sort.order === 'desc' ? 'asc' : 'desc' })}>{sort.order === 'desc' ? '▼ DESC' : '▲ ASC'}</button>
        <button className="tb green" onClick={go} disabled={busy}>{busy ? 'SCREENING…' : 'RUN SCREEN'}</button>
        <button className="tb" onClick={async () => {
          const n = prompt('save screen as');
          if (!n) return;
          const s = { ...saved, [n]: { filters, sort: sort.by, order: sort.order, columns: cols } };
          setSaved(s);
          await store.set('screens', s);
          toast(`screen saved: ${n}`);
        }}>SAVE</button>
      </div>
      <table className="t" style={{ width: 'auto' }}>
        <tbody>
          {filters.map((fl, i) => (
            <tr key={i}>
              <td className="l">
                <select className="inp" value={fl.left} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, left: e.target.value } : x)))}>
                  {Object.entries(fields).map(([k, v]) => <option key={k} value={k}>{v.group} · {v.label}</option>)}
                </select>
              </td>
              <td className="l">
                <select className="inp" value={fl.operation} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, operation: e.target.value, right: e.target.value.includes('range') ? [0, 0] : 0 } : x)))}>
                  {(meta.data.operations as string[]).map((o) => <option key={o}>{o}</option>)}
                </select>
              </td>
              <td className="l">
                <input className="inp" style={{ width: 160 }} value={Array.isArray(fl.right) ? fl.right.join(', ') : fl.right}
                  onChange={(e) => {
                    const v = e.target.value;
                    const right = fl.operation.includes('range') ? v.split(',').map((x) => Number(x.trim())) : fields[fl.left]?.unit === 'text' ? v : Number(v);
                    setFilters(filters.map((x, j) => (j === i ? { ...x, right } : x)));
                  }} />
                <span className="muted"> {fields[fl.left]?.unit}</span>
              </td>
              <td><span className="muted" style={{ cursor: 'pointer' }} onClick={() => setFilters(filters.filter((_, j) => j !== i))}>✕</span></td>
            </tr>
          ))}
          <tr><td colSpan={4} className="l"><button className="tb" onClick={() => setFilters([...filters, { left: 'price_earnings_ttm', operation: 'less', right: 15 }])}>+ FILTER</button>
            <span className="lbl">COLUMNS</span>
            <select className="inp" value="" onChange={(e) => e.target.value && setCols([...new Set([...cols, e.target.value])])}>
              <option value="">add column…</option>{Object.entries(fields).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
            {cols.map((c) => <button key={c} className="tb" onClick={() => setCols(cols.filter((x) => x !== c))}>{fields[c]?.label ?? c} ✕</button>)}
          </td></tr>
        </tbody>
      </table>
      <ErrorBox error={err} />
      {res && (
        <>
          <div className="note">{res.rows.length} rows{res.total != null ? ` of ${res.total} matches` : ''} · source {res.source}{res.source === 'sim' ? ' (demo: only price/volume fields)' : ''}</div>
          <table className="t">
            <thead><tr><th className="l">#</th><th className="l">SECURITY</th><th className="l">NAME</th>{cols.map((c) => <th key={c}>{fields[c]?.label ?? c}</th>)}</tr></thead>
            <tbody>
              {res.rows.map((r: any, i: number) => (
                <tr key={r.symbol} className="click" onClick={() => setSecurity(r.symbol)} onDoubleClick={() => run('GP', r.symbol)}>
                  <td className="l muted">{i + 1}</td><td className="l sym">{shortSym(r.symbol)}</td><td className="l name">{r.description}</td>
                  {cols.map((c) => <td key={c} className={c === 'change' || c.startsWith('Perf') ? cls(r[c]) : fields[c]?.unit === 'text' ? 'l' : ''}>{fmtCell(c, r[c])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
