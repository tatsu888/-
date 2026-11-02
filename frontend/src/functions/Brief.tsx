// BRIEF — the morning brief (rule-based, no AI): markets, macro quadrant, style factors, Trinity AUTO changes and
// ideas, earnings (today / tomorrow / this week / recent reactions), portfolio earnings risk, 信用残, data health.
// Saved as <coverage root>/_terminal/briefs/YYYY-MM-DD.md (and .json) — made automatically once a day by AUTO.
import { useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, fmtPct } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

const dirCls = (d?: string) => (d?.startsWith('LONG') ? 'up' : d?.startsWith('SHORT') ? 'down' : 'muted');
const sgn = (v: number | null | undefined) => ((v ?? 0) >= 0 ? 'up' : 'down');
const bp = (v: number | null | undefined) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(0)}bp`);

export function BRIEF() {
  const { run, toast } = useTerminal();
  const [date, setDate] = useState('');
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState<any>(null);
  const r = useAsync(() => api.get<any>(date ? `/brief/${date}` : '/brief'), [date]);
  const d = data ?? r.data;
  const b = d?.brief;
  const make = async () => {
    setBusy(true);
    try { setData(await api.post<any>('/brief/generate', {})); setDate(''); toast('朝のブリーフを作成しました'); } catch (e: any) { toast(e.message); }
    setBusy(false);
  };
  const setAuto = async (patch: any) => { try { await api.put('/brief/config', { ...d.config, ...patch }); setData(null); r.reload(); } catch (e: any) { toast(e.message); } };
  const stock = (sym: string) => run('STK', sym.includes(':') ? sym : `TSE:${sym}`);
  return (
    <div>
      <div className="toolbar">
        <span className="amber" style={{ fontSize: 14 }}>朝のブリーフ</span>
        <select className="inp" value={date || (b?.date ?? '')} onChange={(e) => { setData(null); setDate(e.target.value); }}>
          {(d?.dates || []).map((x: string) => <option key={x} value={x}>{x}</option>)}
        </select>
        <button className="tb on" disabled={busy} onClick={make}>{busy ? '作成中…' : '⟳ 今すぐ作成'}</button>
        {d?.config && <label className="muted" title="AUTO の実行のうち、この時刻以降の最初の 1 回で作成">
          <input type="checkbox" checked={!!d.config.auto} onChange={(e) => setAuto({ auto: e.target.checked })} /> 毎朝自動
          <input className="inp" style={{ width: 52, marginLeft: 4 }} defaultValue={d.config.time} onBlur={(e) => e.target.value !== d.config.time && setAuto({ time: e.target.value })} />
        </label>}
        {b?.health?.demo && <span className="badge demo">DEMO</span>}
        {b && <span className="muted" style={{ fontSize: 10 }}>作成 {b.generated_at?.replace('T', ' ')} · {b.md_path || `${d.dir}/${b.date}.md`}</span>}
      </div>
      {r.loading && !d && <Loading />}
      <ErrorBox error={r.error} />
      {d && !b && <div className="note">まだブリーフがありません。「今すぐ作成」、または AUTO（三位一体）が毎朝 {d.config?.time} 以降に作成します。</div>}
      {b && (
        <div className="brief-grid">
          <div className="box">
            <h4>市場</h4>
            <table className="t nowrap"><thead><tr><th className="l" /><th>終値</th><th>1日</th><th>1週</th><th>1か月</th></tr></thead>
              <tbody>{b.markets.map((m: any) => (
                <tr key={m.symbol} style={{ cursor: 'pointer' }} onClick={() => run('GP', m.symbol)}>
                  <td className="l">{m.label}</td>
                  {m.error ? <td colSpan={4} className="muted">{m.error}</td> : <>
                    <td>{fmtNum(m.last, 2)}</td>
                    {(['d1', 'w1', 'm1'] as const).map((k) => <td key={k} className={sgn(m[k])}>{m.kind === 'bp' ? bp(m[k]) : fmtPct(m[k], 1)}</td>)}
                  </>}
                </tr>
              ))}</tbody></table>
          </div>
          <div className="box">
            <h4>マクロ局面・ファクター</h4>
            <div className="pad">
              {b.auto.available ? <div>成長×流動性 <span className="yellow">{b.auto.quadrant?.name || '—'}</span> → 次 {b.auto.next_quadrant?.name || '—'} <button className="tb mini" onClick={() => run('GLQ')}>GLQ</button></div>
                : <div className="muted">AUTO の結果がまだない</div>}
              {Object.entries(b.auto.sectors || {}).map(([region, qs]: [string, any]) => (
                <div key={region} style={{ fontSize: 11 }}>セクター回転 {region === 'JP17' ? '日本' : '米国'}: {Object.entries(qs).map(([k, v]: [string, any]) => (
                  <span key={k} className={k === '主導' || k === '改善' ? 'up' : k === '減速' || k === '劣後' ? 'down' : ''}> {k} {v.join('・')}</span>
                ))} <button className="tb mini" onClick={() => run('RRG')}>RRG</button></div>
              ))}
              {b.factors.rows.length ? <>
                <div style={{ marginTop: 4 }}>強いスタイル（1 週）: {b.factors.best.map((f: any) => <span key={f.factor} className="up"> {f.factor} {fmtPct(f['1W'], 1)}</span>)}</div>
                <div>弱いスタイル（1 週）: {b.factors.worst.map((f: any) => <span key={f.factor} className="down"> {f.factor} {fmtPct(f['1W'], 1)}</span>)}</div>
                <button className="tb mini" onClick={() => run('FCTR')}>FCTR</button>
              </> : <div className="muted">ファクター・ライブラリが未作成（AUTO / FCTR）</div>}
            </div>
          </div>
          <div className="box">
            <h4>三位一体 AUTO {b.auto.generated_at ? `（${b.auto.generated_at.slice(5, 16).replace('T', ' ')}）` : ''}</h4>
            {b.auto.available ? (
              <div className="pad" style={{ fontSize: 11 }}>
                <div>対象 {b.auto.universe} · グロス {fmtPct(b.auto.book?.gross_pct, 1, false)} · ネット {fmtPct(b.auto.book?.net_pct, 1)} · 前日からの変化 {b.auto.n_changes} 件 <button className="tb mini" onClick={() => run('TRIN')}>TRIN</button></div>
                {b.auto.changes.slice(0, 10).map((c: any, i: number) => (
                  <div key={i} style={{ cursor: c.symbol.includes(':') ? 'pointer' : undefined }} onClick={() => c.symbol.includes(':') && stock(c.symbol)}>
                    • <span className="amber">{c.symbol}</span> {c.from || '新規'} → <span className={dirCls(c.to)}>{c.to}</span>
                  </div>
                ))}
                {(['longs', 'shorts'] as const).map((k) => b.auto[k].length > 0 && (
                  <div key={k} style={{ marginTop: 4 }}><span className={k === 'longs' ? 'up' : 'down'}>{k === 'longs' ? 'LONG' : 'SHORT'}</span>{' '}
                    {b.auto[k].map((x: any) => <span key={x.symbol} className="amber" style={{ cursor: 'pointer', marginRight: 6 }} onClick={() => stock(x.symbol)}>{x.symbol} c{x.conviction}</span>)}
                  </div>
                ))}
                {b.auto.errors?.length > 0 && <div className="muted" style={{ fontSize: 10 }}>取得できなかったもの: {b.auto.errors.join(', ')}</div>}
              </div>
            ) : <div className="pad muted">AUTO の結果がまだない</div>}
          </div>
          <div className="box">
            <h4>決算</h4>
            <div className="pad" style={{ fontSize: 11 }}>
              {([['今日', 'today'], ['明日', 'tomorrow'], ['今週（2〜7 日後）', 'week']] as const).map(([t, k]) => (
                <div key={k} style={{ marginBottom: 3 }}><span className="yellow">{t}</span>{' '}
                  {b.earnings[k].length ? b.earnings[k].map((x: any) => (
                    <span key={x.ticker + x.id} style={{ cursor: 'pointer', marginRight: 8 }} onClick={() => stock(x.ticker)} title={x.label_ja}>
                      <span className="amber">{x.ticker}</span> {x.name} {x.label} <span className={`badge st-${x.status}`}>{x.status}</span>
                      {x.typical ? <span className="muted"> ±{(x.typical * 100).toFixed(1)}%</span> : null}{x.auto ? <span className={dirCls(x.auto)}> {x.auto}</span> : null}
                    </span>
                  )) : <span className="muted">なし</span>}
                </div>
              ))}
              {b.earnings.recent.length > 0 && <div style={{ marginTop: 4 }}><span className="yellow">直近の決算と反応</span>
                {b.earnings.recent.map((x: any) => {
                  const mv = x.reaction ? (x.reaction.x1 ?? x.reaction.r1) : null;
                  return (
                    <div key={x.ticker + x.id} style={{ cursor: 'pointer' }} onClick={() => stock(x.ticker)}>
                      • <span className="amber">{x.ticker}</span> {x.name} {x.label} {x.date}
                      {mv != null ? <> <span className={sgn(mv)}>{fmtPct(mv * 100, 1)}</span>{x.reaction.vs_typical ? <span className={x.reaction.vs_typical >= 2 ? 'yellow' : 'muted'}>（通常の {x.reaction.vs_typical.toFixed(1)} 倍）</span> : null}{x.reaction.kind === '検出' ? <span className="badge st-検出">検出</span> : null}</> : <span className="muted"> 反応なし／価格なし</span>}
                    </div>
                  );
                })}</div>}
            </div>
          </div>
          <div className="box">
            <h4>ポートフォリオの決算リスク（14 日以内）</h4>
            {b.portfolio.rows.length ? (
              <>
                <table className="t nowrap" style={{ fontSize: 11 }}><thead><tr><th className="l">銘柄</th><th>決算</th><th>比率</th><th>通常の値動き</th><th>想定の振れ</th></tr></thead>
                  <tbody>{b.portfolio.rows.map((x: any) => (
                    <tr key={x.symbol} style={{ cursor: 'pointer' }} onClick={() => stock(x.symbol)}>
                      <td className="l amber">{x.symbol}</td><td>{x.date}（{x.days}日）<span className={`badge st-${x.status}`}>{x.status}</span></td>
                      <td>{fmtPct(x.weight_pct, 1, false)}</td><td>{x.typical_pct != null ? `±${x.typical_pct.toFixed(1)}%` : <span className="muted">不明</span>}</td>
                      <td className="yellow">{x.swing_pct_of_gross != null ? fmtPct(x.swing_pct_of_gross, 2, false) : '—'}</td>
                    </tr>
                  ))}</tbody></table>
                <div className="pad muted" style={{ fontSize: 10 }}>想定の振れ = グロスに占める比率 × 通常の値動き（対市場の平均絶対値）。{b.portfolio.total_swing_pct != null ? `単純合計 ${b.portfolio.total_swing_pct.toFixed(2)}%。` : ''}{b.portfolio.unknown ? `通常の値動きが分からない銘柄 ${b.portfolio.unknown}（実データで AUTO が計算）。` : ''}</div>
              </>
            ) : <div className="pad muted">14 日以内に決算のある保有銘柄なし（保有 {b.portfolio.positions}）<button className="tb mini" onClick={() => run('PORT')}>PORT</button></div>}
          </div>
          <div className="box">
            <h4>信用残（{b.margin.last_date || '未取り込み'}）</h4>
            {b.margin.rows.length ? (
              <table className="t nowrap" style={{ fontSize: 11 }}><thead><tr><th className="l">銘柄</th><th>信用倍率</th><th>前週</th><th>買残</th><th>売残</th></tr></thead>
                <tbody>{b.margin.rows.map((x: any) => (
                  <tr key={x.ticker} style={{ cursor: 'pointer' }} onClick={() => stock(x.ticker)}>
                    <td className="l"><span className="amber">{x.ticker}</span> {x.name}</td><td>{fmtNum(x.ratio, 2)}</td><td className="muted">{fmtNum(x.ratio_prev, 2)}</td>
                    <td className={sgn(x.long_chg_pct)}>{fmtPct(x.long_chg_pct, 1)}</td><td className={sgn(x.short_chg_pct)}>{fmtPct(x.short_chg_pct, 1)}</td>
                  </tr>
                ))}</tbody></table>
            ) : <div className="pad muted">信用残のデータなし <button className="tb mini" onClick={() => run('MRGN')}>MRGN で取り込む</button></div>}
          </div>
          <div className="box">
            <h4>データの状態</h4>
            <div className="pad" style={{ fontSize: 11 }}>
              {Object.entries(b.health.items || {}).map(([k, v]) => <div key={k}><span className="muted">{k}</span> {String(v)}</div>)}
              <div className="muted" style={{ fontSize: 10, marginTop: 4 }}>ルールベースで作成（AI は使っていない）。数値はターミナルのデータから。</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
