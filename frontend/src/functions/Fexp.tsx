// FEXP — factor analysis of a security, a basket or the book: market, sector, style, FX, rates, commodities, overseas.
// Numbered menu like Bloomberg (3 <GO>). The maths is in backend/app/fexpmodel.py (docs/ANALYTICS.md §FEXP).
import { useState } from 'react';
import { api } from '../lib/api';
import { ErrorBox, Loading, useAsync, useMenu } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { WindowSlider, type WindowValue } from '../components/WindowSlider';
import { fmtNum, fmtPct } from '../lib/format';
import { useTerminal } from '../ctx';

const TABS = ['EXPO', 'RISK', 'ATTR', 'ROLL', 'MAP', 'SCEN', 'COMP'] as const;
type Tab = (typeof TABS)[number];
const TAB_JA: Record<Tab, string> = { EXPO: '感応度', RISK: 'リスク分解', ATTR: '寄与', ROLL: '推移', MAP: '地図', SCEN: 'シナリオ', COMP: 'カバレッジ比較' };
const HELP: Record<Tab, string> = {
  EXPO: '要因が 1%（金利は 10bp）動いたときの株価の動き（%）。為替・金利・商品・海外株は市場と無関係な部分に直してあるので、市場β は全体の感応度、ほかは「市場以上の」感応度。|t| ≥ 2 が黄色。東証の引け後に動く要因は翌日の分も足した値（同日／翌日）。',
  RISK: '株価の分散のうち、どの要因群で説明できるか（Euler 分解。合計 = R²）。残りが個社要因。Notion の典型（日本の単一銘柄）: 市場 40–50% / スタイル 25–30% / セクター 15–20% / 個別 ≈10%。',
  ATTR: '直近の窓のリターンを要因の寄与と個社要因（α＋残差）に分ける。β は窓より前の期間で推定（先読みなし）。',
  ROLL: '選んだ要因の感応度の推移（小さなモデルで推定窓を 5 日ずつずらす）。感応度が変わったか（円安の効き方、セクターとの連動）を見る。',
  MAP: '各要因を市場と一緒に 1 つずつ当てはめた結果。市場調整後 β ＝ 市場以上の感応度、単独 β ＝ その要因だけで見た連動（市場経由を含む）。どのセクター・通貨・スタイルのように動くかが分かる。',
  SCEN: '要因のショック（%・bp）を入れると、株価の予想変化 ± 1 標準誤差。市場と一緒に動かした場合も整合的に計算（為替などは市場と無関係な部分だけが効く）。入れない要因は 0。',
  COMP: 'カバレッジ全銘柄の感応度を横に並べる（各地域の既定のモデル）。色は t（濃いほど確か）。行をクリックでその銘柄の FEXP。',
};
const GROUP_COL: Record<string, string> = {
  マーケット: '#5ea9ff', セクター: '#ffa028', スタイル: '#a98bff', 為替: '#59e3ff', 金利: '#ffd84a', 商品: '#ff7a59', 海外株: '#7dd87d', 個社要因: '#2fd17a',
};
const LINE_COL = ['#ffffff', '#ffa028', '#59e3ff', '#a98bff', '#7dd87d', '#ff7a59'];
const ts = (d: string) => Math.floor(Date.parse(d + 'T00:00:00Z') / 1000);
const tcls = (t?: number | null) => (t == null ? 'muted' : Math.abs(t) >= 2 ? 'yellow' : 'muted');
const unitTxt = (e: any) => (e.unit === '10bp' ? '10bp' : '1%');
const PRESETS: { label: string; shocks: Record<string, number> }[] = [
  { label: '円高 5%（ドル円 −5%）', shocks: { 'fx.usdjpy': -5 } },
  { label: '円安 5%', shocks: { 'fx.usdjpy': 5 } },
  { label: 'TOPIX −5%', shocks: { mkt: -5 } },
  { label: 'リスクオフ（市場 −5%・円高 3%・米10年 −20bp）', shocks: { mkt: -5, 'fx.usdjpy': -3, 'rate.us10': -20 } },
  { label: '米10年 +50bp', shocks: { 'rate.us10': 50 } },
  { label: '日10年 +25bp', shocks: { 'rate.jp10': 25 } },
  { label: '原油 +20%', shocks: { 'cmd.oil': 20 } },
  { label: 'SOX −10%', shocks: { 'os.sox': -10 } },
];

