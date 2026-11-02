// Research tools: CYCL (Fourier cycles & forecast), MACRO (macro dashboard / regimes),
// MRGN (Japan margin trading 信用残), TRND (Google Trends & social attention).
import { useMemo, useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, fmtPct } from '../lib/format';
import { Bars, ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';

// ---------------------------------------------------------------- CYCL
export function CYCL({ symbol }: { symbol: string }) {
  const [iv, setIv] = useState('1D');
  const [k, setK] = useState(3);
  const [h, setH] = useState(20);
  const [bars, setBars] = useState(750);
  const [detrend, setDetrend] = useState('loglinear');
  const r = useAsync(() => api.get<any>('/analytics/fourier', { symbol, interval: iv, k, horizon: h, bars, detrend }), [symbol, iv, k, h, bars, detrend]);
  const d = r.data;
  const lines = useMemo(() => {
    if (!d) return [];
    const tail = (x: any[]) => x.slice(-Math.min(x.length, 400));
    return [
      { name: 'price', data: tail(d.series.price), color: '#ffa028' },
      { name: 'fit', data: tail(d.series.fitted), color: '#5ea9ff' },
      { name: 'forecast', data: d.series.forecast, color: '#ff6ad5' },
      { name: '+2σ', data: d.series.upper, color: '#555' },
      { name: '−2σ', data: d.series.lower, color: '#555' },
    ];
  }, [d]);
  const bt = d?.backtest;
  return (
    <div>
      <div className="toolbar">
        {['60', '1D', '1W'].map((x) => <button key={x} className={`tb ${iv === x ? 'on' : ''}`} onClick={() => setIv(x)}>{x}</button>)}
        <span className="lbl">CYCLES k</span>
        <select className="inp" value={k} onChange={(e) => setK(+e.target.value)}>{[1, 2, 3, 4, 5, 6].map((x) => <option key={x}>{x}</option>)}</select>
        <span className="lbl">HORIZON</span>
        <select className="inp" value={h} onChange={(e) => setH(+e.target.value)}>{[5, 10, 20, 60].map((x) => <option key={x}>{x}</option>)}</select>
        <span className="lbl">BARS</span>
        <select className="inp" value={bars} onChange={(e) => setBars(+e.target.value)}>{[256, 500, 750, 1500, 3000].map((x) => <option key={x}>{x}</option>)}</select>
        <span className="lbl">DETREND</span>
        <select className="inp" value={detrend} onChange={(e) => setDetrend(e.target.value)}><option>loglinear</option><option>linear</option></select>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>Cycles used</span><span className="yellow">{d.fit.periods.map((p: number) => p.toFixed(1)).join(', ')} bars</span>
            <span>In-sample R²</span><span>{fmtNum(d.fit.r2, 3)}</span>
            <span>Backtest MAPE</span><span>fourier {fmtNum(bt.mape.fourier, 2)}% · naive {fmtNum(bt.mape.naive, 2)}% · drift {fmtNum(bt.mape.drift, 2)}%</span>
            <span>Skill vs naive</span>
            <span className={bt.skill_vs_naive > 0.05 ? 'up' : bt.skill_vs_naive < -0.05 ? 'down' : 'yellow'}>{bt.skill_vs_naive != null ? fmtPct(bt.skill_vs_naive * 100, 1) : '--'} — {bt.verdict}</span>
            <span>Direction hit</span><span>{fmtPct(bt.directional_hit_rate.fourier, 0, false)} (drift {fmtPct(bt.directional_hit_rate.drift, 0, false)})</span>
            <span>Origins</span><span>{bt.origins} × {bt.horizon} bars</span>
          </div>
          <div className="note">⚠ {d.note} Price series behave close to a random walk — trust the skill score, not the pretty fit.</div>
          <LineChart lines={lines} height={260} />
          <div className="note">DOMINANT CYCLES (periodogram peaks, share of detrended variance)</div>
          <div style={{ overflowX: 'auto', padding: 6 }}>
            <Bars values={d.periodogram.peaks.map((p: any) => p.share * 100)} labels={d.periodogram.peaks.map((p: any) => p.period.toFixed(0))} height={110} />
          </div>
          <table className="t">
            <thead><tr><th>PERIOD (bars)</th><th>≈ CALENDAR</th><th>SHARE</th><th>AMPLITUDE (fit)</th></tr></thead>
            <tbody>
              {d.periodogram.peaks.map((p: any) => {
                const comp = d.fit.components.find((c: any) => Math.abs(c.period - p.period) < 1e-6);
                const days = iv === '1W' ? p.period * 7 : iv === '60' ? p.period / 7 : p.period * 1.45;
                return (
                  <tr key={p.k} className={comp ? 'sel' : ''}>
                    <td className="amber">{p.period.toFixed(1)}</td><td className="muted">{iv === '60' ? `${fmtNum(days, 1)} sessions` : `${fmtNum(days, 0)} days`}</td>
                    <td>{fmtPct(p.share * 100, 1, false)}</td><td>{comp ? fmtNum(comp.amplitude, 4) : ''}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
