// MODEL — forecast harness UI. The spec (JSON) holds every assumption; the backend engine computes
// deterministically and returns provenance, guardrail checks and input/output hashes. AI agents
// should only write/modify the spec, never the numbers (docs/FORECAST_HARNESS.md).
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, fmtPct, heat } from '../lib/format';
import { ErrorBox, Loading, useAsync } from '../components/ui';
import { useTerminal } from '../ctx';
import { AiAssist, AssumptionEditor, Versions } from './ModelTools';

const KEY_DERIVED = ['gross_profit', 'operating_profit', 'ebitda', 'pretax_profit', 'net_income', 'eps', 'fcff', 'dividends'];
const RATIOS = ['revenue_growth', 'gross_margin', 'operating_margin', 'net_margin'];

export function MODEL() {
  const { toast } = useTerminal();
  const models = useAsync(() => api.get<{ saved: string[]; examples: string[] }>('/harness/models'), []);
  const catalog = useAsync(() => api.get<any>('/harness/catalog'), []);
  const [text, setText] = useState('');
  const [name, setName] = useState('');
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<'result' | 'assumptions' | 'spec' | 'versions' | 'ai' | 'catalog'>('result');
  const templates = useAsync(() => api.get<{ name: string; description: string }[]>('/harness/templates'), []);
  const specObj = (() => {
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  })();
  const setSpec = (s: any, rerun = true) => {
    setText(JSON.stringify(s, null, 2));
    if (rerun) run(s);
  };

  async function loadModel(n: string, kind: 'ex' | 'sv' | 'tp') {
    const spec = kind === 'tp' ? await api.get<any>(`/harness/templates/${n}`) : await api.get<any>(`/harness/models/${n}`, { example: kind === 'ex' });
    setText(JSON.stringify(spec, null, 2));
    setName(kind === 'sv' ? n : '');
    run(spec);
    if (kind === 'tp') setTab('assumptions');
  }
  useEffect(() => {
    if (!text && models.data?.examples?.length) loadModel(models.data.examples[0], 'ex');
  }, [models.data]); // eslint-disable-line react-hooks/exhaustive-deps

  function parse(): any | null {
    try {
      return JSON.parse(text);
    } catch (e: any) {
      setErr(`JSON: ${e.message}`);
      return null;
    }
  }
  async function run(spec = parse()) {
    if (!spec) return;
    setBusy(true);
    setErr(undefined);
    try {
      setRes(await api.post('/harness/run', spec));
      setTab('result');
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    const spec = parse();
    const n = name || prompt('model name (e.g. TSE_7203_base)') || '';
    if (!spec || !n) return;
    const note = prompt('version note (改訂理由, optional)', '') ?? '';
    const r = await fetch(`/api/harness/models/${encodeURIComponent(n)}?note=${encodeURIComponent(note)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec),
    }).then((x) => x.json());
    setName(n);
    models.reload();
    toast(`saved ${n} (v${r.version})`);
  }

  const p = res?.projection;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="toolbar">
        <select className="inp" value="" onChange={(e) => {
          const [kind, n] = e.target.value.split('|');
          if (n) loadModel(n, kind as 'ex' | 'sv' | 'tp');
        }}>
          <option value="">LOAD MODEL…</option>
          {(templates.data ?? []).map((t) => <option key={'tp' + t.name} value={`tp|${t.name}`}>template: {t.name} — {t.description}</option>)}
          {(models.data?.examples ?? []).map((m) => <option key={'ex' + m} value={`ex|${m}`}>example: {m}</option>)}
          {(models.data?.saved ?? []).map((m) => <option key={'sv' + m} value={`sv|${m}`}>{m}</option>)}
        </select>
        <button className="tb green" onClick={() => run()} disabled={busy}>{busy ? 'RUNNING…' : 'RUN'}</button>
        <button className="tb" onClick={save}>SAVE{name ? ` (${name})` : ''}</button>
        <button className="tb" onClick={() => { const s = parse(); if (s) api.download('/harness/export.xlsx', s, `${(s.company?.symbol ?? 'model').replace(':', '_')}_harness.xlsx`).catch((e) => toast(e.message)); }}>EXPORT XLSX</button>
        <span className="lbl">│</span>
        {(['result', 'assumptions', 'spec', 'versions', 'ai', 'catalog'] as const).map((t) => <button key={t} className={`tb ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)}>{t.toUpperCase()}</button>)}
        {res && (
          <span>
            <span className="badge pass">{res.check_summary.PASS} PASS</span> <span className="badge warn">{res.check_summary.WARN} WARN</span> <span className="badge fail">{res.check_summary.FAIL} FAIL</span>
          </span>
        )}
      </div>
      <ErrorBox error={err} />
      <div style={{ flex: 1, overflow: 'auto' }}>
        {tab === 'spec' && (
          <textarea className="inp" spellCheck={false} style={{ height: '100%', minHeight: 400, resize: 'none' }} value={text} onChange={(e) => setText(e.target.value)} />
        )}
        {tab === 'catalog' && (catalog.data ? <Catalog c={catalog.data} /> : <Loading />)}
        {tab === 'assumptions' && (specObj && catalog.data ? <AssumptionEditor spec={specObj} mp={catalog.data.method_params} onChange={(s) => setSpec(s)} /> : <div className="err">spec JSON is invalid — fix it in SPEC</div>)}
        {tab === 'versions' && <Versions name={name} onLoad={(s) => setSpec(s)} />}
        {tab === 'ai' && (specObj ? <AiAssist spec={specObj} onApply={(s) => setSpec(s)} /> : <div className="err">spec JSON is invalid</div>)}
        {tab === 'result' && res && p && (
          <div>
            <div className="note">
              <span className="amber">{res.company?.name ?? ''}</span> {res.company?.symbol} · unit {res.company?.unit ?? ''} {res.company?.currency ?? ''} · engine {res.meta.engine_version}
              <br />input {res.meta.input_hash.slice(0, 16)}… · output {res.meta.output_hash.slice(0, 16)}… (same spec ⇒ same hash)
              {res.meta.excel_refs?.length > 0 && (
                <>
                  <br />excel refs: {res.meta.excel_refs.map((r: any) => `${r.path} ← ${r.file} ${r.range}`).join(' · ')}
                </>
              )}
            </div>
            <table className="t">
              <thead>
                <tr>
                  <th className="l">LINE</th>
                  {p.years_hist.map((y: string) => <th key={y} className="muted">{y}</th>)}
                  {p.years.map((y: string) => <th key={y}>{y}</th>)}
                  <th className="l">METHOD / FORMULA</th>
                  <th className="l">SOURCE</th>
                </tr>
              </thead>
              <tbody>
                <tr className="group"><td colSpan={99}>PROJECTED LINES</td></tr>
                {Object.keys(p.lines).map((k) => (
                  <tr key={k}>
                    <td className="l amber">{k}</td>
                    {p.years_hist.map((_: string, i: number) => <td key={i} className="muted">{fmtNum(p.history[k]?.[i], 1)}</td>)}
                    {p.lines[k].map((v: number, i: number) => <td key={i}>{fmtNum(v, 1)}</td>)}
                    <td className="l muted" style={{ maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis' }} title={`${p.provenance[k]?.method}: ${p.provenance[k]?.formula}`}>{p.provenance[k]?.method}: {p.provenance[k]?.formula}</td>
                    <td className={`l ${p.provenance[k]?.source ? '' : 'muted'}`} style={{ maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' }} title={p.provenance[k]?.source ?? ''}>{p.provenance[k]?.source ?? '—'}</td>
                  </tr>
                ))}
                <tr className="group"><td colSpan={99}>DERIVED (P&L / CASH FLOW)</td></tr>
                {KEY_DERIVED.map((k) => (
                  <tr key={k}>
                    <td className="l">{k}</td>
                    {p.years_hist.map((_: string, i: number) => <td key={i} className="muted">{fmtNum(p.history_derived?.[k]?.[i], 1)}</td>)}
                    {p.derived[k].map((v: number | null, i: number) => <td key={i}>{fmtNum(v, 1)}</td>)}
                    <td className="l muted">{p.derived_formulas[k]}</td>
                    <td />
                  </tr>
                ))}
                {RATIOS.map((k) => (
                  <tr key={k}>
                    <td className="l">{k}</td>
                    {p.years_hist.map((_: string, i: number) => <td key={i} className="muted">{fmtPct((p.history_derived?.[k]?.[i] ?? NaN) * 100, 1, false)}</td>)}
                    {p.derived[k].map((v: number | null, i: number) => <td key={i}>{fmtPct(v != null ? v * 100 : null, 1, false)}</td>)}
                    <td className="l muted">{p.derived_formulas[k]}</td>
                    <td />
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="cols">
              <Valuation v={res.valuation} />
              <div className="box">
                <h4>GUARDRAIL CHECKS</h4>
                <table className="t">
                  <tbody>
                    {res.checks.map((c: any) => (
                      <tr key={c.id}>
                        <td className="l"><span className={`badge ${c.status.toLowerCase()}`}>{c.status}</span></td>
                        <td className="l" style={{ whiteSpace: 'normal' }}>{c.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {res.scenarios && (
                <div className="box">
                  <h4>SCENARIOS</h4>
                  <table className="t">
                    <thead><tr><th className="l">SCENARIO</th><th>PROB</th>{Object.keys(Object.values(res.scenarios).find((s: any) => s.outputs) as any ? (Object.values(res.scenarios).find((s: any) => s.outputs) as any).outputs : {}).map((o) => <th key={o}>{o.split('.').slice(-2).join('.')}</th>)}</tr></thead>
                    <tbody>
                      {Object.entries(res.scenarios).map(([k, s]: any) => (
                        <tr key={k}>
                          <td className="l amber">{k}</td>
                          <td>{s.probability != null ? fmtPct(s.probability * 100, 0, false) : ''}</td>
                          {s.error ? <td className="l down" colSpan={9}>{s.error}</td> : Object.values(s.outputs ?? s).map((v: any, i) => <td key={i}>{fmtNum(v, 1)}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {res.monte_carlo && !res.monte_carlo.error && (
                <div className="box">
                  <h4>MONTE CARLO ({res.monte_carlo.valid}/{res.monte_carlo.n}, seed {res.monte_carlo.seed}) — {res.monte_carlo.output}</h4>
                  <div className="kv">
                    {Object.entries(res.monte_carlo.percentiles).map(([k, v]: any) => [<span key={k}>{k}</span>, <span key={k + 'v'}>{fmtNum(v, 1)}</span>])}
                    <span>mean ± sd</span><span>{fmtNum(res.monte_carlo.mean, 1)} ± {fmtNum(res.monte_carlo.sd, 1)}</span>
                    {res.monte_carlo.prob_above_current != null && (<><span>P(&gt; current)</span><span>{fmtPct(res.monte_carlo.prob_above_current * 100, 1, false)}</span></>)}
                  </div>
                  <Histogram h={res.monte_carlo.histogram} />
                </div>
              )}
            </div>
            {res.sensitivity && (
              <div className="box" style={{ margin: 6 }}>
                <h4>SENSITIVITY — {res.sensitivity.output} (rows: {res.sensitivity.y.path}, cols: {res.sensitivity.x.path})</h4>
                <table className="t">
                  <thead><tr><th className="l" />{res.sensitivity.x.values.map((x: number) => <th key={x}>{x}</th>)}</tr></thead>
                  <tbody>
                    {res.sensitivity.grid.map((row: (number | null)[], i: number) => {
                      const mid = res.sensitivity.grid[Math.floor(res.sensitivity.grid.length / 2)][Math.floor(row.length / 2)] ?? 1;
                      return (
                        <tr key={i}>
                          <td className="l amber">{res.sensitivity.y.values[i]}</td>
                          {row.map((v, j) => <td key={j} style={{ background: heat(v != null ? ((v - mid) / Math.abs(mid)) * 100 : null, 20) }}>{fmtNum(v, 0)}</td>)}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        {tab === 'result' && !res && !err && <Loading what="RUN A MODEL" />}
      </div>
    </div>
  );
}

function Valuation({ v }: { v: any }) {
  if (!v) return <div className="box"><h4>VALUATION</h4><div className="note">no valuation block in spec</div></div>;
  return (
    <div className="box">
      <h4>VALUATION (per share)</h4>
      <table className="t">
        <tbody>
          {v.dcf && Object.entries(v.dcf.methods).map(([k, m]: any) => (
            <tr key={k}><td className="l amber">DCF · {k}</td><td>{fmtNum(m.price_per_share, 0)}</td><td className="muted">EV {fmtNum(m.enterprise_value, 0)} · TV {fmtPct(m.tv_share_of_ev * 100, 0, false)}</td></tr>
          ))}
          {v.dcf && <tr><td className="l muted">WACC</td><td>{fmtPct(v.dcf.wacc.wacc * 100, 2, false)}</td><td className="muted">{v.dcf.wacc.formula}</td></tr>}
          {v.multiples && ['per', 'ev_ebitda', 'pbr'].filter((k) => v.multiples[k]).map((k) => (
            <tr key={k}><td className="l amber">{k.toUpperCase()} × {v.multiples[k].multiple}</td><td>{fmtNum(v.multiples[k].price, 0)}</td><td /></tr>
          ))}
          {v.ddm && <tr><td className="l amber">DDM</td><td>{fmtNum(v.ddm.price_per_share, 0)}</td><td className="muted">ke {fmtPct(v.ddm.cost_of_equity * 100, 2, false)}</td></tr>}
          {v.residual_income && <tr><td className="l amber">Residual income</td><td>{fmtNum(v.residual_income.price_per_share, 0)}</td><td /></tr>}
          {v.upside && Object.entries(v.upside).map(([k, u]: any) => (
            <tr key={'u' + k}><td className="l muted">upside vs current · {k}</td><td className={u > 0 ? 'up' : 'down'}>{fmtPct(u * 100, 1)}</td><td /></tr>
          ))}
          {Object.entries(v.errors ?? {}).map(([k, e]: any) => <tr key={'e' + k}><td className="l down">{k}</td><td className="l down" colSpan={2}>{e}</td></tr>)}
        </tbody>
      </table>
    </div>
  );
}

function Histogram({ h }: { h: { start: number; width: number; counts: number[] } }) {
  const max = Math.max(...h.counts, 1);
  return (
    <svg width="100%" height={80} viewBox={`0 0 ${h.counts.length * 10} 80`} preserveAspectRatio="none">
      {h.counts.map((c, i) => (
        <rect key={i} x={i * 10 + 1} width={8} y={80 - (c / max) * 78} height={(c / max) * 78} fill="#ffa028">
          <title>{`${fmtNum(h.start + i * h.width, 1)}–${fmtNum(h.start + (i + 1) * h.width, 1)}: ${c}`}</title>
        </rect>
      ))}
    </svg>
  );
}

function Catalog({ c }: { c: any }) {
  return (
    <div className="pad">
      <div className="note">MECE map of the harness ({c.engine_version}). Line methods: <span className="yellow">{c.line_methods.join(', ')}</span></div>
      {c.catalog.map((layer: any) => (
        <div key={layer.layer} className="box" style={{ marginBottom: 6 }}>
          <h4>{layer.layer}</h4>
          <table className="t">
            <tbody>
              {layer.items.map((it: any) => (
                <tr key={it.id}>
                  <td className="l amber" style={{ width: 140 }}>{it.id}</td>
                  <td className="l">{it.name}</td>
                  <td className="l muted">{it.api}</td>
                  <td className="l muted" style={{ whiteSpace: 'normal' }}>{it.use ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