function Bar2({ v, max, color }: { v: number; max: number; color: string }) {
  const w = Math.min(50, (Math.abs(v) / (max || 1)) * 50);
  return <div className="hbar2"><span style={{ left: v >= 0 ? '50%' : `${50 - w}%`, width: `${w}%`, background: color }} /></div>;
}

export function FEXP({ symbol, args }: { symbol: string; args?: string }) {
  const a = (args || '').trim();
  const tabArg = (TABS as readonly string[]).includes(a.toUpperCase()) ? (a.toUpperCase() as Tab) : null;
  const target = a && !tabArg ? a : symbol;
  const [tab, setTab] = useState<Tab>(tabArg || 'EXPO');
  const [est, setEst] = useState(504);
  const [w, setW] = useState<WindowValue>({ length: 21, offset: 0 });
  const [ids, setIds] = useState<string[] | null>(null);
  const [rids, setRids] = useState<string[] | null>(null);
  const menu = useMenu((n) => TABS[n - 1] && setTab(TABS[n - 1]));
  const r = useAsync(() => api.get<any>('/fexp', { target, est, window: w.length, end_offset: w.offset, factors: ids?.join(',') || undefined, roll_factors: rids?.join(',') || undefined }),
    [target, est, w.length, w.offset, ids?.join(','), rids?.join(',')]);
  const d = r.data;
  return (
    <div ref={menu} data-menu>
      <div className="bb-head">
        <span className="bb-code">FEXP</span><span className="bb-title">FACTOR EXPOSURE</span><span className="muted">ファクター分析</span>
        <span className="amber">{d ? (d.kind === 'port' ? 'PORT（保有・円建て）' : d.kind === 'basket' ? `バスケット ${d.symbols.length} 銘柄` : target) : target}</span>
        {d?.source === 'sim' && <span className="badge demo">DEMO</span>}
        <span className="lbl" style={{ marginLeft: 8 }}>推定期間</span>
        <select className="inp" value={est} onChange={(e) => setEst(+e.target.value)}>{[252, 504, 750].map((x) => <option key={x} value={x}>{x === 252 ? '1 年' : x === 504 ? '2 年' : '3 年'}（{x} 日）</option>)}</select>
      </div>
      <div className="bb-menu">
        {TABS.map((t, i) => (
          <button key={t} className={`bb-item ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)} title={`${i + 1} と入力して Enter（${i + 1} <GO>）でも切り替え`}>
            <span className="bb-num">{i + 1})</span> {t} <span className="bb-ja">{TAB_JA[t]}</span>
          </button>
        ))}
      </div>
      <div className="bb-help">{HELP[tab]}</div>
      {tab !== 'COMP' && (
        <>
          {r.loading && !d && <Loading />}
          <ErrorBox error={r.error} />
          {d && <Summary d={d} />}
          {d && tab === 'EXPO' && <Expo d={d} setIds={setIds} />}
          {d && tab === 'RISK' && <Risk d={d} />}
          {d && tab === 'ATTR' && <Attr d={d} w={w} setW={setW} />}
          {d && tab === 'ROLL' && <Roll d={d} setRids={setRids} />}
          {d && tab === 'MAP' && <Maps d={d} setIds={setIds} />}
          {d && tab === 'SCEN' && <Scen d={d} reload={r.reload} />}
        </>
      )}
      {tab === 'COMP' && <Comp est={est} offset={w.offset} />}
    </div>
  );
}

function Summary({ d }: { d: any }) {
  const item = (k: string, v: React.ReactNode) => <span><span className="muted">{k}</span> {v}</span>;
  return (
    <div className="pad" style={{ fontSize: 11 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px' }}>
        {item('期間', `${d.from} → ${d.to}（${d.n} 日）`)}
        {item('R²', <span className="amber">{fmtNum(d.r2, 2)}</span>)}
        {item('ボラ（年率）', fmtPct(d.vol_pct, 1, false))}
        {item('個別ボラ', fmtPct(d.idio_vol_pct, 1, false))}
        {item('α（年率）', <span className={d.alpha_ann_pct >= 0 ? 'up' : 'down'}>{fmtPct(d.alpha_ann_pct, 1)}</span>)}
        <span className="yellow">{d.verdict}</span>
        {d.lagged && <span className="muted">日本の銘柄：東証の引け後に動く要因は翌日分も含む</span>}
      </div>
      {d.warnings?.map((x: string) => <div key={x} className="yellow">{x}</div>)}
      {Object.keys(d.errors || {}).length > 0 && <div className="muted">取得できなかった記号: {Object.keys(d.errors).slice(0, 8).join('、')}{Object.keys(d.errors).length > 8 ? ' …' : ''}</div>}
    </div>
  );
}

function Expo({ d, setIds }: { d: any; setIds: (v: string[] | null) => void }) {
  const [draft, setDraft] = useState<string[]>(d.ids);
  const maxImp = Math.max(0.01, ...d.exposures.map((e: any) => Math.abs(e.impact_1sd_pct)));
  const groups = [...new Set<string>(d.catalog.map((f: any) => f.group))];
  return (
    <>
      <table className="t nowrap" style={{ fontSize: 11 }}>
        <thead><tr><th className="l">要因</th><th className="l">群</th><th>単位</th><th>感応度（%）</th><th>±se</th><th>t</th><th>同日 / 翌日</th><th className="l" style={{ width: 160 }}>1σ の影響（%/日）</th><th>リスク寄与</th></tr></thead>
        <tbody>{d.exposures.map((e: any) => (
          <tr key={e.id} title={e.warn || ''}>
            <td className="l amber">{e.label}{e.warn && <span className="yellow"> ⚠</span>}</td>
            <td className="l" style={{ color: GROUP_COL[e.group] }}>{e.group}</td>
            <td className="muted">{unitTxt(e)}</td>
            <td className={e.per_unit_pct >= 0 ? 'up' : 'down'}>{fmtNum(e.per_unit_pct, 3)}</td>
            <td className="muted">{fmtNum(e.se_unit_pct, 3)}</td>
            <td className={tcls(e.t)}>{fmtNum(e.t, 1)}</td>
            <td className="muted">{e.lagged ? `${fmtNum(e.same_day_pct, 2)} / ${fmtNum(e.next_day_pct, 2)}` : '—'}</td>
            <td className="l"><Bar2 v={e.impact_1sd_pct} max={maxImp} color={GROUP_COL[e.group] || '#888'} /></td>
            <td>{fmtPct(e.risk_share * 100, 1, false)}</td>
          </tr>
        ))}</tbody>
      </table>
      <div className="box" style={{ margin: 6 }}>
        <h4>モデルに入れる要因 <button className="tb mini" onClick={() => setIds(draft)}>適用</button> <button className="tb mini" onClick={() => { setDraft(d.default_ids); setIds(null); }}>既定に戻す</button>
          <span className="muted" style={{ fontWeight: 400 }}> 選んだ数 {draft.length}（多すぎると β が不安定になる。地図 5) MAP で候補を比べてから入れる）</span></h4>
        <div className="pad" style={{ fontSize: 11, columns: 3 }}>
          {groups.map((g) => (
            <div key={g} style={{ breakInside: 'avoid', marginBottom: 4 }}>
              <div style={{ color: GROUP_COL[g] }}>{g}</div>
              {d.catalog.filter((f: any) => f.group === g).map((f: any) => (
                <label key={f.id} style={{ display: 'block' }} className={f.available ? '' : 'muted'} title={f.available ? (f.late ? '東証の引け後に動く → 翌日分も推定' : '') : 'データが取れていない'}>
                  <input type="checkbox" disabled={!f.available} checked={draft.includes(f.id)}
                    onChange={(e) => setDraft(e.target.checked ? [...draft, f.id] : draft.filter((x) => x !== f.id))} /> {f.label}{f.id === d.sector_id ? '（自セクター）' : ''}
                </label>
              ))}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function Risk({ d }: { d: any }) {
  const parts: [string, number][] = [...Object.entries(d.risk.groups as Record<string, number>), ['個社要因', d.risk.specific]];
  const byF = [...d.exposures].sort((a: any, b: any) => Math.abs(b.risk_share) - Math.abs(a.risk_share));
  return (
    <div className="pad">
      <div className="stack" style={{ height: 24 }}>
        {parts.map(([k, v]) => (
          <span key={k} style={{ width: `${Math.max(0, v * 100)}%`, background: GROUP_COL[k] || '#888' }} title={`${k} ${fmtPct(v * 100, 1, false)}`}>{v >= 0.06 ? `${k} ${Math.round(v * 100)}` : ''}</span>
        ))}
      </div>
      <table className="t" style={{ fontSize: 11, maxWidth: 520 }}>
        <tbody>{parts.map(([k, v]) => (
          <tr key={k}><td className="l" style={{ color: GROUP_COL[k] }}>{k}</td><td>{fmtPct(v * 100, 1, false)}</td></tr>
        ))}</tbody>
      </table>
      <div className="muted" style={{ marginTop: 6 }}>要因ごと（負の値 = 他の要因の動きを打ち消している）</div>
      <table className="t nowrap" style={{ fontSize: 11, maxWidth: 620 }}>
        <tbody>{byF.map((e: any) => (
          <tr key={e.id}><td className="l amber">{e.label}</td><td className="l" style={{ color: GROUP_COL[e.group] }}>{e.group}</td>
            <td className={e.risk_share >= 0 ? '' : 'down'}>{fmtPct(e.risk_share * 100, 2, false)}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function Attr({ d, w, setW }: { d: any; w: WindowValue; setW: (v: WindowValue) => void }) {
  const a = d.attribution;
  if (a?.error) return <><WindowSlider label="窓" value={w} onChange={setW} min={5} max={252} maxOffset={500} asof={d.to} /><div className="note">{a.error}</div></>;
  const parts: [string, number][] = [...Object.entries(a.groups_pct as Record<string, number>), ['個社要因', a.specific_pct]];
  const max = Math.max(0.5, ...parts.map(([, v]) => Math.abs(v)), Math.abs(a.total_pct));
  return (
    <>
      <WindowSlider label="窓" value={w} onChange={setW} min={5} max={252} maxOffset={500} asof={a.to} />
      <div className="pad" style={{ fontSize: 15 }}>
        {a.from} → {a.to} のリターン <span className={a.total_pct >= 0 ? 'up' : 'down'}>{fmtPct(a.total_pct, 2)}</span>
        <span className="muted" style={{ fontSize: 11 }}>（対数。β は {a.est_from} → {a.est_to} で推定）</span>
      </div>
      <table className="t" style={{ fontSize: 11 }}>
        <tbody>{parts.map(([k, v]) => (
          <tr key={k}><td className="l" style={{ color: GROUP_COL[k] || '#ddd', width: 90 }}>{k}</td>
            <td style={{ width: 70 }} className={v >= 0 ? 'up' : 'down'}>{fmtPct(v, 2)}</td>
            <td className="l"><Bar2 v={v} max={max} color={GROUP_COL[k] || '#888'} /></td></tr>
        ))}</tbody>
      </table>
      <LineChart height={170} lines={[
        { name: '株価（累積）', data: a.series.map((p: any) => ({ time: ts(p.date), value: p.total })), color: '#ffffff' },
        { name: '要因の寄与', data: a.series.map((p: any) => ({ time: ts(p.date), value: p.factor })), color: '#a98bff' },
        { name: '個社要因', data: a.series.map((p: any) => ({ time: ts(p.date), value: p.specific })), color: '#2fd17a' },
      ]} />
      <table className="t nowrap" style={{ fontSize: 11 }}>
        <thead><tr><th className="l">要因</th><th className="l">群</th><th>寄与</th></tr></thead>
        <tbody>{a.factors.map((f: any) => (
          <tr key={f.id}><td className="l amber">{f.label}</td><td className="l" style={{ color: GROUP_COL[f.group] }}>{f.group}</td>
            <td className={f.contribution_pct >= 0 ? 'up' : 'down'}>{fmtPct(f.contribution_pct, 2)}</td></tr>
        ))}</tbody>
      </table>
    </>
  );
}

function Roll({ d, setRids }: { d: any; setRids: (v: string[] | null) => void }) {
  const ro = d.rolling;
  const [draft, setDraft] = useState<string[]>(ro.ids);
  const lines = ro.ids.map((id: string, i: number) => ({
    name: ro.labels[id],
    data: ro.dates.map((dt: string, k: number) => ({ time: ts(dt), value: ro.beta[id][k] })).filter((p: any) => p.value != null),
    color: LINE_COL[i % LINE_COL.length],
  }));
  return (
    <>
      <div className="toolbar" style={{ flexWrap: 'wrap' }}>
        <span className="lbl">推移を見る要因（最大 6）</span>
        {d.exposures.map((e: any) => (
          <label key={e.id} style={{ fontSize: 11 }}><input type="checkbox" checked={draft.includes(e.id)} disabled={!draft.includes(e.id) && draft.length >= 6}
            onChange={(ev) => setDraft(ev.target.checked ? [...draft, e.id] : draft.filter((x) => x !== e.id))} />{e.label}</label>
        ))}
        <button className="tb mini" onClick={() => setRids(draft)}>適用</button>
      </div>
      {ro.dates.length ? <LineChart height={260} lines={lines} baseline={0} /> : <div className="note">推移を出すには履歴が足りない</div>}
      <table className="t nowrap" style={{ fontSize: 11 }}>
        <thead><tr><th className="l">要因</th><th>最新</th><th>最小</th><th>最大</th><th>最新の t</th></tr></thead>
        <tbody>{ro.ids.map((id: string) => {
          const v = (ro.beta[id] as (number | null)[]).filter((x): x is number => x != null);
          const tl = ro.t[id][ro.t[id].length - 1];
          return <tr key={id}><td className="l amber">{ro.labels[id]}</td><td>{fmtNum(v[v.length - 1], 3)}</td><td>{fmtNum(Math.min(...v), 3)}</td><td>{fmtNum(Math.max(...v), 3)}</td><td className={tcls(tl)}>{fmtNum(tl, 1)}</td></tr>;
        })}</tbody>
      </table>
      <div className="note">推定窓 {ro.window} 日を 5 日ずつずらした値（感応度は 1%・金利は 10bp あたりの %）。</div>
    </>
  );
}

function Maps({ d, setIds }: { d: any; setIds: (v: string[] | null) => void }) {
  return (
    <div className="brief-grid">
      {Object.entries(d.maps as Record<string, any[]>).map(([g, rows]) => {
        const max = Math.max(1, ...rows.map((x) => Math.abs(x.t || 0)));
        return (
          <div key={g} className="box">
            <h4 style={{ color: GROUP_COL[g] }}>{g}</h4>
            <table className="t nowrap" style={{ fontSize: 11 }}>
              <thead><tr><th className="l">要因</th><th>市場調整後</th><th>t</th><th className="l" style={{ width: 90 }} /><th>単独</th><th /></tr></thead>
              <tbody>{rows.map((x) => (
                <tr key={x.id}>
                  <td className="l amber">{x.label}{x.id === d.sector_id ? ' ★' : ''}</td>
                  <td className={x.beta >= 0 ? 'up' : 'down'}>{fmtNum(x.beta, 3)}</td>
                  <td className={tcls(x.t)}>{fmtNum(x.t, 1)}</td>
                  <td className="l"><Bar2 v={x.t || 0} max={max} color={GROUP_COL[g]} /></td>
                  <td className="muted">{fmtNum(x.total_beta, 3)}</td>
                  <td>{x.in_model ? <span className="muted">モデル内</span> : <button className="tb mini" onClick={() => setIds([...d.ids, x.id])}>＋</button>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        );
      })}
      <div className="note">単位：1%（金利は 10bp）あたりの %。★ = 自セクター。「＋」でその要因をモデルに入れて再計算。</div>
    </div>
  );
}

function Scen({ d, reload }: { d: any; reload: () => void }) {
  const { toast } = useTerminal();
  const [shocks, setShocks] = useState<Record<string, string>>({});
  const [res, setRes] = useState<any>(null);
  const run = async (s = shocks) => {
    const num = Object.fromEntries(Object.entries(s).filter(([, v]) => v !== '' && isFinite(+v)).map(([k, v]) => [k, +v]));
    try { setRes(await api.post<any>('/fexp/scenario', { key: d.key, shocks: num })); }
    catch (e: any) { toast(e.message); reload(); }
  };
  const preset = (p: Record<string, number>) => {
    const s = Object.fromEntries(Object.entries(p).filter(([k]) => d.ids.includes(k)).map(([k, v]) => [k, String(v)]));
    setShocks(s);
    run(s);
  };
  const totals = Object.values(d.maps || {}).flat() as any[];
  return (
    <div className="pad">
      <div className="toolbar" style={{ flexWrap: 'wrap' }}>
        {PRESETS.filter((p) => Object.keys(p.shocks).some((k) => d.ids.includes(k))).map((p) => <button key={p.label} className="tb mini" onClick={() => preset(p.shocks)}>{p.label}</button>)}
        <button className="tb mini" onClick={() => { setShocks({}); setRes(null); }}>クリア</button>
      </div>
      <table className="t nowrap" style={{ fontSize: 11, maxWidth: 560 }}>
        <thead><tr><th className="l">要因</th><th>ショック</th><th className="l">単位</th></tr></thead>
        <tbody>{d.exposures.map((e: any) => (
          <tr key={e.id}><td className="l amber">{e.label}</td>
            <td><input className="inp" style={{ width: 70, textAlign: 'right' }} value={shocks[e.id] ?? ''} onChange={(ev) => setShocks({ ...shocks, [e.id]: ev.target.value })} onKeyDown={(ev) => ev.key === 'Enter' && run()} /></td>
            <td className="l muted">{e.kind === 'bp' ? 'bp' : '%'}</td></tr>
        ))}</tbody>
      </table>
      <button className="tb" onClick={() => run()}>計算</button>
      {res && (
        <div className="box" style={{ marginTop: 6 }}>
          <h4>予想される株価の変化</h4>
          <div className="pad" style={{ fontSize: 18 }}>
            <span className={res.expected_pct >= 0 ? 'up' : 'down'}>{fmtPct(res.expected_pct, 2)}</span>
            <span className="muted" style={{ fontSize: 12 }}> ± {fmtNum(res.se_pct, 2)}%（1 標準誤差。個社要因のぶれは含まない：1 日の個別ボラ {fmtNum(d.idio_vol_pct / Math.sqrt(252), 2)}%）</span>
          </div>
          <table className="t nowrap" style={{ fontSize: 11 }}><tbody>{res.contributions.map((c: any) => (
            <tr key={c.id}><td className="l amber">{c.label}</td><td className={c.pct >= 0 ? 'up' : 'down'}>{fmtPct(c.pct, 2)}</td></tr>
          ))}</tbody></table>
        </div>
      )}
      {totals.length > 0 && (
        <div className="box" style={{ marginTop: 6 }}>
          <h4>その要因だけが動いたときの平均的な連動（単独 β、市場経由を含む）</h4>
          <table className="t nowrap" style={{ fontSize: 11 }}><tbody>{totals.filter((x) => ['fx.usdjpy', 'fx.eurjpy', 'fx.dxy', 'rate.us10', 'rate.jp10', 'cmd.oil', 'os.sox', 'os.spx'].includes(x.id)).map((x) => (
            <tr key={x.id}><td className="l amber">{x.label}</td><td className="muted">{x.unit} あたり</td><td className={x.total_beta >= 0 ? 'up' : 'down'}>{fmtNum(x.total_beta, 3)}%</td><td className={tcls(x.total_t)}>t {fmtNum(x.total_t, 1)}</td></tr>
          ))}</tbody></table>
        </div>
      )}
    </div>
  );
}

function Comp({ est, offset }: { est: number; offset: number }) {
  const { run } = useTerminal();
  const r = useAsync(() => api.get<any>('/fexp/coverage', { est, end_offset: offset }), [est, offset]);
  const [sort, setSort] = useState<string | null>(null);
  const d = r.data;
  if (r.loading && !d) return <Loading what="カバレッジの全銘柄を計算中" />;
  if (r.error) return <ErrorBox error={r.error} />;
  if (!d) return null;
  return (
    <div>
      {Object.entries(d.columns as Record<string, any[]>).map(([reg, cols]) => {
        let rows = d.rows.filter((x: any) => x.region === reg);
        if (sort) rows = [...rows].sort((a: any, b: any) => ((b.cells?.[sort]?.beta ?? -1e9) - (a.cells?.[sort]?.beta ?? -1e9)));
        return (
          <div key={reg} className="box" style={{ margin: 6 }}>
            <h4>{reg === 'JP' ? '日本株' : '米国株ほか'}（{rows.length} 銘柄）{d.source === 'sim' && <span className="badge demo">DEMO</span>}</h4>
            <table className="t nowrap" style={{ fontSize: 11 }}>
              <thead><tr><th className="l">銘柄</th>{cols.map((c: any) => <th key={c.key} style={{ cursor: 'pointer' }} className={sort === c.key ? 'amber' : ''} onClick={() => setSort(c.key)}>{c.label}</th>)}
                <th>R²</th><th>個社</th><th>1M</th><th>うち個社</th></tr></thead>
              <tbody>{rows.map((x: any) => (
                <tr key={x.symbol} style={{ cursor: 'pointer' }} onClick={() => run('FEXP', x.symbol)}>
                  <td className="l"><span className="amber">{x.ticker || x.symbol}</span> {x.name}</td>
                  {x.error ? <td colSpan={cols.length + 4} className="l muted">{x.error}</td> : cols.map((c: any) => {
                    const v = x.cells?.[c.key];
                    if (!v) return <td key={c.key} className="muted">—</td>;
                    const a = Math.min(0.7, Math.abs(v.t || 0) / 6);
                    return <td key={c.key} title={`${v.label} t=${fmtNum(v.t, 1)}`} style={{ background: `rgba(${v.beta >= 0 ? '47,209,122' : '255,69,69'},${a})` }}>{fmtNum(v.beta, 2)}</td>;
                  })}
                  {!x.error && <><td>{fmtNum(x.r2, 2)}</td><td>{fmtPct(x.specific * 100, 0, false)}</td>
                    <td className={(x.att_1m?.total_pct ?? 0) >= 0 ? 'up' : 'down'}>{fmtPct(x.att_1m?.total_pct, 1)}</td>
                    <td className={(x.att_1m?.specific_pct ?? 0) >= 0 ? 'up' : 'down'}>{fmtPct(x.att_1m?.specific_pct, 1)}</td></>}
                </tr>
              ))}</tbody>
            </table>
          </div>
        );
      })}
      <div className="note">感応度は 1%（金利は 10bp）あたりの %。セクターは各銘柄の自セクター。列名をクリックで並べ替え。推定 {d.est} 日。</div>
    </div>
  );
}
