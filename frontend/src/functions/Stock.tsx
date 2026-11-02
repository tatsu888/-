// STK — the individual stock page: everything about one stock in one place.
//   株価の要因分解: 個社要因 vs マーケット・セクター・スタイル・マクロ（betas estimated before the window; sliders)
//   信用残（JPX 週次）・需給・三位一体・決算／書き起こし・ファイル（Excel・レポート）・同業
// FCTR — macro side: which factors are strong (Notion 04.4: style / macro / sector factor returns).
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, fmtPct } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { WindowSlider, type WindowValue } from '../components/WindowSlider';
import { useTerminal } from '../ctx';
import { NewsList } from './Info';

const ts = (d: string) => Math.floor(Date.parse(d) / 1000);
const dirCls = (d?: string) => (d === 'LONG' ? 'up' : d === 'SHORT' ? 'down' : 'muted');
const GROUP_COL: Record<string, string> = { マーケット: '#5ea9ff', セクター: '#ffa028', スタイル: '#a98bff', マクロ: '#59e3ff', 個社要因: '#2fd17a' };

function Attribution({ symbol }: { symbol: string }) {
  const { run } = useTerminal();
  const [w, setW] = useState<WindowValue>({ length: 21, offset: 0 });
  const [est, setEst] = useState(252);
  const r = useAsync(() => api.get<any>(`/factors/attribution/${encodeURIComponent(symbol)}`, { window: w.length, end_offset: w.offset, est }), [symbol, w.length, w.offset, est]);
  const d = r.data;
  const parts = d ? [...Object.entries(d.groups_pct), ['個社要因', d.specific_pct]] as [string, number][] : [];
  const maxAbs = Math.max(0.5, ...parts.map(([, v]) => Math.abs(v)), Math.abs(d?.total_pct || 0));
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>株価の要因分解 — 個社要因か、ファクター・スタイルか <button className="tb mini" onClick={() => run('FEXP', symbol)}>FEXP で詳しく（為替・スタイル・セクター）</button></h4>
      <WindowSlider label="窓" value={w} onChange={setW} min={5} max={252} maxOffset={500} asof={d?.to} />
      <div className="toolbar"><span className="lbl">β 推定期間</span>
        <select className="inp" value={est} onChange={(e) => setEst(+e.target.value)}>{[126, 252, 504].map((x) => <option key={x} value={x}>{x}日（窓の前）</option>)}</select>
        {d && <span className="muted">{d.from} → {d.to}（推定 {d.est_from} → {d.est_to}、R² {fmtNum(d.r2_est, 2)}）</span>}
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <>
          <div className="pad" style={{ fontSize: 16 }}>
            窓のリターン <span className={d.total_pct >= 0 ? 'up' : 'down'}>{fmtPct(d.total_pct, 2)}</span> → <span className="yellow">{d.verdict}</span>
            <span className="muted">（ファクターで説明できた割合 {fmtPct((d.factor_share ?? 0) * 100, 0, false)}）</span>
          </div>
          <table className="t">
            <tbody>{parts.map(([k, v]) => (
              <tr key={k}><td className="l" style={{ color: GROUP_COL[k] || '#ddd', width: 90 }}>{k}</td>
                <td style={{ width: 70 }} className={v >= 0 ? 'up' : 'down'}>{fmtPct(v, 2)}</td>
                <td className="l"><div className="hbar2"><span style={{ left: v >= 0 ? '50%' : `${50 - (Math.abs(v) / maxAbs) * 50}%`, width: `${(Math.abs(v) / maxAbs) * 50}%`, background: GROUP_COL[k] || '#888' }} /></div></td></tr>
            ))}</tbody>
          </table>
          <LineChart height={170} lines={[
            { name: '株価（累積）', data: d.series.map((p: any) => ({ time: ts(p.date), value: p.total })), color: '#ffffff' },
            { name: 'ファクター寄与', data: d.series.map((p: any) => ({ time: ts(p.date), value: p.factor })), color: '#a98bff' },
            { name: '個社要因', data: d.series.map((p: any) => ({ time: ts(p.date), value: p.specific })), color: '#2fd17a' },
          ]} />
          <table className="t nowrap">
            <thead><tr><th className="l">FACTOR</th><th className="l">GROUP</th><th>β</th><th>t</th><th>寄与</th></tr></thead>
            <tbody>{d.factors.map((f: any) => (
              <tr key={f.factor}><td className="l amber">{f.factor}</td><td className="l" style={{ color: GROUP_COL[f.group] }}>{f.group}</td>
                <td>{fmtNum(f.beta, 3)}</td><td className={Math.abs(f.t) >= 2 ? 'yellow' : 'muted'}>{fmtNum(f.t, 1)}</td>
                <td className={f.contribution_pct >= 0 ? 'up' : 'down'}>{fmtPct(f.contribution_pct, 2)}</td></tr>
            ))}</tbody>
          </table>
          <div className="note">{d.note} 判定: ファクターで説明できた割合 ≥ 60% → ファクター・スタイル主導、≤ 35% → 個社要因主導。スタイルはカバレッジから作った Notion のスタイル・ファクター（FCTR）。</div>
        </>
      )}
    </div>
  );
}

