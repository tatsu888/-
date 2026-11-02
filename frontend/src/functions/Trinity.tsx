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

export const TRIN_TABS = ['MAP', 'SCORE', 'KELLY', 'RULE', 'PAIR', 'SHRT', 'CHIP', 'GATE', 'GLQ'] as const;
type Tab = (typeof TRIN_TABS)[number];
const TAB_LABEL: Record<Tab, string> = {
  MAP: '三位一体', SCORE: '評点表', KELLY: 'ケリー', RULE: '六層規律', PAIR: 'ペア', SHRT: '空売り8', CHIP: '天井/底', GATE: '関門', GLQ: '成長×流動性',
};
const ts = (d: string) => Math.floor(Date.parse(d) / 1000);
const stCls = (s: string) => (s === 'PASS' ? 'up' : s === 'FAIL' ? 'down' : s === 'WARN' ? 'yellow' : 'muted');
const dirCls = (d?: string) => (d === 'LONG' ? 'up' : d === 'SHORT' ? 'down' : 'yellow');

function useMeta() {
  return useAsync(() => api.get<any>('/framework/meta'), []);
}

export function TRIN({ symbol, tab: initial, onPick }: { symbol: string; tab?: string; onPick?: (s: string) => void }) {
  const [tab, setTab] = useState<Tab>((TRIN_TABS as readonly string[]).includes(initial || '') ? (initial as Tab) : 'MAP');
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
  const [pw, setPw] = useState(0.6);
  const [xw, setXw] = useState(30);
  const [xl, setXl] = useState(15);
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
  const r = useAsync(() => (q ? api.post<any>('/framework/pair', q) : Promise.resolve(null)), [q]);
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
      </div>
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
  const r = useAsync(() => api.get<any>('/macro/growth_liquidity', { source: source || undefined }), [source]);
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
      {r.loading && <Loading />}
      <ErrorBox error={r.error || gl?.error} />
      {occ && !occ.error && <GLPanel gl={occ} />}
    </div>
  );
}
