// COV — coverage list (tickers read from the Notion 銘柄マスタ): sector tree / ticker list, earnings dates from the
// terminal's own earnings calendar (JPX → TradingView → estimates; Notion is NOT the source of truth), local folders
// (sector or ticker layout; OneDrive-ready, stored relative to the root), and per-stock actions: XLS view, open/create
// Excel, open folder, open Notion page, rule-based fundamental report (→ reports/; Notion export optional).
import { useMemo, useState } from 'react';
import { api } from '../lib/api';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

const dirCls = (d?: string) => (d === 'LONG' ? 'up' : d === 'SHORT' ? 'down' : 'muted');

export function COV() {
  const { run, setSecurity, toast } = useTerminal();
  const r = useAsync(() => api.get<any>('/coverage'), []);
  const [q, setQ] = useState('');
  const [group, setGroup] = useState<'GICS' | 'TICKER' | 'EARN'>('GICS');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [pane, setPane] = useState<'' | 'SETTINGS' | 'NOTION' | 'FOLDERS' | 'LOG'>('');
  const elog = useAsync(() => (pane === 'LOG' ? api.get<any>('/earnings/log', { limit: 200 }) : Promise.resolve(null)), [pane]);
  const [plan, setPlan] = useState<any>(null);
  const [fplan, setFplan] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [opt, setOpt] = useState({ create_pages: true, update_master: true, add_properties: false, days_ahead: 60 });
  const d = r.data;
  const items: any[] = d?.items || [];
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    let xs = items.filter((x) => !s || x.ticker.toLowerCase().includes(s) || (x.name || '').toLowerCase().includes(s) || (x.gics_sub || '').toLowerCase().includes(s));
    if (group === 'TICKER') xs = [...xs].sort((a, b) => a.ticker.localeCompare(b.ticker));
    if (group === 'EARN') xs = xs.filter((x) => x.earnings?.next).sort((a, b) => a.earnings.next.localeCompare(b.earnings.next));
    return xs;
  }, [items, q, group]);
  const act = async (label: string, fn: () => Promise<any>, done?: (x: any) => void) => {
    setBusy(label); setErr('');
    try { const x = await fn(); done?.(x); r.reload(); } catch (e: any) { setErr(e.message); }
    setBusy('');
  };
  const openUrl = (u?: string) => { if (u) window.open(u, '_blank', 'noopener'); };
  let lastGroup = '';
  return (
    <div>
      <div className="toolbar">
        <button className="tb on" disabled={!!busy} onClick={() => act('SYNC', () => api.post('/coverage/sync', {}), (x) => toast(`Notion 同期: ${x.items} 銘柄、個社ページ ${x.pages}（API ${x.calls} 回）`))}>⟳ SYNC FROM NOTION</button>
        <button className="tb" disabled={!!busy || !items.length} title="JPX 決算発表予定日 → TradingView → 推定 の順に機械的に埋める（手入力は上書きしない）" onClick={() => act('EARN', () => api.post('/coverage/earnings/refresh', {}), (x) => toast(`決算日を更新: ${x.companies} 社、変更 ${x.n_changes} 件${x.errors && Object.keys(x.errors).length ? '（' + Object.keys(x.errors).join(', ') + ' 取得失敗）' : ''}`))}>決算日を更新</button>
        <label className="tb" title="JPX の決算発表予定日一覧（xlsx）を手動で取り込む" style={{ cursor: 'pointer' }}>JPX 取り込み
          <input type="file" accept=".xlsx" style={{ display: 'none' }} onChange={(ev) => { const f = ev.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append('file', f); act('JPX', () => fetch('/api/earnings/jpx/import', { method: 'POST', body: fd }).then(async (res) => { if (!res.ok) throw new Error((await res.json()).detail); return res.json(); }), (x) => toast(`JPX: ${x.records} 件取り込み、変更 ${x.n_changes} 件`)); ev.target.value = ''; }} />
        </label>
        <button className={`tb ${pane === 'LOG' ? 'on' : ''}`} onClick={() => setPane(pane === 'LOG' ? '' : 'LOG')}>決算ログ</button>
        <button className={`tb ${pane === 'FOLDERS' ? 'on' : ''}`} onClick={() => setPane(pane === 'FOLDERS' ? '' : 'FOLDERS')}>フォルダ…</button>
        <button className={`tb ${pane === 'SETTINGS' ? 'on' : ''}`} onClick={() => { setCfg({ ...(d?.config || {}), db_id: d?.db_id || '', micro_page: d?.micro_page || '' }); setPane(pane === 'SETTINGS' ? '' : 'SETTINGS'); }}>SETTINGS</button>
        <input className="inp" style={{ width: 150 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="ticker / 社名 / サブグループ" />
        {(['GICS', 'TICKER', 'EARN'] as const).map((g) => <button key={g} className={`tb ${group === g ? 'on' : ''}`} onClick={() => setGroup(g)}>{g === 'GICS' ? 'セクター別' : g === 'TICKER' ? 'ティッカー順' : '決算日順'}</button>)}
        {busy && <span className="yellow">{busy}…</span>}
      </div>
      <div className="pad muted" style={{ fontSize: 11 }}>
        {d ? <>銘柄 {items.length} · 個社ページ {d.pages_found} · 同期 {d.synced_at?.replace('T', ' ') || '—'} · Notion token {d.notion_token ? '✓' : <span className="down">未設定（.env の NOTION_TOKEN）</span>} · ルート {d.config.root_resolved}（{d.config.layout === 'sector' ? 'セクター別' : 'ティッカー別'}）</> : null}
      </div>
      {err && <div className="err">{err}</div>}
      {pane === 'SETTINGS' && cfg && (
        <div className="box" style={{ margin: 6 }}>
          <h4>SETTINGS — OneDrive に移すときはルートを変えるだけ（保存はルートからの相対パス）</h4>
          <div className="pad theme-form">
            <label>ルート・フォルダ<input className="inp" value={cfg.root || ''} onChange={(e) => setCfg({ ...cfg, root: e.target.value })} placeholder="C:\Users\you\OneDrive\Coverage" /></label>
            <label>レイアウト<select className="inp" value={cfg.layout} onChange={(e) => setCfg({ ...cfg, layout: e.target.value })}><option value="sector">セクター（GICS 産業グループ）の下に個別銘柄</option><option value="ticker">ティッカーで整理（フラット）</option></select></label>
            <label>銘柄マスタ DB ID<input className="inp" value={cfg.db_id || ''} onChange={(e) => setCfg({ ...cfg, db_id: e.target.value })} /></label>
            <label>ATLAS / MICRO ページ ID<input className="inp" value={cfg.micro_page || ''} onChange={(e) => setCfg({ ...cfg, micro_page: e.target.value })} /></label>
            <div><button className="tb on" onClick={() => act('SAVE', () => api.put('/coverage/config', cfg), () => setPane(''))}>SAVE</button> <span className="muted">トークンは画面では扱わない（.env の NOTION_TOKEN）</span></div>
            <div className="muted" style={{ marginTop: 6 }}>決算・四半期はターミナルの決算カレンダーで管理（Notion は正本ではない）。<button className="tb mini" onClick={() => setPane('NOTION')}>任意: Notion へ書き出す（非推奨）</button></div>
          </div>
        </div>
      )}
      {pane === 'NOTION' && (
        <div className="box" style={{ margin: 6 }}>
          <h4>（任意・非推奨）NOTION へ書き出す — 正本はターミナルの決算カレンダー。まず PREVIEW、確認してから APPLY</h4>
          <div className="toolbar">
            <label className="muted"><input type="checkbox" checked={opt.create_pages} onChange={(e) => setOpt({ ...opt, create_pages: e.target.checked })} /> 個社ページの下に四半期ページ（例: FY2027 3Q）を作成（既にあれば作らない）</label>
            <label className="muted"><input type="checkbox" checked={opt.update_master} onChange={(e) => setOpt({ ...opt, update_master: e.target.checked })} /> 銘柄マスタの 次回決算日／次回決算期 を更新</label>
            <label className="muted"><input type="checkbox" checked={opt.add_properties} onChange={(e) => setOpt({ ...opt, add_properties: e.target.checked })} /> プロパティが無ければ追加</label>
            <span className="lbl">対象: 今日から</span><input className="inp num" type="number" value={opt.days_ahead} onChange={(e) => setOpt({ ...opt, days_ahead: +e.target.value })} /><span className="lbl">日以内</span>
            <button className="tb" onClick={() => act('PREVIEW', () => api.post('/coverage/notion/earnings', { ...opt, apply: false }), setPlan)}>PREVIEW</button>
            <button className="tb on" disabled={!plan?.plan?.length} onClick={() => { if (confirm(`${plan.plan.length} 銘柄分を Notion に書き込みます。よろしいですか？`)) act('NOTION', () => api.post('/coverage/notion/earnings', { ...opt, apply: true }), setPlan); }}>APPLY</button>
          </div>
          {plan && (
            <table className="t nowrap"><thead><tr><th className="l">TICKER</th><th className="l">社名</th><th>決算日</th><th>日数</th><th className="l">四半期ページ</th><th className="l">ページ</th><th className="l">銘柄マスタ</th></tr></thead>
              <tbody>{plan.plan.map((p: any) => (
                <tr key={p.ticker}><td className="l amber">{p.ticker}</td><td className="l">{p.name}</td><td title={p.source || ''}>{p.date} {p.status ? <span className={`badge st-${p.status}`}>{p.status}</span> : null}</td><td>{p.days}</td><td className="l">{p.title || '—'}{p.note ? <span className="yellow" title={p.note}> ⚠ FY</span> : null}</td>
                  <td className={`l ${String(p.page_action).startsWith('created') ? 'up' : String(p.page_action).startsWith('error') ? 'down' : 'muted'}`}>{p.page_action}{p.page_url ? <a href={p.page_url} target="_blank" rel="noreferrer"> ↗</a> : null}</td>
                  <td className={`l ${p.master_action === 'updated' ? 'up' : String(p.master_action).startsWith('error') ? 'down' : 'muted'}`}>{p.master_action}</td></tr>
              ))}</tbody></table>
          )}
        </div>
      )}
      {pane === 'LOG' && (
        <div className="box" style={{ margin: 6 }}>
          <h4>決算ログ — 機械的な更新・手入力・不一致の記録</h4>
          <table className="t nowrap"><tbody>{(elog.data?.log || []).map((x: any, i: number) => (
            <tr key={i}><td className="muted">{String(x.at).slice(5, 16).replace('T', ' ')}</td><td className="l amber">{x.ticker}</td><td className="l">{x.qid || ''}</td>
              <td className={`l ${String(x.what).includes('不一致') ? 'down' : ''}`}>{x.what}</td><td className="l muted">{String(x.from)}</td><td className="l">→ {String(x.to)}</td><td className="l muted">{x.source}</td></tr>
          ))}</tbody></table>
          {!elog.data?.log?.length && <div className="note">まだ記録がありません。</div>}
        </div>
      )}
      {pane === 'FOLDERS' && (
        <div className="box" style={{ margin: 6 }}>
          <h4>フォルダ — {d?.config.root_resolved}</h4>
          <div className="toolbar">
            <span className="lbl">レイアウト</span>
            <select className="inp" value={fplan?.layout || d?.config.layout} onChange={(e) => act('PREVIEW', () => api.post('/coverage/folders', { apply: false, layout: e.target.value }), setFplan)}>
              <option value="sector">セクター/銘柄（Notion と同じ）</option><option value="ticker">ティッカー</option>
            </select>
            <button className="tb" onClick={() => act('PREVIEW', () => api.post('/coverage/folders', { apply: false, layout: fplan?.layout || d?.config.layout }), setFplan)}>PREVIEW</button>
            <button className="tb on" disabled={!fplan?.plan?.length} onClick={() => { if (confirm(`フォルダを作成・移動します（${JSON.stringify(fplan.summary)}）。よろしいですか？`)) act('FOLDERS', () => api.post('/coverage/folders', { apply: true, layout: fplan.layout }), setFplan); }}>APPLY</button>
            {fplan?.summary && <span className="muted">作成 {fplan.summary.create} · 既存を採用 {fplan.summary.adopt} · 移動 {fplan.summary.move} · OK {fplan.summary.ok}</span>}
          </div>
          {fplan && (
            <table className="t nowrap"><thead><tr><th className="l">TICKER</th><th>ACTION</th><th className="l">フォルダ（ルートからの相対）</th><th className="l">結果</th></tr></thead>
              <tbody>{fplan.plan.slice(0, 400).map((p: any) => (
                <tr key={p.ticker}><td className="l amber">{p.ticker}</td><td className={p.action === 'move' ? 'yellow' : p.action === 'create' ? 'up' : 'muted'}>{p.action}</td><td className="l">{p.rel}</td><td className="l muted">{p.result || ''}</td></tr>
              ))}</tbody></table>
          )}
          <div className="note">各銘柄フォルダに reports/ と .coverage.json（ティッカーの目印）を作成。Excel はフォルダ名のティッカーで XLS に自動で紐付く。セクター・フォルダは「GICS4530_…」（4桁コードがティッカーと誤マッチしないよう接頭辞付き）。Windows / OneDrive で使えない文字（| : * ? など）は _ に置換。</div>
        </div>
      )}
      {r.loading && !d && <Loading />}
      <ErrorBox error={r.error} />
      {d && !items.length && <div className="note">カバレッジが空です。.env に NOTION_TOKEN を設定し、銘柄マスタと ATLAS/MICRO をインテグレーションに共有してから「SYNC FROM NOTION」。</div>}
      <div className="trin-split">
        <div style={{ flex: 3, minWidth: 560, overflowX: 'auto' }}>
          <table className="t nowrap">
            <thead><tr><th className="l">TICKER</th><th className="l">ACTIONS</th><th className="l">社名</th><th>次回決算</th><th className="l">四半期</th><th>決算月</th><th>Excel</th><th>AUTO</th><th className="l">サブグループ</th></tr></thead>
            <tbody>
              {shown.map((x) => {
                const hdr = group === 'GICS' && x.gics_group !== lastGroup ? (lastGroup = x.gics_group || '', true) : false;
                const e = x.earnings || {};
                return [
                  hdr ? <tr key={'g' + x.gics_group}><td colSpan={9} className="l yellow" style={{ background: '#111' }}>{x.gics_group || '（GICS 未設定）'}</td></tr> : null,
                  <tr key={x.ticker}>
                    <td className="l amber" style={{ cursor: 'pointer' }} title="個別銘柄ページ（STK）" onClick={() => { setSecurity(x.symbol); run('STK', x.symbol); }}>{x.ticker}</td>
                    <td className="l" style={{ whiteSpace: 'nowrap' }}>
                      <button className="tb" title="XLS（ターミナル内で表示・編集）" onClick={() => run('XLS', x.symbol)}>XLS</button>
                      <button className="tb" title="Excel で開く（無ければモデルを作成）" onClick={() => act('EXCEL', () => api.post(`/coverage/${x.ticker}/excel`, {}), (y) => toast(y.created ? `作成: ${y.created}` : `Excel: ${y.file?.name}`))}>Excel</button>
                      <button className="tb" title="フォルダを開く" onClick={() => act('FOLDER', () => api.post(`/coverage/${x.ticker}/open_folder`, {}), (y) => toast(y.opened ? `開く: ${y.path}` : `フォルダ: ${y.path}`))}>📁</button>
                      <button className="tb" title="Notion の個社ページ" disabled={!x.page} onClick={() => openUrl(x.page?.url)}>N</button>
                      <button className="tb" title="ファンダメンタル・レポート（ルールベース）" onClick={() => act('REPORT', () => api.post(`/coverage/${x.ticker}/report`, { save: true, to_notion: false }), (y) => setReport({ ...y, ticker: x.ticker, hasPage: !!x.page }))}>REPORT</button>
                    </td>
                    <td className="l">{x.name}</td>
                    <td className={e.days != null && e.days >= 0 && e.days <= 14 ? 'yellow' : ''} title={e.next_source || ''}>{e.next || ''}{e.days != null ? <span className="muted"> ({e.days}d)</span> : null} {e.next_status ? <span className={`badge st-${e.next_status}`}>{e.next_status}</span> : null}</td>
                    <td className="l muted" title={e.next_label_ja || ''}>{e.next_title || ''}</td>
                    <td title={e.fye_source ? `決算期末月の出所: ${e.fye_source}${x.fye_month && e.fye_month && x.fye_month !== e.fye_month ? `（Notion は ${x.fye_month}月 — 不一致）` : ''}` : 'Notion 銘柄マスタ'}>
                      {(e.fye_month ?? x.fye_month) ? `${e.fye_month ?? x.fye_month}月${!e.fye_month && x.fye_uncertain ? '?' : ''}` : ''}
                      {x.fye_month && e.fye_month && x.fye_month !== e.fye_month ? <span className="down" style={{ fontSize: 10 }}> ≠N</span> : null}
                    </td>
                    <td>{x.excel_files || ''}</td>
                    <td className={dirCls(x.auto?.direction)}>{x.auto ? `${x.auto.direction[0]}${x.auto.conviction}` : ''}</td>
                    <td className="l muted">{x.gics_sub || ''}</td>
                  </tr>,
                ];
              })}
            </tbody>
          </table>
        </div>
        {report && (
          <div style={{ flex: 2, minWidth: 320 }}>
            <div className="box" style={{ margin: 6 }}>
              <h4>{report.title}</h4>
              <div className="toolbar">
                <button className="tb" disabled={!report.hasPage} onClick={() => act('NOTION', () => api.post(`/coverage/${report.ticker}/report`, { save: false, to_notion: true }), (y) => { setReport({ ...report, notion_url: y.notion_url }); toast('Notion に書き出しました'); })}>Notion に書き出す</button>
                {report.notion_url && <a href={report.notion_url} target="_blank" rel="noreferrer" className="up">Notion ↗</a>}
                <button className="tb" onClick={() => navigator.clipboard?.writeText(report.markdown)}>COPY</button>
                <button className="tb" onClick={() => setReport(null)}>✕</button>
              </div>
              <div className="pad muted" style={{ fontSize: 10 }}>保存: {report.path}</div>
              <pre className="report-md">{report.markdown}</pre>
              {report.errors && Object.keys(report.errors).length > 0 && <div className="note">取得できなかったデータ: {Object.keys(report.errors).join(', ')}</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