function Margin({ m, symbol }: { m: any; symbol: string }) {
  const { run } = useTerminal();
  if (m === undefined) return null;
  if (!m) return (
    <div className="box" style={{ margin: 6 }}><h4>信用残（JPX 週次）</h4>
      <div className="pad muted">データなし — <button className="tb" onClick={() => run('MRGN', symbol)}>MRGN</button> で JPX の銘柄別信用取引週末残高を取り込む</div></div>
  );
  const L = m.latest || {};
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>信用残（JPX 週次）— {L.date}</h4>
      <div className="kv" style={{ gridTemplateColumns: 'repeat(2, max-content 1fr)' }}>
        <span>信用倍率</span><span className="amber" style={{ fontSize: 16 }}>{fmtNum(L.ratio, 2)} <span className="muted">（自己の過去 {m.weeks} 週で {fmtNum(m.ratio_percentile, 0)} pctl）</span></span>
        <span>買残 / 売残</span><span>{fmtNum(L.long, 0)} / {fmtNum(L.short, 0)}</span>
        <span>前週比</span><span><span className={L.long_chg > 0 ? 'down' : 'up'}>買 {fmtNum(L.long_chg, 0)}</span> · <span className={L.short_chg > 0 ? 'up' : 'down'}>売 {fmtNum(L.short_chg, 0)}</span></span>
        <span>買残 ÷ 20日出来高</span><span className={m.buy_days >= 5 ? 'down' : ''}>{fmtNum(m.buy_days, 1)} 日 <span className="muted">（売残 {fmtNum(m.sell_days, 1)} 日）</span></span>
        {m.ratio_change_vs_fwd4w && <><span>倍率変化 vs 4週後</span><span>相関 {fmtNum(m.ratio_change_vs_fwd4w.corr, 2)}（n={m.ratio_change_vs_fwd4w.n}）</span></>}
      </div>
      {m.rows?.length > 2 && <LineChart height={130} lines={[{ name: '信用倍率', data: m.rows.filter((x: any) => x.ratio != null).map((x: any) => ({ time: ts(x.date), value: x.ratio })), color: '#ffd84a' }]} />}
      <div className="note">信用倍率 = 買残 ÷ 売残。上位の倍率・買残の日数が大きい = 将来の売り圧力（天井シグナルの一つ）。ランキングは MRGN。</div>
    </div>
  );
}


const CHECK_PRE = ['会社計画・コンセンサスの確認', '注目点（数量・ASP・マージン）を書く', '前回からの変化点'];
const CHECK_POST = ['結果 vs 予想（サプライズ）', 'ガイダンスの変化', '株価の反応（翌日）', '評点表（SCORE）を更新'];
const stateCls = (s?: string) => (s === '決算待ち' ? 'yellow' : s === '期中' ? 'amber' : 'muted');

