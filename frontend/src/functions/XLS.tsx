// XLS — Excel models linked to the loaded security.
// Read-only, lossless view of what Excel calculated + formatting. Edit in real Excel ("OPEN IN EXCEL");
// the view refreshes on save. Browser edits are WHAT-IF overrides (never written) unless the server
// enables write-back (TERMINAL_EXCEL_WRITE=xlwings|openpyxl). See docs/EXCEL.md.
import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { useFeedMessages } from '../lib/feed';
import { colLetter, parseAddr, renderValue } from '../lib/xlsfmt';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

interface Cell { v: any; f?: string; nf?: string; s?: number; calc?: boolean }
interface Sheet { name: string; state: string; max_row: number; max_col: number; truncated: boolean; merged: string[]; cols: Record<string, { w?: number; hidden?: boolean }>; rows: Record<string, { h?: number; hidden?: boolean }>; cells: Record<string, Cell>; gridlines: boolean; tab_color?: string }
interface View { id: string; name: string; mtime: number; sheets: Sheet[]; styles: any[]; write_mode: string; lossy_parts: string[]; engine_filled?: number }

const BORDER: Record<string, string> = { thin: '1px solid #000', medium: '2px solid #000', thick: '3px solid #000', dashed: '1px dashed #000', dotted: '1px dotted #000', double: '3px double #000', hair: '1px solid #999' };

