// STK — the individual stock page: everything about one stock in one place.
//   株価の要因分解: 個社要因 vs マーケット・セクター・スタイル・マクロ（betas estimated before the window; sliders)
//   信用残（JPX 週次）・需給・三位一体・決算／書き起こし・ファイル（Excel・レポート）・同業
// FCTR — macro side: which factors are strong (Notion 04.4: style / macro / sector factor returns).
import { useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, fmtPct } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { WindowSlider, type WindowValue } from '../components/WindowSlider';
import { useTerminal } from '../ctx';

const ts = (d: string) => Math.floor(Date.parse(d) / 1000);
const dirCls = (d?: string) => (d === 'LONG' ? 'up' : d === 'SHORT' ? 'down' : 'muted');
const GROUP_COL: Record<string, string> = { マーケット: '#5ea9ff', セクター: '#ffa028', スタイル: '#a98bff', マクロ: '#59e3ff', 個社要因: '#2fd17a' };

function Attribution({ symbol }: { symbol: string }) {
  const [w, setW] = useState<WindowValue>({ length: 21, offset: 0 });
  const [est, setEst] = useState(252);
  const r = useAsync(() => api.get<any>(`/factors/attribution/${encodeURIComponent(symbol)}`, { window: w.length, end_offset: w.offset, est }), [symbol, w.length, w.offset, est]);
  const d = r.data;
  const parts = d ? [...Object.entries(d.groups_pct), ['個社要因', d.specific_pct]] as [string, number][] : [];
  const maxAbs = Math.max(0.5, ...parts.map(([, v]) => Math.abs(v)), Math.abs(d?.total_pct || 0));
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>株価の要因分解 — 個社要因か、ファクター・スタイルか</h4>
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

export function STK({ symbol }: { symbol: string }) {
  const { run, toast } = useTerminal();
  const r = useAsync(() => api.get<any>(`/stock/${encodeURIComponent(symbol)}/page`), [symbol]);
  const [rep, setRep] = useState<any>(null);
  const d = r.data;
  const cv = d?.coverage;
  const e = cv?.earnings || {};
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
            <div className="box" style={{ margin: 6 }}>
              <h4>決算・書き起こし</h4>
              <div className="pad">
                <div>次回 <span className={e.days != null && e.days <= 14 ? 'yellow' : ''}>{e.next || '—'}</span> {e.next_title || ''} {e.days != null ? <span className="muted">（あと {e.days} 日）</span> : null}</div>
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