/** Quarter pages of one company — the terminal's earnings calendar is the system of record (not Notion). */
function Quarters({ ticker, symbol }: { ticker: string; symbol: string }) {
  const { toast, run } = useTerminal();
  const r = useAsync(() => api.get<any>(`/earnings/${ticker}`), [ticker]);
  const [view, setView] = useState<any>(null);   // latest server response (PUT returns the company view)
  const [sel, setSel] = useState<string | null>(null);
  const [pin, setPin] = useState('');
  const [notes, setNotes] = useState<string | null>(null);
  const [fye, setFye] = useState('');
  const [all, setAll] = useState(false);
  const rx = useAsync(() => api.get<any>(`/earnings/${ticker}/reactions`), [ticker]);
  useEffect(() => { if (rx.data?.detected_now > 0) { setView(null); r.reload(); } }, [rx.data]);   // dates were detected
  const d = view ?? r.data;
  const qs: any[] = d?.quarters || [];
  const q = qs.find((x) => x.id === (sel || d?.next?.id)) || qs.find((x) => x.state === '期中') || qs[qs.length - 1];
  const call = async (fn: () => Promise<any>) => { try { setView(await fn()); } catch (e: any) { toast(e.message); } };
  const put = (body: any) => call(() => api.put(`/earnings/${ticker}/${q.id}`, body));
  const patch = (fields: any) => setView({ ...d, quarters: qs.map((x) => (x.id === q.id ? { ...x, ...fields } : x)) });
  const chk = q?.checklist || {};
  const qe = q?.earnings || {};
  const idx = q ? qs.indexOf(q) : 0;
  const shown = all ? qs : qs.filter((_, i) => Math.abs(i - idx) <= 4);
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>四半期ページ（決算カレンダー — 正本はターミナル）</h4>
      {r.loading && !d && <Loading />}
      <ErrorBox error={r.error} />
      {d && !qs.length && <div className="pad muted">四半期がまだない — COV の「決算日を更新」で作成（決算期末月が必要）</div>}
      {d && (
        <div className="pad muted" style={{ fontSize: 11 }}>
          決算期末 <span className="amber">{d.company?.fye_month ?? '—'}月</span>（{d.company?.fye_source || '不明'}）· FY 表記 {d.convention === 'end' ? '決算期の年（標準）' : 'ATLAS（開始年+1）'}
          <span style={{ marginLeft: 6, whiteSpace: 'nowrap' }}>
            <input className="inp num" style={{ width: 36 }} value={fye} placeholder="月" onChange={(e) => setFye(e.target.value.replace(/[^0-9]/g, ''))} />
            <button className="tb mini" disabled={!fye} onClick={() => call(() => api.put(`/earnings/${ticker}/fye`, { month: +fye })).then(() => setFye(''))}>決算期末月を修正</button>
          </span>
        </div>
      )}
      {q && (
        <div className="pad" style={{ borderBottom: '1px solid #222' }}>
          <div><span className="amber" style={{ fontSize: 14 }}>{q.label}</span> <span>{q.label_ja}</span> <span className={stateCls(q.state)}>［{q.state}］</span></div>
          <div className="muted" style={{ fontSize: 11 }}>期間 {q.period_start} 〜 {q.period_end}</div>
          <div>決算発表 <span className={qe.status === '推定' ? 'muted' : ''}>{qe.date || '—'}</span> {qe.status ? <span className={`badge st-${qe.status}`}>{qe.status}</span> : null} <span className="muted" style={{ fontSize: 11 }}>{qe.source || ''}</span></div>
          {(q.candidates || []).length > 0 && <div className="muted" style={{ fontSize: 10 }}>候補: {q.candidates.map((c: any) => `${c.date} ${c.status}（${c.source}）`).join(' / ')}</div>}
          {(() => { const x = (rx.data?.rows || []).find((y: any) => y.id === q.id && y.r1 != null); return x ? (
            <div>決算時の反応 {!rx.data?.real ? <span className="badge demo">DEMO</span> : null} <span className={x.r1 >= 0 ? 'up' : 'down'}>{fmtPct(x.r1 * 100, 1)}</span>{x.x1 != null ? <> （対市場 <span className={x.x1 >= 0 ? 'up' : 'down'}>{fmtPct(x.x1 * 100, 1)}</span>）</> : null}
              <span className="muted" style={{ fontSize: 11 }}> · 反応日 {x.reaction_day}（{x.timing}）· 出来高 {fmtNum(x.vol_ratio, 1)} 倍{x.drift != null ? ` · その後 4 日 ${fmtPct(x.drift * 100, 1)}` : ''}</span></div>) : null; })()}
          {q.notes_conflict && <div className="yellow" style={{ fontSize: 11 }}>⚠ notes.md と競合: ファイル側の内容を {q.notes_conflict} に保存した（四半期フォルダ内）。確認してメモを保存すると解消</div>}
          <div className="toolbar">
            <input className="inp" type="date" value={pin} onChange={(e) => setPin(e.target.value)} />
            <button className="tb mini" disabled={!pin} onClick={() => put({ earnings_date: pin }).then(() => setPin(''))}>手入力で固定</button>
            {qe.status === '手入力' && <button className="tb mini" onClick={() => put({ earnings_date: '' })}>固定を解除</button>}
            <button className="tb mini" onClick={async () => { try { const x = await api.post<any>(`/earnings/${ticker}/${q.id}/folder`, {}); toast(x.path); } catch (e: any) { toast(e.message); } }}title="<銘柄フォルダ>/quarters/<期>/ を作って開く。notes.md はこのページのメモと双方向に同期">📁 四半期フォルダ</button>
          </div>
          <div className="trin-split" style={{ fontSize: 11 }}>
            {([['決算前', CHECK_PRE], ['決算後', CHECK_POST]] as const).map(([t, items]) => (
              <div key={t} style={{ flex: 1 }}><div className="muted">{t}</div>
                {items.map((it) => (
                  <label key={it} style={{ display: 'block', cursor: 'pointer' }}>
                    <input type="checkbox" checked={!!chk[it]} onChange={(e) => { const next = { ...chk, [it]: e.target.checked }; patch({ checklist: next }); put({ checklist: next }); }} /> {it}
                  </label>
                ))}
              </div>
            ))}
          </div>
          <textarea className="inp" style={{ width: '100%', height: 64, marginTop: 4, boxSizing: 'border-box' }} value={notes ?? q.notes ?? ''}
            placeholder="この四半期のメモ（注目点・結果・ガイダンス）" onChange={(e) => setNotes(e.target.value)} />
          <button className="tb mini" disabled={notes === null || notes === (q.notes ?? '')} onClick={() => put({ notes }).then(() => setNotes(null))}>メモを保存</button>
          {notes !== null && notes !== (q.notes ?? '') && <span className="yellow" style={{ fontSize: 10 }}> 未保存</span>}
          <Docs ticker={ticker} symbol={symbol} qid={q.id} onTxt={() => run('TXT', symbol)} />
        </div>
      )}
      {qs.length > 0 && (
        <>
          <table className="t nowrap" style={{ fontSize: 11 }}><tbody>{[...shown].reverse().map((x) => {
            const e = x.earnings || {};
            return (
              <tr key={x.id} className={q?.id === x.id ? 'sel' : ''} style={{ cursor: 'pointer' }} title={x.label_ja}
                onClick={() => { setSel(x.id); setNotes(null); setPin(''); }}>
                <td className="l amber">{x.label}</td>
                <td className={`l ${stateCls(x.state)}`}>{x.state}</td>
                <td className={e.status === '推定' ? 'muted' : ''}>{e.date || ''}</td>
                <td className="l">{e.status ? <span className={`badge st-${e.status}`}>{e.status}</span> : null}{x.notes ? ' ✎' : ''}</td>
              </tr>
            );
          })}</tbody></table>
          <div className="pad"><button className="tb mini" onClick={() => setAll(!all)}>{all ? '前後 4 四半期だけ' : `すべて表示（${qs.length}）`}</button></div>
        </>
      )}
      <Reactions rx={rx} onPick={(id) => { setSel(id); setNotes(null); setPin(''); }} />
    </div>
  );
}

