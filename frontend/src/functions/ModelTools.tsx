// MODEL sub-tools: assumption form editor, version history / revision diff, AI assistant loop.
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { fmtNum } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';

type Spec = any;
type MethodParams = Record<string, { required: Record<string, string>; optional: Record<string, string>; judgmental: boolean; desc: string }>;

const clone = (x: any) => JSON.parse(JSON.stringify(x));

function show(v: any): string {
  if (v == null) return '';
  if (Array.isArray(v) && v.every((x) => typeof x === 'number' || x == null)) return v.join(', ');
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function parseVal(text: string, type: string): any {
  const t = text.trim();
  if (t === '') return undefined;
  if (t.startsWith('{') || t.startsWith('[')) return JSON.parse(t); // excel refs, paths, dicts, explicit lists
  if (type === 'vec' || type === 'list') {
    const parts = t.split(/[,\s]+/).filter(Boolean).map(Number);
    if (parts.some((x) => Number.isNaN(x))) throw new Error('numbers separated by commas');
    return parts.length === 1 && type === 'vec' ? parts[0] : parts;
  }
  if (type === 'number' || type === 'int') {
    const n = Number(t);
    if (Number.isNaN(n)) throw new Error('number expected');
    return n;
  }
  if (type === 'lines') return t.split(/[,\s]+/).filter(Boolean);
  if (type === 'path' || type === 'dict') return JSON.parse(t);
  return t;
}

/** Text field that parses on blur according to the param type, showing parse errors inline. */
function Field({ value, type, onChange, width = 140, placeholder }: { value: any; type: string; onChange: (v: any) => void; width?: number; placeholder?: string }) {
  const [draft, setDraft] = useState(show(value));
  const [bad, setBad] = useState<string>();
  useEffect(() => setDraft(show(value)), [JSON.stringify(value)]); // eslint-disable-line react-hooks/exhaustive-deps
  const commit = () => {
    try {
      onChange(parseVal(draft, type));
      setBad(undefined);
    } catch (e: any) {
      setBad(e.message);
    }
  };
  return (
    <input
      className="inp"
      style={{ width, borderColor: bad ? '#ff4545' : undefined }}
      title={bad ?? `${type}${type === 'vec' ? ': one number or one per forecast year, e.g. 0.03, 0.03, 0.02 — or {"excel": "0/file.xlsx", "range": "Model!B4:F4"}' : ''}`}
      value={draft}
      placeholder={placeholder ?? type}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && commit()}
    />
  );
}

