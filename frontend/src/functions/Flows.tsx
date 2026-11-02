// FLOW — global money flows: asset class / country / sector / style factor (ETF footprints + recorded creations).
import { useState } from 'react';
import { api } from '../lib/api';
import { fmtBig, fmtNum, fmtPct } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { WindowSlider, type WindowValue } from '../components/WindowSlider';
import { useTerminal } from '../ctx';

const LENS_ORDER = ['ASSET', 'COUNTRY', 'SECTOR_US', 'SECTOR_JP', 'STYLE_US', 'STYLE_JP'];

export function FLOW({ args }: { args?: string }) {
  const { setSecurity, run } = useTerminal();
  const [lens, setLens] = useState((args || 'ASSET').toUpperCase());
  const [w, setW] = useState<WindowValue>({ length: 21, offset: 0 });
  const r = useAsync(() => api.get<any>('/flows', { lens, window: w.length, end_offset: w.offset }), [lens, w.length, w.offset]);
  const d = r.data;
  return (
    <div>
      <div className="toolbar">
        {LENS_ORDER.map((k) => <button key={k} className={`tb ${lens === k ? 'on' : ''}`} onClick={() => setLens(k)}>{d?.lenses?.[k] || k}</button>)}
        {d && <span className="muted">vs {d.bench} · 設定・解約の記録 {d.shares_days} 日</span>}
      </div>
      <WindowSlider label="期間" value={w} onChange={setW} min={5} max={126} maxOffset={500} asof={d?.asof} />
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {d && (
        <>
          <div className="box" style={{ margin: 6 }}>
            <h4>グローバル資金フローの読み（ルール）</h4>
            <table className="t nowrap"><tbody>{d.summary.map((s: any) => (
              <tr key={s.rule}><td className="l amber">{s.rule}</td><td className={`l ${s.reading === '拮抗' ? 'muted' : 'yellow'}`}>{s.reading}</td><td className="muted">{fmtNum(s.spread, 2)}</td></tr>
            ))}</tbody></table>
          </div>
          <table className="t nowrap">
            <thead><tr><th className="l">{d.label}</th><th>フロー</th><th className="l" style={{ width: '18%' }}>スコア（−1〜+1）</th><th>リターン</th><th>相対</th><th>売買代金比</th><th>CMF</th><th>OBV</th><th>設定・解約 1W</th><th>1M</th></tr></thead>
            <tbody>{d.rows.map((x: any) => (
              <tr key={x.symbol} style={{ cursor: 'pointer' }} onClick={() => setSecurity(x.symbol)} onDoubleClick={() => run('GP', x.symbol)}>
                <td className="l amber">{x.label} <span className="muted">{x.symbol.split(':')[1]}</span></td>
                {x.error ? <td colSpan={9} className="l muted">{x.error}</td> : (<>
                  <td className={x.flow === '流入' ? 'up' : x.flow === '流出' ? 'down' : 'muted'}>{x.flow}</td>
                  <td className="l"><div className="hbar2"><span style={{ left: x.flow_score >= 0 ? '50%' : `${50 - Math.abs(x.flow_score) * 50}%`, width: `${Math.min(1, Math.abs(x.flow_score ?? 0)) * 50}%`, background: x.flow_score >= 0 ? '#2fd17a' : '#ff4545' }} /></div></td>
                  <td className={x.ret >= 0 ? 'up' : 'down'}>{fmtPct(x.ret, 1)}</td><td className={(x.rs ?? 0) >= 0 ? 'up' : 'down'}>{fmtPct(x.rs, 1)}</td>
                  <td className={x.value_ratio >= 1.3 ? 'yellow' : ''}>{fmtNum(x.value_ratio, 2)}</td><td>{fmtNum(x.cmf, 2)}</td><td>{fmtNum(x.obv, 2)}</td>
                  <td className={(x.creations?.w1 ?? 0) >= 0 ? 'up' : 'down'}>{x.creations?.w1 != null ? fmtBig(x.creations.w1) : <span className="muted">—</span>}</td>
                  <td className={(x.creations?.m1 ?? 0) >= 0 ? 'up' : 'down'}>{x.creations?.m1 != null ? fmtBig(x.creations.m1) : <span className="muted">—</span>}</td>
                </>)}
              </tr>
            ))}</tbody>
          </table>
          <div className="note">{d.note} スコア = CMF・OBV・売買代金の急増（相対強度の向き付き）の平均。≥ 0.25 流入 / ≤ −0.25 流出。</div>
        </>
      )}
    </div>
  );
}