export function XLS({ symbol, args }: { symbol: string; args?: string }) {
  const { toast } = useTerminal();
  const linked = useAsync(() => api.get<any[]>('/excel/for_symbol', { symbol }), [symbol]);
  const all = useAsync(() => api.get<any>('/excel/files'), []);
  const [fileId, setFileId] = useState<string | undefined>(args);
  const [view, setView] = useState<View | null>(null);
  const [err, setErr] = useState<string>();
  const [sheetIdx, setSheetIdx] = useState(0);
  const [sel, setSel] = useState<string>('A1');
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [overrides, setOverrides] = useState<Record<string, any>>({});
  const [changed, setChanged] = useState<Record<string, any>>({});
  const [liveVals, setLiveVals] = useState<Record<string, any>>({});
  const [stale, setStale] = useState<string[]>([]);
  const [limit, setLimit] = useState(300);
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!fileId && linked.data?.length) setFileId(linked.data[0].id);
  }, [linked.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setFileId(args), [args]);

  const load = (id = fileId) => {
    if (!id) return;
    setErr(undefined);
    api.get<View>('/excel/view', { id }).then(
      (v) => {
        setView(v);
        setSheetIdx((i) => Math.min(i, v.sheets.length - 1));
      },
      (e) => setErr(e.message),
    );
  };
  useEffect(() => {
    setView(null);
    setOverrides({});
    setChanged({});
    load();
  }, [fileId]); // eslint-disable-line react-hooks/exhaustive-deps

  useFeedMessages((m) => {
    if (m.type === 'excel_changed' && m.id === fileId) {
      toast(`${view?.name ?? 'workbook'} saved in Excel — reloaded`);
      load();
    }
  });

  async function recompute(ov: Record<string, any>) {
    if (!fileId) return;
    if (!Object.keys(ov).length && !live) return (setChanged({}), setStale([]));
    try {
      const r = await api.post<any>('/excel/whatif', { id: fileId, overrides: ov });
      setChanged(r.changed);
      setLiveVals(r.live ?? {});
      setStale(r.stale);
    } catch (e: any) {
      toast(e.message);
    }
  }
  useEffect(() => {
    if (!live) return setLiveVals({});
    recompute(overrides);
    const t = setInterval(() => recompute(overrides), 3000);
    return () => clearInterval(t);
  }, [live, overrides]); // eslint-disable-line react-hooks/exhaustive-deps

  const sheet = view?.sheets[sheetIdx];
  const merges = useMemo(() => {
    const anchor: Record<string, [number, number]> = {};
    const covered = new Set<string>();
    for (const m of sheet?.merged ?? []) {
      const [a, b] = m.split(':');
      const [r1, c1] = parseAddr(a), [r2, c2] = parseAddr(b);
      anchor[a] = [r2 - r1 + 1, c2 - c1 + 1];
      for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) if (r !== r1 || c !== c1) covered.add(`${colLetter(c)}${r}`);
    }
    return { anchor, covered };
  }, [sheet]);

  function commitEdit(addr: string, value: string) {
    setEditing(null);
    if (!sheet) return;
    const key = `${sheet.name}!${addr}`;
    const ov = { ...overrides };
    if (value === '' && !(key in overrides)) return;
    ov[key] = value;
    setOverrides(ov);
    recompute(ov);
  }

  async function writeBack() {
    if (!view || !sheet) return;
    const updates: Record<string, any> = {};
    for (const [k, v] of Object.entries(overrides)) {
      const [sh, a] = k.split('!');
      if (sh === sheet.name) updates[a] = v;
    }
    if (!confirm(`Write ${Object.keys(updates).length} cell(s) to ${view.name} (${view.write_mode})? A backup is made first in openpyxl mode.`)) return;
    try {
      await api.post('/excel/write', { id: view.id, sheet: sheet.name, updates });
      toast('written');
      setOverrides({});
      setChanged({});
      load();
    } catch (e: any) {
      toast(e.message);
    }
  }

  async function upload(f: File) {
    const fd = new FormData();
    fd.append('file', f);
    const r = await fetch('/api/excel/upload', { method: 'POST', body: fd });
    if (!r.ok) return toast(await r.text());
    const j = await r.json();
    all.reload();
    setFileId(j.id);
  }

  const isLinked = linked.data?.some((x) => x.id === fileId && x.link === 'manual');
  const cell = sheet?.cells[sel];
  const selKey = sheet ? `${sheet.name}!${sel}` : '';
  const shown = (addr: string, c?: Cell) => {
    const key = `${sheet!.name}!${addr}`;
    if (key in overrides) return { v: overrides[key], cls: 'over' };
    if (key in changed) return { v: changed[key], cls: 'changed' };
    if (key in liveVals) return { v: liveVals[key], cls: 'calc' };
    return { v: c?.v, cls: c?.calc ? 'calc' : '' };
  };
  const colW = (c: number) => {
    const d = sheet?.cols[colLetter(c)];
    if (d?.hidden) return 0;
    return Math.round((d?.w ?? 8.43) * 7 + 5);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="toolbar">
        <span className="lbl">LINKED TO {symbol}</span>
        {(linked.data ?? []).map((x) => (
          <button key={x.id} className={`tb ${x.id === fileId ? 'on' : ''}`} onClick={() => setFileId(x.id)} title={`${x.link} link · ${x.path}`}>
            {x.link === 'manual' ? '★ ' : ''}{x.name}
          </button>
        ))}
        {linked.data && !linked.data.length && <span className="muted">no auto-match (ticker in file/folder name) —</span>}
        <select className="inp" value={fileId ?? ''} onChange={(e) => setFileId(e.target.value || undefined)} style={{ maxWidth: 220 }}>
          <option value="">(all workbooks…)</option>
          {(all.data?.files ?? []).map((f: any) => <option key={f.id} value={f.id} disabled={!f.viewable}>{f.path}</option>)}
        </select>
        {fileId && (
          <button className="tb" onClick={() => api.post('/excel/link', { symbol, file_id: fileId, linked: !isLinked }).then(linked.reload)}>
            {isLinked ? 'UNLINK' : `LINK→${symbol.split(':').pop()}`}
          </button>
        )}
        <label className="tb">UPLOAD<input type="file" accept=".xlsx,.xlsm" style={{ display: 'none' }} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
      </div>
      {view && (
        <div className="toolbar">
          <button className="tb green" onClick={() => api.post('/excel/open', { id: view.id }).then(() => toast('opening in Excel on the server machine…'), (e) => toast(e.message))}>OPEN IN EXCEL</button>
          <a className="tb" href={api.url('/excel/download', { id: view.id })}>DOWNLOAD</a>
          <button className="tb" onClick={() => load()}>RELOAD</button>
          <span className="lbl">WHAT-IF</span>
          <span className="muted">{Object.keys(overrides).length} override(s)</span>
          <button className="tb" disabled={!Object.keys(overrides).length} onClick={() => (setOverrides({}), setChanged({}), setStale([]))}>RESET</button>
          <button className={`tb ${live ? 'on' : ''}`} onClick={() => setLive(!live)} title="re-evaluate every 3s (live TV() quotes)">LIVE</button>
          {view.write_mode !== 'off' ? (
            <button className="tb red" disabled={!Object.keys(overrides).length} onClick={writeBack}>WRITE TO FILE ({view.write_mode})</button>
          ) : (
            <span className="muted" title="set TERMINAL_EXCEL_WRITE=xlwings to enable lossless write-back">read-only (edit in Excel)</span>
          )}
          {view.lossy_parts.length > 0 && <span className="badge warn" title={view.lossy_parts.join(', ')}>contains: {view.lossy_parts.slice(0, 3).join(', ')}</span>}
          {(view.engine_filled ?? 0) > 0 && <span className="badge warn" title="file has no Excel-cached results (saved by another tool); dotted cells were computed by the terminal engine">{view.engine_filled} cell(s) engine-computed</span>}
          {stale.length > 0 && <span className="muted" title={stale.join(', ')}>{stale.length} cell(s) use functions not in the engine — Excel value kept</span>}
        </div>
      )}
      {view && (
        <div className="fbar">
          <span className="addr">{sel}</span>
          <span className="f">
            {cell?.f ? <span className="yellow">{cell.f}</span> : String(cell?.v ?? '')}
            {selKey in overrides && <span className="blue"> → override: {String(overrides[selKey])}</span>}
          </span>
        </div>
      )}
      <ErrorBox error={err || linked.error} />
      {!view && fileId && !err && <Loading />}
      {!fileId && (
        <div className="pad muted">
          Excel フォルダ: {(all.data?.roots ?? []).join(', ')}
          <br />ファイル名かフォルダ名にティッカー (例: <span className="yellow">7203</span>, <span className="yellow">AAPL</span>) を含めると自動で紐付きます。手動リンクも可能。
          <br />環境変数 TERMINAL_EXCEL_DIRS にモデルフォルダを指定してください (docs/EXCEL.md)。
        </div>
      )}
      {sheet && (
        <div style={{ flex: 1, overflow: 'auto', background: '#fff' }}>
          <table className={`xl ${sheet.gridlines ? '' : 'nogrid'}`}>
            <thead>
              <tr>
                <th className="rh" />
                {Array.from({ length: sheet.max_col }, (_, i) => i + 1).map((c) => (
                  <th key={c} style={{ minWidth: colW(c), maxWidth: colW(c), display: colW(c) ? undefined : 'none' }}>{colLetter(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: Math.min(sheet.max_row, limit) }, (_, i) => i + 1).map((r) => {
                const rd = sheet.rows[String(r)];
                if (rd?.hidden) return null;
                return (
                  <tr key={r} style={{ height: rd?.h ? rd.h * 1.33 : undefined }}>
                    <th className="rh">{r}</th>
                    {Array.from({ length: sheet.max_col }, (_, i) => i + 1).map((c) => {
                      const addr = `${colLetter(c)}${r}`;
                      if (merges.covered.has(addr)) return null;
                      const w = colW(c);
                      if (!w) return null;
                      const cl = sheet.cells[addr];
                      const st = cl?.s != null ? view!.styles[cl.s] : {};
                      const span = merges.anchor[addr];
                      const { v, cls } = shown(addr, cl);
                      const rendered = renderValue(v, cl?.nf);
                      const style: React.CSSProperties = {
                        minWidth: w, maxWidth: span ? undefined : w, fontWeight: st.b ? 700 : undefined, fontStyle: st.i ? 'italic' : undefined,
                        textDecoration: st.u ? 'underline' : undefined, color: rendered.color ?? (st.fc ? `#${st.fc}` : undefined),
                        background: st.bg ? `#${st.bg}` : undefined, textAlign: st.ha ?? (typeof v === 'number' ? 'right' : undefined),
                        paddingLeft: st.ind ? st.ind * 9 : undefined, whiteSpace: st.wrap ? 'normal' : undefined,
                        borderTop: BORDER[st.bt], borderBottom: BORDER[st.bb], borderLeft: BORDER[st.bl], borderRight: BORDER[st.br],
                      };
                      return (
                        <td
                          key={c}
                          rowSpan={span?.[0]}
                          colSpan={span?.[1]}
                          style={style}
                          className={`${sel === addr ? 'sel' : ''} ${cls}`}
                          onClick={() => setSel(addr)}
                          onDoubleClick={() => {
                            setSel(addr);
                            setEditing(addr);
                            const key = `${sheet.name}!${addr}`;
                            setDraft(String(key in overrides ? overrides[key] : cl?.f ?? cl?.v ?? ''));
                          }}
                          title={cl?.f ?? undefined}
                        >
                          {editing === addr ? (
                            <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={() => commitEdit(addr, draft)} onKeyDown={(e) => {
                              if (e.key === 'Enter') commitEdit(addr, draft);
                              if (e.key === 'Escape') setEditing(null);
                            }} />
                          ) : (
                            rendered.text
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {sheet.max_row > limit && <button className="tb" style={{ margin: 6 }} onClick={() => setLimit(limit + 500)}>SHOW MORE ROWS ({sheet.max_row - limit} more)</button>}
          {sheet.truncated && <div className="note">sheet truncated for display (max 3000 rows × 120 cols) — open in Excel for the full sheet</div>}
        </div>
      )}
      {view && (
        <div className="tabs">
          {view.sheets.map((s, i) => (
            <span key={s.name} className={`tab ${i === sheetIdx ? 'on' : ''}`} style={{ borderBottom: s.tab_color ? `2px solid #${s.tab_color}` : undefined, opacity: s.state !== 'visible' ? 0.5 : 1 }} onClick={() => setSheetIdx(i)}>
              {s.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