export function AssumptionEditor({ spec, onChange, mp }: { spec: Spec; onChange: (s: Spec) => void; mp: MethodParams }) {
  const [newLine, setNewLine] = useState({ name: '', method: 'growth' });
  if (!spec?.lines) return <div className="note">spec has no lines</div>;
  const lines = Object.keys(spec.lines);
  const set = (fn: (s: Spec) => void) => {
    const s = clone(spec);
    fn(s);
    onChange(s);
  };
  const setParam = (line: string, k: string, v: any) =>
    set((s) => {
      s.lines[line].params ??= {};
      if (v === undefined) delete s.lines[line].params[k];
      else s.lines[line].params[k] = v;
    });
  const A: [string, string][] = [['tax_rate', 'vec'], ['minority_pct', 'vec'], ['payout_ratio', 'vec'], ['dso', 'vec'], ['dio', 'vec'], ['dpo', 'vec'], ['shares', 'number'], ['per_share_factor', 'number']];
  const V: [string, string][] = [['terminal_growth', 'number'], ['exit_ev_ebitda', 'number'], ['net_debt', 'number'], ['book_equity', 'number'], ['current_price', 'number']];
  const W: [string, string][] = [['rf', 'number'], ['beta', 'number'], ['erp', 'number'], ['size_premium', 'number'], ['cost_of_debt', 'number'], ['debt_weight', 'number']];
  return (
    <div>
      <div className="note">前提を編集 → RUN。入力は Enter / フォーカス移動で反映。判断を伴う前提には SOURCE（出典）を必ず記入。値に {'{"excel": "<file id>", "range": "Sheet!B4:F4"}'} と書くと Excel の値を参照します。</div>
      <table className="t">
        <thead><tr><th className="l">LINE</th><th className="l">METHOD</th><th className="l">PARAMETERS</th><th className="l">SOURCE</th><th /></tr></thead>
        <tbody>
          {lines.map((ln) => {
            const L = spec.lines[ln];
            const meta = mp[L.method];
            const keys = meta ? [...Object.entries(meta.required).map(([k, t]) => [k, t, true] as const), ...Object.entries(meta.optional).map(([k, t]) => [k, t, false] as const)] : [];
            return (
              <tr key={ln}>
                <td className="l amber">{ln}</td>
                <td className="l">
                  <select className="inp" value={L.method} title={meta?.desc} onChange={(e) => set((s) => {
                    const m = e.target.value;
                    const src = s.lines[ln].params?.source;
                    s.lines[ln] = { method: m, params: src ? { source: src } : {} };
                  })}>
                    {Object.keys(mp).map((m) => <option key={m}>{m}</option>)}
                  </select>
                </td>
                <td className="l" style={{ whiteSpace: 'normal' }}>
                  {keys.map(([k, t, req]) => (
                    <span key={k} style={{ display: 'inline-flex', alignItems: 'center', marginRight: 8, marginBottom: 2 }}>
                      <span className={req ? 'yellow' : 'muted'} style={{ marginRight: 3 }}>{k}{req ? '*' : ''}</span>
                      {t === 'line' ? (
                        <select className="inp" value={L.params?.[k] ?? ''} onChange={(e) => setParam(ln, k, e.target.value || undefined)}>
                          <option value="" />
                          {lines.filter((x) => x !== ln).map((x) => <option key={x}>{x}</option>)}
                        </select>
                      ) : t.startsWith('enum:') ? (
                        <select className="inp" value={L.params?.[k] ?? ''} onChange={(e) => setParam(ln, k, e.target.value || undefined)}>
                          <option value="" />
                          {t.slice(5).split('|').map((x) => <option key={x}>{x}</option>)}
                        </select>
                      ) : (
                        <Field value={L.params?.[k]} type={t} width={t === 'path' || t === 'dict' ? 220 : 130} onChange={(v) => setParam(ln, k, v)}
                          placeholder={t === 'path' ? '{"line":"units"}' : t} />
                      )}
                    </span>
                  ))}
                </td>
                <td className="l">
                  {meta?.judgmental ? (
                    <Field value={L.params?.source} type="string" width={220} onChange={(v) => setParam(ln, 'source', v)} placeholder="出典 / 根拠 (必須)" />
                  ) : <span className="muted">statistical</span>}
                </td>
                <td><span className="muted" style={{ cursor: 'pointer' }} title="delete line" onClick={() => ln !== 'revenue' && confirm(`delete line ${ln}?`) && set((s) => delete s.lines[ln])}>✕</span></td>
              </tr>
            );
          })}
          <tr>
            <td className="l"><input className="inp" style={{ width: 110 }} placeholder="new line" value={newLine.name} onChange={(e) => setNewLine({ ...newLine, name: e.target.value.trim() })} /></td>
            <td className="l">
              <select className="inp" value={newLine.method} onChange={(e) => setNewLine({ ...newLine, method: e.target.value })}>{Object.keys(mp).map((m) => <option key={m}>{m}</option>)}</select>
              <button className="tb" disabled={!newLine.name || lines.includes(newLine.name)} onClick={() => (set((s) => (s.lines[newLine.name] = { method: newLine.method, params: {} })), setNewLine({ ...newLine, name: '' }))}>+ ADD</button>
            </td>
            <td colSpan={3} className="l muted">e.g. segment lines, then revenue = sum(items)</td>
          </tr>
        </tbody>
      </table>
      <div className="cols">
        <div className="box">
          <h4>ASSUMPTIONS</h4>
          <div className="kv">
            {A.map(([k, t]) => [<span key={k}>{k}</span>, <Field key={k + 'f'} value={spec.assumptions?.[k]} type={t} onChange={(v) => set((s) => { s.assumptions ??= {}; if (v === undefined) delete s.assumptions[k]; else s.assumptions[k] = v; })} />])}
          </div>
        </div>
        <div className="box">
          <h4>VALUATION</h4>
          <div className="kv">
            {V.map(([k, t]) => [<span key={k}>{k}</span>, <Field key={k + 'f'} value={spec.valuation?.[k]} type={t} onChange={(v) => set((s) => { s.valuation ??= {}; if (v === undefined) delete s.valuation[k]; else s.valuation[k] = v; })} />])}
            {typeof spec.valuation?.wacc === 'object'
              ? W.map(([k, t]) => [<span key={k}>wacc.{k}</span>, <Field key={k + 'f'} value={spec.valuation.wacc[k]} type={t} onChange={(v) => set((s) => { if (v === undefined) delete s.valuation.wacc[k]; else s.valuation.wacc[k] = v; })} />])
              : [<span key="w">wacc</span>, <Field key="wf" value={spec.valuation?.wacc} type="number" onChange={(v) => set((s) => { s.valuation ??= {}; s.valuation.wacc = v; })} />]}
          </div>
        </div>
      </div>
    </div>
  );
}

