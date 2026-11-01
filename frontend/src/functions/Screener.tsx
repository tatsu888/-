// MOST (screener presets) and HMAP (market heatmap treemap).
import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { cls, fmtBig, fmtPct, fmtPrice, heat, shortSym } from '../lib/format';
import { squarify } from '../lib/treemap';
import type { Quote } from '../lib/types';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

const MARKETS = ['america', 'japan', 'uk', 'germany', 'hongkong', 'china', 'india', 'crypto', 'forex'];
const PRESETS = ['most_active', 'gainers', 'losers', 'largest'];

export function MOST({ args }: { args?: string }) {
  const { setSecurity, run } = useTerminal();
  const [market, setMarket] = useState(args?.toLowerCase().includes('jp') ? 'japan' : 'america');
  const [preset, setPreset] = useState('most_active');
  const r = useAsync(() => api.get<Quote[]>('/screener', { market, preset, limit: 50 }), [market, preset]);
  return (
    <div>
      <div className="toolbar">
        {PRESETS.map((p) => (
          <button key={p} className={`tb ${p === preset ? 'on' : ''}`} onClick={() => setPreset(p)}>
            {p.toUpperCase()}
          </button>
        ))}
        <span className="lbl">MKT</span>
        <select className="inp" value={market} onChange={(e) => setMarket(e.target.value)}>
          {MARKETS.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
        <button className="tb" onClick={r.reload}>
          REFRESH
        </button>
        <span className="muted">snapshot (TradingView scanner)</span>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      <table className="t">
        <thead>
          <tr>
            <th className="l">#</th>
            <th className="l">SECURITY</th>
            <th className="l">NAME</th>
            <th>LAST</th>
            <th>%CHG</th>
            <th>VOLUME</th>
            <th>MKT CAP</th>
            <th>P/E</th>
          </tr>
        </thead>
        <tbody>
          {(r.data ?? []).map((q, i) => (
            <tr key={q.symbol} className="click" onClick={() => setSecurity(q.symbol)} onDoubleClick={() => run('GP', q.symbol)}>
              <td className="l muted">{i + 1}</td>
              <td className="l sym">{shortSym(q.symbol)}</td>
              <td className="l name">{q.name}</td>
              <td>{fmtPrice(q.last)}</td>
              <td className={cls(q.change_pct)}>{fmtPct(q.change_pct)}</td>
              <td>{fmtBig(q.volume)}</td>
              <td>{fmtBig(q.market_cap)}</td>
              <td>{q.pe != null ? q.pe.toFixed(1) : '--'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HMAP() {
  const { setSecurity, run } = useTerminal();
  const [market, setMarket] = useState('america');
  const [n, setN] = useState(80);
  const r = useAsync(() => api.get<Quote[]>('/screener', { market, preset: 'largest', limit: n }), [market, n]);
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 600, h: 400 });
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const cells = squarify(
    (r.data ?? []).map((q) => ({ value: q.market_cap ?? q.volume ?? 1, data: q })),
    { x: 0, y: 0, w: size.w, h: size.h },
  );
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="toolbar">
        <span className="lbl">MKT</span>
        <select className="inp" value={market} onChange={(e) => setMarket(e.target.value)}>
          {MARKETS.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
        <span className="lbl">N</span>
        <select className="inp" value={n} onChange={(e) => setN(+e.target.value)}>
          {[40, 80, 150].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
        <span className="muted">size = market cap · colour = %chg (±3%)</span>
      </div>
      <ErrorBox error={r.error} />
      <div ref={box} style={{ position: 'relative', flex: 1, minHeight: 0 }}>
        {cells.map((c) => (
          <div
            key={c.data.symbol}
            onClick={() => setSecurity(c.data.symbol)}
            onDoubleClick={() => run('GP', c.data.symbol)}
            title={`${c.data.symbol} ${c.data.name ?? ''} ${fmtPct(c.data.change_pct)} cap ${fmtBig(c.data.market_cap)}`}
            style={{
              position: 'absolute', left: c.x, top: c.y, width: c.w, height: c.h, background: heat(c.data.change_pct),
              border: '1px solid #000', overflow: 'hidden', cursor: 'pointer', padding: 2, fontSize: Math.max(9, Math.min(16, Math.sqrt(c.w * c.h) / 6)),
              textAlign: 'center', display: 'flex', flexDirection: 'column', justifyContent: 'center',
            }}
          >
            {c.w > 34 && c.h > 18 && <b>{shortSym(c.data.symbol)}</b>}
            {c.w > 44 && c.h > 32 && <span>{fmtPct(c.data.change_pct)}</span>}
            {c.w > 70 && c.h > 46 && <span className="muted" style={{ fontSize: 10 }}>{fmtPrice(c.data.last)}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
