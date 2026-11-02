// ECST — macro statistics (~400 series: Japan + overseas). Official sources (FRED, e-Stat, ECB, Eurostat, World Bank,
// DBnomics) + markets, updated automatically. DASH: composites (成長・インフレ・流動性) per country/WORLD, statistical
// Growth × Liquidity quadrant, surprise index, heatmap. FLOWS: money flows derived from the statistics. RELEASES,
// BROWSE, SERIES (chart, regime / lead-lag vs an asset), SOURCES (status, keys, fixes, e-Stat tables, search, upload).
import { useMemo, useState } from 'react';
import { api } from '../lib/api';
import { fmtNum } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { GLQuad } from './Trinity';
import { useTerminal } from '../ctx';

const TABS = ['DASH', 'FLOWS', 'RELEASES', 'BROWSE', 'SERIES', 'SOURCES'] as const;
type Tab = (typeof TABS)[number];
const TAB_JA: Record<Tab, string> = { DASH: 'ダッシュボード', FLOWS: '資金フロー', RELEASES: '発表', BROWSE: '一覧', SERIES: '系列', SOURCES: 'データ源' };
const COMP_JA: Record<string, string> = { growth: '成長', inflation: 'インフレ', liquidity: '流動性' };
const ts = (d: string) => Date.parse((d.length === 7 ? d + '-01' : d) + 'T00:00:00Z') / 1000;
const zc = (v?: number | null) => (v == null ? 'muted' : v >= 0.5 ? 'up' : v <= -0.5 ? 'down' : '');
const sgn = (v?: number | null, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}`);
const heatBg = (v?: number) => (v == null ? undefined : `rgba(${v < 0 ? '255,69,69' : '47,209,122'},${Math.min(0.6, Math.abs(v) / 2.5)})`);
const ASSETS = [['TVC:TOPIX', 'TOPIX'], ['TVC:NI225', '日経平均'], ['SP:SPX', 'S&P 500'], ['NASDAQ:SOX', 'SOX'], ['FX:USDJPY', 'ドル円'],
  ['TVC:US10Y', '米10年'], ['TVC:JP10Y', '日10年'], ['TVC:GOLD', '金'], ['COMEX:HG1!', '銅'], ['TVC:USOIL', 'WTI']];

export function ECST({ args }: { args?: string }) {
  const [tab, setTab] = useState<Tab>((TABS as readonly string[]).includes(args?.toUpperCase() || '') ? (args!.toUpperCase() as Tab) : 'DASH');
  const [sel, setSel] = useState<string>('US.CPI');
  const open = (id: string) => { setSel(id); setTab('SERIES'); };
  return (
    <div>
      <div className="toolbar">
        <span className="amber" style={{ fontSize: 14 }}>マクロ統計</span>
        {TABS.map((t) => <button key={t} className={`tb ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)}>{t}<span className="muted" style={{ fontSize: 9 }}> {TAB_JA[t]}</span></button>)}
        <UpdateButton />
      </div>
      {tab === 'DASH' && <Dash open={open} />}
      {tab === 'FLOWS' && <Flows open={open} />}
      {tab === 'RELEASES' && <Releases open={open} />}
      {tab === 'BROWSE' && <Browse open={open} />}
      {tab === 'SERIES' && <Series id={sel} setId={setSel} />}
      {tab === 'SOURCES' && <Sources open={open} />}
      <div className="pad muted" style={{ fontSize: 9 }}>出典：FRED（Federal Reserve Bank of St. Louis）、政府統計総合窓口（e-Stat）、ECB Data Portal、Eurostat、World Bank、DBnomics、TradingView／Yahoo。このサービスは、政府統計総合窓口(e-Stat)のAPI機能を使用していますが、サービスの内容は国によって保証されたものではありません。</div>
    </div>
  );
}

function UpdateButton() {
  const { toast } = useTerminal();
  const st = useAsync(() => api.get<any>('/econ/status'), []);
  const s = st.data;
  const run = async () => {
    try { const r = await api.post<any>('/econ/update', {}); toast(r.started ? '統計の更新を開始（期限の来た系列）' : '更新中です'); setTimeout(() => st.reload(), 1500); } catch (e: any) { toast(e.message); }
  };
  return (
    <span className="muted" style={{ fontSize: 10, marginLeft: 8 }}>
      <button className="tb" onClick={run}>⟳ 更新</button>
      {s && <> {s.job.running ? <span className="yellow">更新中 {s.job.done}/{s.job.total}</span> : `最終 ${s.last_sweep ? s.last_sweep.replace('T', ' ').slice(5, 16) : '—'}`} · {s.total} 系列 · 自動 {s.auto ? 'ON' : s.auto_env ? 'OFF' : 'OFF（TERMINAL_ECON_AUTO=0）'}
        {!s.keys.ESTAT_APP_ID && <span className="down"> · ESTAT_APP_ID {s.key_problems?.ESTAT_APP_ID ? '要確認' : '未設定'}</span>}{!s.keys.FRED_API_KEY && <span className="muted"> · FRED は鍵なし（CSV）</span>}
        <button className="tb mini" onClick={() => st.reload()}>↻</button></>}
    </span>
  );
}

