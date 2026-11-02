// TRIN — 投資の三位一体 (Fundamental × Macro × Quant) as a working tool.
// Tabs map 1:1 to the user's Notion framework (docs/FRAMEWORK.md):
//   MAP   第5部 意思決定パイプライン + 三位の一致 (overview for the loaded security)
//   SCORE 02.4 評点表 + 3.5句          KELLY 04.2 期待値・ケリー + 評点差→サイズ
//   RULE  04.3 六層のエクスポージャー   PAIR  04.3/05.4 Pair Sigma・適性・A-1
//   SHRT  04.5 空売り8モデル            CHIP  03.5 天井/底シグナル・混雑度
//   GATE  05.6 関門チェックリスト        GLQ   03.4 成長×流動性 4象限
import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { fmtBig, fmtNum, fmtPct } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { takeKellyPrefill } from './Insight';
import { WindowSlider, type WindowValue } from '../components/WindowSlider';

export const TRIN_TABS = ['AUTO', 'MAP', 'SCORE', 'KELLY', 'RULE', 'PAIR', 'SHRT', 'CHIP', 'GATE', 'GLQ'] as const;
type Tab = (typeof TRIN_TABS)[number];
const TAB_LABEL: Record<Tab, string> = {
  AUTO: '自動判定', MAP: '三位一体', SCORE: '評点表', KELLY: 'ケリー', RULE: '六層規律', PAIR: 'ペア', SHRT: '空売り8', CHIP: '天井/底', GATE: '関門', GLQ: '成長×流動性',
};
const ts = (d: string) => Math.floor(Date.parse(d) / 1000);
const stCls = (s: string) => (s === 'PASS' ? 'up' : s === 'FAIL' ? 'down' : s === 'WARN' ? 'yellow' : 'muted');
const dirCls = (d?: string) => (d === 'LONG' ? 'up' : d === 'SHORT' ? 'down' : 'yellow');

function useMeta() {
  return useAsync(() => api.get<any>('/framework/meta'), []);
}

