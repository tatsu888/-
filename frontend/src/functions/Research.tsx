// Research tools: CYCL (Fourier cycles & forecast), MACRO (macro dashboard / regimes),
// MRGN (Japan margin trading 信用残), TRND (Google Trends & social attention).
import { useMemo, useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, fmtPct } from '../lib/format';
import { Bars, ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { GLPanel } from './Trinity';

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

// ---------------------------------------------------------------- shared bits
function Spark({ v, w = 70, h = 16, color = '#ffa028' }: { v: number[]; w?: number; h?: number; color?: string }) {
  if (!v?.length) return null;
  const pts = v.map((y, i) => `${(i / (v.length - 1)) * w},${h - y * h}`).join(' ');
  return <svg width={w} height={h} style={{ display: 'block' }}><polyline fill="none" stroke={color} strokeWidth={1.2} points={pts} /></svg>;
}
const zColor = (z: number | null | undefined) => {
  if (z == null || !isFinite(z)) return '#1a1a1a';
  const a = Math.min(Math.abs(z) / 2.5, 1);
  return z >= 0 ? `rgba(0, 170, 80, ${0.2 + a * 0.65})` : `rgba(220, 40, 40, ${0.2 + a * 0.65})`;
};
const fmtChg = (v: number | null | undefined, kind: string) => (v == null ? '--' : kind === 'yield' ? `${v > 0 ? '+' : ''}${v.toFixed(0)}bp` : fmtPct(v, 1));

// ---------------------------------------------------------------- PROP
export function PROP({ onChart }: { onChart: (symbol: string) => void }) {
  const [zw, setZw] = useState(20);
  const [gap, setGap] = useState(1.0);
  const [source, setSource] = useState('');
  const [tab, setTab] = useState<'map' | 'edit'>('map');
  const [selId, setSelId] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const r = useAsync(() => api.get<any>('/macro/propagation', { z_window: zw, gap, source: source || undefined }), [zw, gap, source, reload]);
  const d = r.data;
  const comp = useMemo(() => {
    if (!d) return [];
    const colors: Record<string, string> = { '1': '#a98bff', '2': '#59e3ff', '3': '#ffa028' };
    return Object.entries<any[]>(d.composites).map(([t, s]) => ({
      name: `Tier ${t}`, color: colors[t],
      data: s.map((p) => ({ time: Math.floor(new Date(p.date + 'T00:00:00Z').getTime() / 1000), value: p.value })),
    }));
  }, [d]);
  const sel = d?.items.find((x: any) => x.id === selId);
  const ll13 = d?.tier_leadlag.find((x: any) => x.from === 1 && x.to === 3);
  return (
    <div>
      <div className="toolbar">
        <button className={`tb ${tab === 'map' ? 'on' : ''}`} onClick={() => setTab('map')}>MAP</button>
        <button className={`tb ${tab === 'edit' ? 'on' : ''}`} onClick={() => setTab('edit')}>EDIT MAP</button>
        <span className="lbl">MOMENTUM WINDOW</span>
        {[10, 20, 60].map((x) => <button key={x} className={`tb ${zw === x ? 'on' : ''}`} onClick={() => setZw(x)}>{x}d</button>)}
        <span className="lbl">GAP |z| ≥</span>
        <select className="inp" value={gap} onChange={(e) => setGap(+e.target.value)}>{[0.5, 1, 1.5, 2].map((x) => <option key={x}>{x}</option>)}</select>
        <span className="lbl">SOURCE</span>
        <select className="inp" value={source} onChange={(e) => setSource(e.target.value)}>{['', 'tradingview', 'yahoo', 'sim'].map((s) => <option key={s} value={s}>{s || '(active)'}</option>)}</select>
        <button className="tb" onClick={() => setReload((x) => x + 1)}>REFRESH</button>
        {d && <span className="muted">source: {d.source}{d.source === 'sim' ? ' (DEMO)' : ''}</span>}
      </div>
      {tab === 'edit' ? <MapEditor onSaved={() => (setReload((x) => x + 1), setTab('map'))} /> : (
        <>
          {r.loading && <Loading what="LOADING ~60 SERIES" />}
          <ErrorBox error={r.error} />
          {d && (
            <>
              <div className="prop-head">
                <div />
                <div className="prop-arrow">認識の伝播 — 色 = 直近{zw}日の変化の z スコア（リスクオン方向 = 緑）</div>
                {[1, 2, 3].map((t) => (
                  <div key={t} className="prop-tier">
                    <b>{t}</b> {d.tiers[t]} <span className={(d.composite_latest[t] ?? 0) >= 0 ? 'up' : 'down'}>{fmtNum(d.composite_latest[t], 2)}</span>
                  </div>
                ))}
              </div>
              {d.classes.map((c: string) => (
                <div key={c} className="prop-row">
                  <div className="prop-cls">{c}</div>
                  {[1, 2, 3].map((t) => {
                    const its = d.items.filter((x: any) => x.cls === c && x.tier === t);
                    const cz = d.class_tier_latest[c]?.[t];
                    return (
                      <div key={t} className={`prop-cell t${t}`}>
                        {its.length === 0 && t === 3 && c === 'コモディティ' && <div className="muted" style={{ fontStyle: 'italic', padding: 8 }}>— 株式・通貨・金利に集約 —</div>}
                        {its.map((it: any) => {
                          const sg = it.signals;
                          return (
                            <div key={it.id} className={`prop-tile ${selId === it.id ? 'sel' : ''}`} style={{ background: zColor(sg.sz) }} onClick={() => setSelId(it.id)}
                              title={`${it.label}\n${JSON.stringify(it.series)}\n${sg.error ?? `z ${fmtNum(sg.sz, 2)} · 5d ${fmtChg(sg.chg_5, it.kind)} · 20d ${fmtChg(sg.chg_20, it.kind)} · 60d ${fmtChg(sg.chg_60, it.kind)}`}`}>
                              <div className="prop-label">{it.label}</div>
                              {sg.error ? <div className="muted" style={{ fontSize: 10 }}>no data</div> : (
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                  <b>{sg.sz != null ? (sg.sz > 0 ? '+' : '') + sg.sz.toFixed(1) : '--'}</b>
                                  <span style={{ fontSize: 10 }}>{fmtChg(sg.chg_20, it.kind)}</span>
                                  <Spark v={sg.spark} color="#fff" />
                                </div>
                              )}
                            </div>
                          );
                        })}
                        {its.length > 0 && cz != null && <div className="prop-cz" style={{ color: cz >= 0 ? '#2fd17a' : '#ff4545' }}>{cz > 0 ? '+' : ''}{cz.toFixed(2)}</div>}
                      </div>
                    );
                  })}
                </div>
              ))}
              <div className="cols">
                <div className="box">
                  <h4>未波及チェック（上流 Tier1-2 vs 下流 Tier3, 平均 signed z）</h4>
                  <table className="t">
                    <thead><tr><th className="l">CLASS</th><th>UPSTREAM</th><th>DOWNSTREAM</th><th>GAP</th><th className="l">STATE</th></tr></thead>
                    <tbody>
                      {d.gaps.map((g: any) => (
                        <tr key={g.cls}>
                          <td className="l amber">{g.cls}</td>
                          <td style={{ background: zColor(g.upstream_sz) }}>{fmtNum(g.upstream_sz, 2)}</td>
                          <td style={{ background: zColor(g.downstream_sz) }}>{fmtNum(g.downstream_sz, 2)}</td>
                          <td>{fmtNum(g.gap, 2)}</td>
                          <td className={`l ${g.state.startsWith('未波及') ? 'yellow' : g.state === '波及途中' ? 'amber' : 'muted'}`}>{g.state}{g.state.startsWith('未波及') || g.state === '波及途中' ? ` → ${g.direction}` : ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="box">
                  <h4>伝播ラグ（Tier 合成指数の変化の相互相関・正のラグ = 上流が先行）</h4>
                  <table className="t">
                    <thead><tr><th className="l">PATH</th><th>BEST LAG</th><th>CORR Δ</th><th>CORR LEVEL</th><th>±BAND</th></tr></thead>
                    <tbody>
                      {d.tier_leadlag.map((x: any) => (
                        <tr key={`${x.from}${x.to}`}>
                          <td className="l amber">Tier {x.from} → Tier {x.to}</td>
                          <td className="yellow">{x.best_lag_days != null ? `${x.best_lag_days} 日` : '--'}</td>
                          <td>{fmtNum(x.corr_changes, 3)}</td><td>{fmtNum(x.corr_levels, 2)}</td><td className="muted">{fmtNum(x.band, 3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {ll13 && <div style={{ overflowX: 'auto' }}><Bars values={ll13.lags.filter((l: any) => l.lag >= 0).map((l: any) => l.corr)} labels={ll13.lags.filter((l: any) => l.lag >= 0).map((l: any) => String(l.lag))} height={90} band={ll13.band} /></div>}
                </div>
              </div>
              <div className="note">TIER COMPOSITES（平均 signed z）— 上流が先に動き、下流が遅れて追随するかを確認</div>
              <LineChart lines={comp} height={220} baseline={0} />
              {sel && (
                <div className="box" style={{ margin: 6 }}>
                  <h4>{sel.label} — Tier {sel.tier} · {sel.cls}</h4>
                  <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
                    <span>series</span><span className="muted">{JSON.stringify(sel.series)}</span>
                    <span>direction</span><span>{sel.dir > 0 ? 'up = risk-on' : 'up = risk-off (inverted)'}</span>
                    <span>last</span><span>{fmtNum(sel.signals.last, 3)} ({sel.signals.date})</span>
                    <span>signed z</span><span style={{ color: (sel.signals.sz ?? 0) >= 0 ? '#2fd17a' : '#ff4545' }}>{fmtNum(sel.signals.sz, 2)}</span>
                    <span>5d / 20d / 60d</span><span>{fmtChg(sel.signals.chg_5, sel.kind)} / {fmtChg(sel.signals.chg_20, sel.kind)} / {fmtChg(sel.signals.chg_60, sel.kind)}</span>
                    <span>above 100d MA</span><span>{sel.signals.above_ma100 == null ? '--' : sel.signals.above_ma100 ? 'yes' : 'no'}</span>
                  </div>
                  {sel.leaders && (
                    <table className="t">
                      <thead><tr><th className="l">LEADING INDICATOR (upstream)</th><th>TIER</th><th>LAG</th><th>CORR</th><th>LAG0</th><th className="l">SIG</th></tr></thead>
                      <tbody>
                        {sel.leaders.map((l: any) => (
                          <tr key={l.id} className="click" onClick={() => setSelId(l.id)}>
                            <td className="l amber">{l.label}</td><td>{l.tier}</td><td className="yellow">+{l.lag}d</td>
                            <td className={(l.corr ?? 0) >= 0 ? 'up' : 'down'}>{fmtNum(l.corr, 3)}</td><td className="muted">{fmtNum(l.lag0, 3)}</td>
                            <td className="l">{l.significant ? <span className="badge pass">YES</span> : <span className="muted">no</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  <div className="toolbar">
                    {(sel.series.sym ? [sel.series.sym] : []).map((s: string) => <button key={s} className="tb" onClick={() => onChart(s)}>GP {s}</button>)}
                  </div>
                </div>
              )}
              {Object.keys(d.errors ?? {}).length > 0 && <div className="note">unavailable series: {Object.keys(d.errors).join(', ')}</div>}
            </>
          )}
        </>
      )}
    </div>
  );
}

function MapEditor({ onSaved }: { onSaved: () => void }) {
  const m = useAsync(() => api.get<any>('/macro/map'), []);
  const [text, setText] = useState('');
  const [err, setErr] = useState<string>();
  if (m.loading) return <Loading />;
  const value = text || JSON.stringify(m.data?.items ?? [], null, 1);
  return (
    <div className="pad">
      <div className="note">
        各項目: id, label, cls ({(m.data?.classes ?? []).join(' / ')}), tier (1-3), series ({'{"sym": S} | {"spread": [A,B]} | {"ratio": [A,B]} | {"basket": [...]} | {"inv": S}'}), kind (price | yield), dir (+1 = 上昇がリスクオン, −1 = 逆)。
        {m.data?.custom ? ' 現在はカスタム定義を使用中。' : ' 現在は既定の定義。'}
      </div>
      <textarea className="inp" spellCheck={false} rows={28} value={value} onChange={(e) => setText(e.target.value)} />
      <ErrorBox error={err} />
      <div className="toolbar">
        <button className="tb green" onClick={async () => {
          try {
            await api.put('/macro/map', { items: JSON.parse(value) });
            onSaved();
          } catch (e: any) {
            setErr(e.message);
          }
        }}>SAVE MAP</button>
        <button className="tb red" onClick={async () => { if (confirm('reset to the default map?')) { await api.del('/macro/map'); onSaved(); } }}>RESET TO DEFAULT</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- MACRO
export function MACRO() {
  const [source, setSource] = useState('');
  const r = useAsync(() => api.get<any>('/macro/dashboard', { source: source || undefined }), [source]);
  const d = r.data;
  const rg = d?.regime;
  const regimes = rg ? Object.keys(rg.returns_by_regime) : [];
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">SOURCE</span>
        <select className="inp" value={source} onChange={(e) => setSource(e.target.value)}>{['', 'tradingview', 'yahoo', 'sim'].map((s) => <option key={s} value={s}>{s || '(active)'}</option>)}</select>
        <button className="tb" onClick={r.reload}>REFRESH</button>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <>
          {rg?.current && (
            <div className="box" style={{ margin: 6 }}>
              <h4>MACRO REGIME (成長 × インフレ) — {rg.current.month}</h4>
              <div className="pad" style={{ fontSize: 16 }}>
                <span className="yellow">{rg.current.regime}</span>
                <span className="muted"> · growth (copper/gold 3M) {fmtPct(rg.current.growth_chg, 1)} · inflation (TIP/IEF 3M) {fmtPct(rg.current.inflation_chg, 2)}</span>
              </div>
              <div style={{ display: 'flex', gap: 2, padding: '0 6px 6px', flexWrap: 'wrap' }}>
                {rg.history.map((h: any) => (
                  <div key={h.month} title={`${h.month}: ${h.regime}`} style={{ width: 22, height: 14, background: h.growth_up ? (h.inflation_up ? '#c98a00' : '#1a8f3a') : h.inflation_up ? '#c2181b' : '#2b4c8c' }} />
                ))}
              </div>
              <div className="note">■ 緑 Goldilocks · ■ 黄 Reflation · ■ 赤 Stagflation · ■ 青 Deflation/Risk-off（直近 36 カ月）— {rg.note}</div>
              <table className="t">
                <thead><tr><th className="l">NEXT-MONTH RETURN BY REGIME</th>{rg.assets.map((a: string) => <th key={a}>{a.split(':').pop()}</th>)}</tr></thead>
                <tbody>
                  {regimes.map((name) => (
                    <tr key={name} className={rg.current.regime === name ? 'sel' : ''}>
                      <td className="l amber">{name}</td>
                      {rg.assets.map((a: string) => {
                        const s = rg.returns_by_regime[name]?.[a];
                        return <td key={a} style={{ background: s ? zColor(s.mean / 2) : undefined }} title={s ? `hit ${s.hit.toFixed(0)}% · n=${s.n}` : ''}>{s ? fmtPct(s.mean, 1) : '--'}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {d.growth_liquidity && !d.growth_liquidity.error && (
            <div className="box" style={{ margin: 6 }}>
              <h4>成長 × 流動性 4象限（Market Timing の一次シグナル）— GLQ</h4>
              <GLPanel gl={d.growth_liquidity} />
            </div>
          )}
          {d.dashboard.map((g: any) => (
            <div key={g.group} className="box" style={{ margin: 6 }}>
              <h4>{g.group}</h4>
              <table className="t">
                <thead><tr><th className="l">SERIES</th><th>LAST</th><th>5D</th><th>20D</th><th>60D</th><th>z (20D)</th><th>&gt;100D MA</th><th className="l">1Y SHAPE</th></tr></thead>
                <tbody>
                  {g.rows.map((x: any) => (
                    <tr key={x.label}>
                      <td className="l amber">{x.label}</td>
                      {x.error ? <td colSpan={7} className="l muted">{x.error}</td> : (
                        <>
                          <td>{fmtNum(x.last, x.kind === 'yield' ? 3 : 2)}</td>
                          <td>{fmtChg(x.chg_5, x.kind)}</td><td>{fmtChg(x.chg_20, x.kind)}</td><td>{fmtChg(x.chg_60, x.kind)}</td>
                          <td style={{ background: zColor(x.sz) }}>{fmtNum(x.sz, 2)}</td>
                          <td className={x.above_ma100 ? 'up' : 'down'}>{x.above_ma100 == null ? '--' : x.above_ma100 ? '▲' : '▼'}</td>
                          <td className="l"><Spark v={x.spark} w={110} /></td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- MRGN (信用残)
const toTs = (d: string) => Math.floor(new Date(d + 'T00:00:00Z').getTime() / 1000);
export function MRGN({ symbol, onPick }: { symbol: string; onPick: (s: string) => void }) {
  const [reload, setReload] = useState(0);
  const dates = useAsync(() => api.get<any>('/margin/dates'), [reload]);
  const [date, setDate] = useState('');
  const rk = useAsync(() => api.get<any>('/margin/ranking', { date: date || undefined }), [date, reload]);
  const st = useAsync(() => (symbol.startsWith('TSE:') ? api.get<any>('/margin/stock', { symbol }) : Promise.resolve(null)), [symbol, reload]);
  const [sort, setSort] = useState<{ k: string; dir: number }>({ k: 'ratio', dir: -1 });
  const [msg, setMsg] = useState<string>();
  const [url, setUrl] = useState('');
  const [fileDate, setFileDate] = useState('');
  async function upload(f: File) {
    const fd = new FormData();
    fd.append('file', f);
    if (fileDate) fd.append('date', fileDate);
    const r = await fetch('/api/margin/import', { method: 'POST', body: fd });
    const j = await r.json();
    setMsg(r.ok ? `imported ${j.records} rows · ${j.codes} codes · ${j.dates.join(', ')}` : `ERROR ${j.detail}`);
    setReload((x) => x + 1);
  }
  const rows = [...(rk.data?.rows ?? [])].sort((a: any, b: any) => ((a[sort.k] ?? -Infinity) - (b[sort.k] ?? -Infinity)) * sort.dir);
  const th = (k: string, l: string) => <th className="sort" onClick={() => setSort({ k, dir: sort.k === k ? -sort.dir : -1 })}>{l}{sort.k === k ? (sort.dir > 0 ? '▲' : '▼') : ''}</th>;
  const s = st.data;
  const ratioLine = useMemo(() => (s?.rows ? [{ name: '信用倍率', data: s.rows.filter((r: any) => r.ratio != null).map((r: any) => ({ time: toTs(r.date), value: r.ratio })), color: '#ffd84a' }] : []), [s]);
  const balLines = useMemo(() => (s?.rows ? [
    { name: '買残', data: s.rows.map((r: any) => ({ time: toTs(r.date), value: r.long })), color: '#2fd17a' },
    { name: '売残', data: s.rows.map((r: any) => ({ time: toTs(r.date), value: r.short })), color: '#ff4545' },
  ] : []), [s]);
  const px = useMemo(() => (s?.rows ? [{ name: 'close', data: s.rows.filter((r: any) => r.close != null).map((r: any) => ({ time: toTs(r.date), value: r.close })), color: '#ffa028' }] : []), [s]);
  return (
    <div>
      <div className="toolbar">
        <label className="tb green">UPLOAD JPX FILE (CSV/XLSX)<input type="file" accept=".csv,.xlsx" style={{ display: 'none' }} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
        <span className="lbl">DATE (if not in file)</span>
        <input className="inp" type="date" value={fileDate} onChange={(e) => setFileDate(e.target.value)} />
        <input className="inp" style={{ width: 260 }} placeholder="https://…/margin file URL" value={url} onChange={(e) => setUrl(e.target.value)} />
        <button className="tb" disabled={!url} onClick={async () => {
          try {
            const j = await api.post<any>('/margin/import_url', { url, date: fileDate || null });
            setMsg(`imported ${j.records} rows · ${j.dates.join(', ')}`);
            setReload((x) => x + 1);
          } catch (e: any) {
            setMsg(`ERROR ${e.message}`);
          }
        }}>IMPORT URL</button>
        <span className="muted">{dates.data ? `${dates.data.dates.length} weeks · ${dates.data.codes} codes stored` : ''}</span>
      </div>
      {msg && <div className={msg.startsWith('ERROR') ? 'err' : 'note'}>{msg}</div>}
      {dates.data && !dates.data.dates.length && (
        <div className="pad muted">
          JPX が毎週火曜に公表する「銘柄別信用取引週末残高」(CSV/Excel) をアップロードしてください。列（コード・銘柄名・売残・買残、合計列を優先）は自動判定します。毎週取り込むと時系列で分析できます。
        </div>
      )}
      {s && !s.error && (
        <div className="box" style={{ margin: 6 }}>
          <h4>{symbol} {s.name ?? ''} — 信用残 ({s.weeks} weeks)</h4>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>信用倍率</span><span className="yellow">{fmtNum(s.latest.ratio, 2)} 倍 ({s.latest.date})</span>
            <span>倍率の分位</span><span>{fmtNum(s.ratio_percentile, 0)}%ile (過去分布)</span>
            <span>買残 / 売残</span><span>{fmtNum(s.latest.long, 0)} / {fmtNum(s.latest.short, 0)}</span>
            <span>前週比</span><span><span className={(s.latest.long_chg ?? 0) >= 0 ? 'up' : 'down'}>買 {fmtNum(s.latest.long_chg, 0)}</span> · <span className={(s.latest.short_chg ?? 0) >= 0 ? 'up' : 'down'}>売 {fmtNum(s.latest.short_chg, 0)}</span></span>
            <span>買残 / 出来高(20D)</span><span>{fmtNum(s.buy_days, 1)} 日分</span>
            <span>売残 / 出来高(20D)</span><span>{fmtNum(s.sell_days, 1)} 日分</span>
            <span>Δ倍率 vs 4週後リターン</span><span>{s.ratio_change_vs_fwd4w ? `corr ${fmtNum(s.ratio_change_vs_fwd4w.corr, 2)} (n=${s.ratio_change_vs_fwd4w.n})` : 'insufficient history'}</span>
          </div>
          <LineChart lines={ratioLine} height={140} baseline={1} />
          <LineChart lines={balLines} height={140} />
          <LineChart lines={px} height={120} />
        </div>
      )}
      {s?.error && symbol.startsWith('TSE:') && <div className="note">{symbol}: {s.error}</div>}
      {rk.data?.rows?.length > 0 && (
        <>
          <div className="toolbar">
            <span className="lbl">RANKING DATE</span>
            <select className="inp" value={date} onChange={(e) => setDate(e.target.value)}>
              <option value="">latest ({rk.data.date})</option>
              {[...(dates.data?.dates ?? [])].reverse().map((d: string) => <option key={d}>{d}</option>)}
            </select>
            <span className="muted">vs {rk.data.previous ?? '—'} · 倍率&lt;1 = 売り長（踏み上げ余地）, 高倍率 = 将来の売り圧力</span>
          </div>
          <table className="t">
            <thead><tr><th className="l">CODE</th><th className="l">NAME</th>{th('ratio', '信用倍率')}{th('ratio_chg', 'Δ倍率')}{th('long', '買残')}{th('long_chg_pct', '買残 WoW%')}{th('short', '売残')}{th('short_chg_pct', '売残 WoW%')}</tr></thead>
            <tbody>
              {rows.slice(0, 300).map((r: any) => (
                <tr key={r.code} className={`click ${symbol === r.symbol ? 'sel' : ''}`} onClick={() => onPick(r.symbol)}>
                  <td className="l sym">{r.code}</td><td className="l name">{r.name}</td>
                  <td className={r.ratio != null && r.ratio < 1 ? 'up' : r.ratio > 10 ? 'down' : ''}>{fmtNum(r.ratio, 2)}</td>
                  <td className={(r.ratio_chg ?? 0) > 0 ? 'down' : 'up'}>{fmtNum(r.ratio_chg, 2)}</td>
                  <td>{fmtNum(r.long, 0)}</td><td>{fmtPct(r.long_chg_pct, 1)}</td><td>{fmtNum(r.short, 0)}</td><td>{fmtPct(r.short_chg_pct, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- TXT (transcripts)
export function TXT({ symbol }: { symbol: string }) {
  const list = useAsync(() => api.get<any>(`/transcripts/${encodeURIComponent(symbol)}`), [symbol]);
  const [sel, setSel] = useState<string | undefined>();
  const items: any[] = list.data?.items || [];
  const an = useAsync(() => (items.length ? api.get<any>(`/transcripts/${encodeURIComponent(symbol)}/analyze`, { id: sel }) : Promise.resolve(null)), [symbol, sel, items.length]);
  const [period, setPeriod] = useState('');
  const [text, setText] = useState('');
  const [brief, setBrief] = useState('');
  const [val, setVal] = useState<any>(null);
  const [pack, setPack] = useState('');
  const [tab, setTab] = useState<'DIFF' | 'QA' | 'NUM' | 'BRIEF'>('DIFF');
  const d = an.data;
  const add = async () => {
    await api.post(`/transcripts/${encodeURIComponent(symbol)}`, { period, text });
    setText(''); setPeriod(''); list.reload();
  };
  const sid = (i: number) => d?.sentences?.[i]?.text ?? '';
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">PERIODS</span>
        {items.map((t) => (
          <button key={t.id} className={`tb ${(sel ?? items[items.length - 1]?.id) === t.id ? 'on' : ''}`} onClick={() => setSel(t.id)}>{t.period}</button>
        ))}
        {(['DIFF', 'QA', 'NUM', 'BRIEF'] as const).map((x) => <button key={x} className={`tb ${tab === x ? 'on' : ''}`} onClick={() => setTab(x)}>{x}</button>)}
      </div>
      <details className="pad" open={!items.length}>
        <summary className="amber">+ 決算説明会・スモールミーティングの書き起こしを追加（ATLAS の文字起こしを貼り付け）</summary>
        <div className="toolbar"><span className="lbl">PERIOD</span><input className="inp" value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026Q2" /><button className="tb on" disabled={!period || !text} onClick={add}>SAVE</button>
          <span className="muted">Q&amp;A は「Q:」「A:」または「質問：」「回答：」で始めると回避度を判定します</span></div>
        <textarea className="inp" style={{ width: '100%', height: 120 }} value={text} onChange={(e) => setText(e.target.value)} />
      </details>
      {an.loading && <Loading />}
      <ErrorBox error={an.error || list.error} />
      {d && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(2, max-content 1fr)' }}>
            <span>NET TONE</span><span className={d.tone.net_tone > 0 ? 'up' : 'down'}>{fmtNum(d.tone.net_tone, 2)} {d.tone_change != null && <span className="muted">(Δ {fmtNum(d.tone_change, 2)})</span>}</span>
            <span>UNCERTAINTY /1k</span><span>{fmtNum(d.tone.uncertainty_per_1k, 1)} {d.uncertainty_change != null && <span className="muted">(Δ {fmtNum(d.uncertainty_change, 1)})</span>}</span>
            <span>LAZY-PRICES CHANGE</span><span className="yellow">{d.diff ? fmtNum(d.diff.change_score, 3) : '— (前期なし)'}</span>
            <span>Q&amp;A EVASIVENESS</span><span className={d.evasiveness_avg >= 0.6 ? 'down' : d.evasiveness_avg >= 0.4 ? 'yellow' : 'up'}>{d.evasiveness_avg != null ? fmtNum(d.evasiveness_avg, 2) : '--'}</span>
            <span>vs</span><span className="muted">{d.prev_period ?? '—'} → {d.period}</span>
          </div>
          {d.history.length > 1 && (
            <table className="t"><thead><tr><th className="l">PERIOD</th><th>CHANGE (1−cos)</th><th>NET TONE</th><th>UNC/1k</th></tr></thead>
              <tbody>{d.history.map((h: any) => <tr key={h.period}><td className="l amber">{h.period}</td><td>{fmtNum(h.change_score, 3)}</td><td>{fmtNum(h.net_tone, 2)}</td><td>{fmtNum(h.uncertainty_per_1k, 1)}</td></tr>)}</tbody></table>
          )}
          {tab === 'DIFF' && d.diff && (
            <div className="trin-split">
              <div className="box" style={{ margin: 6, flex: 1 }}><h4>NEW — 今回新たに出てきた文 ({d.diff.new_count})</h4>
                {d.diff.new_sentences.map((s: any) => <div key={s.sid} className={`pad ${s.tone > 0 ? 'up' : s.tone < 0 ? 'down' : ''}`}>[S{s.sid}] {s.text}</div>)}</div>
              <div className="box" style={{ margin: 6, flex: 1 }}><h4>DROPPED — 前回あって今回消えた文 ({d.diff.dropped_count})</h4>
                {d.diff.dropped_sentences.map((s: any) => <div key={s.sid} className="pad muted">{s.text}</div>)}</div>
              <div className="note" style={{ flexBasis: '100%' }}>{d.diff.note}</div>
            </div>
          )}
          {tab === 'DIFF' && !d.diff && <div className="note">前期の書き起こしを保存すると、言語変化（Lazy Prices）を計測します。</div>}
          {tab === 'QA' && (
            <table className="t"><thead><tr><th>SCORE</th><th className="l">Q</th><th className="l">A</th><th className="l">回避フレーズ</th></tr></thead>
              <tbody>{d.qa.map((q: any, i: number) => (
                <tr key={i}><td className={q.score >= 0.6 ? 'down' : q.score >= 0.4 ? 'yellow' : 'up'}>{fmtNum(q.score, 2)} {q.label}</td><td className="l">{q.q}</td><td className="l">{q.a}</td><td className="l muted">{q.non_answer_phrases.join(', ')}</td></tr>
              ))}</tbody></table>
          )}
          {tab === 'NUM' && (
            <table className="t"><thead><tr><th>S#</th><th>VALUE</th><th>UNIT</th><th>GUIDE</th><th className="l">CONTEXT</th></tr></thead>
              <tbody>{d.numbers.map((n: any, i: number) => (
                <tr key={i}><td className="muted">S{n.sid}</td><td className="amber">{fmtNum(n.value, Math.abs(n.value) < 100 ? 2 : 0)}</td><td>{n.unit}</td><td className={n.guidance ? 'yellow' : 'muted'}>{n.guidance ? '見通し' : ''}</td><td className="l">{n.context}</td></tr>
              ))}</tbody></table>
          )}
          {tab === 'BRIEF' && (
            <div className="pad">
              <div className="note">AIに書かせる Bull/Bear ブリーフを「出典 [S#] 必須・出典にない数字は禁止」で検証するハーネス。① プロンプトをコピーしてAIへ → ② 回答を貼り付けて VALIDATE。</div>
              <button className="tb" onClick={async () => { const p = await api.get<any>(`/transcripts/${encodeURIComponent(symbol)}/brief_pack`, { id: sel }); setPack(p.prompt); navigator.clipboard?.writeText(p.prompt).catch(() => {}); }}>① COPY PROMPT</button>
              {pack && <span className="muted"> copied ({pack.length} chars)</span>}
              <textarea className="inp" style={{ width: '100%', height: 140, marginTop: 4 }} value={brief} onChange={(e) => setBrief(e.target.value)} placeholder={'## Bull\n- … [S3]\n## Bear\n- … [S7]'} />
              <button className="tb on" disabled={!brief} onClick={async () => setVal(await api.post<any>(`/transcripts/${encodeURIComponent(symbol)}/validate_brief`, { brief, id: sel }))}>② VALIDATE</button>
              {val && (
                <>
                  <div className={val.ok ? 'up' : 'down'}>{val.ok ? '✓ 全行が出典と整合' : `✕ ${val.violations}/${val.checked} 行に問題`}</div>
                  <table className="t"><tbody>{val.lines.map((l: any, i: number) => (
                    <tr key={i}><td className={l.ok ? 'up' : 'down'}>{l.ok ? '✓' : '✕'}</td><td className="l">{l.line}<div className="muted" style={{ fontSize: 10 }}>{l.cites.map((c: number) => `[S${c}] ${sid(c)}`).join(' / ')}</div></td><td className="l down">{l.problems.join('; ')}</td></tr>
                  ))}</tbody></table>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- TRND (Google Trends / X / StockTwits)
export function TRND({ symbol }: { symbol: string }) {
  const [kw, setKw] = useState('');
  const [geo, setGeo] = useState('JP');
  const [tf, setTf] = useState('today 12-m');
  const [link, setLink] = useState(true);
  const [q, setQ] = useState<any>(null);
  const gt = useAsync(() => (q ? api.get<any>('/trends/google', q) : Promise.resolve(null)), [q]);
  const [xq, setXq] = useState('');
  const [xr, setXr] = useState<any>(null);
  const [xe, setXe] = useState('');
  const st = useAsync(() => api.get<any>('/social/stocktwits', { symbol: symbol.includes(':') && !/^(NASDAQ|NYSE|AMEX)/.test(symbol) ? undefined : symbol }), [symbol]);
  const d = gt.data;
  const lines = d ? Object.entries(d.series).map(([k, s]: any, i) => ({ name: k, data: s.map((p: any) => ({ time: p.time, value: p.value })), color: ['#ffa028', '#59e3ff', '#ff6ad5', '#2fd17a', '#ffd84a'][i] })) : [];
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">GOOGLE TRENDS</span>
        <input className="inp" style={{ width: 220 }} value={kw} onChange={(e) => setKw(e.target.value)} placeholder="keyword1, keyword2 (≤5)" />
        <select className="inp" value={geo} onChange={(e) => setGeo(e.target.value)}>{['', 'JP', 'US', 'CN', 'KR', 'TW'].map((g) => <option key={g} value={g}>{g || 'WORLD'}</option>)}</select>
        <select className="inp" value={tf} onChange={(e) => setTf(e.target.value)}>{['now 7-d', 'today 1-m', 'today 3-m', 'today 12-m', 'today 5-y'].map((t) => <option key={t}>{t}</option>)}</select>
        <label className="muted"><input type="checkbox" checked={link} onChange={(e) => setLink(e.target.checked)} /> vs {symbol}</label>
        <button className="tb on" disabled={!kw.trim()} onClick={() => setQ({ keywords: kw, geo, timeframe: tf, symbol: link ? symbol : undefined })}>GO</button>
      </div>
      {gt.loading && <Loading />}
      <ErrorBox error={gt.error} />
      {d && (
        <>
          <LineChart lines={lines} height={220} />
          <table className="t">
            <thead><tr><th className="l">KEYWORD</th><th>SPIKE z</th><th>MOMENTUM</th><th>vs PRICE: best lead</th><th>contemp. corr</th><th>Granger att→px p</th></tr></thead>
            <tbody>{d.keywords.map((k: string) => {
              const sp = d.spikes[k];
              const vp = d.vs_price?.[k];
              return (
                <tr key={k}><td className="l amber">{k}</td><td className={sp?.z > 2 ? 'down' : ''}>{fmtNum(sp?.z, 2)}</td><td>{sp?.momentum != null ? fmtPct(sp.momentum * 100, 0) : '--'}</td>
                  <td>{vp?.best_lead ? `lag ${vp.best_lead.lag} · r ${fmtNum(vp.best_lead.corr, 2)}` : vp?.error || '--'}</td><td>{fmtNum(vp?.contemporaneous, 2)}</td><td>{fmtNum(vp?.granger_attention_to_price?.p, 3)}</td></tr>
              );
            })}</tbody>
          </table>
          {d.related && (
            <div className="trin-split">
              {Object.entries(d.related).map(([k, r]: any) => (
                <div key={k} className="box" style={{ margin: 6, flex: 1 }}>
                  <h4>{k} — RISING / TOP queries</h4>
                  <table className="t"><tbody>{r.rising.map((x: any) => <tr key={'r' + x.query}><td className="l yellow">{x.query}</td><td>{x.value}</td></tr>)}
                    {r.top.slice(0, 8).map((x: any) => <tr key={'t' + x.query}><td className="l muted">{x.query}</td><td className="muted">{x.value}</td></tr>)}</tbody></table>
                </div>
              ))}
            </div>
          )}
          {d.vs_price_error && <div className="note">price: {d.vs_price_error}</div>}
        </>
      )}
      <div className="toolbar">
        <span className="lbl">X (Twitter)</span>
        <input className="inp" style={{ width: 220 }} value={xq} onChange={(e) => setXq(e.target.value)} placeholder="$NVDA OR 半導体" />
        <button className="tb" disabled={!xq} onClick={async () => { setXe(''); try { setXr(await api.get<any>('/social/x', { query: xq })); } catch (e: any) { setXe(e.message); } }}>GO</button>
        <span className="muted">要 X_BEARER_TOKEN（有料 API）</span>
      </div>
      {xe && <div className="err">{xe}</div>}
      {xr && (
        <div className="trin-split">
          <div style={{ flex: 1 }}><LineChart height={140} lines={[{ name: 'posts/day', data: xr.series.map((p: any) => ({ time: ts2(p.date), value: p.value })), color: '#59e3ff' }]} /></div>
          <div style={{ flex: 1 }} className="pad">
            spike z {fmtNum(xr.spike?.z, 2)} · bullish {fmtPct(xr.sentiment.bullish_share, 0, false)} ({xr.sentiment.with_signal}/{xr.sentiment.posts})
            {xr.top_posts.map((p: any, i: number) => <div key={i} className="muted" style={{ fontSize: 11 }}>♥{p.weight} {p.text.slice(0, 140)}</div>)}
          </div>
        </div>
      )}
      <div className="box" style={{ margin: 6 }}>
        <h4>STOCKTWITS {st.data?.symbol ? `— ${st.data.symbol}` : '— trending'}</h4>
        <ErrorBox error={st.error} />
        {st.data?.trending && <div className="pad">{st.data.trending.map((t: any) => <span key={t.symbol} className="amber" style={{ marginRight: 10 }}>{t.symbol}<span className="muted"> {fmtNum(t.watchers, 0)}</span></span>)}</div>}
        {st.data?.sentiment && (
          <div className="pad">watchers {fmtNum(st.data.watchers, 0)} · bullish {fmtPct(st.data.sentiment.bullish_share, 0, false)} ({st.data.sentiment.with_signal} labelled)
            {st.data.recent.slice(0, 8).map((p: any, i: number) => <div key={i} className={p.label === 'Bullish' ? 'up' : p.label === 'Bearish' ? 'down' : 'muted'} style={{ fontSize: 11 }}>{p.label || '·'} {p.text.slice(0, 160)}</div>)}
          </div>
        )}
      </div>
      <div className="note">PROP の第1段（ニッチ／マクロ専門家）で起きた変化が、検索・SNS の関心（第2〜3段）に波及しているかの確認に使う。Google Trends は非公式エンドポイント（仕様変更で失敗し得る）。</div>
    </div>
  );
}
const ts2 = (d: string) => Math.floor(Date.parse(d) / 1000);
