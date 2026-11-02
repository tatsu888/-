// ALIGN / CHECK / EVAL — the Trinity as an analysis tool (TRIN tabs; backend trinity_eval.py, docs/FRAMEWORK.md §12).
//   ALIGN  where every AUTO name stands against 「三方向から同じ結論に着いたときだけ確信度を上げてよい」 + the arbitration rules
//   CHECK  a proposed order through gates ①–④, the six-layer discipline and the book
//   EVAL   past AUTO verdicts graded by forward market-relative returns + backtests of the price-reproducible layers
import { useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, fmtPct } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

const ST_COL: Record<string, string> = {
  ALIGN3: '#2fd17a', ALIGN2: '#7dd87d', F_ONLY: '#aaaaaa', CONF_M: '#ffa028', CONF_L: '#ffd84a', CONF_ML: '#ff4545', NO_F_ML: '#59e3ff', NONE: '#555555',
};
const stCls = (s: string) => (s === 'PASS' ? 'up' : s === 'FAIL' ? 'down' : s === 'WARN' ? 'yellow' : 'muted');
const VERDICT_CLS: Record<string, string> = { 発注可: 'up', 条件付きで可: 'yellow', 未確認の項目あり: 'amber', 見送り: 'down' };

// ---------------------------------------------------------------- ALIGN
export function AlignTab({ go }: { go: (tab: string, sym?: string) => void }) {
  const r = useAsync(() => api.get<any>('/trinity/align'), []);
  const d = r.data;
  if (r.loading && !d) return <Loading />;
  if (r.error) return <ErrorBox error={r.error} />;
  if (!d) return null;
  const cols = ['逆風', '中立', '順風'];
  const rowsL = ['順風', '中立', '逆風'];
  const cell = (side: string, li: number, mi: number) => {
    const xs = d.grid[side][li][mi] as any[];
    const best = li === 0 && mi === 2;
    const worst = li === 2 && mi === 0;
    return (
      <td key={mi} style={{ verticalAlign: 'top', minWidth: 160, background: best ? 'rgba(47,209,122,0.15)' : worst ? 'rgba(255,69,69,0.12)' : mi === 0 || li === 2 ? 'rgba(255,160,40,0.06)' : undefined }}>
        {xs.map((x) => (
          <div key={x.symbol} style={{ cursor: 'pointer' }} onClick={() => go('CHECK', x.symbol)} title="CHECK で発注前チェック">
            <span className="amber">{x.symbol.split(':')[1]}</span> <span className="muted">{(x.name || '').slice(0, 10)}</span> c{x.conviction}{x.size_pct ? ` ${fmtNum(x.size_pct, 1)}%` : ''}
          </div>
        ))}
      </td>
    );
  };
  return (
    <div className="pad">
      <div className="muted" style={{ fontSize: 11 }}>
        AUTO {d.generated_at?.replace('T', ' ').slice(0, 16)}　象限 <span className="amber">{d.quadrant?.name || '—'}</span>{d.next_quadrant ? ` → 次 ${d.next_quadrant.name}` : ''}
        　ブックのうち一致（三位・二位）{d.book.aligned_share != null ? fmtPct(d.book.aligned_share * 100, 0, false) : '—'}（{fmtNum(d.book.aligned_pct, 1)}% / グロス {fmtNum(d.book.gross_pct, 1)}%）・衝突 {fmtNum(d.book.conflict_pct, 1)}%
      </div>
      <div className="brief-grid">
        {(['LONG', 'SHORT'] as const).map((side) => (
          <div key={side} className="box">
            <h4>F が {side === 'LONG' ? 'ロング' : 'ショート'} の銘柄 — 縦：需給、横：マクロ（F から見て）</h4>
            <table className="t" style={{ fontSize: 11 }}>
              <thead><tr><th className="l">需給 ＼ マクロ</th>{cols.map((c) => <th key={c} className="l">{c}</th>)}</tr></thead>
              <tbody>{rowsL.map((lab, li) => <tr key={lab}><td className="l muted">{lab}</td>{[0, 1, 2].map((mi) => cell(side, li, mi))}</tr>)}</tbody>
            </table>
            <div className="muted" style={{ fontSize: 10 }}>右上＝三位一致（確信度 3）。左列＝マクロ逆風 → ペアで持つ。下段＝需給逆向き → エントリーを待つ。銘柄をクリックで CHECK。</div>
          </div>
        ))}
      </div>
      <table className="t nowrap" style={{ fontSize: 11 }}>
        <thead><tr><th className="l">状態</th><th>銘柄数</th><th>サイズ計</th><th className="l">どうするか</th><th className="l">銘柄</th></tr></thead>
        <tbody>{d.states.filter((s: any) => s.n).map((s: any) => (
          <tr key={s.id}><td className="l" style={{ color: ST_COL[s.id] }}>{s.label}</td><td>{s.n}</td><td>{fmtNum(s.size_pct, 1)}%</td>
            <td className="l muted">{s.hint}</td><td className="l">{s.symbols.slice(0, 12).map((x: string) => x.split(':')[1]).join(' ')}{s.symbols.length > 12 ? ' …' : ''}</td></tr>
        ))}</tbody>
      </table>
      <div className="box" style={{ marginTop: 6 }}>
        <h4>裁定ルールが当たる銘柄</h4>
        <table className="t nowrap" style={{ fontSize: 11 }}><tbody>{d.rows.filter((x: any) => x.rules.length).map((x: any) => (
          <tr key={x.symbol}><td className="l amber" style={{ cursor: 'pointer' }} onClick={() => go('CHECK', x.symbol)}>{x.symbol}</td>
            <td className="l" style={{ color: ST_COL[x.state] }}>{x.state_label}</td><td className="l">{x.rules.join(' ／ ')}</td></tr>
        ))}</tbody></table>
      </div>
      {d.candidates.length > 0 && (
        <div className="box" style={{ marginTop: 6 }}>
          <h4 style={{ color: ST_COL.NO_F_ML }}>F なし・マクロと需給が一致 — 評点表をつける候補</h4>
          <div className="pad" style={{ fontSize: 11 }}>{d.candidates.map((x: any) => (
            <span key={x.symbol} style={{ marginRight: 12, cursor: 'pointer' }} onClick={() => go('SCORE', x.symbol)}>
              <span className="amber">{x.symbol}</span> {x.m > 0 ? '▲ロング方向' : '▼ショート方向'}（{x.m_reason}・{x.l_zone}）
            </span>
          ))}</div>
        </div>
      )}
      {d.changes.length > 0 && (
        <div className="box" style={{ marginTop: 6 }}>
          <h4>前日からの変化</h4>
          <div className="pad" style={{ fontSize: 11 }}>{d.changes.map((c: any) => <div key={c.symbol}><span className="amber">{c.symbol}</span> {c.from} → <b>{c.to}</b></div>)}</div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- CHECK
export function CheckTab({ symbol }: { symbol: string }) {
  const { toast } = useTerminal();
  const [f, setF] = useState<any>({ symbol, side: 'LONG', weight: '2', pair_with: '', short_type: '', expected_downside_pct: '', pw: '', xw: '', xl: '' });
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const num = (v: string) => (v === '' || !isFinite(+v) ? null : +v);
  const run = async () => {
    setBusy(true);
    try {
      setRes(await api.post<any>('/trinity/check', {
        symbol: f.symbol, side: f.side, weight: num(f.weight), pair_with: f.pair_with || null, short_type: f.short_type || null,
        expected_downside_pct: num(f.expected_downside_pct), pw: num(f.pw) != null ? num(f.pw)! / 100 : null,
        xw: num(f.xw) != null ? num(f.xw)! / 100 : null, xl: num(f.xl) != null ? num(f.xl)! / 100 : null,
      }));
    } catch (e: any) { toast(e.message); } finally { setBusy(false); }
  };
  const inp = (k: string, w = 90, ph = '') => <input className="inp" style={{ width: w }} value={f[k]} placeholder={ph} onChange={(e) => setF({ ...f, [k]: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && run()} />;
  return (
    <div className="pad">
      <div className="toolbar" style={{ flexWrap: 'wrap' }}>
        <span className="lbl">銘柄</span>{inp('symbol', 110)}
        <select className="inp" value={f.side} onChange={(e) => setF({ ...f, side: e.target.value })}><option>LONG</option><option>SHORT</option></select>
        <span className="lbl">サイズ（% NAV）</span>{inp('weight', 60)}
        <span className="lbl">ペアの相手</span>{inp('pair_with', 110, 'TSE:8035')}
        {f.side === 'SHORT' && <>
          <select className="inp" value={f.short_type} onChange={(e) => setF({ ...f, short_type: e.target.value })}>
            <option value="">ショートの型</option><option value="alpha">① アルファ</option><option value="catalyst">② 短期カタリスト</option><option value="pair_leg">③ ペア相方</option><option value="funding">④ Funding</option>
          </select>
          {f.short_type === 'alpha' && <><span className="lbl">下落見込み %</span>{inp('expected_downside_pct', 50)}</>}
        </>}
        <span className="lbl" title="任意。勝率・勝ったとき・負けたとき（%）">ケリー PW/XW/XL %</span>{inp('pw', 44, '60')}{inp('xw', 44, '30')}{inp('xl', 44, '15')}
        <button className="tb" disabled={busy} onClick={run}>判定</button>
      </div>
      {busy && <Loading />}
      {res && (
        <>
          <div className="pad" style={{ fontSize: 18 }}>
            <span className={VERDICT_CLS[res.verdict] || ''}>{res.verdict}</span>
            <span className="muted" style={{ fontSize: 12 }}>　{res.symbol} {res.side} {fmtNum(res.weight, 2)}%{res.blocked_at ? ` — ${res.blocked_at}で止まる` : ''}
              {res.auto_row ? `　AUTO: ${res.auto_row.direction} c${res.auto_row.conviction}${res.auto_row.mini ? '（この銘柄だけ計算）' : ''}` : '　AUTO の判定なし'}</span>
          </div>
          <div className="brief-grid">
            {res.gates.map((g: any) => (
              <div key={g.id} className="box">
                <h4>{g.title} <span className={stCls(g.status)}>{g.status}</span></h4>
                <div className="pad" style={{ fontSize: 11 }}>{g.items.map((i: any, k: number) => (
                  <div key={k}><span className={stCls(i.status)} style={{ display: 'inline-block', width: 40 }}>{i.status}</span> {i.text}</div>
                ))}</div>
              </div>
            ))}
          </div>
          <div className="muted" style={{ fontSize: 11 }}>
            発注後のブック：グロス {fmtNum(res.book_after.gross, 1)}%・ネット {fmtNum(res.book_after.net, 1)}%・{res.book_after.names} 銘柄・{res.book_after.pairs} ペア
            {res.book_before ? `（前：グロス ${fmtNum(res.book_before.gross, 1)}%・ネット ${fmtNum(res.book_before.net, 1)}%）` : ''}
            {res.kelly ? `　ケリー：E ${fmtNum(res.kelly.e, 4)}・F ${fmtNum(res.kelly.f_pct, 1)}%・推奨 ${fmtNum(res.kelly.recommended_pct, 2)}%` : ''}
            {res.pair && !res.pair.error ? `　ペア：Pair Sigma ${fmtNum(res.pair.pair_sigma_pct, 1)}%・相関 ${fmtNum(res.pair.pair_correlation, 2)}` : ''}
          </div>
        </>
      )}
      <div className="note">関門の判定は AUTO の F・マクロ・需給、保存した評点表（SCORE）、RULE のブック（セクター・ネットなど）、ペアの価格から。①〜④に FAIL があれば見送り、未確認（OPEN）が残れば確認してから。</div>
    </div>
  );
}

// ---------------------------------------------------------------- EVAL
function StatRow({ k, s, label }: { k: string; s: any; label?: string }) {
  if (!s || !s.n) return <tr><td className="l">{label || k}</td><td colSpan={5} className="muted">—</td></tr>;
  return (
    <tr><td className="l">{label || k}</td><td>{s.n}</td>
      <td className={s.mean_pct >= 0 ? 'up' : 'down'}>{fmtPct(s.mean_pct, 2)}</td>
      <td>{fmtPct(s.hit * 100, 0, false)}</td>
      <td className="muted">{fmtPct(s.hit_lo * 100, 0, false)}〜{fmtPct(s.hit_hi * 100, 0, false)}</td>
      <td className={s.t != null && Math.abs(s.t) >= 2 ? 'yellow' : 'muted'}>{fmtNum(s.t, 1)}</td></tr>
  );
}
const HEAD = <thead><tr><th className="l">区分</th><th>n</th><th>平均（超過・方向込み）</th><th>勝率</th><th>勝率の 90% 区間</th><th>t</th></tr></thead>;
const STATE_LBL: Record<string, string> = { ALIGN3: '三位一致', ALIGN2: '二位一致', F_ONLY: 'F のみ', CONF_M: 'マクロと衝突', CONF_L: '需給と衝突', CONF_ML: '両方と衝突' };

export function EvalTab() {
  const [h, setH] = useState('21');
  const [n, setN] = useState(0);
  const r = useAsync(() => api.get<any>('/trinity/eval', { horizons: '5,21,63', refresh: n > 0 || undefined }), [n]);
  const d = r.data;
  const a = d?.auto?.horizons?.[h];
  const m = d?.m?.horizons?.[h === '5' ? '21' : h];
  const l = d?.l?.horizons?.[h === '5' ? '21' : h];
  return (
    <div className="pad">
      <div className="toolbar">
        <span className="lbl">何日後で測るか</span>
        {['5', '21', '63'].map((x) => <button key={x} className={`tb mini ${h === x ? 'on' : ''}`} onClick={() => setH(x)}>{x} 日</button>)}
        <button className="tb mini" onClick={() => setN(n + 1)}>⟳ 計算し直す</button>
        {d?.source === 'sim' && <span className="badge demo">DEMO</span>}
      </div>
      {r.loading && <Loading what="AUTO の履歴と過去の価格で計算中" />}
      <ErrorBox error={r.error} />
      {d && (
        <>
          <div className="box">
            <h4>A. AUTO の判定の答え合わせ（{d.auto?.from || '—'} → {d.auto?.to || '—'}、スナップショット {d.auto?.snapshots ?? 0}）</h4>
            {!a ? <div className="note">{d.auto?.note || 'まだ評価できる判定がない'}</div> : (
              <>
                <div className="pad" style={{ fontSize: 13 }}>{a.verdict ? <span className="yellow">{a.verdict}</span> : <span className="muted">確信度 1 と 3 がそれぞれ 20 件そろうまで結論を出さない</span>}
                  <span className="muted" style={{ fontSize: 11 }}>　使った日 {a.dates_used}（{h} 日以上離して重なりなし）・結果待ち {a.pending}</span></div>
                <table className="t nowrap" style={{ fontSize: 11 }}>{HEAD}<tbody>
                  <StatRow k="ALL" s={a.stats.ALL} label="全体" />
                  {[3, 2, 1].map((c) => <StatRow key={c} k={`c${c}`} s={a.stats[`c${c}`]} label={`確信度 ${c}`} />)}
                  {Object.keys(STATE_LBL).map((st) => <StatRow key={st} k={st} s={a.stats[`state:${st}`]} label={`　${STATE_LBL[st]}`} />)}
                  <StatRow k="src:SCORE" s={a.stats['src:SCORE']} label="評点表（人）" />
                  <StatRow k="src:RULE" s={a.stats['src:RULE']} label="ルール採点" />
                  <StatRow k="dir:LONG" s={a.stats['dir:LONG']} label="ロング" />
                  <StatRow k="dir:SHORT" s={a.stats['dir:SHORT']} label="ショート" />
                </tbody></table>
              </>
            )}
          </div>
          <div className="box" style={{ marginTop: 6 }}>
            <h4>B. マクロ層の過去検証 — 成長×流動性の象限で優位なセクター − 逆風のセクター（TOPIX-17、{d.m?.from || '—'} → {d.m?.to || '—'}）</h4>
            {d.m?.error ? <div className="note">{d.m.error}</div> : m && (
              <table className="t nowrap" style={{ fontSize: 11 }}>{HEAD}<tbody>
                <StatRow k="spread" s={m.spread} label="優位 − 逆風（毎月）" />
                <StatRow k="+1" s={m.by_view['+1']} label="　優位なセクター（対 TOPIX）" />
                <StatRow k="-1" s={m.by_view['-1']} label="　逆風のセクター（対 TOPIX）" />
                {Object.entries(m.by_quadrant).map(([q, s]: any) => <StatRow key={q} k={q} s={s} label={`　象限 ${q} のとき`} />)}
              </tbody></table>
            )}
          </div>
          <div className="box" style={{ marginTop: 6 }}>
            <h4>C. 需給層の過去検証 — 天井寄り／底寄りのその後（ユニバース {d.l?.universe ?? '—'} 銘柄、観測 {d.l?.observations ?? 0}）</h4>
            {d.l?.error ? <div className="note">{d.l.error}</div> : l && (
              <table className="t nowrap" style={{ fontSize: 11 }}>{HEAD}<tbody>
                <StatRow k="signed" s={l.signed} label="判定の向きに張った場合" />
                {['底寄り', '中間帯', '天井寄り'].map((z) => <StatRow key={z} k={z} s={l.by_zone[z]} label={`　${z}（対市場）`} />)}
                <StatRow k="crowded" s={l.crowded} label="　混雑（対市場）" />
              </tbody></table>
            )}
          </div>
          <ul className="note">{(d.notes || []).map((x: string) => <li key={x}>{x}</li>)}</ul>
        </>
      )}
    </div>
  );
}