/** Files in the quarter folder (短信・資料・書き起こし…): open, or import a text transcript into TXT. */
function Docs({ ticker, symbol, qid, onTxt }: { ticker: string; symbol: string; qid: string; onTxt: () => void }) {
  const { toast } = useTerminal();
  const f = useAsync(() => api.get<any>(`/earnings/${ticker}/${qid}/files`), [ticker, qid]);
  const files: any[] = f.data?.files || [];
  const post = async (path: string, name: string, ok: (x: any) => void) => { try { ok(await api.post<any>(`/earnings/${ticker}/${qid}/files/${path}`, { name })); } catch (e: any) { toast(e.message); } };
  if (!f.data?.exists) return <div className="muted" style={{ fontSize: 10, marginTop: 4 }}>資料: 四半期フォルダを作ると、置いたファイル（短信・資料・書き起こし）がここに出る</div>;
  return (
    <div style={{ marginTop: 4, fontSize: 11 }}>
      <span className="muted">資料（四半期フォルダ）</span> <button className="tb mini" onClick={() => f.reload()}>⟳</button>
      {!files.length && <span className="muted"> まだない — {symbol} の四半期フォルダに置く</span>}
      {files.map((x) => (
        <div key={x.name}>
          <button className="tb mini" onClick={() => post('open', x.name, (y) => toast(y.opened ? `開く: ${y.path}` : y.path))}>開く</button>{' '}
          {x.name} <span className="muted">{x.size >= 1e6 ? `${(x.size / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(x.size / 1e3))} KB`}</span>
          {x.text && <> <button className="tb mini" title="説明会の書き起こしとして TXT に取り込み（トーン・前の期からの言葉の変化・回避度）" onClick={() => post('transcript', x.name, (y) => toast(`TXT に取り込み: ${y.period}（${y.chars} 文字、${y.encoding}）`))}>書き起こしとして取り込む</button> <button className="tb mini" onClick={onTxt}>TXT</button></>}
        </div>
      ))}
    </div>
  );
}