export function Versions({ name, onLoad }: { name: string; onLoad: (spec: Spec) => void }) {
  const v = useAsync(() => (name ? api.get<any[]>(`/harness/models/${encodeURIComponent(name)}/versions`) : Promise.resolve([])), [name]);
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  const d = useAsync(() => (a && b && a !== b ? api.get<any>(`/harness/models/${encodeURIComponent(name)}/diff`, { a, b }) : Promise.resolve(null)), [a, b, name]);
  if (!name) return <div className="note">SAVE the model first — every save with changed inputs becomes a version (forecast revision log).</div>;
  if (v.loading) return <Loading />;
  const list = v.data ?? [];
  return (
    <div>
      <div className="note">予想の改訂履歴。A と B を選ぶと、前提の変更点と主要な出力の変化を表示します。</div>
      <table className="t">
        <thead><tr><th>A</th><th>B</th><th>VER</th><th className="l">SAVED (UTC)</th><th className="l">NOTE</th><th>OP [0]</th><th>EPS [0]</th><th>DCF / share</th><th className="l">CHECKS</th><th /></tr></thead>
        <tbody>
          {[...list].reverse().map((x) => (
            <tr key={x.version}>
              <td><input type="radio" checked={a === x.version} onChange={() => setA(x.version)} /></td>
              <td><input type="radio" checked={b === x.version} onChange={() => setB(x.version)} /></td>
              <td className="amber">v{x.version}</td>
              <td className="l muted">{x.saved_at}</td>
              <td className="l">{x.note}</td>
              <td>{fmtNum(x.summary?.operating_profit?.[0], 1)}</td>
              <td>{fmtNum(x.summary?.eps?.[0], 1)}</td>
              <td>{fmtNum(x.summary?.dcf_price, 0)}</td>
              <td className="l muted">{x.summary?.checks ? `${x.summary.checks.PASS}/${x.summary.checks.WARN}/${x.summary.checks.FAIL}` : x.summary?.error}</td>
              <td><button className="tb" onClick={() => api.get<any>(`/harness/models/${encodeURIComponent(name)}/versions/${x.version}`).then((r) => onLoad(r.spec))}>LOAD</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <ErrorBox error={d.error} />
      {d.data && (
        <div className="box" style={{ margin: 6 }}>
          <h4>v{d.data.a} → v{d.data.b}: {d.data.changes.length} change(s)</h4>
          <table className="t">
            <thead><tr><th className="l">PATH</th><th className="l">BEFORE</th><th className="l">AFTER</th></tr></thead>
            <tbody>
              {d.data.changes.map((c: any) => (
                <tr key={c.path}><td className="l amber">{c.path}</td><td className="l muted">{show(c.before)}</td><td className="l yellow">{show(c.after)}</td></tr>
              ))}
            </tbody>
          </table>
          <OutputDelta a={d.data.summary_a} b={d.data.summary_b} />
        </div>
      )}
    </div>
  );
}

function OutputDelta({ a, b }: { a: any; b: any }) {
  if (!a || !b) return null;
  const rows: [string, any, any][] = [
    ['DCF / share', a.dcf_price, b.dcf_price],
    ...(a.eps ?? []).map((v: number, i: number) => [`EPS [${i}]`, v, b.eps?.[i]] as [string, any, any]),
    ...(a.operating_profit ?? []).map((v: number, i: number) => [`OP [${i}]`, v, b.operating_profit?.[i]] as [string, any, any]),
  ];
  return (
    <table className="t">
      <thead><tr><th className="l">OUTPUT</th><th>BEFORE</th><th>AFTER</th><th>Δ%</th></tr></thead>
      <tbody>
        {rows.map(([k, x, y]) => (
          <tr key={k}><td className="l">{k}</td><td>{fmtNum(x, 1)}</td><td>{fmtNum(y, 1)}</td>
            <td className={x && y ? (y > x ? 'up' : y < x ? 'down' : '') : ''}>{x && y != null ? fmtNum((y / x - 1) * 100, 1) : '--'}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export function AiAssist({ spec, onApply }: { spec: Spec; onApply: (s: Spec) => void }) {
  const { toast } = useTerminal();
  const [task, setTask] = useState('');
  const [answer, setAnswer] = useState('');
  const [preview, setPreview] = useState<any>(null);
  const [err, setErr] = useState<string>();
  async function copyBrief() {
    try {
      const r = await fetch('/api/harness/brief', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ spec, task }) });
      const md = await r.text();
      try {
        await navigator.clipboard.writeText(md);
        toast('AI brief copied — paste it into ChatGPT / Claude');
      } catch {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([md], { type: 'text/markdown' }));
        a.download = 'harness_brief.md';
        a.click();
      }
    } catch (e: any) {
      setErr(e.message);
    }
  }
  async function doPreview() {
    setErr(undefined);
    let parsed: any;
    try {
      const m = answer.match(/```(?:json)?\s*([\s\S]*?)```/);
      parsed = JSON.parse(m ? m[1] : answer);
    } catch (e: any) {
      return setErr(`AI answer is not valid JSON: ${e.message}`);
    }
    try {
      setPreview({ ...(await api.post<any>('/harness/apply_changes', { spec, changes: parsed })), questions: parsed.questions, missing: parsed.missing_data, notes: parsed.changes });
    } catch (e: any) {
      setErr(e.message);
    }
  }
  return (
    <div className="pad">
      <div className="note">
        AI は前提（spec）の変更案だけを JSON で返し、数値はハーネスが計算します。① 依頼を書いて BRIEF をコピー → ② ChatGPT/Claude に貼る → ③ 回答を下に貼って PREVIEW → ④ 差分と影響を確認して ACCEPT。
        出典の無い変更・実績(history)の変更は自動で拒否されます。
      </div>
      <textarea className="inp" rows={3} placeholder="依頼内容 (例: 最新の決算説明資料を踏まえて数量成長率とマージンを見直して)" value={task} onChange={(e) => setTask(e.target.value)} />
      <div className="toolbar"><button className="tb green" onClick={copyBrief}>① COPY AI BRIEF</button><a className="tb" href="/api/harness/schema" target="_blank" rel="noreferrer">JSON SCHEMA</a></div>
      <textarea className="inp" rows={8} placeholder="③ AI の回答 (```json … ``` を含む全文でも可) を貼り付け" value={answer} onChange={(e) => setAnswer(e.target.value)} />
      <div className="toolbar"><button className="tb" onClick={doPreview} disabled={!answer}>PREVIEW CHANGES</button></div>
      <ErrorBox error={err} />
      {preview && (
        <div className="box">
          <h4>PREVIEW — {preview.diff.length} change(s), {preview.rejected.length} rejected</h4>
          {preview.rejected.map((r: string) => <div key={r} className="err">REJECTED {r}</div>)}
          <table className="t">
            <thead><tr><th className="l">PATH</th><th className="l">BEFORE</th><th className="l">AFTER</th></tr></thead>
            <tbody>{preview.diff.map((c: any) => <tr key={c.path}><td className="l amber">{c.path}</td><td className="l muted">{show(c.before)}</td><td className="l yellow">{show(c.after)}</td></tr>)}</tbody>
          </table>
          {(preview.notes ?? []).filter((n: any) => n.rationale).map((n: any) => <div key={n.path} className="note">{n.path}: {n.rationale}</div>)}
          {preview.before && <OutputDelta a={{ ...preview.before, dcf_price: preview.before.dcf_price }} b={preview.after} />}
          {preview.run_error && <div className="err">{preview.run_error}</div>}
          {(preview.questions ?? []).length > 0 && <div className="note">AI questions: {preview.questions.join(' / ')}</div>}
          {(preview.missing ?? []).length > 0 && <div className="note">missing data: {preview.missing.join(' / ')}</div>}
          <div className="toolbar">
            <button className="tb green" disabled={!preview.diff.length} onClick={() => (onApply(preview.spec), setPreview(null), setAnswer(''), toast('changes applied — SAVE to record a version'))}>④ ACCEPT</button>
            <button className="tb red" onClick={() => setPreview(null)}>DISCARD</button>
          </div>
        </div>
      )}
    </div>
  );
}
