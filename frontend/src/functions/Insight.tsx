// Analysis expansion (rule-based):
//   XRAY  return decomposition & unintended factor bets (stock / book)
//   RRG   relative rotation graph (TOPIX-17 / US sectors / coverage / custom)
//   THEME Theme Alpha baskets: phase of the reaction lag, basket flow, driver lead
//   PFND  automatic pair candidates inside each subsector
//   TRAK  track record from the blotter with Bayesian hit rates → KELLY
import { useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, fmtPct } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { useTerminal } from '../ctx';
import { WindowSlider, type WindowValue } from '../components/WindowSlider';

const SRC = ['', 'tradingview', 'yahoo', 'sim'];
const ts = (d: string) => Math.floor(Date.parse(d) / 1000);
const stCls = (s: string) => (s === 'PASS' ? 'up' : s === 'FAIL' ? 'down' : s === 'WARN' ? 'yellow' : 'muted');
const SHARE_COL: Record<string, string> = { market: '#5ea9ff', style: '#a98bff', sector: '#ffa028', idio: '#2fd17a' };
const SHARE_LBL: Record<string, string> = { market: 'マーケット', style: 'スタイル・マクロ', sector: 'セクター', idio: '個別固有' };

function SourceSel({ v, set }: { v: string; set: (s: string) => void }) {
  return (
    <>
      <span className="lbl">SOURCE</span>
      <select className="inp" value={v} onChange={(e) => set(e.target.value)}>{SRC.map((s) => <option key={s} value={s}>{s || '(active)'}</option>)}</select>
    </>
  );
}