export function TRIN({ symbol, tab: initial, onPick }: { symbol: string; tab?: string; onPick?: (s: string) => void }) {
  const [tab, setTab] = useState<Tab>((TRIN_TABS as readonly string[]).includes(initial || '') ? (initial as Tab) : 'AUTO');
  useEffect(() => {
    if (initial && (TRIN_TABS as readonly string[]).includes(initial)) setTab(initial as Tab);
  }, [initial]);
  return (
    <div>
      <div className="toolbar">
        {TRIN_TABS.map((t) => (
          <button key={t} className={`tb ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)} title={TAB_LABEL[t]}>
            {t} <span className="muted">{TAB_LABEL[t]}</span>
          </button>
        ))}
      </div>
      {tab === 'AUTO' && <AutoTab symbol={symbol} onPick={onPick} go={setTab} />}
      {tab === 'MAP' && <MapTab symbol={symbol} go={setTab} />}
      {tab === 'SCORE' && <ScoreTab symbol={symbol} onPick={onPick} />}
      {tab === 'KELLY' && <KellyTab />}
      {tab === 'RULE' && <RuleTab />}
      {tab === 'PAIR' && <PairTab symbol={symbol} />}
      {tab === 'SHRT' && <ShortTab symbol={symbol} />}
      {tab === 'CHIP' && <ChipTab symbol={symbol} />}
      {tab === 'GATE' && <GateTab />}
      {tab === 'GLQ' && <GLQ />}
    </div>
  );
}

// ---------------------------------------------------------------- AUTO (rule-based, scheduled)
const RQC: Record<string, string> = { Leading: '#2fd17a', Weakening: '#ffd84a', Lagging: '#ff4545', Improving: '#5ea9ff' };
const RQJ: Record<string, string> = { Leading: '主導', Weakening: '減速', Lagging: '劣後', Improving: '改善' };
const vSym = (v: number) => (v > 0 ? <span className="up">▲</span> : v < 0 ? <span className="down">▼</span> : <span className="muted">·</span>);

function AutoTab({ symbol, onPick, go }: { symbol: string; onPick?: (s: string) => void; go: (t: Tab) => void }) {
  const r = useAsync(() => api.get<any>('/trinity/latest'), []);
  const ch = useAsync(() => api.get<any>('/trinity/changes', { limit: 30 }), []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [filter, setFilter] = useState('ACTIONABLE');
  const [cfgOpen, setCfgOpen] = useState(false);
  const [extra, setExtra] = useState('');
  const [interval, setIv] = useState(60);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    const c = r.data?.config;
    if (c) { setExtra((c.extra || []).join(', ')); setIv(c.interval_min || 60); }
  }, [r.data]);
  useEffect(() => {
    const t = setInterval(r.reload, 60_000); // pick up scheduled runs
    const onUpd = () => { r.reload(); ch.reload(); }; // manual refresh from the top bar
    window.addEventListener('trinity-updated', onUpd);
    return () => { clearInterval(t); window.removeEventListener('trinity-updated', onUpd); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const runNow = async () => {
    setBusy(true); setErr('');
    try { await api.post('/trinity/run', {}); r.reload(); ch.reload(); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const saveCfg = async () => {
    await api.put('/trinity/config', { extra: extra.split(/[,\s]+/).filter(Boolean).map((x) => x.toUpperCase()), interval_min: interval, enabled: true });
    setCfgOpen(false); r.reload();
  };
  const snap = r.data?.snapshot;
  const st = r.data?.status;
  const rows: any[] = (snap?.rows || []).filter((x: any) => filter === 'ALL' || (filter === 'ACTIONABLE' ? x.size_pct > 0 : x.direction === filter));
  const detail = snap?.rows?.find((x: any) => x.symbol === (sel || symbol));
  return (
    <div>
      <div className="toolbar">
        <button className="tb on" onClick={runNow} disabled={busy || st?.running}>{busy || st?.running ? '⟳ 更新中…' : '⟳ 今すぐ更新'}</button>
        <span className="muted">最終 {snap?.generated_at?.replace('T', ' ') || '—'} · 次回 {st?.next_run?.replace('T', ' ') || '—'} · {r.data?.config?.interval_min}分ごと · {snap?.universe ?? 0}銘柄 · {snap?.source} {snap?.seconds != null ? `· ${snap.seconds}s` : ''}</span>
        {['ACTIONABLE', 'LONG', 'SHORT', 'NEUTRAL', 'ALL'].map((f) => <button key={f} className={`tb ${filter === f ? 'on' : ''}`} onClick={() => setFilter(f)}>{f}</button>)}
        <button className="tb" onClick={() => setCfgOpen(!cfgOpen)}>UNIVERSE</button>
      </div>
      {cfgOpen && (
        <div className="toolbar">
          <span className="lbl">対象 = ウォッチリスト + SCORE保存銘柄 + PORT +</span>
          <input className="inp" style={{ width: 320 }} value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="TSE:6501, TSE:6503 …" />
          <span className="lbl">間隔(分)</span><input className="inp num" type="number" min={5} value={interval} onChange={(e) => setIv(+e.target.value)} />
          <button className="tb on" onClick={saveCfg}>SAVE</button>
        </div>
      )}
      {(err || st?.last_error) && <div className="err">{err || st?.last_error}</div>}
      {r.loading && !snap && <Loading />}
      {!snap && !r.loading && <div className="note">まだ実行されていません。「⟳ 今すぐ更新」（上部バーの「⟳ 三位一体を更新」でも可）を押すか、起動後の自動実行（約20秒後）を待ってください。</div>}
      {snap && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>MACRO</span><span className="yellow">{snap.quadrant?.name || '—'} <span className="muted">→ {snap.next_quadrant?.name || ''} ({snap.rotation || ''})</span></span>
            <span>BOOK (rule)</span><span>L {snap.book.longs} / S {snap.book.shorts} · G {fmtPct(snap.book.gross_pct, 1, false)} · <span className={snap.book.net_ok ? 'up' : 'down'}>N {fmtPct(snap.book.net_pct, 1)}</span></span>
          </div>
          <div className="trin-split">
            <div style={{ flex: 3, minWidth: 520, overflowX: 'auto' }}>
              <table className="t nowrap">
                <thead><tr><th className="l">SYMBOL</th><th>F</th><th>src</th><th>M</th><th>需給</th><th>SECT</th><th>固有</th><th>決算</th><th>VERDICT</th><th>確信</th><th>SIZE</th><th>①②③④</th><th className="l">FLAGS</th></tr></thead>
                <tbody>
                  {rows.map((x: any) => (
                    <tr key={x.symbol} className={(sel || symbol) === x.symbol ? 'sel' : ''} style={{ cursor: 'pointer' }} onClick={() => { setSel(x.symbol); onPick?.(x.symbol); }}>
                      <td className="l amber">{x.symbol}<span className="muted"> {(x.name || '').slice(0, 14)}</span></td>
                      <td className={dirCls(x.f.direction)}>{fmtNum(x.f.score, 2)}</td><td className="muted">{x.f.source}</td>
                      <td>{vSym(x.m.view)}</td><td>{vSym(x.l.view)}</td>
                      <td style={{ color: RQC[x.sector_rrg?.quadrant] || '#777' }} title={x.sector_rrg ? `${x.sector_rrg.label} ${x.sector_rrg.quadrant}` : ''}>{x.sector_rrg ? RQJ[x.sector_rrg.quadrant] : '·'}</td>
                      <td className={x.xray?.idio != null && x.xray.idio < 0.3 ? 'down' : 'muted'}>{x.xray?.idio != null ? Math.round(x.xray.idio * 100) : ''}</td>
                      <td className={x.days_to_earnings != null && x.days_to_earnings >= 0 && x.days_to_earnings <= 30 ? 'yellow' : 'muted'}>{x.days_to_earnings != null && x.days_to_earnings >= 0 ? `${x.days_to_earnings}d` : ''}</td>
                      <td className={dirCls(x.direction)}>{x.direction}</td>
                      <td>{'●'.repeat(x.conviction)}<span className="muted">{'○'.repeat(3 - x.conviction)}</span></td>
                      <td className="yellow">{x.size_pct ? fmtPct(x.size_pct, 2, false) : ''}</td>
                      <td>{Object.values(x.gates).map((g: any, i: number) => <span key={i} className={stCls(g)}>{g === 'PASS' ? '●' : g === 'FAIL' ? '✕' : '·'}</span>)}</td>
                      <td className="l muted" style={{ fontSize: 10, whiteSpace: 'nowrap', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }} title={[...x.flags, ...x.short_models].join('\n')}>{[...x.flags, ...x.short_models.map((m: string) => '空売り' + m)].slice(0, 2).join(' / ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ flex: 2, minWidth: 280 }}>
              {detail && (
                <div className="box" style={{ margin: 6 }}>
                  <h4>{detail.symbol} — 判定の根拠（ルール）</h4>
                  <div className="pad">
                    <div><span className="amber">F</span> {detail.f.source === 'SCORE' ? `評点表 ${fmtNum(detail.f.score, 2)}` : detail.f.score != null ? `ルール採点 ${fmtNum(detail.f.score, 2)}（同ユニバース内 ${fmtPct((detail.f.detail?.percentile ?? 0) * 100, 0, false)} 位置・${detail.f.detail?.peers}銘柄比較）` : `N/A — ${detail.f.detail?.reason || ''}`} → <span className={dirCls(detail.f.direction)}>{detail.f.direction}</span></div>
                    {detail.f.detail?.components && <div className="muted" style={{ fontSize: 11 }}>{Object.entries(detail.f.detail.components).map(([k, v]: any) => `${k} ${fmtNum(v * 100, 0)}`).join(' · ')}</div>}
                    <div><span className="amber">M</span> {detail.m.reason} {vSym(detail.m.view)} <span className="muted">次の象限 {vSym(detail.m.next_view ?? 0)}</span></div>
                    <div><span className="amber">需給</span> {detail.l.zone} {vSym(detail.l.view)} <span className="muted">· 3M {fmtPct(detail.l.mom_3m_pct, 1)} · 高値比 −{fmtNum(detail.l.drawdown_pct, 1)}% · vol {fmtNum(detail.l.vol_pct, 0)}% · 売買pctl {fmtNum(detail.l.activity_pctl, 0)}</span></div>
                    {detail.l.signals.map((s: string) => <div key={s} className="muted" style={{ fontSize: 11 }}>• {s}</div>)}
                    <div style={{ marginTop: 4 }}>→ <span className={dirCls(detail.direction)}>{detail.direction}</span> 確信 {detail.conviction}/3 · サイズ {fmtPct(detail.size_pct, 2, false)}（一致 {detail.agree}・逆行 {detail.oppose}）</div>
                    {detail.flags.map((f: string) => <div key={f} className="yellow">• {f}</div>)}
                    {detail.short_models.length > 0 && <div className="down">空売りモデル該当: {detail.short_models.join(' / ')}</div>}
                    <div style={{ marginTop: 4 }}><button className="tb" onClick={() => go('SCORE')}>SCORE で上書き採点</button> <button className="tb" onClick={() => go('PAIR')}>PAIR</button> <button className="tb" onClick={() => go('CHIP')}>CHIP</button></div>
                  </div>
                </div>
              )}
              {(snap.themes || []).length > 0 && (
                <div className="box" style={{ margin: 6 }}>
                  <h4>THEMES — 反応ラグのフェーズ（自動）</h4>
                  <table className="t"><tbody>{snap.themes.map((t: any) => (
                    <tr key={t.id}><td className="l amber">{t.name}</td><td className={`l ${String(t.phase).startsWith('②') ? 'up' : String(t.phase).startsWith('③') ? 'yellow' : 'muted'}`}>{t.phase}</td>
                      <td title="spread z / driver z">{fmtNum(t.spread_z, 1)} / {fmtNum(t.driver_z, 1)}</td><td>{t.basket_flow ? <span className="down">B-1</span> : ''}</td></tr>
                  ))}</tbody></table>
                </div>
              )}
              {snap.sectors && Object.keys(snap.sectors).length > 0 && (
                <div className="box" style={{ margin: 6 }}>
                  <h4>SECTORS — RRG（セクター・フローの代理）</h4>
                  <div className="pad" style={{ fontSize: 11 }}>{Object.entries(snap.sectors).map(([k, rows]: any) => (
                    <div key={k}><span className="muted">{k}: </span>{rows.map((r: any) => <span key={r.symbol} style={{ color: RQC[r.quadrant], marginRight: 8 }} title={`${r.quadrant} ratio ${fmtNum(r.ratio, 1)} mom ${fmtNum(r.momentum, 1)}`}>{r.label}</span>)}</div>
                  ))}</div>
                </div>
              )}
              <div className="box" style={{ margin: 6 }}>
                <h4>CHANGES（自動実行ごとの変化）</h4>
                <table className="t"><tbody>{(ch.data?.changes || []).map((c: any, i: number) => (
                  <tr key={i}><td className="muted">{c.at?.slice(5, 16).replace('T', ' ')}</td><td className="l amber">{c.symbol}</td><td className="l">{c.from ?? ''} → <span className="yellow">{c.to}</span></td></tr>
                ))}</tbody></table>
              </div>
              {Object.keys(snap.errors || {}).length > 0 && <div className="note">data: {Object.entries(snap.errors).slice(0, 6).map(([k, v]) => `${k}: ${String(v).slice(0, 60)}`).join(' | ')}</div>}
            </div>
          </div>
          <div className="note">ルールベース・自動更新（AIなし）。F＝評点表があればそれ、なければスキャナーのファンダメンタルズを同ユニバース内で順位付け（上下10%だけが3.4超／2.7未満）。M＝成長×流動性の象限でのセクター優位。需給＝天井/底シグナル。F が無ければポジションなし。確信度＝1＋一致数−逆行数。サイズ＝上限（L3% / S2%）×確信/3×min(1, 30%/ボラ)。SECT＝銘柄のセクター ETF の RRG（劣後のロング／主導のショートは①関門 FAIL）、固有＝XRAY の個別固有の分散比率（%）、決算＝次回決算までの日数。詳細は docs/FRAMEWORK.md §8。</div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- MAP
const PIPE = [
  { l: 'LAYER 1 — ファンダメンタル', q: '何を、どちらの方向で持つか', tools: '3.5句・能力の輪・EVベース評価・情報の2軸', out: '銘柄・方向・確信度', tabs: ['SCORE'] },
  { l: 'LAYER 2 — マクロ', q: 'その判断は、いつ・どこまで効くか', tools: 'クロスアセット・反応ラグ・Growth×Liquidity・セクターフロー', out: '実行時期／順風・逆風', tabs: ['GLQ'], ext: 'PROP / MACRO / LAG' },
  { l: 'LAYER 3 — 需給・行動', q: 'いつ入り、いつ出るか', tools: '混雑度・浮動株・天井/底シグナル・カタリスト', out: 'エントリー／エグジット', tabs: ['CHIP', 'SHRT'], ext: 'MRGN / EARN / EVT' },
  { l: 'LAYER 4 — サイジング', q: 'どれだけ張るか', tools: 'ケリー・グロス/ネット規則・ペア管理', out: 'ウェイト', tabs: ['KELLY', 'RULE', 'PAIR'], ext: 'PORT / FACT' },
];

function MapTab({ symbol, go }: { symbol: string; go: (t: Tab) => void }) {
  const meta = useMeta();
  const ov = useAsync(() => api.get<any>(`/framework/overview/${encodeURIComponent(symbol)}`), [symbol]);
  const d = ov.data;
  return (
    <div>
      <div className="note">「ファンダメンタルを土台に、マクロを意識し、クオンツで量を縛る」— 三方向から同じ結論に着いたときだけ確信度を上げてよい。</div>
      <div className="trin-pipe">
        {PIPE.map((p) => (
          <div key={p.l} className="box trin-layer">
            <h4>{p.l}</h4>
            <div className="pad">
              <div className="amber">{p.q}</div>
              <div className="muted" style={{ fontSize: 11 }}>{p.tools}</div>
              <div>→ <span className="yellow">{p.out}</span></div>
              <div style={{ marginTop: 4 }}>
                {p.tabs.map((t) => <button key={t} className="tb" onClick={() => go(t as Tab)}>{t}</button>)}
                {p.ext && <span className="muted" style={{ fontSize: 11 }}> + {p.ext}</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="box" style={{ margin: 6 }}>
        <h4>{symbol} — 三位の現在地</h4>
        {ov.loading && <Loading />}
        <ErrorBox error={ov.error} />
        {d && (
          <table className="t">
            <thead><tr><th className="l">位相</th><th className="l">判定</th><th className="l">根拠</th></tr></thead>
            <tbody>
              {d.phases.map((p: any) => (
                <tr key={p.phase}><td className="l amber">{p.phase}</td><td className={`l ${dirCls(p.view)}`}>{p.view}</td><td className="l">{p.detail}</td></tr>
              ))}
              {!d.score && <tr><td className="l amber">ファンダメンタル</td><td className="l muted" colSpan={2}>評点表が未作成 → SCORE タブで採点</td></tr>}
            </tbody>
          </table>
        )}
        {d && <div className="note">{d.rule}</div>}
      </div>
      {meta.data && (
        <div className="box" style={{ margin: 6 }}>
          <h4>位相が衝突したときの裁定ルール（05.2）</h4>
          <table className="t">
            <tbody>{meta.data.arbitration.map((a: any) => <tr key={a.conflict}><td className="l amber">{a.conflict}</td><td className="l">{a.ruling}</td></tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- SCORE
function ScoreTab({ symbol, onPick }: { symbol: string; onPick?: (s: string) => void }) {
  const meta = useMeta();
  const list = useAsync(() => api.get<any>('/framework/scorecards'), []);
  const card = useAsync(() => api.get<any>(`/framework/scorecards/${encodeURIComponent(symbol)}`), [symbol]);
  const [rows, setRows] = useState<any[]>([]);
  const [text, setText] = useState<Record<string, string>>({});
  const [moat, setMoat] = useState<Record<string, any>>({});
  const [reason, setReason] = useState('');
  const [sector, setSector] = useState('');
  const [subsector, setSubsector] = useState('');
  const [res, setRes] = useState<any>(null);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    if (!meta.data || card.loading) return;
    const last = card.data?.latest?.sheet;
    const base = meta.data.score_factors.map((f: any) => {
      const old = last?.rows?.find((r: any) => r.id === f.id);
      // a new version starts from last time's scores; Previous Score is filled by the server on save
      return { ...f, weight: old?.weight ?? f.weight, score: old?.score ?? '', ai_score: old?.ai_score ?? '', prev_score: '' };
    });
    setRows(base);
    setText(last?.text || {});
    setMoat(last?.moat || {});
    setReason(last?.reason || '');
    setSector(last?.sector || '');
    setSubsector(last?.subsector || '');
    setRes(card.data?.latest?.result || null);
  }, [meta.data, card.data, card.loading]);

  const sheet = () => ({ rows, text, moat, reason, sector, subsector });
  useEffect(() => {
    if (!rows.length) return;
    const t = setTimeout(() => api.post<any>('/framework/score/evaluate', sheet()).then(setRes).catch(() => {}), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, text, moat, reason]);

  const set = (i: number, k: string, v: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const save = async () => {
    const r = await api.post<any>(`/framework/scorecards/${encodeURIComponent(symbol)}`, sheet());
    setMsg(`saved v${r.version}`);
    card.reload();
    list.reload();
  };
  const md = meta.data;
  return (
    <div className="trin-split">
      <div style={{ flex: 3, minWidth: 540 }}>
        {(meta.loading || card.loading) && <Loading />}
        <ErrorBox error={meta.error || card.error} />
        {md && <div className="note">⚠ {md.weights_note}</div>}
        <div className="toolbar">
          <span className="lbl">SECTOR</span><input className="inp" value={sector} onChange={(e) => setSector(e.target.value)} style={{ width: 110 }} />
          <span className="lbl">SUBSECTOR</span><input className="inp" value={subsector} onChange={(e) => setSubsector(e.target.value)} style={{ width: 130 }} />
          <button className="tb on" onClick={save}>SAVE VERSION</button>
          <span className="muted">{msg} {card.data?.versions?.length ? `· ${card.data.versions.length} versions` : ''}</span>
        </div>
        <table className="t trin-score">
          <thead><tr><th className="l">CATEGORY / FACTOR</th><th>WEIGHT</th><th>SCORE</th><th>AI SCORE</th><th>PREV</th><th>W×S</th></tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const prev = card.data?.latest?.sheet?.rows?.find((x: any) => x.id === r.id)?.score;
              const s = parseFloat(r.score);
              const ai = parseFloat(r.ai_score);
              return (
                <tr key={r.id}>
                  <td className="l"><span className="muted">{r.group} · </span>{r.factor}</td>
                  <td><input className="inp num" value={r.weight} onChange={(e) => set(i, 'weight', e.target.value)} /></td>
                  <td><input className="inp num" value={r.score} placeholder="1-5" onChange={(e) => set(i, 'score', e.target.value)} /></td>
                  <td><input className={`inp num ${Math.abs(s - ai) >= 1 ? 'warnbg' : ''}`} value={r.ai_score} placeholder="AI" onChange={(e) => set(i, 'ai_score', e.target.value)} /></td>
                  <td className="muted">{prev ?? ''}</td>
                  <td>{isFinite(s) ? fmtNum((s * parseFloat(r.weight)) / 100, 2) : ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="box" style={{ margin: 6 }}>
          <h4>3.5句（独占・NW 1 ／ コスト・コスパ 1 ／ ブランド 1 ／ 技術 0.5）</h4>
          <div className="pad trin-moat">
            {[['monopoly_network', '独占・ネットワーク効果'], ['cost_cospa', 'コスト／コスパ'], ['brand', 'ブランド（値上げしても数量が落ちないか）'], ['technology', '技術リーダーシップ']].map(([k, l]) => (
              <label key={k}>
                <select className="inp" value={moat[k] ?? 0} onChange={(e) => setMoat({ ...moat, [k]: parseFloat(e.target.value) })}>
                  <option value={0}>✕</option><option value={0.5}>△</option><option value={1}>◎</option>
                </select>{' '}{l}{' '}
                <span className="muted">
                  <input type="checkbox" checked={(moat.physical || []).includes(k)} onChange={(e) => {
                    const p = new Set<string>(moat.physical || []);
                    if (e.target.checked) p.add(k); else p.delete(k);
                    setMoat({ ...moat, physical: [...p] });
                  }} /> 物理的優位（買った設備）
                </span>
              </label>
            ))}
          </div>
        </div>
        <div className="box" style={{ margin: 6 }}>
          <h4>REASON（3.5 Sentences）と記述ブロック</h4>
          <div className="pad">
            <textarea className="inp" style={{ width: '100%', height: 48 }} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="なぜこの点数か — 前提まで遡って説明" />
            {md?.score_text_blocks.map((b: any) => (
              <div key={b.id} className="trin-text">
                <span className="lbl">{b.label}</span>
                <textarea className="inp" value={text[b.id] || ''} onChange={(e) => setText({ ...text, [b.id]: e.target.value })} />
              </div>
            ))}
          </div>
        </div>
      </div>
      <div style={{ flex: 2, minWidth: 260 }}>
        {res && (
          <div className="box" style={{ margin: 6 }}>
            <h4>TOTAL SCORE</h4>
            <div className="pad trin-total">
              <span className={dirCls(res.direction)} style={{ fontSize: 28 }}>{fmtNum(res.total, 2)}</span>{' '}
              <span className={dirCls(res.direction)} style={{ fontSize: 18 }}>{res.direction}</span>
              <div className="muted">AI {fmtNum(res.ai_total, 2)} ({res.ai_direction}) · PREV {fmtNum(res.prev_total, 2)} · Δ {fmtNum(res.delta, 2)}</div>
              <div className="muted">LT {fmtNum(res.groups['Long-term']?.score, 2)} · ST {fmtNum(res.groups['Short-term']?.score, 2)} · VAL {fmtNum(res.groups['Valuation']?.score, 2)}</div>
              {res.profile && <div className="yellow">{res.profile}</div>}
              <div>3.5句 {fmtNum(res.moat.score, 2)} / 3.5 {res.moat.matched.length ? `（${res.moat.matched.join('・')}）` : '（該当なし）'}</div>
              <div className="note">{res.rule}</div>
              {res.issues.map((x: any, i: number) => <div key={i} className={x.level === 'error' ? 'down' : 'yellow'}>• {x.msg}</div>)}
              {res.divergence.length > 0 && <div className="note">AIと1点以上乖離: {res.divergence.map((x: any) => x.factor.split('（')[0]).join(', ')}</div>}
            </div>
          </div>
        )}
        <div className="box" style={{ margin: 6 }}>
          <h4>COVERAGE — 評点表の更新結果としての候補</h4>
          <table className="t">
            <thead><tr><th className="l">SYMBOL</th><th className="l">SUB</th><th>TOTAL</th><th>PREV</th><th>DIR</th></tr></thead>
            <tbody>
              {list.data?.rows.map((r: any) => (
                <tr key={r.symbol} className={r.symbol === symbol ? 'sel' : ''} onClick={() => onPick?.(r.symbol)} style={{ cursor: 'pointer' }}>
                  <td className="l amber">{r.symbol}</td><td className="l muted">{r.subsector || ''}</td>
                  <td>{fmtNum(r.total, 2)}</td><td className="muted">{fmtNum(r.previous_total, 2)}</td><td className={dirCls(r.direction)}>{r.direction}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- KELLY
function KellyTab() {
  const [pre] = useState(() => takeKellyPrefill()); // from TRAK → KELLY (own track record)
  const [pw, setPw] = useState(pre ? Math.round(pre.pw * 1000) / 1000 : 0.6);
  const [xw, setXw] = useState(pre ? Math.round(pre.xw * 100) / 100 : 30);
  const [xl, setXl] = useState(pre ? Math.round(pre.xl * 100) / 100 : 15);
  const [side, setSide] = useState('long');
  const [ruin, setRuin] = useState(0);
  const [frac, setFrac] = useState(0.5);
  const k = useAsync(() => api.post<any>('/framework/kelly', { pw, xw: xw / 100, xl: xl / 100, side, ruin_prob: ruin / 100, fraction: frac }), [pw, xw, xl, side, ruin, frac]);
  const [ls, setLs] = useState(4.4);
  const [ss, setSs] = useState(2.8);
  const gap = useAsync(() => api.post<any>('/framework/score_gap', { long_score: ls, short_score: ss }), [ls, ss]);
  const pairs = useAsync(() => api.get<any>('/framework/pairs_from_scores'), []);
  const d = k.data;
  const maxG = d ? Math.max(...d.curve.map((c: any) => c.g ?? -1e9)) : 0;
  return (
    <div className="trin-split">
      <div style={{ flex: 1, minWidth: 300 }}>
        <div className="box" style={{ margin: 6 }}>
          <h4>期待値とケリー（04.2）— F = E / (XW × XL)</h4>
          {pre && <div className="note">TRAK（自分の実績）から入力: {pre.label} — 勝率は事後平均（ベイズ更新）</div>}
          <div className="toolbar">
            <span className="lbl">勝率 PW</span><input className="inp num" type="number" step={0.01} min={0} max={1} value={pw} onChange={(e) => setPw(+e.target.value)} />
            <span className="lbl">XW %</span><input className="inp num" type="number" value={xw} onChange={(e) => setXw(+e.target.value)} />
            <span className="lbl">XL %</span><input className="inp num" type="number" value={xl} onChange={(e) => setXl(+e.target.value)} />
            <select className="inp" value={side} onChange={(e) => setSide(e.target.value)}><option value="long">LONG</option><option value="short">SHORT</option></select>
            <span className="lbl">全損確率 %</span><input className="inp num" type="number" step={0.1} value={ruin} onChange={(e) => setRuin(+e.target.value)} />
            <span className="lbl">KELLY ×</span>
            <select className="inp" value={frac} onChange={(e) => setFrac(+e.target.value)}>{[0.25, 0.5, 0.75, 1].map((x) => <option key={x} value={x}>{x}</option>)}</select>
          </div>
          <ErrorBox error={k.error} />
          {d && (
            <>
              <div className="kv" style={{ gridTemplateColumns: 'repeat(3, max-content 1fr)' }}>
                <span>E</span><span className={d.e > 0 ? 'up' : 'down'}>{fmtPct(d.e * 100, 2)}</span>
                <span>Kelly F</span><span className="yellow">{fmtPct(d.f_pct, 1, false)}</span>
                <span>推奨ウェイト</span><span className="amber">{fmtPct(d.recommended_pct, 2, false)} <span className="muted">(×{d.fraction}, cap {d.cap_pct}%)</span></span>
                <span>σ</span><span>{fmtPct(Math.sqrt(Math.max(d.variance, 0)) * 100, 1, false)}</span>
                <span>G*</span><span>{fmtNum(d.g_star, 5)}</span>
                <span>1回あたり成長</span><span>{fmtPct(d.growth_per_bet_pct, 3)}</span>
              </div>
              <svg viewBox="0 0 400 120" className="trin-curve">
                {d.curve.map((c: any, i: number) => {
                  if (i === 0 || c.g == null || d.curve[i - 1].g == null) return null;
                  const fx = (f: number) => (f / d.curve[d.curve.length - 1].f) * 390 + 5;
                  const gy = (g: number) => 110 - (Math.max(g, -maxG) / (maxG || 1)) * 50 - 50;
                  return <line key={i} x1={fx(d.curve[i - 1].f)} y1={gy(d.curve[i - 1].g)} x2={fx(c.f)} y2={gy(c.g)} stroke="#ffa028" />;
                })}
                <line x1={5} x2={395} y1={60} y2={60} stroke="#333" />
                {d.f > 0 && <line x1={(d.f / d.curve[d.curve.length - 1].f) * 390 + 5} x2={(d.f / d.curve[d.curve.length - 1].f) * 390 + 5} y1={5} y2={115} stroke="#59e3ff" strokeDasharray="3 3" />}
                <text x={8} y={14} fill="#888" fontSize={9}>G(f) — 資金の対数成長率（破線 = Kelly F）</text>
              </svg>
              <table className="t">
                <thead><tr><th>#</th><th className="l">六つの原則</th><th className="l">判定</th></tr></thead>
                <tbody>{d.principles.map((p: any) => (
                  <tr key={p.n}><td>{p.n}</td><td className="l">{p.rule}</td><td className={`l ${p.ok === true ? 'up' : p.ok === false ? 'down' : 'muted'}`}>{p.ok === true ? '✓ ' : p.ok === false ? '✕ ' : ''}{p.detail}</td></tr>
                ))}</tbody>
              </table>
              <div className="note">{d.formula} — {d.note}</div>
            </>
          )}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 280 }}>
        <div className="box" style={{ margin: 6 }}>
          <h4>評点差 → サイズ（02.4 スズキ例）</h4>
          <div className="toolbar">
            <span className="lbl">LONG SCORE</span><input className="inp num" type="number" step={0.1} value={ls} onChange={(e) => setLs(+e.target.value)} />
            <span className="lbl">SHORT SCORE</span><input className="inp num" type="number" step={0.1} value={ss} onChange={(e) => setSs(+e.target.value)} />
          </div>
          {gap.data && <div className="pad">差 <span className="yellow">{fmtNum(gap.data.gap, 2)}</span> → 各脚 <span className="amber" style={{ fontSize: 18 }}>{fmtPct(gap.data.size_pct, 2, false)}</span><div className="note">{gap.data.note}</div></div>}
        </div>
        <div className="box" style={{ margin: 6 }}>
          <h4>保存済み評点表からのペア候補（サブセクター内 最高×最低）</h4>
          <table className="t">
            <thead><tr><th className="l">SUBSECTOR</th><th className="l">LONG</th><th className="l">SHORT</th><th>差</th><th>SIZE</th></tr></thead>
            <tbody>{pairs.data?.pairs.map((p: any) => (
              <tr key={p.subsector}><td className="l amber">{p.subsector}</td><td className="l up">{p.long.symbol} {fmtNum(p.long.total, 2)}</td><td className="l down">{p.short.symbol} {fmtNum(p.short.total, 2)}</td><td>{fmtNum(p.gap, 2)}</td><td className="yellow">{fmtPct(p.size_pct, 2, false)}</td></tr>
            ))}</tbody>
          </table>
          {!pairs.data?.pairs.length && <div className="note">同じサブセクターで2銘柄以上を SCORE で保存すると表示されます。</div>}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- RULE
const POS_COLS: [string, string, number][] = [['symbol', 'SYMBOL', 110], ['weight', 'W %NAV', 60], ['sector', 'SECTOR', 90], ['subsector', 'SUBSECTOR', 110], ['pair', 'PAIR', 50], ['short_type', 'SHORT TYPE', 100], ['mcap_usd', 'MCAP $', 80], ['beta', 'β', 50], ['expected_downside_pct', '下落見込%', 60]];

function RuleTab() {
  const meta = useMeta();
  const [book, setBook] = useState<any>(null);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [nav, setNav] = useState('');
  const [ccy, setCcy] = useState('JPY');
  useEffect(() => {
    api.get<any>('/framework/book').then((b) => { setBook(b); setNav(b?.nav ? String(b.nav) : ''); });
  }, []);
  if (!book) return <Loading />;
  const pos: any[] = book.positions || [];
  const upd = (b: any) => { setBook(b); api.put('/framework/book', b).catch(() => {}); };
  const setCell = (i: number, k: string, v: string) => upd({ ...book, positions: pos.map((p, j) => (j === i ? { ...p, [k]: ['weight', 'mcap_usd', 'beta', 'expected_downside_pct'].includes(k) ? (v === '' ? null : parseFloat(v)) : v || null } : p)) });
  const run = async () => {
    setBusy(true); setErr('');
    try { setRes(await api.post<any>('/framework/exposure', { positions: pos, level: book.level, drawdown_pct: book.drawdown_pct })); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  const fromPort = async () => {
    setErr('');
    try { const r = await api.post<any>('/framework/book/from_portfolio', { nav: parseFloat(nav), base_currency: ccy }); setBook(r.book); if (Object.keys(r.errors || {}).length) setErr(JSON.stringify(r.errors)); } catch (e: any) { setErr(e.message); }
  };
  const groups = res ? ['L1', 'L2', 'L3', 'L4', 'L5', 'L6'].map((l) => [l, res.checks.filter((c: any) => c.layer === l)] as [string, any[]]).filter(([, c]) => c.length) : [];
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">LEVEL</span>
        <select className="inp" value={book.level} onChange={(e) => upd({ ...book, level: e.target.value })}><option value="book">BOOK (PM 1人: G 60–70% / N ≤5%)</option><option value="fund">FUND (G 150–300% / N ±10%)</option></select>
        <span className="lbl">DD %</span><input className="inp num" value={book.drawdown_pct ?? ''} onChange={(e) => upd({ ...book, drawdown_pct: e.target.value === '' ? null : parseFloat(e.target.value) })} />
        <span className="lbl">NAV</span><input className="inp num" style={{ width: 110 }} value={nav} onChange={(e) => setNav(e.target.value)} />
        <select className="inp" value={ccy} onChange={(e) => setCcy(e.target.value)}>{['JPY', 'USD'].map((c) => <option key={c}>{c}</option>)}</select>
        <button className="tb" onClick={fromPort} disabled={!parseFloat(nav)}>IMPORT FROM PORT</button>
        <button className="tb" onClick={() => upd({ ...book, positions: [...pos, { symbol: '', weight: null }] })}>+ ROW</button>
        <button className="tb on" onClick={run} disabled={busy}>{busy ? 'CHECKING…' : 'CHECK RULES'}</button>
      </div>
      {err && <div className="err">{err}</div>}
      <table className="t">
        <thead><tr>{POS_COLS.map(([, l]) => <th key={l} className="l">{l}</th>)}<th /></tr></thead>
        <tbody>
          {pos.map((p, i) => (
            <tr key={i}>
              {POS_COLS.map(([k, , w]) => (
                <td key={k} className="l">
                  {k === 'short_type' ? (
                    <select className="inp" value={p[k] || ''} onChange={(e) => setCell(i, k, e.target.value)} disabled={!(p.weight < 0)}>
                      <option value="">—</option>{meta.data && Object.entries(meta.data.short_types).map(([v, l]) => <option key={v} value={v}>{l as string}</option>)}
                    </select>
                  ) : <input className="inp" style={{ width: w }} value={p[k] ?? ''} onChange={(e) => setCell(i, k, e.target.value)} />}
                </td>
              ))}
              <td><button className="tb" onClick={() => upd({ ...book, positions: pos.filter((_, j) => j !== i) })}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {res && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>GROSS</span><span className="amber">{fmtPct(res.gross, 1, false)}</span><span>NET</span><span className={Math.abs(res.net) > 5 ? 'down' : 'up'}>{fmtPct(res.net, 1)}</span>
            <span>LONG / SHORT</span><span>{fmtPct(res.long, 1, false)} / {fmtPct(res.short, 1)}</span><span>NAMES / PAIRS</span><span>{res.names} / {res.pairs}</span>
            <span>RESULT</span><span><span className="up">{res.summary.PASS} PASS</span> · <span className="yellow">{res.summary.WARN} WARN</span> · <span className="down">{res.summary.FAIL} FAIL</span></span>
          </div>
          {groups.map(([l, cs]) => (
            <div key={l} className="box" style={{ margin: 6 }}>
              <h4>{l} {({ L1: '単一ポジション', L2: 'ペア', L3: 'サブセクター', L4: 'セクター', L5: 'ブック', L6: 'ファンド' } as any)[l]}</h4>
              <table className="t">
                <tbody>{cs.map((c: any, i: number) => (
                  <tr key={i}><td className={stCls(c.status)}>{c.status}</td><td className="l">{c.rule}</td><td className="l amber">{c.subject}</td>
                    <td>{typeof c.value === 'number' ? (Math.abs(c.value) > 1e6 ? fmtBig(c.value) : fmtNum(c.value, 2)) : JSON.stringify(c.value)}</td>
                    <td className="l muted">{c.msg}</td></tr>
                ))}</tbody>
              </table>
            </div>
          ))}
          {Object.keys(res.errors || {}).length > 0 && <div className="note">data: {JSON.stringify(res.errors)}</div>}
        </>
      )}
      <div className="note">L1 ロング3%（〜4%）／ショート2%（〜3%）・小型株ショート禁止 · L2 Pair Sigma &lt;25–30%・Beta調整Net÷Gross &lt;30%（超過3ペアまで）・同一サブセクター · L3 ±3% · L4 ±5% · L5 G 60–70%・N ≤5%・40–80銘柄・30–40ペア・DD −5%でグロス半減 · L6 G 150–300%・N ±10%・単一±5%</div>
    </div>
  );
}

// ---------------------------------------------------------------- PAIR
function PairTab({ symbol }: { symbol: string }) {
  const [long, setLong] = useState(symbol);
  const [short, setShort] = useState('');
  const [cls, setCls] = useState('');
  const [borrow, setBorrow] = useState('');
  const [earn, setEarn] = useState('');
  const [q, setQ] = useState<any>(null);
  useEffect(() => setLong(symbol), [symbol]);
  const [pw, setPw] = useState<WindowValue>({ length: 500, offset: 0 });
  const [sw, setSw] = useState(21);
  const r = useAsync(() => (q ? api.post<any>('/framework/pair', { ...q, lookback: pw.length, end_offset: pw.offset, sigma_window: sw }) : Promise.resolve(null)), [q, pw.length, pw.offset, sw]);
  const go = () => setQ({
    long, short, spread_class: cls || null, borrow_ok: borrow === '' ? null : borrow === 'yes',
    earnings_dirs: earn.trim() ? earn.trim().split(/\s+/).map((t) => t.split('/').map((x) => (x.startsWith('-') ? -1 : 1))) : null,
  });
  const d = r.data;
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">LONG</span><input className="inp" value={long} onChange={(e) => setLong(e.target.value.toUpperCase())} style={{ width: 110 }} />
        <span className="lbl">SHORT</span><input className="inp" value={short} onChange={(e) => setShort(e.target.value.toUpperCase())} style={{ width: 110 }} placeholder="TSE:6503" />
        <span className="lbl">SPREAD CLASS</span>
        <select className="inp" value={cls} onChange={(e) => setCls(e.target.value)}><option value="">未宣言</option>{['A-1', 'A-2', 'B-1', 'B-2'].map((c) => <option key={c}>{c}</option>)}</select>
        <span className="lbl">貸株</span><select className="inp" value={borrow} onChange={(e) => setBorrow(e.target.value)}><option value="">?</option><option value="yes">OK</option><option value="no">NG</option></select>
        <span className="lbl">営業利益方向(四半期)</span><input className="inp" value={earn} onChange={(e) => setEarn(e.target.value)} placeholder="+/- -/+ +/+" style={{ width: 120 }} />
        <button className="tb on" onClick={go} disabled={!long || !short}>ANALYZE</button>
        <span className="lbl">Pair Sigma 窓</span>
        <select className="inp" value={sw} onChange={(e) => setSw(+e.target.value)}>{[21, 42, 63].map((x) => <option key={x} value={x}>{x}日</option>)}</select>
      </div>
      <WindowSlider label="期間" value={pw} onChange={setPw} min={80} max={1500} step={10} maxOffset={750} asof={r.data?.asof} />
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <div className="trin-split">
          <div style={{ flex: 3, minWidth: 480 }}>
            <div className="kv" style={{ gridTemplateColumns: 'repeat(2, max-content 1fr)' }}>
              <span>PAIR SIGMA (1M, 年率)</span><span className={stCls(d.verdict.pair_sigma)} style={{ fontSize: 16 }}>{fmtPct(d.pair_sigma_pct, 1, false)}</span>
              <span>PAIR CORRELATION (60D)</span><span>{fmtNum(d.pair_correlation, 2)}</span>
              <span>β LONG / SHORT</span><span>{fmtNum(d.beta_long, 2)} / {fmtNum(d.beta_short, 2)}</span>
              <span>BETA-ADJ NET÷GROSS</span><span className={d.beta_net_gross >= 0.3 ? 'down' : 'up'}>{fmtPct((d.beta_net_gross ?? NaN) * 100, 0, false)}</span>
              <span>20D SPREAD PCTL</span><span className={d.entry_blocked ? 'down' : 'up'}>{fmtNum(d.spread_percentile_20d, 0)}</span>
              <span>ENTRY</span><span className={d.entry_blocked ? 'down' : 'up'}>{d.verdict.entry}</span>
            </div>
            <LineChart height={200} lines={[{ name: 'log(L/S) spread', data: d.spread.map((p: any) => ({ time: ts(p.date), value: p.v })), color: '#ffa028' }]} />
            <LineChart height={140} lines={[{ name: 'Pair Sigma (21D, %)', data: d.sigma_series.map((p: any) => ({ time: ts(p.date), value: p.v })), color: '#59e3ff' }]} />
          </div>
          <div style={{ flex: 2, minWidth: 320 }}>
            <div className="box" style={{ margin: 6 }}>
              <h4>ペア適性の4判別基準 + A-1宣言（05.4）</h4>
              <table className="t"><tbody>{d.criteria.map((c: any) => (
                <tr key={c.criterion}><td className={stCls(c.status)}>{c.status}</td><td className="l">{c.criterion}<div className="muted" style={{ fontSize: 10 }}>{c.detail}</div></td></tr>
              ))}</tbody></table>
            </div>
            <div className="box" style={{ margin: 6 }}>
              <h4>サブセクター別の非同期スコア（Notion 表）</h4>
              <table className="t"><tbody>{d.sector_table.map((s: any) => (
                <tr key={s.subsector}><td className="l amber">{s.subsector}</td><td>{s.score}</td><td>{s.grade}</td><td className="l muted" style={{ fontSize: 10 }}>{s.note}</td></tr>
              ))}</tbody></table>
            </div>
          </div>
        </div>
      )}
      {!d && !r.loading && <div className="note">Pair Sigma = 前日引けのペアを過去1ヶ月保有した想定の年率ボラ（25〜30%未満、理想10%前後）。20日スプレッドが上位20%の拡大局面ではエントリーしない。</div>}
    </div>
  );
}

// ---------------------------------------------------------------- SHRT
const SHORT_FIELDS: [string, string, string][] = [
  ['valuation_percentile', '自社ヒストリカル・バリュエーション pctl', 'num'], ['growth_path', '利益成長率の推移 % (過去→予測, 例 30,20,10)', 'list'],
  ['crowding_pct', '混雑度 pctl', 'num'], ['drawdown_from_high_pct', '高値からの下落 %', 'num'], ['volume_trend', '出来高 20D/前60D', 'num'],
  ['downgrade_share', 'セルサイド格下げ比率 (0-1)', 'num'], ['longonly_selling', '主力ロングオンリーの処分売り', 'bool'],
  ['revenue_growth_pct', '売上成長率 %', 'num'], ['op_margin_pct', '営業利益率 %', 'num'], ['fcf_negative', 'FCF マイナス', 'bool'],
  ['industry_growth_pct', '業界成長率 %', 'num'], ['market_rank', '業界順位', 'num'], ['share_change_pp', 'シェア変化 pp', 'num'],
  ['fraud_confirmed', '粉飾が摘発・確定', 'bool'], ['winner_take_all', 'n²/2 勝者総取り業界', 'bool'], ['disruption', '降維打撃を受けている', 'bool'],
  ['cyclical', 'シクリカル', 'bool'], ['pe_percentile', 'PE 自社ヒストリカル pctl', 'num'], ['cycle_stage', 'サイクル段階 (peak/other)', 'text'],
  ['market_cap_usd', '時価総額 USD', 'num'],
];

function ShortTab({ symbol }: { symbol: string }) {
  const [inp, setInp] = useState<Record<string, any>>({});
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState('');
  const run = async (withSym: boolean) => {
    setErr('');
    const inputs: Record<string, any> = {};
    for (const [k, , t] of SHORT_FIELDS) {
      const v = inp[k];
      if (v === undefined || v === '') continue;
      inputs[k] = t === 'num' ? parseFloat(v) : t === 'list' ? String(v).split(/[,\s]+/).filter(Boolean).map(Number) : t === 'bool' ? v === 'yes' : v;
    }
    try { setRes(await api.post<any>('/framework/short_models', { symbol: withSym ? symbol : null, inputs })); } catch (e: any) { setErr(e.message); }
  };
  useEffect(() => { setRes(null); }, [symbol]);
  return (
    <div className="trin-split">
      <div style={{ flex: 2, minWidth: 280 }}>
        <div className="toolbar">
          <button className="tb on" onClick={() => run(true)}>EVALUATE {symbol} (自動取得あり)</button>
          <button className="tb" onClick={() => run(false)}>入力値のみ</button>
        </div>
        {err && <div className="err">{err}</div>}
        <table className="t"><tbody>{SHORT_FIELDS.map(([k, l, t]) => (
          <tr key={k}><td className="l">{l}</td><td className="l">
            {t === 'bool' ? (
              <select className="inp" value={inp[k] ?? ''} onChange={(e) => setInp({ ...inp, [k]: e.target.value })}><option value="">?</option><option value="yes">YES</option><option value="no">NO</option></select>
            ) : <input className="inp" value={inp[k] ?? ''} placeholder={res?.auto?.[k] != null ? `auto ${fmtNum(res.auto[k], 2)}` : ''} onChange={(e) => setInp({ ...inp, [k]: e.target.value })} />}
          </td></tr>
        ))}</tbody></table>
        <div className="note">空欄は「不明」のまま評価（推測で埋めない）。自動取得: 高値からの下落・出来高トレンド・時価総額・売上成長・営業利益率・FCF・3.5句（SCOREから）。</div>
      </div>
      <div style={{ flex: 3, minWidth: 0 }}>
        {res && (
          <>
            {res.guards.map((g: string) => <div key={g} className="down" style={{ padding: '2px 6px' }}>⛔ {g}</div>)}
            <div className="pad">該当モデル: {res.matches.length ? <span className="down">{res.matches.join(' / ')}</span> : <span className="muted">なし</span>}</div>
            {res.models.map((m: any) => (
              <div key={m.id} className="box" style={{ margin: 6 }}>
                <h4><span className={m.status === 'MATCH' ? 'down' : m.status === 'NO' ? 'muted' : 'yellow'}>{m.status}</span> {m.name} <span className="muted">{m.met}/{m.conds.length}（不明 {m.unknown}）</span></h4>
                <table className="t"><tbody>{m.conds.map((c: any) => (
                  <tr key={c.label}><td className={c.ok === true ? 'down' : c.ok === false ? 'up' : 'muted'}>{c.ok === true ? '●' : c.ok === false ? '○' : '?'}</td><td className="l">{c.label}</td><td className="l muted">{c.value == null ? '' : JSON.stringify(c.value)}</td></tr>
                ))}</tbody></table>
              </div>
            ))}
            <div className="note">{res.note} 型の宣言: {Object.values(res.short_types).join(' / ')}</div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- CHIP
function ChipTab({ symbol }: { symbol: string }) {
  const [scope, setScope] = useState('stock');
  const [hv, setHv] = useState('');
  const [inst, setInst] = useState('');
  const r = useAsync(() => api.get<any>(`/framework/top_bottom/${encodeURIComponent(symbol)}`, { scope, holding_value: hv || undefined, inst_ownership_pct: inst || undefined }), [symbol, scope, hv, inst]);
  const d = r.data;
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">SCOPE</span>
        <select className="inp" value={scope} onChange={(e) => setScope(e.target.value)}><option value="stock">個別（1日平均10%×1か月）</option><option value="market">市場全体（70%×1か月）</option></select>
        <span className="lbl">保有金額</span><input className="inp num" style={{ width: 110 }} value={hv} onChange={(e) => setHv(e.target.value)} placeholder="混雑度用" />
        <span className="lbl">機関保有 %</span><input className="inp num" value={inst} onChange={(e) => setInst(e.target.value)} />
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <>
          <div className="pad" style={{ fontSize: 16 }}><span className="yellow">{d.zone}</span> <span className="muted">· 回転率pctl {fmtNum(d.turnover_percentile, 0)} · 浮動株 {fmtBig(d.shares)} · 配当 {fmtPct(d.dividend_yield_pct, 2, false)} vs {d.risk_free.symbol} {fmtNum(d.risk_free.value, 3)}</span></div>
          <div className="trin-split">
            {[['天井シグナル', d.top], ['底シグナル', d.bottom]].map(([t, rows]: any) => (
              <div key={t} className="box" style={{ margin: 6, flex: 1 }}>
                <h4>{t}</h4>
                <table className="t"><tbody>{rows.map((s: any) => (
                  <tr key={s.signal}><td className={s.on ? 'down' : 'muted'}>{s.on ? 'ON' : '—'}</td><td className="l">{s.signal}</td><td>{typeof s.value === 'number' ? fmtNum(s.value, 2) : s.value == null ? '' : String(s.value)}</td></tr>
                ))}</tbody></table>
              </div>
            ))}
            <div className="box" style={{ margin: 6, flex: 1 }}>
              <h4>混雑度（保有金額÷1日売買代金・機関保有）</h4>
              <div className="pad">
                <div>20日平均売買代金 {fmtBig(d.adv_value)}</div>
                <div>保有日数 <span className="yellow">{fmtNum(d.crowding.days_of_volume, 1)}</span></div>
                {d.crowding.flags.map((f: string) => <div key={f} className="down">• {f}</div>)}
                <div className={d.crowding.crowded ? 'down' : 'up'}>{d.crowding.crowded ? 'CROWDED' : 'not crowded (入力ベース)'}</div>
                {d.margin && <div className="muted">信用倍率 {fmtNum(d.margin.ratio, 2)}（{d.margin.date}）pctl {fmtNum(d.margin.ratio_percentile, 0)} · 買残/出来高 {fmtNum(d.margin.buy_days, 1)}日</div>}
              </div>
            </div>
          </div>
          {d.turnover.length > 0 && <LineChart height={160} lines={[{ name: 'daily turnover % (volume / float)', data: d.turnover.map((p: any) => ({ time: p.time, value: p.v })), color: '#ffd84a' }]} />}
          <div className="note">{d.note} {d.scan_error ? `（浮動株・配当の取得失敗: ${d.scan_error}）` : ''} 閾値の解釈（個別=1日平均、市場=月合計）は docs/FRAMEWORK.md 参照。</div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- GATE
function GateTab() {
  const meta = useMeta();
  const r = useAsync(() => api.get<any>('/framework/ideas'), []);
  const [sel, setSel] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const ideas: any[] = r.data?.ideas || [];
  const idea = ideas.find((i) => i.id === sel) || ideas[0];
  const save = async (i: any) => { await api.post('/framework/ideas', i); r.reload(); };
  const answer = (gid: string, k: number, v: string) => idea && save({ ...idea, answers: { ...idea.answers, [`${gid}:${k}`]: v }, progress: undefined });
  return (
    <div className="trin-split">
      <div style={{ flex: 1, minWidth: 220 }}>
        <div className="toolbar">
          <input className="inp" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="アイデア / テーマ" />
          <button className="tb" disabled={!title} onClick={async () => { await save({ title }); setTitle(''); }}>+ ADD</button>
        </div>
        <table className="t"><tbody>{ideas.map((i) => (
          <tr key={i.id} className={idea?.id === i.id ? 'sel' : ''} onClick={() => setSel(i.id)} style={{ cursor: 'pointer' }}>
            <td className="l amber">{i.title}</td>
            <td className={i.progress.position_ok ? 'up' : 'yellow'}>{i.progress.position_ok ? 'OK' : (i.progress.blocked_at || '').slice(0, 2)}</td>
            <td><button className="tb" onClick={async (e) => { e.stopPropagation(); await api.del(`/framework/ideas/${i.id}`); r.reload(); }}>✕</button></td>
          </tr>
        ))}</tbody></table>
        <div className="box" style={{ margin: 6 }}>
          <h4>⑤ 毎月ゼロから作り直す</h4>
          <div className="pad">
            <button className="tb" onClick={async () => { if (confirm('今月のチェック結果をアーカイブし、全回答をリセットしますか？')) { await api.post('/framework/ideas/monthly_reset', {}); r.reload(); } }}>MONTHLY RESET ({r.data?.month})</button>
            <div className="muted">archive: {(r.data?.archive_months || []).join(', ') || '—'}</div>
          </div>
        </div>
      </div>
      <div style={{ flex: 3, minWidth: 0 }}>
        {!idea && <div className="note">アイデアを追加すると、05.6 の関門 ①〜⑤ と四半期点検 Ⅰ〜Ⅳ を1項目ずつ通過させられます。全項目が「YES/NA」になって初めてポジション成立。</div>}
        {idea && meta.data && [...meta.data.gates, ...meta.data.quarterly].map((g: any) => {
          const pg = idea.progress.gates.find((x: any) => x.id === g.id);
          return (
            <div key={g.id} className="box" style={{ margin: 6 }}>
              <h4><span className={stCls(pg?.status)}>{pg?.status}</span> {g.title} <span className="muted">{pg?.yes}/{pg?.total}</span></h4>
              <table className="t"><tbody>{g.items.map((it: string, k: number) => {
                const v = idea.answers[`${g.id}:${k}`];
                return (
                  <tr key={k}>
                    <td style={{ whiteSpace: 'nowrap' }}>{['yes', 'no', 'na'].map((o) => <button key={o} className={`tb ${v === o ? 'on' : ''}`} onClick={() => answer(g.id, k, o)}>{o.toUpperCase()}</button>)}</td>
                    <td className={`l ${v === 'no' ? 'down' : v ? '' : 'muted'}`}>{it}</td>
                  </tr>
                );
              })}</tbody></table>
            </div>
          );
        })}
        {idea && <div className="note">{idea.progress.note}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- GLQ (also embedded in MACRO)
const QCOL: Record<number, string> = { 1: '#1a8f3a', 2: '#c98a00', 3: '#c2181b', 4: '#2b4c8c' };

export function GLQuad({ gl }: { gl: any }) {
  const pts: any[] = gl.trail;
  const lim = Math.max(2, ...pts.map((p) => Math.max(Math.abs(p.growth), Math.abs(p.liquidity)))) * 1.1;
  const X = (v: number) => 150 + (v / lim) * 140;
  const Y = (v: number) => 150 - (v / lim) * 140;
  const close = pts.slice(-gl.closeup_days);
  return (
    <svg viewBox="0 0 300 300" className="glq">
      <rect x={150} y={10} width={140} height={140} fill={QCOL[1]} opacity={0.15} />
      <rect x={150} y={150} width={140} height={140} fill={QCOL[2]} opacity={0.15} />
      <rect x={10} y={150} width={140} height={140} fill={QCOL[3]} opacity={0.15} />
      <rect x={10} y={10} width={140} height={140} fill={QCOL[4]} opacity={0.15} />
      <line x1={10} x2={290} y1={150} y2={150} stroke="#444" /><line y1={10} y2={290} x1={150} x2={150} stroke="#444" />
      {[1, 2, 3, 4].map((q) => {
        const pos = { 1: [220, 24], 2: [220, 284], 3: [80, 284], 4: [80, 24] }[q]!;
        return <text key={q} x={pos[0]} y={pos[1]} fill="#bbb" fontSize={9} textAnchor="middle">{gl.quadrants[q].name}</text>;
      })}
      <text x={292} y={146} fill="#777" fontSize={8} textAnchor="end">成長 加速 →</text>
      <text x={154} y={18} fill="#777" fontSize={8}>↑ 流動性 緩和</text>
      <polyline fill="none" stroke="#666" strokeWidth={1} points={pts.map((p) => `${X(p.growth)},${Y(p.liquidity)}`).join(' ')} />
      <polyline fill="none" stroke="#ffa028" strokeWidth={1.8} points={close.map((p) => `${X(p.growth)},${Y(p.liquidity)}`).join(' ')} />
      {pts.length > 0 && <circle cx={X(pts[pts.length - 1].growth)} cy={Y(pts[pts.length - 1].liquidity)} r={5} fill="#ffd84a" />}
      {pts.length > 0 && <circle cx={X(pts[0].growth)} cy={Y(pts[0].liquidity)} r={3} fill="#666" />}
    </svg>
  );
}

export function GLPanel({ gl }: { gl: any }) {
  const qs = Object.keys(gl.fwd_returns || {}).map(Number).sort();
  const assets = Object.keys(gl.assets || {});
  return (
    <div className="trin-split">
      <div style={{ flex: '0 0 320px' }}><GLQuad gl={gl} /></div>
      <div style={{ flex: 1, minWidth: 260 }}>
        <div className="pad" style={{ fontSize: 16 }}>
          現在地 <span style={{ color: QCOL[gl.current.q] }}>■</span> <span className="yellow">{gl.current.name}</span>
          <span className="muted"> （{gl.current.liq_label} × {gl.current.growth_label}）{gl.current.date}</span>
        </div>
        <div className="pad">優位: <span className="amber">{gl.current.assets}</span></div>
        <div className="pad">回転: <span className={gl.rotation.startsWith('時計') ? 'up' : 'yellow'}>{gl.rotation}</span> → 次: <span className="yellow">{gl.next.name}</span>（優位: {gl.next.assets}）</div>
        <div className="pad muted">growth z {fmtNum(gl.current.growth, 2)} · liquidity z {fmtNum(gl.current.liquidity, 2)} — 灰線 6ヶ月軌跡 / 橙 直近3ヶ月</div>
        <table className="t">
          <thead><tr><th className="l">COMPONENT</th><th>sign</th><th>last z</th></tr></thead>
          <tbody>{['growth', 'liquidity'].flatMap((ax) => gl.inputs[ax].map((c: any) => (
            <tr key={ax + c.label}><td className="l">{ax} · {c.label}</td><td>{c.sign > 0 ? '+' : '−'}</td><td>{fmtNum(c.last_z, 2)}</td></tr>
          )))}</tbody>
        </table>
      </div>
      {qs.length > 0 && (
        <div style={{ flexBasis: '100%' }}>
          <table className="t">
            <thead><tr><th className="l">翌1ヶ月リターン（象限別）</th>{assets.map((a) => <th key={a}>{a}</th>)}</tr></thead>
            <tbody>{qs.map((q) => (
              <tr key={q} className={q === gl.current.q ? 'sel' : ''}>
                <td className="l" style={{ color: QCOL[q] }}>{gl.quadrants[q].name} <span className="muted">n={gl.occupancy[q]}d</span></td>
                {assets.map((a) => { const s = gl.fwd_returns[q]?.[a]; return <td key={a} className={s ? (s.mean > 0 ? 'up' : 'down') : 'muted'} title={s ? `hit ${s.hit.toFixed(0)}% n=${s.n}` : ''}>{s ? fmtPct(s.mean, 1) : '--'}</td>; })}
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <div className="note" style={{ flexBasis: '100%' }}>{gl.note}</div>
    </div>
  );
}

export function GLQ() {
  const [source, setSource] = useState('');
  const [w, setW] = useState<WindowValue>({ length: 63, offset: 0 });
  const r = useAsync(() => api.get<any>('/macro/growth_liquidity', { source: source || undefined, horizon: w.length, end_offset: w.offset }), [source, w.length, w.offset]);
  const gl = r.data;
  const occ = useMemo(() => gl, [gl]);
  return (
    <div>
      <div className="toolbar">
        <span className="lbl">SOURCE</span>
        <select className="inp" value={source} onChange={(e) => setSource(e.target.value)}>{['', 'tradingview', 'yahoo', 'sim'].map((s) => <option key={s} value={s}>{s || '(active)'}</option>)}</select>
        <button className="tb" onClick={r.reload}>REFRESH</button>
        <span className="muted">4 ボトミング → 1 回復 → 2 ピーキング → 3 スローダウン（時計回り）</span>
      </div>
      <WindowSlider label="変化の期間" value={w} onChange={setW} min={20} max={252} maxOffset={1000} asof={gl?.asof} />
      {r.loading && <Loading />}
      <ErrorBox error={r.error || gl?.error} />
      {occ && !occ.error && <GLPanel gl={occ} />}
      <StatQuadrants />
    </div>
  );
}

/** The same quadrant computed from macro statistics (ECST composites) — next to the market-proxy version above. */
function StatQuadrants() {
  const d = useAsync(() => api.get<any>('/econ/dashboard'), []);
  const cs = d.data?.countries || {};
  const rows = ['WORLD', 'US', 'JP', 'EA', 'CN', 'UK'].filter((c) => cs[c]?.quadrant?.available);
  if (!rows.length) return <div className="note">統計版（ECST の合成指数による成長×流動性）は、マクロ統計を取得すると表示されます（ECST → ⟳ 更新）。</div>;
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>統計版の成長 × 流動性（ECST：実際の経済統計の合成指数）</h4>
      <table className="t nowrap" style={{ fontSize: 11 }}><tbody>{rows.map((c) => {
        const q = cs[c].quadrant;
        return <tr key={c}><td className="l">{c === 'WORLD' ? '世界（米欧日中）' : d.data.country_names[c]}</td><td className="yellow">{q.current.name}</td><td className="muted">→ {q.next.name}</td><td className="muted">{q.rotation}</td>
          <td className="muted">成長 {q.current.growth.toFixed(2)} · 流動性 {q.current.liquidity.toFixed(2)}（{q.current.month}）</td></tr>;
      })}</tbody></table>
      <div className="note" style={{ fontSize: 10 }}>上の図は市場データの代理指標、この表は経済統計（生産・雇用・物価・マネー・信用・金融環境など）の合成。食い違うときは、市場が統計を先取りしているか、統計が遅れているかを考える。</div>
    </div>
  );
}
