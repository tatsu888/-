// XLS — Excel models linked to the loaded security, viewable AND editable from the terminal.
//
// EDIT mode (default when the server can write): typing into a cell writes it to the workbook.
//   On Windows the server drives the real Excel application via xlwings, so nothing is lost
//   (charts, macros, pivots…) and if the workbook is open the user's Excel window updates live.
// WHAT-IF mode: edits are evaluated in memory only (never written) — scenario playground.
// Keyboard: arrows/Tab move · Shift+arrows/click select a range · Enter/F2 edit · type to overwrite ·
// Delete clears · Ctrl+C / Ctrl+V copy-paste (TSV, works with Excel) · Ctrl+Z undo · Esc cancel.
// See docs/EXCEL.md.
import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import { useFeedMessages } from '../lib/feed';
import { colLetter, parseAddr, renderValue } from '../lib/xlsfmt';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

interface Cell { v: any; f?: string; nf?: string; s?: number; calc?: boolean }
interface Sheet { name: string; state: string; max_row: number; max_col: number; truncated: boolean; merged: string[]; cols: Record<string, { w?: number; hidden?: boolean }>; rows: Record<string, { h?: number; hidden?: boolean }>; cells: Record<string, Cell>; gridlines: boolean; tab_color?: string }
interface View { id: string; name: string; mtime: number; sheets: Sheet[]; styles: any[]; write_mode: string; write_reason: string; lossy_parts: string[]; engine_filled?: number }
interface UndoItem { sheet: string; before: Record<string, any>; label: string }

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
  const [anchor, setAnchor] = useState<string | null>(null); // range selection: anchor..sel
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState<'edit' | 'whatif'>('edit');
  const [saving, setSaving] = useState(false);
  const [undo, setUndo] = useState<UndoItem[]>([]);
  const [overrides, setOverrides] = useState<Record<string, any>>({});
  const [changed, setChanged] = useState<Record<string, any>>({});
  const [liveVals, setLiveVals] = useState<Record<string, any>>({});
  const [stale, setStale] = useState<string[]>([]);
  const [limit, setLimit] = useState(300);
  const [live, setLive] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);
  const fbarRef = useRef<HTMLInputElement>(null);

  const canWrite = !!view && view.write_mode !== 'off';
  const editMode = mode === 'edit' && canWrite;

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
    setUndo([]);
    load();
  }, [fileId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (view && view.write_mode === 'off') setMode('whatif');
  }, [view?.write_mode]); // eslint-disable-line react-hooks/exhaustive-deps

  useFeedMessages((m) => {
    if (m.type === 'excel_changed' && m.id === fileId) {
      toast(`${view?.name ?? 'workbook'} が Excel で保存されました — 再読込`);
      load();
    }
  });

  // ---------------------------------------------------------------- what-if
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

  // ---------------------------------------------------------------- writing
  async function write(sheetName: string, updates: Record<string, any>, label: string, pushUndo = true) {
    if (!view) return;
    setSaving(true);
    try {
      const r = await api.post<any>('/excel/write', { id: view.id, sheet: sheetName, updates });
      if (pushUndo) setUndo((u) => [...u.slice(-49), { sheet: sheetName, before: r.before, label }]);
      setView(r.view);
    } catch (e: any) {
      toast(`保存できません: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function doUndo() {
    const last = undo[undo.length - 1];
    if (!last) return;
    setUndo((u) => u.slice(0, -1));
    await write(last.sheet, Object.fromEntries(Object.entries(last.before).map(([k, v]) => [k, v ?? ''])), 'undo', false);
    toast(`UNDO ${last.label}`);
  }

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

  function commit(addr: string, value: string, move: 'down' | 'right' | 'none' = 'down') {
    setEditing(null);
    if (!sheet) return;
    const cur = sheet.cells[addr];
    const original = cur?.f ?? (cur?.v == null ? '' : String(cur.v));
    if (editMode) {
      if (value !== original) write(sheet.name, { [addr]: value }, `${sheet.name}!${addr}`);
    } else {
      const key = `${sheet.name}!${addr}`;
      if (value === original && !(key in overrides)) return;
      const ov = { ...overrides, [key]: value };
      setOverrides(ov);
      recompute(ov);
    }
    if (move !== 'none') moveSel(move === 'down' ? 1 : 0, move === 'right' ? 1 : 0);
    gridRef.current?.focus();
  }

  function moveSel(dr: number, dc: number, extend = false) {
    if (!sheet) return;
    if (extend) setAnchor((a) => a ?? sel);
    else setAnchor(null);
    const [r, c] = parseAddr(sel);
    const nr = Math.max(1, Math.min(r + dr, Math.max(sheet.max_row + 50, 1)));
    const nc = Math.max(1, Math.min(c + dc, Math.max(sheet.max_col + 10, 1)));
    setSel(`${colLetter(nc)}${nr}`);
  }

  function startEdit(addr: string, initial?: string) {
    if (!sheet) return;
    const key = `${sheet.name}!${addr}`;
    const cl = sheet.cells[addr];
    setSel(addr);
    setAnchor(null);
    setEditing(addr);
    setDraft(initial ?? String(!editMode && key in overrides ? overrides[key] : cl?.f ?? cl?.v ?? ''));
  }

  function onGridKey(e: React.KeyboardEvent) {
    if (editing || !sheet) return;
    const k = e.key;
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === 'z') {
      e.preventDefault();
      if (editMode) doUndo();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const moves: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], Tab: [0, e.shiftKey ? -1 : 1] };
    if (moves[k]) {
      e.preventDefault();
      moveSel(moves[k][0], moves[k][1], e.shiftKey && k !== 'Tab');
    } else if (k === 'Enter' || k === 'F2') {
      e.preventDefault();
      startEdit(sel);
    } else if (k === 'Delete' || k === 'Backspace') {
      e.preventDefault();
      if (anchor) applyBlock(rangeAddrs().map((row) => row.map(() => '')), 'clear range');
      else commit(sel, '', 'none');
    } else if (k === 'Escape') {
      setAnchor(null);
    } else if (k.length === 1) {
      e.preventDefault();
      startEdit(sel, k); // typing overwrites, like Excel
    }
  }

  // ---------------------------------------------------------------- ranges, copy & paste
  function rangeBounds(): [number, number, number, number] {
    const [r1, c1] = parseAddr(anchor ?? sel), [r2, c2] = parseAddr(sel);
    return [Math.min(r1, r2), Math.min(c1, c2), Math.max(r1, r2), Math.max(c1, c2)];
  }
  function rangeAddrs(): string[][] {
    const [r1, c1, r2, c2] = rangeBounds();
    const out: string[][] = [];
    for (let r = r1; r <= r2; r++) {
      const row: string[] = [];
      for (let c = c1; c <= c2; c++) row.push(`${colLetter(c)}${r}`);
      out.push(row);
    }
    return out;
  }
  const inRange = (addr: string) => {
    if (!anchor) return false;
    const [r, c] = parseAddr(addr), [r1, c1, r2, c2] = rangeBounds();
    return r >= r1 && r <= r2 && c >= c1 && c <= c2;
  };

  /** Write a 2-D block of raw inputs starting at the top-left of the selection (EDIT) or as what-if overrides. */
  function applyBlock(block: string[][], label: string) {
    if (!sheet || !block.length) return;
    const [r0, c0] = anchor ? rangeBounds() : parseAddr(sel);
    const updates: Record<string, string> = {};
    block.forEach((row, i) => row.forEach((v, j) => (updates[`${colLetter(c0 + j)}${r0 + i}`] = v)));
    if (editMode) write(sheet.name, updates, `${label} ${Object.keys(updates).length} cells`);
    else {
      const ov = { ...overrides };
      for (const [a, v] of Object.entries(updates)) ov[`${sheet.name}!${a}`] = v;
      setOverrides(ov);
      recompute(ov);
    }
  }

  function onCopy(e: React.ClipboardEvent) {
    if (editing || !sheet) return;
    e.preventDefault();
    const tsv = rangeAddrs()
      .map((row) => row.map((a) => {
        const { v } = shown(a, sheet.cells[a]);
        return v == null ? '' : String(v);
      }).join('\t'))
      .join('\n');
    e.clipboardData.setData('text/plain', tsv);
    toast(`copied ${rangeAddrs().flat().length} cell(s)`);
  }

  function onPaste(e: React.ClipboardEvent) {
    if (editing || !sheet) return;
    e.preventDefault();
    const text = e.clipboardData.getData('text/plain').replace(/\r/g, '').replace(/\n$/, '');
    if (!text) return;
    const block = text.split('\n').map((line) => line.split('\t'));
    if (block.flat().length > 2000) return toast('paste too large (max 2000 cells)');
    applyBlock(block, 'paste');
  }

  // keep the selected cell visible
  useEffect(() => {
    gridRef.current?.querySelector('td.sel')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [sel]);

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
    if (!editMode) {
      if (key in overrides) return { v: overrides[key], cls: 'over' };
      if (key in changed) return { v: changed[key], cls: 'changed' };
    }
    if (key in liveVals) return { v: liveVals[key], cls: 'calc' };
    return { v: c?.v, cls: c?.calc ? 'calc' : '' };
  };
  const colW = (c: number) => {
    const d = sheet?.cols[colLetter(c)];
    if (d?.hidden) return 0;
    return Math.round((d?.w ?? 8.43) * 7 + 5);
  };
  const fbarValue = editing === sel ? draft : !editMode && selKey in overrides ? String(overrides[selKey]) : String(cell?.f ?? cell?.v ?? '');

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
          <button className={`tb ${editMode ? 'on' : ''}`} disabled={!canWrite} onClick={() => setMode('edit')} title={view.write_reason}>
            EDIT
          </button>
          <button className={`tb ${mode === 'whatif' || !canWrite ? 'on' : ''}`} onClick={() => setMode('whatif')} title="ファイルに書き込まず、メモリ上で再計算">
            WHAT-IF
          </button>
          {editMode ? (
            <>
              <span className={canWrite ? 'up' : 'muted'}>● {view.write_mode === 'xlwings' ? 'Excel 本体経由で保存' : '直接保存 (自動バックアップ)'}</span>
              <button className="tb" disabled={!undo.length || saving} onClick={doUndo} title="Ctrl+Z">
                UNDO{undo.length ? ` (${undo.length})` : ''}
              </button>
              {saving && <span className="yellow">SAVING…</span>}
            </>
          ) : (
            <>
              <span className="muted">{Object.keys(overrides).length} override(s)</span>
              <button className="tb" disabled={!Object.keys(overrides).length} onClick={() => (setOverrides({}), setChanged({}), setStale([]))}>RESET</button>
              {canWrite && Object.keys(overrides).length > 0 && (
                <button
                  className="tb red"
                  onClick={async () => {
                    const bySheet: Record<string, Record<string, any>> = {};
                    for (const [k, v] of Object.entries(overrides)) {
                      const i = k.lastIndexOf('!');
                      (bySheet[k.slice(0, i)] ??= {})[k.slice(i + 1)] = v;
                    }
                    if (!confirm(`What-if の ${Object.keys(overrides).length} セルをファイルに反映しますか?`)) return;
                    for (const [sh, ups] of Object.entries(bySheet)) await write(sh, ups, `apply what-if (${Object.keys(ups).length})`);
                    setOverrides({});
                    setChanged({});
                  }}
                >
                  APPLY TO FILE
                </button>
              )}
              {!canWrite && <span className="muted" title={view.write_reason}>read-only: {view.write_reason}</span>}
            </>
          )}
          <button className={`tb ${live ? 'on' : ''}`} onClick={() => setLive(!live)} title="=TV() のライブ値を 3 秒ごとに更新">LIVE</button>
          <span className="lbl">│</span>
          <button className="tb green" onClick={() => api.post('/excel/open', { id: view.id }).then(() => toast('Excel で開いています…'), (e) => toast(e.message))}>OPEN IN EXCEL</button>
          <a className="tb" href={api.url('/excel/download', { id: view.id })}>DOWNLOAD</a>
          <button className="tb" onClick={() => load()}>RELOAD</button>
          {view.lossy_parts.length > 0 && <span className="badge warn" title={view.lossy_parts.join(', ')}>contains: {view.lossy_parts.slice(0, 3).join(', ')}</span>}
          {(view.engine_filled ?? 0) > 0 && <span className="badge warn" title="Excel が計算した結果がファイルにないため、点線のセルはターミナルのエンジンで計算した値です (Excel で開いて保存すると正式な値になります)">{view.engine_filled} cell(s) engine-computed</span>}
          {stale.length > 0 && <span className="muted" title={stale.join(', ')}>{stale.length} cell(s) use functions not in the engine — Excel value kept</span>}
        </div>
      )}
      {view && (
        <div className="fbar">
          <span className="addr">{anchor ? `${rangeAddrs()[0][0]}:${sel}`.replace(/^(.*):\1$/, '$1') : sel}</span>
          <span className="muted">fx</span>
          <input
            ref={fbarRef}
            className="inp"
            style={{ flex: 1, color: editMode ? '#ffd84a' : '#5ea9ff' }}
            value={fbarValue}
            onFocus={() => {
              if (editing !== sel) startEdit(sel);
            }}
            onChange={(e) => {
              if (editing !== sel) startEdit(sel);
              setDraft(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit(sel, draft);
              if (e.key === 'Escape') (setEditing(null), gridRef.current?.focus());
            }}
            placeholder={editMode ? '値または =数式 を入力して Enter で保存' : 'What-if: 値または =数式 (ファイルは変更しない)'}
          />
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
        <div ref={gridRef} tabIndex={0} data-own-keys onKeyDown={onGridKey} onCopy={onCopy} onPaste={onPaste} style={{ flex: 1, overflow: 'auto', background: '#fff', outline: 'none' }}>
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
                          className={`${sel === addr ? 'sel' : ''} ${inRange(addr) ? 'rng' : ''} ${cls}`}
                          onClick={(e) => {
                            if (editing && editing !== addr) commit(editing, draft, 'none');
                            if (e.shiftKey) setAnchor((a) => a ?? sel);
                            else setAnchor(null);
                            setSel(addr);
                            gridRef.current?.focus();
                          }}
                          onDoubleClick={() => startEdit(addr)}
                          title={cl?.f ?? undefined}
                        >
                          {editing === addr ? (
                            <input
                              autoFocus
                              value={draft}
                              onChange={(e) => setDraft(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') commit(addr, draft, 'down');
                                else if (e.key === 'Tab') (e.preventDefault(), commit(addr, draft, 'right'));
                                else if (e.key === 'Escape') (setEditing(null), gridRef.current?.focus());
                              }}
                            />
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