/** 決算時の株価反応 — reaction day, market-adjusted move, drift; past dates detected from volume when unknown. */
function Reactions({ rx, onPick }: { rx: { data?: any; error?: string; loading: boolean }; onPick: (id: string) => void }) {
  const x = rx.data;
  const s = x?.summary || {};
  const rows: any[] = [...(x?.rows || [])].reverse();
  return (
    <div style={{ borderTop: '1px solid #222' }}>
      <div className="pad"><span className="amber">決算時の株価反応</span> {x && !x.real ? <span className="badge demo">DEMO</span> : null}
        {x && <span className="muted" style={{ fontSize: 10 }}> {x.symbol} · 市場 {x.market ? x.market_symbol : 'なし'} · {x.provider}{!x.real ? '（SIM の価格。検出した日付は保存しない）' : ''}</span>}</div>
      {rx.loading && !x && <Loading />}
      {rx.error && <div className="pad muted" style={{ fontSize: 11 }}>価格を取得できない: {rx.error}</div>}
      {s.n > 0 && (
        <div className="pad" style={{ fontSize: 11 }}>
          通常の値動き（{s.basis}、過去 {s.n} 回）: <span className="yellow">平均 ±{fmtNum(s.avg_abs * 100, 1)}%</span>（中央値 ±{fmtNum(s.median_abs * 100, 1)}%、最大 ±{fmtNum(s.max_abs * 100, 1)}%）
          · 上昇 {s.up} / 下落 {s.down}
          {s.drift_follow != null && <> · その後 4 日 <span className={s.drift_follow >= 0 ? 'up' : 'down'}>{s.drift_follow >= 0 ? '継続' : '反転'} {fmtPct(s.drift_follow * 100, 1)}</span></>}
          {s.detected > 0 && <span className="muted"> · うち {s.detected} 回は出来高から検出した日付</span>}
        </div>
      )}
      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
        <table className="t nowrap" style={{ fontSize: 11 }}>
          <thead><tr><th className="l">期</th><th>発表</th><th>反応日</th><th>反応</th><th>対市場</th><th>5日</th><th>その後</th><th>出来高</th><th className="l">日付</th></tr></thead>
          <tbody>{rows.map((y) => (
            <tr key={y.id} style={{ cursor: 'pointer' }} onClick={() => onPick(y.id)} title={y.timing || ''}>
              <td className="l amber">{y.label}</td><td>{y.announce}</td><td>{y.reaction_day || '—'}</td>
              <td className={(y.r1 ?? 0) >= 0 ? 'up' : 'down'}>{y.r1 != null ? fmtPct(y.r1 * 100, 1) : ''}</td>
              <td className={(y.x1 ?? 0) >= 0 ? 'up' : 'down'}>{y.x1 != null ? fmtPct(y.x1 * 100, 1) : ''}</td>
              <td className={(y.x5 ?? y.r5 ?? 0) >= 0 ? 'up' : 'down'}>{(y.x5 ?? y.r5) != null ? fmtPct((y.x5 ?? y.r5) * 100, 1) : ''}</td>
              <td className={(y.drift ?? 0) >= 0 ? 'up' : 'down'}>{y.drift != null ? fmtPct(y.drift * 100, 1) : ''}</td>
              <td>{y.vol_ratio != null ? `${fmtNum(y.vol_ratio, 1)}×` : ''}</td>
              <td className="l">{y.kind === '検出' ? <span className="badge st-検出">検出</span> : y.kind === '検出できず' ? <span className="muted">検出できず</span> : <span className="muted">{y.status}</span>}</td>
            </tr>
          ))}</tbody>
        </table>
        </div>
      )}
      <div className="note" style={{ fontSize: 10 }}>反応日：発表日が分かっている期は、当日と翌営業日のうち出来高の急増が大きい方（はっきりしなければ引け後と仮定）。日付が推定の期は、推定日 ±10 日で出来高が 20 日中央値の 2 倍以上の日を反応日とし、その前営業日を発表日とみなす（「検出」。実データのときだけカレンダーに保存）。</div>
    </div>
  );
}