function Stack({ shares, height = 18 }: { shares: Record<string, number>; height?: number }) {
  return (
    <div className="stack" style={{ height }}>
      {['market', 'style', 'sector', 'idio'].map((k) => (
        <span key={k} style={{ width: `${Math.max(0, (shares[k] || 0) * 100)}%`, background: SHARE_COL[k] }} title={`${SHARE_LBL[k]} ${fmtPct((shares[k] || 0) * 100, 0, false)}`}>
          {(shares[k] || 0) >= 0.08 ? `${Math.round((shares[k] || 0) * 100)}` : ''}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- XRAY
export function XRAY({ symbol }: { symbol: string }) {
  const [mode, setMode] = useState<'STOCK' | 'BOOK'>('STOCK');
  const [w, setW] = useState<WindowValue>({ length: 252, offset: 0 });
  const [source, setSource] = useState('');
  const one = useAsync(() => (mode === 'STOCK' ? api.get<any>('/insight/xray', { symbol, lookback: w.length, end_offset: w.offset, source: source || undefined }) : Promise.resolve(null)), [symbol, w.length, w.offset, source, mode]);
  const book = useAsync(() => (mode === 'BOOK' ? api.post<any>('/insight/xray/book', { lookback: w.length, end_offset: w.offset, source: source || null }) : Promise.resolve(null)), [w.length, w.offset, source, mode]);
  const d = one.data;
  const b = book.data;
  const maxImp = d ? Math.max(0.01, ...d.coefficients.map((c: any) => Math.abs(c.impact_1sd_pct))) : 1;
  return (
    <div>
      <div className="toolbar">
        {(['STOCK', 'BOOK'] as const).map((m) => <button key={m} className={`tb ${mode === m ? 'on' : ''}`} onClick={() => setMode(m)}>{m === 'STOCK' ? `銘柄 ${symbol}` : 'ブック（RULE）'}</button>)}
        <SourceSel v={source} set={setSource} />
      </div>
      <WindowSlider label="推定期間" value={w} onChange={setW} min={120} max={1000} step={5} maxOffset={750} asof={one.data?.to} />
      {(one.loading || book.loading) && <Loading />}
      <ErrorBox error={mode === 'STOCK' ? one.error : book.error} />
      {mode === 'STOCK' && d && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(3, max-content 1fr)' }}>
            <span>ボラ（年率）</span><span>{fmtPct(d.vol_pct, 1, false)}</span>
            <span>個別ボラ</span><span>{fmtPct(d.idio_vol_pct, 1, false)}</span>
            <span>R²</span><span>{fmtNum(d.r2, 2)} <span className="muted">n={d.n}</span></span>
            <span>セクター</span><span className="amber">{d.sector_label || d.sector_etf || '—'}</span>
            <span>期間</span><span className="muted">{d.from} → {d.to}</span>
          </div>
          <div className="pad">
            <div className="muted">リターン分散の分解（マーケット → スタイル・マクロ → セクター → 個別固有）</div>
            <Stack shares={d.shares} height={22} />
            <div className="muted" style={{ marginTop: 4 }}>Notion の典型（日本の単一銘柄）: マーケット 40–50% / スタイル 25–30% / セクター 15–20% / 個別 ≈10%</div>
            <Stack shares={{ market: 0.45, style: 0.275, sector: 0.175, idio: 0.1 }} height={10} />
            <div style={{ marginTop: 6 }} className={d.shares.idio >= 0.5 ? 'up' : d.shares.idio < 0.3 ? 'down' : 'yellow'}>→ {d.verdict}</div>
            <div className="xlegend">{Object.keys(SHARE_COL).map((k) => <span key={k}><i style={{ background: SHARE_COL[k] }} /> {SHARE_LBL[k]} {fmtPct(d.shares[k] * 100, 0, false)}</span>)}</div>
          </div>
          <table className="t">
            <thead><tr><th className="l">FACTOR</th><th>β</th><th>t</th><th>1σ インパクト（%/日）</th><th className="l" style={{ width: '35%' }} /></tr></thead>
            <tbody>
              {d.coefficients.map((c: any) => (
                <tr key={c.factor}>
                  <td className="l amber">{c.factor}</td><td>{fmtNum(c.beta, c.kind === 'bp' ? 4 : 2)}</td>
                  <td className={Math.abs(c.t) >= 2 ? 'yellow' : 'muted'}>{fmtNum(c.t, 1)}</td>
                  <td className={c.impact_1sd_pct > 0 ? 'up' : 'down'}>{fmtNum(c.impact_1sd_pct, 3)}</td>
                  <td className="l"><div className="hbar"><span style={{ width: `${(Math.abs(c.impact_1sd_pct) / maxImp) * 100}%`, background: c.impact_1sd_pct > 0 ? '#2fd17a' : '#ff4545' }} /></div></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="note">ルール: 日次リターンを順にマーケット → スタイル・マクロ（為替・金利・原油・銅・半導体・中国・スタイル ETF）→ セクター ETF で回帰し、R² の増分を各層の寄与とする（順序依存の階層分解）。金利は bp 変化。1σ インパクト = β × 因子の日次σ。</div>
        </>
      )}
      {mode === 'BOOK' && b && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>銘柄数</span><span>{b.positions}</span>
            <span>ブック・ボラ</span><span>{fmtPct(b.vol_pct, 2, false)}</span>
            <span>ファクター由来</span><span className={b.factor_var_share > 0.5 ? 'down' : 'up'}>{fmtPct((b.factor_var_share ?? 0) * 100, 0, false)}</span>
            <span>個別由来</span><span>{fmtPct((b.idio_var_share ?? 0) * 100, 0, false)}</span>
            <span>マーケット露出</span><span className={Math.abs(b.market_exposure_pct) > 5 ? 'down' : 'up'}>{fmtPct(b.market_exposure_pct, 2)}</span>
          </div>
          {b.flags.map((f: string) => <div key={f} className="down" style={{ padding: '2px 6px' }}>⚠ {f}</div>)}
          {!b.flags.length && <div className="up" style={{ padding: '2px 6px' }}>✓ 意図しないファクター・ベットの兆候なし（ルール: 単一因子 &gt; 20%、マーケット露出 &gt; 5%、個別由来 &lt; 50%）</div>}
          <table className="t">
            <thead><tr><th className="l">FACTOR</th><th>EXPOSURE</th><th>1σ（bp/日）</th><th>分散寄与</th><th className="l" style={{ width: '30%' }} /></tr></thead>
            <tbody>{b.factors.map((f: any) => (
              <tr key={f.factor}>
                <td className="l amber">{f.factor}</td><td>{fmtNum(f.exposure, 4)}</td><td>{fmtNum(f.impact_1sd_bp, 1)}</td>
                <td className={f.var_share > 0.2 ? 'down' : ''}>{fmtPct((f.var_share ?? 0) * 100, 1)}</td>
                <td className="l"><div className="hbar"><span style={{ width: `${Math.min(100, Math.abs(f.var_share ?? 0) * 100)}%`, background: (f.var_share ?? 0) > 0.2 ? '#ff4545' : '#5ea9ff' }} /></div></td>
              </tr>
            ))}</tbody>
          </table>
          <table className="t">
            <thead><tr><th className="l">SYMBOL</th><th>W %</th><th className="l" style={{ width: '45%' }}>分解</th><th className="l">判定</th></tr></thead>
            <tbody>{b.by_symbol.map((s: any) => (
              <tr key={s.symbol}><td className="l amber">{s.symbol}</td><td>{fmtNum(s.weight, 2)}</td><td className="l"><Stack shares={s} height={12} /></td><td className="l muted" style={{ fontSize: 10 }}>{s.verdict}</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- RRG
const QC: Record<string, string> = { Leading: '#1a8f3a', Weakening: '#c98a00', Lagging: '#c2181b', Improving: '#2b4c8c' };

export function RRG({ args }: { args?: string }) {
  const { setSecurity, run } = useTerminal();
  const [uni, setUni] = useState((args || 'JP17').toUpperCase());
  const [syms, setSyms] = useState('');
  const [q, setQ] = useState<any>({ universe: (args || 'JP17').toUpperCase() });
  const [w, setW] = useState<WindowValue>({ length: 8, offset: 0 });
  const [n, setN] = useState(10);
  const [source, setSource] = useState('');
  const r = useAsync(() => api.get<any>('/insight/rrg', { ...q, tail: w.length, end_weeks: w.offset, n, source: source || undefined }), [q, w.length, w.offset, n, source]);
  const d = r.data;
  const rows: any[] = (d?.rows || []).filter((x: any) => x.quadrant);
  const pts = rows.flatMap((x: any) => x.tail);
  const span = pts.length ? Math.max(1.5, ...pts.map((p: any) => Math.max(Math.abs(p.ratio - 100), Math.abs(p.momentum - 100)))) * 1.1 : 3;
  const X = (v: number) => 200 + ((v - 100) / span) * 185;
  const Y = (v: number) => 200 - ((v - 100) / span) * 185;
  return (
    <div>
      <div className="toolbar">
        {['JP17', 'US11', 'COVER', 'CUSTOM'].map((u) => <button key={u} className={`tb ${uni === u ? 'on' : ''}`} onClick={() => { setUni(u); if (u !== 'CUSTOM') setQ({ universe: u }); }}>{u === 'JP17' ? 'TOPIX-17' : u === 'US11' ? 'US セクター' : u === 'COVER' ? 'カバレッジ' : 'CUSTOM'}</button>)}
        {uni === 'CUSTOM' && (<><input className="inp" style={{ width: 260 }} value={syms} onChange={(e) => setSyms(e.target.value)} placeholder="TSE:8035, TSE:6857, …" /><button className="tb on" onClick={() => setQ({ universe: 'CUSTOM', symbols: syms })}>GO</button></>)}
        <span className="lbl">平滑化</span>
        <select className="inp" value={n} onChange={(e) => setN(+e.target.value)}>{[6, 10, 14, 20].map((x) => <option key={x} value={x}>{x}週</option>)}</select>
        <SourceSel v={source} set={setSource} />
        {d && <span className="muted">vs {d.bench} · {d.weeks} weeks</span>}
      </div>
      <WindowSlider label="軌跡" unit="weeks" value={w} onChange={setW} min={2} max={26} maxOffset={156} asof={d?.asof} />
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <div className="trin-split">
          <div style={{ flex: '0 0 380px' }}>
            <svg viewBox="0 0 400 400" className="glq" style={{ maxWidth: 380 }}>
              <rect x={200} y={15} width={185} height={185} fill={QC.Leading} opacity={0.14} />
              <rect x={200} y={200} width={185} height={185} fill={QC.Weakening} opacity={0.14} />
              <rect x={15} y={200} width={185} height={185} fill={QC.Lagging} opacity={0.14} />
              <rect x={15} y={15} width={185} height={185} fill={QC.Improving} opacity={0.14} />
              <line x1={15} x2={385} y1={200} y2={200} stroke="#444" /><line y1={15} y2={385} x1={200} x2={200} stroke="#444" />
              <text x={380} y={30} fill="#bbb" fontSize={10} textAnchor="end">主導 Leading</text>
              <text x={380} y={378} fill="#bbb" fontSize={10} textAnchor="end">減速 Weakening</text>
              <text x={20} y={378} fill="#bbb" fontSize={10}>劣後 Lagging</text>
              <text x={20} y={30} fill="#bbb" fontSize={10}>改善 Improving</text>
              <text x={385} y={195} fill="#777" fontSize={8} textAnchor="end">RS-Ratio →</text>
              <text x={204} y={24} fill="#777" fontSize={8}>↑ RS-Momentum</text>
              {rows.map((x: any) => (
                <g key={x.symbol} style={{ cursor: 'pointer' }} onClick={() => setSecurity(x.symbol)}>
                  <polyline fill="none" stroke={QC[x.quadrant]} strokeWidth={1.3} opacity={0.8} points={x.tail.map((p: any) => `${X(p.ratio)},${Y(p.momentum)}`).join(' ')} />
                  <circle cx={X(x.ratio)} cy={Y(x.momentum)} r={4} fill={QC[x.quadrant]} stroke="#fff" strokeWidth={0.6} />
                  <text x={X(x.ratio) + 5} y={Y(x.momentum) - 4} fill="#ddd" fontSize={8.5}>{String(x.label).slice(0, 10)}</text>
                </g>
              ))}
            </svg>
          </div>
          <div style={{ flex: 1, minWidth: 560 }}>
            <table className="t nowrap">
              <thead><tr><th className="l">NAME</th><th>QUAD</th><th>RATIO</th><th>MOM</th><th>回転</th><th>次</th><th>4W 相対</th><th>売買代金比</th><th>上昇週比率</th><th className="l">資金</th></tr></thead>
              <tbody>{rows.map((x: any) => (
                <tr key={x.symbol} style={{ cursor: 'pointer' }} onClick={() => setSecurity(x.symbol)} onDoubleClick={() => run('GP', x.symbol)}>
                  <td className="l amber">{x.label} <span className="muted">{x.symbol.split(':')[1]}</span></td>
                  <td style={{ color: QC[x.quadrant] }}>{x.quadrant_ja}</td><td>{fmtNum(x.ratio, 2)}</td><td>{fmtNum(x.momentum, 2)}</td>
                  <td className={x.rotation === '時計回り' ? 'muted' : 'yellow'}>{x.rotation}</td><td className="muted">{x.next}</td>
                  <td className={x.rel_4w_pct > 0 ? 'up' : 'down'}>{fmtPct(x.rel_4w_pct, 1)}</td>
                  <td className={x.value_ratio >= 1.2 ? 'yellow' : ''}>{fmtNum(x.value_ratio, 2)}</td><td>{x.up_share != null ? fmtPct(x.up_share * 100, 0, false) : '--'}</td>
                  <td className={`l ${x.flow_view === '資金流入が強い' ? 'up' : x.flow_view === '資金流出' ? 'down' : 'muted'}`}>{x.flow_view || ''}</td>
                </tr>
              ))}</tbody>
            </table>
            <div className="note">{d.note} 売買代金比 = 直近4週の売買代金 ÷ 52週平均。海外勢のセクター別フローは非公開のため、相対強度 × 売買代金をその代理とする（Notion 03.4 セクター・ファンドフロー・モニター）。</div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- THEME
const parseMembers = (t: string) => t.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean).map((x) => {
  const [s, w] = x.split(/[:\s]+/);
  return { symbol: s.toUpperCase(), weight: w ? parseFloat(w) : undefined };
});
const fmtMembers = (ms: any[] = []) => ms.map((m) => (m.weight && m.weight !== 1 ? `${m.symbol}:${m.weight}` : m.symbol)).join('\n');

export function THEME() {
  const { setSecurity } = useTerminal();
  const list = useAsync(() => api.get<any>('/insight/themes'), []);
  const [sel, setSel] = useState<string | null>(null);
  const [edit, setEdit] = useState<any>(null);
  const [source, setSource] = useState('');
  const themes: any[] = list.data?.themes || [];
  const cur = themes.find((t) => t.id === sel) || themes[0];
  const [tw, setTw] = useState<WindowValue>({ length: 500, offset: 0 });
  const an = useAsync(() => (cur ? api.get<any>(`/insight/themes/${cur.id}/analyze`, { source: source || undefined, lookback: tw.length, end_offset: tw.offset }) : Promise.resolve(null)), [cur?.id, source, list.data, tw.length, tw.offset]);
  const d = an.data;
  const startEdit = (t: any) => setEdit({ ...t, longsText: fmtMembers(t.longs), shortsText: fmtMembers(t.shorts), driverText: typeof t.driver === 'string' || !t.driver ? t.driver || '' : JSON.stringify(t.driver) });
  const save = async () => {
    let driver: any = edit.driverText?.trim() || null;
    if (driver && driver.startsWith('{')) { try { driver = JSON.parse(driver); } catch { /* keep text */ } }
    const body = { ...edit, driver, longs: parseMembers(edit.longsText || ''), shorts: parseMembers(edit.shortsText || ''), driver_dir: +edit.driver_dir || 1 };
    delete body.longsText; delete body.shortsText; delete body.driverText;
    const t = await api.post<any>('/insight/themes', body);
    setEdit(null); setSel(t.id); list.reload();
  };
  const lines = d?.series ? [
    { name: 'spread β中立', data: d.series.dates.map((x: string, i: number) => ({ time: ts(x), value: d.series.spread_bn[i] })), color: '#ffa028' },
    { name: 'long', data: d.series.dates.map((x: string, i: number) => ({ time: ts(x), value: d.series.long[i] })), color: '#2fd17a' },
    { name: 'short/hedge', data: d.series.dates.map((x: string, i: number) => ({ time: ts(x), value: d.series.short[i] })), color: '#ff4545' },
  ] : [];
  return (
    <div className="trin-split">
      <div style={{ flex: '0 0 230px' }}>
        <div className="toolbar">
          <button className="tb" onClick={() => startEdit({ name: '', engine: 'Theme Alpha', driver_dir: 1, driver_kind: 'price', hedge: 'TVC:TOPIX', longs: [], shorts: [] })}>+ NEW</button>
          <select className="inp" value="" onChange={async (e) => { if (e.target.value) { const t = await api.post<any>('/insight/themes/from_template', { name: e.target.value }); setSel(t.id); list.reload(); } }}>
            <option value="">+ TEMPLATE…</option>{(list.data?.templates || []).map((n: string) => <option key={n}>{n}</option>)}
          </select>
        </div>
        <table className="t"><tbody>{themes.map((t) => (
          <tr key={t.id} className={cur?.id === t.id ? 'sel' : ''} style={{ cursor: 'pointer' }} onClick={() => { setSel(t.id); setEdit(null); }}>
            <td className="l amber">{t.name}<div className="muted" style={{ fontSize: 10 }}>{t.engine} · L{(t.longs || []).length} / S{(t.shorts || []).length || 'idx'}</div></td>
          </tr>
        ))}</tbody></table>
        {!themes.length && <div className="note">テーマがありません。+ TEMPLATE で Notion のテーマ（2% Japan など）を読み込むか、+ NEW で作成。</div>}
        <div className="pad"><SourceSel v={source} set={setSource} /></div>
      </div>
      <div style={{ flex: 1, minWidth: 420 }}>
        {edit && (
          <div className="box" style={{ margin: 6 }}>
            <h4>THEME 編集 — 事実 → 理由 → バスケット</h4>
            <div className="pad theme-form">
              <label>名前<input className="inp" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
              <label>エンジン<select className="inp" value={edit.engine} onChange={(e) => setEdit({ ...edit, engine: e.target.value })}><option>Theme Alpha</option><option>Market Timing</option></select></label>
              <label>事実（Fact）<textarea className="inp" value={edit.fact || ''} onChange={(e) => setEdit({ ...edit, fact: e.target.value })} /></label>
              <label>理由（Reason）<textarea className="inp" value={edit.reason || ''} onChange={(e) => setEdit({ ...edit, reason: e.target.value })} /></label>
              <label>ドライバー（マクロ系列）<input className="inp" value={edit.driverText || ''} onChange={(e) => setEdit({ ...edit, driverText: e.target.value })} placeholder='TVC:JP10Y  /  {"ratio":["COMEX:HG1!","TVC:GOLD"]}' /></label>
              <label>種類<select className="inp" value={edit.driver_kind} onChange={(e) => setEdit({ ...edit, driver_kind: e.target.value })}><option value="price">価格（対数変化）</option><option value="yield">金利（bp 変化）</option></select></label>
              <label>方向<select className="inp" value={edit.driver_dir} onChange={(e) => setEdit({ ...edit, driver_dir: +e.target.value })}><option value={1}>上昇でテーマが進む</option><option value={-1}>下落でテーマが進む</option></select></label>
              <label>ロング（1行1銘柄、SYM:ウェイト可）<textarea className="inp" style={{ height: 90 }} value={edit.longsText || ''} onChange={(e) => setEdit({ ...edit, longsText: e.target.value })} /></label>
              <label>ショート（空ならヘッジ指数）<textarea className="inp" style={{ height: 60 }} value={edit.shortsText || ''} onChange={(e) => setEdit({ ...edit, shortsText: e.target.value })} /></label>
              <label>ヘッジ指数<input className="inp" value={edit.hedge || ''} onChange={(e) => setEdit({ ...edit, hedge: e.target.value.toUpperCase() })} /></label>
              <div><button className="tb on" disabled={!edit.name} onClick={save}>SAVE</button> <button className="tb" onClick={() => setEdit(null)}>CANCEL</button></div>
            </div>
          </div>
        )}
        {cur && !edit && (
          <div className="toolbar">
            <span className="amber" style={{ fontSize: 14 }}>{cur.name}</span>
            <button className="tb" onClick={() => startEdit(cur)}>EDIT</button>
            <button className="tb" onClick={async () => { if (confirm(`delete ${cur.name}?`)) { await api.del(`/insight/themes/${cur.id}`); setSel(null); list.reload(); } }}>DELETE</button>
            {cur.template && <span className="yellow" style={{ fontSize: 11 }}>⚠ {list.data?.template_note}</span>}
          </div>
        )}
        {cur && !edit && (cur.fact || cur.reason) && <div className="pad muted" style={{ fontSize: 11 }}>事実: {cur.fact} ／ 理由: {cur.reason} {cur.portfolio ? `／ ${cur.portfolio}` : ''}</div>}
        {cur && !edit && <WindowSlider label="期間" value={tw} onChange={setTw} min={120} max={1500} step={10} maxOffset={750} asof={d?.asof} />}
        {an.loading && <Loading />}
        <ErrorBox error={an.error || d?.error} />
        {d && !d.error && !edit && (
          <>
            <div className="pad" style={{ fontSize: 17 }}>フェーズ: <span className="yellow">{d.phase}</span></div>
            <div className="kv" style={{ gridTemplateColumns: 'repeat(2, max-content 1fr)' }}>
              <span>スプレッド z（20日）</span><span>{fmtNum(d.spread_z, 2)}</span>
              <span>ドライバー z</span><span>{fmtNum(d.driver.z, 2)} <span className="muted">{d.driver.last != null ? `(last ${fmtNum(d.driver.last, 3)})` : ''}</span></span>
              <span>先行</span><span>{d.driver.lead ? `${d.driver.lead.lag}日 r=${fmtNum(d.driver.lead.corr, 2)}${d.driver.significant ? ' ✓' : ''}` : '—'}</span>
              <span>銘柄間相関（60日）</span><span className={d.flow.dominant ? 'down' : ''}>{fmtNum(d.flow.avg_corr, 2)} <span className="muted">pctl {fmtNum(d.flow.pctl, 0)}</span></span>
              <span>分散（1M）</span><span>{fmtPct(d.dispersion_1m_pct, 1, false)}</span>
              <span>混雑（売買pctl）</span><span className={d.crowding_pctl >= 85 ? 'down' : ''}>{fmtNum(d.crowding_pctl, 0)}</span>
              <span>β中立 1W/1M/3M/6M</span><span>{['1W', '1M', '3M', '6M'].map((k) => <span key={k} className={d.perf_bn_pct[k] > 0 ? 'up' : 'down'}>{fmtPct(d.perf_bn_pct[k], 1)} </span>)}</span>
              <span>最大DD</span><span className="down">{fmtPct(d.max_dd_bn_pct, 1)}</span>
              <span>ヘッジ比率</span><span>{fmtNum(d.hedge_ratio, 2)} <span className="muted">vs {d.short_side.join(', ')}</span></span>
            </div>
            {d.flags.map((f: string) => <div key={f} className="yellow" style={{ padding: '1px 6px' }}>• {f}</div>)}
            <LineChart lines={lines} height={220} />
            <table className="t">
              <thead><tr><th className="l">MEMBER</th><th>SIDE</th><th>W</th><th>1M</th><th>3M</th><th>バスケットとの相関</th><th>売買pctl</th></tr></thead>
              <tbody>{d.members.map((m: any) => (
                <tr key={m.side + m.symbol} style={{ cursor: 'pointer' }} onClick={() => setSecurity(m.symbol)}>
                  <td className="l amber">{m.symbol}</td><td className={m.side === 'L' ? 'up' : 'down'}>{m.side}</td><td>{fmtNum(m.weight, 1)}</td>
                  {m.error ? <td colSpan={4} className="muted">{m.error}</td> : (<>
                    <td className={m.ret_1m > 0 ? 'up' : 'down'}>{fmtPct(m.ret_1m, 1)}</td><td className={m.ret_3m > 0 ? 'up' : 'down'}>{fmtPct(m.ret_3m, 1)}</td>
                    <td>{fmtNum(m.corr_to_basket, 2)}</td><td>{fmtNum(m.activity_pctl, 0)}</td></>)}
                </tr>
              ))}</tbody>
            </table>
            <div className="note">フェーズ（ルール）: ドライバー z ≥ 1 かつスプレッド z &lt; 0.5 →「②→③ エントリーゾーン（未波及）」、両方 ≥ 1／1.5 →「③ 織り込み進行」。銘柄間相関が過去1年の上位20%かつ 0.5 以上 → バスケット買いが支配（限界④）。AUTO 実行時に全テーマを再計算し、フェーズが変わると通知。</div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- PFND
export function PFND() {
  const { run } = useTerminal();
  const [by, setBy] = useState('subsector');
  const [custom, setCustom] = useState('');
  const [source, setSource] = useState('');
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [onlyPass, setOnlyPass] = useState(false);
  const [pw, setPw] = useState<WindowValue>({ length: 252, offset: 0 });
  const go = async () => {
    setBusy(true); setErr('');
    let groups: any = null;
    if (custom.trim()) {
      groups = {};
      for (const line of custom.split('\n')) {
        const [g, rest] = line.includes(':') && !/^[A-Z]+:\d/.test(line.trim()) ? [line.split(':')[0], line.slice(line.indexOf(':') + 1)] : ['custom', line];
        const syms = rest.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
        if (syms.length) groups[g.trim() || 'custom'] = [...(groups[g.trim() || 'custom'] || []), ...syms];
      }
    }
    try { setRes(await api.post<any>('/insight/pairs/screen', { by, groups, source: source || null, lookback: pw.length, end_offset: pw.offset })); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const rows: any[] = (res?.pairs || []).filter((p: any) => !onlyPass || (p.verdict === 'PASS' && !p.entry_blocked));
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">GROUP BY</span>
        <select className="inp" value={by} onChange={(e) => setBy(e.target.value)}><option value="subsector">サブセクター（SCORE）→ 業種</option><option value="industry">業種（スキャナー）</option><option value="sector">セクター</option></select>
        <SourceSel v={source} set={setSource} />
        <button className="tb on" onClick={go} disabled={busy}>{busy ? 'SCREENING…' : 'SCREEN'}</button>
        <label className="muted"><input type="checkbox" checked={onlyPass} onChange={(e) => setOnlyPass(e.target.checked)} /> PASS かつ入場可のみ</label>
        {res && <span className="muted">{res.evaluated} ペア評価 · 評点あり {res.scored} 銘柄</span>}
      </div>
      <WindowSlider label="β・固有の期間" value={pw} onChange={setPw} min={60} max={500} step={5} maxOffset={500} asof={res?.asof} />
      <details className="pad"><summary className="muted">カスタム・グループ（任意）: 1行に「グループ名: SYM, SYM, …」— 空欄なら AUTO のユニバースを業種別に</summary>
        <textarea className="inp" style={{ width: '100%', height: 70 }} value={custom} onChange={(e) => setCustom(e.target.value)} placeholder={'半導体製造装置: TSE:8035, TSE:6857, TSE:7735, TSE:6920\nFA: TSE:6954, TSE:6273, TSE:6506'} />
      </details>
      {err && <div className="err">{err}</div>}
      {res && (
        <table className="t">
          <thead><tr><th className="l">GROUP</th><th className="l">LONG</th><th className="l">SHORT</th><th>判定</th><th>σ pair</th><th>相関</th><th>相関&lt;0.5</th><th>βN÷G</th><th>固有min</th><th>20D pctl</th><th>評点差</th><th>SIZE</th></tr></thead>
          <tbody>{rows.map((p: any, i: number) => (
            <tr key={i} style={{ cursor: 'pointer' }} onClick={() => run('SPRD', p.long, p.short)} title="クリックで SPRD（スプレッド・バックテスト）">
              <td className="l muted">{p.group}</td><td className="l up">{p.long}{p.score_long != null && <span className="muted"> {fmtNum(p.score_long, 2)}</span>}</td>
              <td className="l down">{p.short}{p.score_short != null && <span className="muted"> {fmtNum(p.score_short, 2)}</span>}</td>
              <td className={stCls(p.verdict)}>{p.verdict}</td><td>{fmtPct(p.pair_sigma_pct, 1, false)}</td><td>{fmtNum(p.pair_corr, 2)}</td>
              <td>{p.share_corr_below_0_5 != null ? fmtPct(p.share_corr_below_0_5 * 100, 0, false) : '--'}</td>
              <td className={p.beta_net_gross >= 0.3 ? 'down' : ''}>{p.beta_net_gross != null ? fmtPct(p.beta_net_gross * 100, 0, false) : '--'}</td>
              <td className={p.idio_min != null && p.idio_min < 0.3 ? 'down' : ''}>{p.idio_min != null ? fmtPct(p.idio_min * 100, 0, false) : '--'}</td>
              <td className={p.entry_blocked ? 'down' : ''}>{fmtNum(p.spread_pctl_20d, 0)}{p.entry_blocked ? ' 待' : ''}</td>
              <td>{p.score_gap != null ? fmtNum(p.score_gap, 2) : <span className="muted">{p.direction}</span>}</td>
              <td className="yellow">{p.size_pct ? fmtPct(p.size_pct, 2, false) : ''}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <div className="note">ルール: ロング＝評点（SCORE、なければ AUTO のルール採点）が高い側。PASS = Pair Sigma &lt; 25% かつ β調整 Net÷Gross &lt; 30%。20日スプレッドが上位20%なら「待」（拡大局面では入らない）。固有 min ≥ 30% と「相関 &lt; 0.5 の比率」はペア適性（05.4）。サイズは評点差→サイズ。</div>
    </div>
  );
}

// ---------------------------------------------------------------- TRAK
export function TRAK() {
  const { run } = useTerminal();
  const [a0, setA0] = useState(1);
  const [b0, setB0] = useState(1);
  const r = useAsync(() => api.get<any>('/insight/track', { a0, b0 }), [a0, b0]);
  const d = r.data;
  const toKelly = (name: string, g: any) => {
    if (!g.xw_pct || !g.xl_pct) return;
    try { localStorage.setItem('kelly_prefill', JSON.stringify({ pw: g.posterior.mean / 100, xw: g.xw_pct, xl: g.xl_pct, label: name })); } catch { /* ignore */ }
    run('KELLY');
  };
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">事前分布 Beta(a0, b0)</span>
        <input className="inp num" type="number" step={0.5} min={0.5} value={a0} onChange={(e) => setA0(+e.target.value || 1)} />
        <input className="inp num" type="number" step={0.5} min={0.5} value={b0} onChange={(e) => setB0(+e.target.value || 1)} />
        <button className="tb" onClick={r.reload}>REFRESH</button>
        <span className="muted">PORT → BLOTTER の約定から。メモに #タグ（例: #2%Japan #alpha_short）を付けるとタグ別に集計</span>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && !Object.keys(d.groups).length && <div className="note">クローズした取引がまだありません（BLOTTER に約定を記録すると集計されます）。</div>}
      {d && Object.keys(d.groups).length > 0 && (
        <>
          <table className="t">
            <thead><tr><th className="l">GROUP</th><th>N</th><th>W/L</th><th>勝率（事後平均）</th><th>90% 区間</th><th>XW</th><th>XL</th><th>ペイオフ</th><th>E</th><th title="理論値 F = E/(XW×XL)">Kelly F</th><th title="min(½F, 3%)（SHORT は 2%）">推奨</th><th className="l">損益の形</th><th>P&amp;L</th><th /></tr></thead>
            <tbody>{Object.entries(d.groups).map(([k, g]: any) => (
              <tr key={k}>
                <td className="l amber">{k}</td><td>{g.n}</td><td>{g.wins}/{g.losses}</td>
                <td className="yellow">{fmtPct(g.posterior.mean, 1, false)}</td><td className="muted">{fmtPct(g.posterior.lo90, 0, false)}–{fmtPct(g.posterior.hi90, 0, false)}</td>
                <td className="up">{fmtPct(g.xw_pct, 1, false)}</td><td className="down">{fmtPct(g.xl_pct, 1, false)}</td><td>{fmtNum(g.payoff, 2)}</td>
                <td className={g.e_pct > 0 ? 'up' : 'down'}>{fmtPct(g.e_pct, 2)}</td><td className="muted">{fmtPct(g.kelly_f_pct, 0, false)}</td><td className="yellow">{fmtPct(g.recommended_pct, 2, false)}</td>
                <td className={`l ${g.shape?.startsWith('保険') ? 'down' : g.shape?.startsWith('凸性') ? 'up' : 'muted'}`}>{g.shape || '—'}</td>
                <td className={g.pnl >= 0 ? 'up' : 'down'}>{fmtNum(g.pnl, 0)}</td>
                <td><button className="tb" disabled={!g.xw_pct || !g.xl_pct} onClick={() => toKelly(k, g)}>→ KELLY</button></td>
              </tr>
            ))}</tbody>
          </table>
          <div className="trin-split">
            {(['week', 'month', 'year'] as const).map((p) => {
              const x = d.periods[p];
              return (
                <div key={p} className="box" style={{ margin: 6, flex: 1, minWidth: 180 }}>
                  <h4>{p === 'week' ? '週次' : p === 'month' ? '月次' : '年次'}勝率</h4>
                  <div className="pad"><span className={x.win_rate >= x.target ? 'up' : 'down'} style={{ fontSize: 18 }}>{fmtPct(x.win_rate, 0, false)}</span>
                    <span className="muted"> 目標 {x.target}% · {x.positive}/{x.periods}</span></div>
                </div>
              );
            })}
          </div>
          <table className="t">
            <thead><tr><th className="l">CLOSED</th><th className="l">SYMBOL</th><th>SIDE</th><th>QTY</th><th>ENTRY</th><th>EXIT</th><th>RET</th><th>P&amp;L</th><th>日数</th><th className="l">TAGS</th></tr></thead>
            <tbody>{d.trips.slice(0, 60).map((t: any, i: number) => (
              <tr key={i}><td className="l muted">{String(t.closed).slice(0, 10)}</td><td className="l amber">{t.symbol}</td><td className={t.side === 'long' ? 'up' : 'down'}>{t.side}</td>
                <td>{fmtNum(t.qty, 0)}</td><td>{fmtNum(t.entry, 2)}</td><td>{fmtNum(t.exit, 2)}</td><td className={t.ret_pct > 0 ? 'up' : 'down'}>{fmtPct(t.ret_pct, 1)}</td>
                <td className={t.pnl > 0 ? 'up' : 'down'}>{fmtNum(t.pnl, 0)}</td><td>{t.hold_days ?? ''}</td><td className="l muted">{t.tags.map((x: string) => '#' + x).join(' ')}</td></tr>
            ))}</tbody>
          </table>
          <div className="note">{d.note} 損益の形: リターンの歪度 &lt; −0.5 = 保険売り型（コツコツドカン）、&gt; 0.5 = 凸性購入型（ドカンコツコツ）— 05.6 Ⅲ。目標は Notion の「週次 68%／月次 76%／年次 90%」。</div>
        </>
      )}
    </div>
  );
}

// KELLY reads this once on mount (set by TRAK → KELLY)
export function takeKellyPrefill(): { pw: number; xw: number; xl: number; label: string } | null {
  try {
    const raw = localStorage.getItem('kelly_prefill');
    if (!raw) return null;
    localStorage.removeItem('kelly_prefill');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