// ---------------------------------------------------------------------------------------------------
function Dash({ open }: { open: (id: string) => void }) {
  const d = useAsync(() => api.get<any>('/econ/dashboard'), []);
  const [region, setRegion] = useState('WORLD');
  const x = d.data;
  const regions = x ? Object.keys(x.countries || {}).sort((a, b) => (a === 'WORLD' ? -1 : b === 'WORLD' ? 1 : (['US', 'JP', 'EA', 'CN'].indexOf(a) + 100) % 104 - (['US', 'JP', 'EA', 'CN'].indexOf(b) + 100) % 104)) : [];
  const name = (c: string) => (c === 'WORLD' ? '世界（米欧日中）' : x?.country_names?.[c] || c);
  const cur = x?.countries?.[region];
  const last = (s: any) => { const ks = Object.keys(s || {}).sort(); return ks.length ? s[ks[ks.length - 1]] : null; };
  const prev3 = (s: any) => { const ks = Object.keys(s || {}).sort(); return ks.length > 3 ? s[ks[ks.length - 4]] : null; };
  const cats = useMemo(() => [...new Set(Object.values(x?.heatmap || {}).flatMap((c: any) => Object.keys(c)))], [x]);
  if (d.loading && !x) return <Loading />;
  return (
    <div>
      <ErrorBox error={d.error} />
      {x && !regions.length && <div className="note">まだ合成できる国がありません。「⟳ 更新」で統計を取得してください（1 か国あたり各分野 3 系列以上が必要）。データ源の状態は SOURCES。</div>}
      <div className="econ-cards">
        {regions.map((c) => {
          const comp = x.countries[c].composites;
          const q = x.countries[c].quadrant;
          const sur = last(x.countries[c].surprise);
          return (
            <div key={c} className={`box econ-card ${region === c ? 'sel' : ''}`} onClick={() => setRegion(c)}>
              <h4>{name(c)}</h4>
              <div className="pad" style={{ fontSize: 11 }}>
                {Object.keys(COMP_JA).map((k) => {
                  const l = last(comp[k]);
                  const p = prev3(comp[k]);
                  return <div key={k}>{COMP_JA[k]} <span className={zc(l?.value)}>{sgn(l?.value, 2)}</span>{l && p ? <span className="muted"> {l.value > p.value ? '↑' : '↓'}</span> : null}
                    {l?.diffusion != null ? <span className="muted" style={{ fontSize: 9 }}> 改善 {l.diffusion.toFixed(0)}%</span> : null}{l ? <span className="muted" style={{ fontSize: 9 }}> n{l.n}</span> : null}</div>;
                })}
                {q?.available && <div className="yellow">{q.current.name} → {q.next.name}</div>}
                {sur && <div className="muted">サプライズ <span className={zc(sur.value)}>{sgn(sur.value, 2)}</span></div>}
              </div>
            </div>
          );
        })}
      </div>
      {cur && (
        <div className="trin-split">
          <div style={{ flex: 3, minWidth: 420 }}>
            <div className="box" style={{ margin: 6 }}>
              <h4>{name(region)}：合成指数（z の平均、良い方向に符号調整）と景気サプライズ</h4>
              <LineChart height={220} baseline={0} lines={[...Object.keys(COMP_JA).filter((k) => cur.composites[k]).map((k) => ({
                name: COMP_JA[k], data: Object.entries(cur.composites[k]).map(([m, v]: any) => ({ time: ts(m), value: v.value })) })),
              ...(Object.keys(cur.surprise || {}).length ? [{ name: 'サプライズ', data: Object.entries(cur.surprise).map(([m, v]: any) => ({ time: ts(m), value: v.value })) }] : [])]} />
              <div className="note" style={{ fontSize: 10 }}>成長 = 生産・消費・住宅・投資・貿易・マインド・雇用、インフレ = 物価・賃金、流動性 = マネー・信用・中銀資産・金融環境（スプレッド等は符号反転）。各系列を過去 10 年で z 化（当時のデータだけ）し、発表のずれは前月値で補う。サプライズは機械的な AR(1) 予想との差で、市場予想ではない。</div>
            </div>
          </div>
          <div style={{ flex: 2, minWidth: 300 }}>
            {cur.quadrant?.available && (
              <div className="box" style={{ margin: 6 }}>
                <h4>成長 × 流動性（統計版）— {cur.quadrant.current.name}</h4>
                <GLQuad gl={cur.quadrant} />
                <div className="pad" style={{ fontSize: 11 }}>次 {cur.quadrant.next.name} · {cur.quadrant.rotation}<br /><span className="muted">優位: {cur.quadrant.current.assets}</span></div>
              </div>
            )}
            {x.global_diffusion && <div className="pad muted" style={{ fontSize: 11 }}>成長の合成が 3 か月前より改善している国：{x.global_diffusion.up.length} / {x.global_diffusion.n}（{x.global_diffusion.up.map((c: string) => x.country_names[c] || c).join('、')}）</div>}
          </div>
        </div>
      )}
      {cats.length > 0 && (
        <div className="box" style={{ margin: 6, overflowX: 'auto' }}>
          <h4>ヒートマップ：国 × 分野（最新値の z、良い方向に符号調整）</h4>
          <table className="t nowrap" style={{ fontSize: 11 }}>
            <thead><tr><th className="l">分野</th>{Object.keys(x.heatmap).map((c) => <th key={c}>{x.country_names[c] || c}</th>)}</tr></thead>
            <tbody>{cats.map((k) => (
              <tr key={k}><td className="l">{k}</td>{Object.keys(x.heatmap).map((c) => {
                const cell = x.heatmap[c][k];
                return <td key={c} style={{ background: heatBg(cell?.value), cursor: cell ? 'pointer' : undefined }} title={cell ? cell.ids.join(', ') : ''} onClick={() => cell && open(cell.ids[0])}>{cell ? `${sgn(cell.value, 1)} (${cell.n})` : ''}</td>;
              })}</tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
function Flows({ open }: { open: (id: string) => void }) {
  const f = useAsync(() => api.get<any>('/econ/flows'), []);
  const g = f.data?.groups || {};
  const [pick, setPick] = useState<string | null>(null);
  if (f.loading && !f.data) return <Loading />;
  return (
    <div>
      <ErrorBox error={f.error} />
      <div className="pad muted" style={{ fontSize: 11 }}>残高の統計は「変化」、フローの統計（ネット購入など）は「合計」を資金の流れとして見る。合計はドル換算できる系列だけ（市場への影響の符号：TGA・リバースレポ・MMF の増加は資金の吸収）。財務省の対外対内証券投資（週次）や JPX の投資部門別は SOURCES からファイルを取り込む。</div>
      {Object.entries(g).map(([name, grp]: any) => (
        <div key={name} className="box" style={{ margin: 6 }}>
          <h4>{name}{grp.total ? <span className="muted" style={{ fontSize: 11 }}> — 合計（10 億ドル、市場への影響）：1 か月 <span className={zc(grp.total.m1)}>{sgn(grp.total.m1, 0)}</span> · 3 か月 <span className={zc(grp.total.m3)}>{sgn(grp.total.m3, 0)}</span> · 12 か月 <span className={zc(grp.total.m12)}>{sgn(grp.total.m12, 0)}</span></span> : null}</h4>
          {!grp.rows.length ? <div className="pad muted">データなし（更新、またはファイルの取り込み）</div> : (
            <div className="trin-split">
              <div style={{ flex: 3, minWidth: 460, overflowX: 'auto' }}>
                <table className="t nowrap" style={{ fontSize: 11 }}>
                  <thead><tr><th className="l">系列</th><th>最新</th><th>直近の期</th><th>短期</th><th>中期</th><th>1 年</th><th>z</th><th>連続</th><th>ドル換算（短期／1 年）</th></tr></thead>
                  <tbody>{grp.rows.map((r: any) => {
                    const sums = Object.entries(r.sums || {});
                    const us = Object.entries(r.usd_sums || {});
                    return (
                      <tr key={r.id} className={pick === r.id ? 'sel' : ''} style={{ cursor: 'pointer' }} onClick={() => setPick(r.id)} onDoubleClick={() => open(r.id)} title={`${r.kind === 'flow' ? 'フローの統計（合計）' : '残高の変化'} · 単位 ${r.unit || ''} · ダブルクリックで系列`}>
                        <td className="l">{r.country} {r.name}{r.sign < 0 ? <span className="muted" style={{ fontSize: 9 }}> （増加＝吸収）</span> : null}</td>
                        <td className="muted">{r.last_date}</td>
                        <td className={zc(r.last * (r.sign || 1))}>{fmtNum(r.last, 0)}</td>
                        {[1, 2, 3].map((i) => <td key={i} className={zc((sums[i]?.[1] as number) * (r.sign || 1))} title={sums[i]?.[0] as string}>{sums[i] ? fmtNum(sums[i][1] as number, 0) : ''}</td>)}
                        <td className={zc(r.z)}>{sgn(r.z, 1)}</td>
                        <td className={r.streak > 0 ? 'up' : r.streak < 0 ? 'down' : 'muted'}>{r.streak > 0 ? `流入 ${r.streak}` : r.streak < 0 ? `流出 ${-r.streak}` : ''}</td>
                        <td className="muted">{us.length ? `${sgn(us[1]?.[1] as number, 0)} / ${sgn(us[3]?.[1] as number, 0)}` : '—'}</td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
              <div style={{ flex: 2, minWidth: 300 }}>
                {(() => {
                  const r = grp.rows.find((x: any) => x.id === pick) || null;
                  if (r && r.cum?.length) return <LineChart height={180} baseline={0} lines={[{ name: `${r.name}（累積）`, data: r.cum.map(([d, v]: any) => ({ time: ts(d), value: v })) }]} />;
                  if (grp.total?.monthly?.length) {
                    let acc = 0;
                    return <LineChart height={180} baseline={0} lines={[{ name: '合計の累積（10 億ドル）', data: grp.total.monthly.map(([m, v]: any) => { acc += v; return { time: ts(m), value: acc }; }) }]} />;
                  }
                  return <div className="pad muted">行を選ぶと累積フローを表示</div>;
                })()}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
function Releases({ open }: { open: (id: string) => void }) {
  const [days, setDays] = useState(14);
  const [keyOnly, setKeyOnly] = useState(false);
  const r = useAsync(() => api.get<any>('/econ/releases', { days, key_only: keyOnly }), [days, keyOnly]);
  const rows: any[] = r.data?.rows || [];
  return (
    <div>
      <div className="toolbar">
        <select className="inp" value={days} onChange={(e) => setDays(+e.target.value)}>{[3, 7, 14, 30, 90].map((d) => <option key={d} value={d}>{d} 日</option>)}</select>
        <label className="muted"><input type="checkbox" checked={keyOnly} onChange={(e) => setKeyOnly(e.target.checked)} /> 主要指標だけ</label>
        <span className="muted" style={{ fontSize: 10 }}>サプライズ = 機械的な AR(1) 予想との差（z）。市場予想ではない。|z| ≥ 1.5 を強調。</span>
      </div>
      {r.loading && !r.data && <Loading />}
      <table className="t nowrap" style={{ fontSize: 11 }}>
        <thead><tr><th>取得</th><th className="l">国</th><th className="l">指標</th><th>期間</th><th>値</th><th>前回</th><th>シグナル</th><th>サプライズ</th></tr></thead>
        <tbody>{rows.map((x, i) => (
          <tr key={i} style={{ cursor: 'pointer' }} onClick={() => open(x.id)}>
            <td className="muted">{x.at.slice(5, 16).replace('T', ' ')}</td><td className="l">{x.country}</td>
            <td className={`l ${x.key ? 'amber' : ''}`}>{x.name}</td><td>{x.ref}</td><td>{fmtNum(x.value, 2)}</td><td className="muted">{fmtNum(x.prev, 2)}</td>
            <td>{x.signal != null ? `${sgn(x.signal, 2)}${x.tf === 'yoy' ? '%' : ''}` : ''}</td>
            <td className={x.surprise != null && Math.abs(x.surprise) >= 1.5 ? 'yellow' : zc((x.surprise ?? 0) * (x.good || 1))}>{sgn(x.surprise, 2)}</td>
          </tr>
        ))}</tbody>
      </table>
      {!rows.length && r.data && <div className="note">この期間の発表はまだありません（自動更新で新しい期間のデータが入ると記録されます。最初の取得は発表として数えない）。</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
function Browse({ open }: { open: (id: string) => void }) {
  const [f, setF] = useState({ country: '', category: '', source: '', q: '', key_only: false });
  const r = useAsync(() => api.get<any>('/econ/catalog', { ...f, country: f.country || undefined, category: f.category || undefined, source: f.source || undefined, q: f.q || undefined }), [f.country, f.category, f.source, f.key_only]);
  const d = r.data;
  const rows: any[] = (d?.rows || []).filter((x: any) => !f.q || (x.name + x.id).toLowerCase().includes(f.q.toLowerCase()));
  return (
    <div>
      <div className="toolbar">
        <select className="inp" value={f.country} onChange={(e) => setF({ ...f, country: e.target.value })}><option value="">国・地域（全部）</option>{Object.entries(d?.countries || {}).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select>
        <select className="inp" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}><option value="">分野（全部）</option>{(d?.categories || []).map((k: string) => <option key={k}>{k}</option>)}</select>
        <select className="inp" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}><option value="">データ源（全部）</option>{['fred', 'estat', 'ecb', 'eurostat', 'wb', 'dbnomics', 'market', 'derived', 'upload'].map((k) => <option key={k}>{k}</option>)}</select>
        <input className="inp" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="検索（名前・id）" />
        <label className="muted"><input type="checkbox" checked={f.key_only} onChange={(e) => setF({ ...f, key_only: e.target.checked })} /> 主要</label>
        <span className="muted">{rows.length} 系列</span>
      </div>
      {r.loading && !d && <Loading />}
      <div style={{ overflowX: 'auto' }}>
        <table className="t nowrap" style={{ fontSize: 11 }}>
          <thead><tr><th className="l">国</th><th className="l">指標</th><th className="l">分野</th><th>頻度</th><th>最新</th><th>値</th><th>変化</th><th>シグナル</th><th>z</th><th>傾向</th><th>状態</th></tr></thead>
          <tbody>{rows.map((x) => (
            <tr key={x.id} style={{ cursor: 'pointer' }} onClick={() => open(x.id)} title={`${x.id} · ${x.source}${x.error ? ' · ' + x.error : ''}`}>
              <td className="l">{x.country_name}</td><td className={`l ${x.key ? 'amber' : ''}`}>{x.name}</td><td className="l muted">{x.category}</td><td>{x.freq}</td>
              <td className="muted">{x.last_date || ''}</td><td>{x.last != null ? fmtNum(x.last, 2) : ''}</td><td className={zc((x.chg ?? 0) * (x.good || 1))}>{x.chg != null ? sgn(x.chg, 2) : ''}</td>
              <td>{x.signal != null ? `${sgn(x.signal, 2)}${x.tf === 'yoy' ? '%' : ''}` : ''}</td><td className={zc((x.z ?? 0) * (x.good || 1))}>{x.z != null ? sgn(x.z, 1) : ''}</td>
              <td className={x.trend > 0 ? 'up' : x.trend < 0 ? 'down' : 'muted'}>{x.trend > 0 ? '改善' : x.trend < 0 ? '悪化' : ''}</td>
              <td><span className={`badge ${x.status === 'ok' ? (x.stale ? 'warn' : 'pass') : x.status === 'error' ? 'fail' : 'delay'}`}>{x.status === 'ok' ? (x.stale ? '更新停止?' : 'OK') : x.status === 'error' ? 'エラー' : '未取得'}</span></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
function Series({ id, setId }: { id: string; setId: (s: string) => void }) {
  const [tf, setTf] = useState('');
  const [asset, setAsset] = useState('TVC:TOPIX');
  const [input, setInput] = useState(id);
  const s = useAsync(() => api.get<any>(`/econ/series/${encodeURIComponent(id)}`, { tf: tf || undefined }), [id, tf]);
  const rg = useAsync(() => api.get<any>('/econ/regime', { id, asset }), [id, asset]);
  const d = s.data;
  const row = d?.row || {};
  return (
    <div>
      <div className="toolbar">
        <input className="inp" style={{ width: 180 }} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && setId(input.trim())} placeholder="系列 id（例 JP.CPI）" />
        <button className="tb" onClick={() => setId(input.trim())}>表示</button>
        <select className="inp" value={tf || d?.tf || ''} onChange={(e) => setTf(e.target.value)}>{[['lvl', '水準'], ['yoy', '前年比 %'], ['d1', '前期差'], ['d12', '前年差']].map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        {d?.url && <a className="tb" href={d.url} target="_blank" rel="noreferrer">出所 ↗</a>}
      </div>
      {s.loading && !d && <Loading />}
      <ErrorBox error={s.error} />
      {d && (
        <div className="trin-split">
          <div style={{ flex: 3, minWidth: 420 }}>
            <div className="box" style={{ margin: 6 }}>
              <h4>{d.entry.country} {d.entry.name} <span className="muted" style={{ fontSize: 11 }}>{d.entry.id} · {d.entry.source} · {d.entry.freq} · {row.status}</span></h4>
              {d.signal.length ? <LineChart height={240} lines={[{ name: d.tf, data: d.signal.map(([t, v]: any) => ({ time: ts(t), value: v })) }]} /> : <div className="pad muted">データがまだない {row.error ? `— ${row.error}` : ''}</div>}
              <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)', fontSize: 11 }}>
                <span>最新</span><span>{row.last_date} {fmtNum(row.last, 2)} {d.entry.unit}</span>
                <span>変化</span><span className={zc((row.chg ?? 0) * (d.entry.good || 1))}>{sgn(row.chg, 2)}</span>
                <span>シグナル</span><span>{sgn(row.signal, 2)}{d.entry.tf === 'yoy' ? '%' : ''}</span>
                <span>z（5 年）</span><span className={zc((row.z ?? 0) * (d.entry.good || 1))}>{sgn(row.z, 2)}</span>
                <span>10 年の位置</span><span>{row.pctl != null ? `${row.pctl.toFixed(0)}%` : '—'}</span>
                <span>傾向</span><span className={row.trend > 0 ? 'up' : row.trend < 0 ? 'down' : ''}>{row.trend > 0 ? '改善' : row.trend < 0 ? '悪化' : '—'}（連続 {row.streak ?? 0}）</span>
                <span>サプライズ</span><span>{sgn(row.surprise, 2)}</span>
                <span>状態</span><span className={row.stale ? 'yellow' : ''}>{row.stale ? `更新停止の疑い（${row.age_days} 日）` : row.status}</span>
              </div>
              {d.resolved && <div className="pad muted" style={{ fontSize: 10 }}>e-Stat の表：{d.resolved.title}（{d.resolved.statsDataId}）· {Object.values(d.resolved.names || {}).join(' / ')}{d.resolved.pinned ? ' · 固定' : ' · 自動で選択'}</div>}
              {d.flows?.n > 0 && <div className="pad" style={{ fontSize: 11 }}>フロー：直近 {fmtNum(d.flows.last, 0)} · {Object.entries(d.flows.sums).map(([k, v]: any) => `${k} ${fmtNum(v, 0)}`).join(' · ')}</div>}
            </div>
          </div>
          <div style={{ flex: 2, minWidth: 320 }}>
            <div className="box" style={{ margin: 6 }}>
              <h4>局面別のリターン・先行性</h4>
              <div className="toolbar"><select className="inp" value={asset} onChange={(e) => setAsset(e.target.value)}>{ASSETS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
                {rg.data?.demo && <span className="badge demo">DEMO</span>}</div>
              {rg.loading && <Loading />}
              {rg.error && <div className="pad muted">{rg.error}</div>}
              {rg.data && (
                <div className="pad" style={{ fontSize: 11 }}>
                  <table className="t nowrap"><thead><tr><th className="l">指標の状態</th><th>n</th><th>翌月</th><th>勝率</th><th>3 か月</th><th>6 か月</th></tr></thead>
                    <tbody>{Object.entries(rg.data.states).map(([k, v]: any) => (
                      <tr key={k} className={rg.data.current_state === k ? 'sel' : ''}><td className="l">{k}{rg.data.current_state === k ? ' ◀ 今' : ''}</td><td>{v.n}</td>
                        <td className={zc(v.m1)}>{v.m1 != null ? `${sgn(v.m1, 2)}%` : ''}</td><td>{v.hit1 != null ? `${v.hit1.toFixed(0)}%` : ''}</td>
                        <td className={zc(v.m3)}>{v.m3 != null ? `${sgn(v.m3, 1)}%` : ''}</td><td className={zc(v.m6)}>{v.m6 != null ? `${sgn(v.m6, 1)}%` : ''}</td></tr>
                    ))}</tbody></table>
                  <div className="muted">全体の翌月平均 {sgn(rg.data.base_m1, 2)}%（勝率 {rg.data.base_hit1?.toFixed(0) ?? '—'}%）· 発表のずれ {rg.data.lag_m} か月</div>
                  <div style={{ marginTop: 4 }}>先行性（指標の 3 か月変化 × k か月後の 1 か月リターンの相関）{rg.data.best ? <span className="yellow"> 最大 {rg.data.best.lead} か月先（{sgn(rg.data.best.corr, 2)}、n {rg.data.best.n}）</span> : ' — 観測不足'}</div>
                  <div className="hbar-list">{rg.data.ccf.map((c: any) => (
                    <div key={c.lead} className="hbar-row"><span className="muted" style={{ width: 28 }}>{c.lead}</span>
                      <span className="hbar2" style={{ flex: 1 }}><span style={{ left: c.corr >= 0 ? '50%' : `${50 + (c.corr ?? 0) * 50}%`, width: `${Math.abs(c.corr ?? 0) * 50}%`, background: (c.corr ?? 0) >= 0 ? '#2fd17a' : '#ff4545' }} /></span>
                      <span style={{ width: 44, textAlign: 'right' }}>{c.corr != null ? c.corr.toFixed(2) : ''}</span></div>
                  ))}</div>
                  <div className="note" style={{ fontSize: 10 }}>{rg.data.note}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
function Sources({ open }: { open: (id: string) => void }) {
  const { toast } = useTerminal();
  const st = useAsync(() => api.get<any>('/econ/status'), []);
  const [q, setQ] = useState({ source: 'fred', text: '' });
  const [found, setFound] = useState<any[] | null>(null);
  const [fix, setFix] = useState<Record<string, string>>({});
  const [cand, setCand] = useState<any>(null);
  const [up, setUp] = useState<any>(null);
  const [map, setMap] = useState<Record<number, any>>({});
  const s = st.data;
  const call = async (fn: () => Promise<any>, ok?: (x: any) => void) => { try { const x = await fn(); ok?.(x); st.reload(); } catch (e: any) { toast(e.message); } };
  return (
    <div>
      {st.loading && !s && <Loading />}
      {s && (
        <div className="trin-split">
          <div style={{ flex: 1, minWidth: 360 }}>
            <div className="box" style={{ margin: 6 }}>
              <h4>データ源の状態（{s.total} 系列）</h4>
              <table className="t nowrap" style={{ fontSize: 11 }}><thead><tr><th className="l">データ源</th><th>OK</th><th>更新停止?</th><th>エラー</th><th>未取得</th><th /></tr></thead>
                <tbody>{Object.entries(s.sources).map(([k, v]: any) => (
                  <tr key={k}><td className="l">{k}</td><td className="up">{v.ok || ''}</td><td className="yellow">{v.stale || ''}</td><td className="down">{v.error || ''}</td><td className="muted">{v['未取得'] || ''}</td>
                    <td><button className="tb mini" onClick={() => call(() => api.post('/econ/update', { source: k, force: true }), () => toast(`${k} を更新`))}>更新</button></td></tr>
                ))}</tbody></table>
              <div className="pad" style={{ fontSize: 11 }}>
                <div>FRED_API_KEY {s.keys.FRED_API_KEY ? <span className="up">設定済み</span> : <span className="muted">なし（CSV で取得。検索には鍵が必要）</span>}</div>
                <div>ESTAT_APP_ID {s.keys.ESTAT_APP_ID ? <span className="up">設定済み</span> : s.key_problems?.ESTAT_APP_ID ? <span className="down">要確認 — {s.key_problems.ESTAT_APP_ID}</span> : <span className="down">なし — 日本の公式統計（e-Stat）に必要。e-Stat にログイン → マイページ →「API 機能（アプリケーション ID 発行）」で発行し、.env に書く</span>}</div>
                <div>
                  <label><input type="checkbox" checked={!!s.config?.auto} onChange={(e) => call(() => api.put('/econ/config', { auto: e.target.checked }), () => toast(e.target.checked ? '自動更新 ON' : '自動更新 OFF'))} /> 自動更新</label>
                  <span className="muted"> · 間隔 </span>
                  <select className="inp" value={s.config?.every_min ?? 30} onChange={(e) => call(() => api.put('/econ/config', { every_min: +e.target.value }))}>{[10, 15, 30, 60, 120, 360].map((m) => <option key={m} value={m}>{m} 分</option>)}</select>
                  <span className="muted"> · 各系列の確認間隔：日次・週次・月次 {s.due_hours?.M} 時間、四半期 {s.due_hours?.Q} 時間、年次 {s.due_hours?.A} 時間（失敗は間隔を延ばして再試行）· 最終 {s.last_sweep || '—'}</span>
                </div>
              </div>
            </div>
            <div className="box" style={{ margin: 6 }}>
              <h4>検索して追加（FRED／e-Stat）</h4>
              <div className="toolbar">
                <select className="inp" value={q.source} onChange={(e) => setQ({ ...q, source: e.target.value })}><option value="fred">FRED</option><option value="estat">e-Stat</option></select>
                <input className="inp" value={q.text} onChange={(e) => setQ({ ...q, text: e.target.value })} placeholder="例 japan exports / 鉱工業指数" />
                <button className="tb" onClick={() => call(() => api.get('/econ/search', { source: q.source, q: q.text }), (x) => setFound(x.rows))}>検索</button>
              </div>
              {found && <table className="t nowrap" style={{ fontSize: 10 }}><tbody>{found.slice(0, 30).map((x: any) => (
                <tr key={x.code || x.id}><td className="l">{x.code || x.id}</td><td className="l">{x.title}</td><td className="muted">{x.freq || x.cycle} {x.last || x.updated || ''}</td>
                  <td>{q.source === 'fred' && <button className="tb mini" onClick={() => call(() => api.post('/econ/custom', { entry: { id: `X.${x.code}`.slice(0, 60), name: x.title, source: 'fred', code: x.code, freq: ({ D: 'D', W: 'W', M: 'M', Q: 'Q', A: 'A' } as any)[x.freq?.[0]] || 'M', tf: 'lvl', axis: 'growth', country: 'GLOBAL', good: 0 } }), () => toast(`追加: ${x.code}（BROWSE で国・分野を確認）`))}>追加</button>}</td></tr>
              ))}</tbody></table>}
            </div>
            <Upload up={up} setUp={setUp} map={map} setMap={setMap} toast={toast} reload={() => st.reload()} />
          </div>
          <div style={{ flex: 1, minWidth: 360 }}>
            <div className="box" style={{ margin: 6 }}>
              <h4>エラーの系列（{s.errors.length}）— コードを直す・e-Stat の表を選ぶ・止める</h4>
              <table className="t" style={{ fontSize: 10 }}><tbody>{s.errors.map((x: any) => (
                <tr key={x.id}>
                  <td className="l amber" style={{ cursor: 'pointer' }} onClick={() => open(x.id)}>{x.id}</td><td className="l">{x.name}<div className="down">{x.error}</div></td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {x.source === 'estat' ? <button className="tb mini" onClick={() => call(() => api.get(`/econ/estat/candidates/${x.id}`), setCand)}>表を選ぶ</button>
                      : <><input className="inp" style={{ width: 120 }} value={fix[x.id] ?? ''} onChange={(e) => setFix({ ...fix, [x.id]: e.target.value })} placeholder="正しいコード" />
                        <button className="tb mini" disabled={!fix[x.id]} onClick={() => call(() => api.put(`/econ/override/${x.id}`, { code: fix[x.id] }), () => toast('次の更新で取得し直す'))}>直す</button></>}
                    <button className="tb mini" onClick={() => call(() => api.put(`/econ/override/${x.id}`, { disabled: true }), () => toast(`止めた: ${x.id}`))}>止める</button>
                  </td>
                </tr>
              ))}</tbody></table>
            </div>
            {cand && (
              <div className="box" style={{ margin: 6 }}>
                <h4>e-Stat の候補 — {cand.id}（検索「{cand.spec.search}」）</h4>
                {cand.candidates.map((t: any) => (
                  <div key={t.id} className="pad" style={{ fontSize: 10, borderBottom: '1px solid #222' }}>
                    <div><span className="amber">{t.id}</span> {t.stat_name} · {t.title} · {t.cycle} · 更新 {t.updated}</div>
                    <div className="muted">選ぶ分類: {Object.entries(t.names).map(([k, v]: any) => `${k}=${v}`).join(' / ')} · 一致 {t.matched.join('、') || 'なし'}</div>
                    <button className="tb mini" onClick={() => call(() => api.put(`/econ/override/${cand.id}`, { resolved: { statsDataId: t.id, codes: t.codes, names: t.names, title: t.title } }), () => { toast(`${cand.id} を ${t.id} に固定`); setCand(null); })}>この表に固定</button>
                  </div>
                ))}
                {!cand.candidates.length && <div className="pad muted">候補なし — 検索語を変えて追加するか、止める</div>}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Upload({ up, setUp, map, setMap, toast, reload }: any) {
  const send = async (f: File) => {
    const fd = new FormData();
    fd.append('file', f);
    try {
      const res = await fetch('/api/econ/upload', { method: 'POST', body: fd });
      if (!res.ok) throw new Error((await res.json()).detail);
      const x = await res.json();
      setUp(x);
      setMap({});
    } catch (e: any) { toast(e.message); }
  };
  const apply = async () => {
    const columns = Object.entries(map).filter(([, v]: any) => v.on).map(([k, v]: any) => ({ index: +k, entry: {
      id: v.id, name: v.name, country: v.country || 'JP', category: v.category || '貿易・対外', axis: 'liquidity', freq: v.freq || 'W', tf: 'lvl', good: 0, unit: v.unit || '',
      ...(v.flow ? { flow: { kind: 'flow', group: v.group || '国際資本フロー', ccy: v.ccy || 'JPY', mult: v.mult ? +v.mult : null, sign: 1 } } : {}) } }));
    try { const r = await api.post<any>('/econ/upload/apply', { token: up.token, columns }); toast(`取り込み: ${r.series.map((s: any) => `${s.id}（${s.n}）`).join('、')}`); setUp(null); reload(); } catch (e: any) { toast(e.message); }
  };
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>ファイルを取り込む（財務省 対外対内証券投資・JPX 投資部門別・自分の CSV / Excel）</h4>
      <div className="toolbar"><input type="file" accept=".csv,.xlsx,.xlsm,.txt" onChange={(e) => e.target.files?.[0] && send(e.target.files[0])} />
        <span className="muted" style={{ fontSize: 10 }}>日付の列（「2026年1月4日～1月10日」の範囲は終わりの日）と数値の列を自動で見つける。同じ id で取り込み直すと追記・更新。</span></div>
      {up && (
        <div className="pad" style={{ fontSize: 10 }}>
          <div className="muted">{up.file} · 見出し {up.header_row + 1} 行目 · 日付列「{up.date_name}」</div>
          <table className="t nowrap"><thead><tr><th /><th className="l">列</th><th>id</th><th>名前</th><th>頻度</th><th>単位</th><th>フロー</th><th>倍率（単位→通貨）</th></tr></thead>
            <tbody>{up.columns.map((c: any) => {
              const v = map[c.index] || {};
              const set = (k: string, val: any) => setMap({ ...map, [c.index]: { id: `JP.UP_${c.index}`, name: c.name, ...v, [k]: val } });
              return (
                <tr key={c.index}><td><input type="checkbox" checked={!!v.on} onChange={(e) => set('on', e.target.checked)} /></td><td className="l">{c.name}</td>
                  <td><input className="inp" style={{ width: 110 }} value={v.id ?? `JP.UP_${c.index}`} onChange={(e) => set('id', e.target.value)} /></td>
                  <td><input className="inp" style={{ width: 150 }} value={v.name ?? c.name} onChange={(e) => set('name', e.target.value)} /></td>
                  <td><select className="inp" value={v.freq || 'W'} onChange={(e) => set('freq', e.target.value)}>{['D', 'W', 'M', 'Q', 'A'].map((x) => <option key={x}>{x}</option>)}</select></td>
                  <td><input className="inp" style={{ width: 50 }} value={v.unit ?? ''} onChange={(e) => set('unit', e.target.value)} placeholder="億円" /></td>
                  <td><input type="checkbox" checked={!!v.flow} onChange={(e) => set('flow', e.target.checked)} /></td>
                  <td><input className="inp" style={{ width: 60 }} value={v.mult ?? ''} onChange={(e) => set('mult', e.target.value)} placeholder="1e8" /></td>
                </tr>
              );
            })}</tbody></table>
          <button className="tb on" disabled={!Object.values(map).some((v: any) => v.on)} onClick={apply}>取り込む</button>
        </div>
      )}
    </div>
  );
}