/** News and filings of one stock: EDINET / EDGAR filings, feed items that mention it, Google News. */
function StockInfo({ symbol }: { symbol: string }) {
  const { run } = useTerminal();
  const r = useAsync(() => api.get<any>(`/info/stock/${encodeURIComponent(symbol)}`), [symbol]);
  const d = r.data;
  const hot = (k: string) => ['大量保有', '自己株買い', '公開買付'].includes(k);
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>ニュース・開示 <button className="tb mini" onClick={() => run('TOP')}>TOP</button></h4>
      {r.loading && !d && <Loading />}
      {r.error && <div className="pad muted" style={{ fontSize: 11 }}>{r.error}</div>}
      {d && (
        <div className="pad" style={{ fontSize: 11 }}>
          <div className="muted">開示（EDINET）</div>
          {d.filings.length ? d.filings.slice(0, 8).map((x: any) => (
            <div key={x.doc_id}>• <span className="muted">{(x.at || x.date).slice(0, 10)}</span> <span className={hot(x.kind) ? 'yellow' : ''}>{x.kind}</span> {x.desc}
              <span className="muted"> {x.filer}</span> <a className="tb mini" href={x.pdf} target="_blank" rel="noreferrer">PDF</a></div>
          )) : <div className="muted">— （EDINET の API キーを TOP → 7) KEYS に入れると自動で取得）</div>}
          {d.edgar?.length > 0 && <><div className="muted" style={{ marginTop: 4 }}>開示（SEC EDGAR）</div>
            {d.edgar.slice(0, 6).map((x: any, i: number) => <div key={i}>• <span className="muted">{x.date}</span> {x.form} {x.kind} {x.url && <a className="tb mini" href={x.url} target="_blank" rel="noreferrer">開く</a>}</div>)}</>}
          {d.items.length > 0 && <><div className="muted" style={{ marginTop: 4 }}>フィードの言及</div>
            {d.items.slice(0, 6).map((x: any) => <div key={x.guid}>• <a href={x.link} target="_blank" rel="noreferrer">{x.title}</a> <span className="muted">{x.feed_name}</span></div>)}</>}
          <div className="muted" style={{ marginTop: 4 }}>ニュース（Google ニュース「{d.news_q}」）</div>
          {d.news_error ? <div className="muted">取得できない: {d.news_error}</div> : <NewsList rows={(d.news || []).slice(0, 8)} />}
        </div>
      )}
    </div>
  );
}

export function STK({ symbol }: { symbol: string }) {
  const { run, toast } = useTerminal();
  const r = useAsync(() => api.get<any>(`/stock/${encodeURIComponent(symbol)}/page`), [symbol]);
  const [rep, setRep] = useState<any>(null);
  const d = r.data;
  const cv = d?.coverage;
  const e = d?.earnings || {};
  const a = d?.auto;
  const call = async (fn: () => Promise<any>, ok: (x: any) => void) => { try { ok(await fn()); r.reload(); } catch (ex: any) { toast(ex.message); } };
  return (
    <div>
      <div className="toolbar">
        <span className="amber" style={{ fontSize: 15 }}>{symbol}</span>
        <span style={{ fontSize: 14 }}>{cv?.name || ''}</span>
        <span className="muted">{cv ? `${cv.gics_group || ''} ／ ${cv.gics_sub || ''} · ${cv.fye_month ? cv.fye_month + '月決算' : ''}` : 'カバレッジ外'}</span>
        <button className="tb" onClick={() => run('GP', symbol)}>GP</button>
        <button className="tb" onClick={() => run('XLS', symbol)}>XLS</button>
        {cv && <>
          <button className="tb" onClick={() => call(() => api.post(`/coverage/${cv.ticker}/excel`, {}), (y) => toast(y.created ? `作成: ${y.created}` : `Excel: ${y.file?.name}`))}>Excel</button>
          <button className="tb" onClick={() => call(() => api.post(`/coverage/${cv.ticker}/open_folder`, {}), (y) => toast(y.path))}>📁</button>
          <button className="tb" disabled={!d?.page} onClick={() => d?.page && window.open(d.page.url, '_blank', 'noopener')}>Notion</button>
          <button className="tb on" onClick={() => call(() => api.post(`/coverage/${cv.ticker}/report`, { save: true }), (y) => setRep(y))}>REPORT</button>
        </>}
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <div className="trin-split">
          <div style={{ flex: 3, minWidth: 480 }}>
            {d.chart && <LineChart height={160} lines={[{ name: symbol, data: d.chart, color: '#ffa028' }]} />}
            <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
              {['1W', '1M', '3M', '1Y'].flatMap((k) => [<span key={k + 'l'}>{k}</span>, <span key={k} className={(d.perf?.[k] ?? 0) >= 0 ? 'up' : 'down'}>{fmtPct(d.perf?.[k], 1)}</span>])}
            </div>
            <Attribution symbol={symbol} />
            <Margin m={d.margin} symbol={symbol} />
          </div>
          <div style={{ flex: 2, minWidth: 300 }}>
            <div className="box" style={{ margin: 6 }}>
              <h4>三位一体（AUTO {d.auto_at ? d.auto_at.slice(5, 16).replace('T', ' ') : '—'}）</h4>
              {a ? (
                <div className="pad">
                  <div><span className={dirCls(a.direction)} style={{ fontSize: 16 }}>{a.direction}</span> 確信 {a.conviction}/3 · サイズ {fmtPct(a.size_pct, 2, false)}</div>
                  <div className="muted">F {fmtNum(a.f.score, 2)}（{a.f.source}）· M {a.m.reason} · 需給 {a.l.zone}</div>
                  {a.sector_rrg && <div className="muted">セクター {a.sector_rrg.label}: {a.sector_rrg.quadrant}</div>}
                  {a.xray && <div className="muted">個別固有の分散比率 {fmtPct(a.xray.idio * 100, 0, false)}</div>}
                  {a.flags.map((f: string) => <div key={f} className="yellow" style={{ fontSize: 11 }}>• {f}</div>)}
                </div>
              ) : <div className="pad muted">AUTO の対象外、または未実行</div>}
              {d.score && <div className="pad">評点 <span className={dirCls(d.score.direction)}>{fmtNum(d.score.total, 2)} {d.score.direction}</span> <span className="muted">（前回 {fmtNum(d.score.prev_total, 2)}、3.5句 {fmtNum(d.score.moat, 1)}）</span> <button className="tb mini" onClick={() => run('SCORE', symbol)}>SCORE</button></div>}
              {d.themes?.length > 0 && <div className="pad">テーマ: {d.themes.join('、')}</div>}
            </div>
            <div className="box" style={{ margin: 6 }}>
              <h4>需給（天井／底・混雑）</h4>
              {d.chip ? <div className="pad">
                <div className="yellow">{d.chip.zone}</div>
                {[...(d.chip.top || []), ...(d.chip.bottom || [])].filter((s: any) => s.on).map((s: any) => <div key={s.signal} style={{ fontSize: 11 }}>• {s.signal}</div>)}
                {d.chip.crowding?.days_of_volume != null && <div className="muted">保有日数 {fmtNum(d.chip.crowding.days_of_volume, 1)}</div>}
              </div> : <div className="pad muted">—</div>}
            </div>
            {cv && <Quarters key={cv.ticker} ticker={cv.ticker} symbol={symbol} />}
            <StockInfo symbol={symbol} />
            <div className="box" style={{ margin: 6 }}>
              <h4>決算・書き起こし</h4>
              <div className="pad">
                <div>次回 <span className={e.days != null && e.days <= 14 ? 'yellow' : ''}>{e.next || '—'}</span> {e.next_title || ''} {e.next_status ? <span className={`badge st-${e.next_status}`}>{e.next_status}</span> : null} {e.days != null ? <span className="muted">（あと {e.days} 日）</span> : null}</div>
                <div className="muted">前回 {e.last || '—'} {e.last_title || ''}</div>
                {d.transcript ? <div>TXT {d.transcript.period}: tone {fmtNum(d.transcript.net_tone, 2)} · 言語変化 {fmtNum(d.transcript.change_score, 3)} · 回避度 {fmtNum(d.transcript.evasiveness, 2)} <button className="tb mini" onClick={() => run('TXT', symbol)}>TXT</button></div>
                  : <div className="muted">書き起こしなし <button className="tb mini" onClick={() => run('TXT', symbol)}>TXT</button></div>}
              </div>
            </div>
            <div className="box" style={{ margin: 6 }}>
              <h4>ファイル</h4>
              <div className="pad">
                {d.folder && <div className="muted" style={{ fontSize: 10 }}>{d.folder}</div>}
                {d.excel.map((f: any) => <div key={f.id}><button className="tb mini" onClick={() => run('XLS', symbol)}>XLS</button> {f.name} <span className="muted">{f.link}</span></div>)}
                {!d.excel.length && <div className="muted">Excel なし（Excel ボタンでモデルを作成）</div>}
                {d.reports.map((n: string) => <div key={n}><button className="tb mini" onClick={() => call(() => api.get(`/stock/${encodeURIComponent(symbol)}/report_file`, { name: n }), setRep)}>開く</button> {n}</div>)}
              </div>
            </div>
            {d.peers?.length > 0 && (
              <div className="box" style={{ margin: 6 }}>
                <h4>同業（{cv?.gics_sub}）</h4>
                <table className="t nowrap"><tbody>{d.peers.map((p: any) => (
                  <tr key={p.symbol} style={{ cursor: 'pointer' }} onClick={() => run('STK', p.symbol)}><td className="l amber">{p.ticker}</td><td className="l">{p.name}</td>
                    <td className={dirCls(p.direction)}>{p.direction ? `${p.direction[0]}${p.conviction}` : ''}</td><td>{fmtNum(p.f, 2)}</td><td className={(p.mom_3m ?? 0) >= 0 ? 'up' : 'down'}>{fmtPct(p.mom_3m, 1)}</td></tr>
                ))}</tbody></table>
              </div>
            )}
            {rep && (
              <div className="box" style={{ margin: 6 }}>
                <h4>{rep.title || rep.name} <button className="tb mini" onClick={() => setRep(null)}>✕</button></h4>
                <pre className="report-md">{rep.markdown}</pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function FCTR() {
  const [w, setW] = useState<WindowValue>({ length: 21, offset: 0 });
  const [busy, setBusy] = useState(false);
  const r = useAsync(() => api.get<any>('/factors/library', { end_offset: w.offset }), [w.offset]);
  const d = r.data;
  const col = w.length <= 5 ? '1W' : w.length <= 21 ? '1M' : w.length <= 63 ? '3M' : '6M';
  const rows: any[] = d ? [...d.rows].sort((a, b) => (b[col] ?? -1e9) - (a[col] ?? -1e9)) : [];
  const maxAbs = Math.max(0.5, ...rows.map((x) => Math.abs(x[col] ?? 0)));
  return (
    <div>
      <div className="toolbar">
        <button className="tb" disabled={busy} onClick={async () => { setBusy(true); try { await api.post('/factors/build', {}); r.reload(); } catch (e: any) { alert(e.message); } setBusy(false); }}>{busy ? 'BUILDING…' : '⟳ スタイル・ファクターを再計算'}</button>
        <span className="muted">スタイル: {d?.library?.generated_at ? `${d.library.generated_at.replace('T', ' ')} · ${d.library.universe} 銘柄` : '未計算（AUTO 実行時に自動計算）'}</span>
      </div>
      <WindowSlider label="並べ替え" value={w} onChange={setW} min={5} max={126} maxOffset={500} asof={d?.asof} />
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <table className="t nowrap">
          <thead><tr><th className="l">GROUP</th><th className="l">FACTOR（Notion 04.4）</th><th>1D</th><th>1W</th><th>1M</th><th>3M</th><th>6M</th><th>z(20D)</th><th className="l" style={{ width: '25%' }}>{col}</th></tr></thead>
          <tbody>{rows.map((x) => (
            <tr key={x.group + x.factor}>
              <td className="l muted">{x.group}</td><td className="l amber">{x.factor}</td>
              {['1D', '1W', '1M', '3M', '6M'].map((k) => <td key={k} className={(x[k] ?? 0) >= 0 ? 'up' : 'down'}>{fmtNum(x[k], x.factor.includes('金利') ? 1 : 2)}</td>)}
              <td className={Math.abs(x.z_20d ?? 0) >= 2 ? 'yellow' : 'muted'}>{fmtNum(x.z_20d, 1)}</td>
              <td className="l"><div className="hbar2"><span style={{ left: (x[col] ?? 0) >= 0 ? '50%' : `${50 - (Math.abs(x[col] ?? 0) / maxAbs) * 50}%`, width: `${(Math.abs(x[col] ?? 0) / maxAbs) * 50}%`, background: (x[col] ?? 0) >= 0 ? '#2fd17a' : '#ff4545' }} /></div></td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <div className="note">単位: % 累積リターン（金利は bp）。スタイル = カバレッジの三分位ロング・ショート（21日ごとにリバランス）、セクター = TOPIX-17 業種 ETF − TOPIX、マクロ = 市場データ。{d?.library?.note}</div>
    </div>
  );
}
