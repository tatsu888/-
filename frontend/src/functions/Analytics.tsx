// Analytics functions: FACT (factor/style), LAG (lead-lag), CORR (correlation), BT (backtest).
import { useMemo, useState } from 'react';
import { api } from '../lib/api';
import { cls, fmtNum, fmtPct, heat, shortSym } from '../lib/format';
import { Bars, ErrorBox, Loading, useAsync } from '../components/ui';
import { LineChart } from '../components/LineChart';
import { useTerminal } from '../ctx';

const SOURCES = ['', 'tradingview', 'yahoo', 'sim'];
function SourcePick({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <>
      <span className="lbl">SOURCE</span>
      <select className="inp" value={value} onChange={(e) => onChange(e.target.value)} title="history source for this analysis (blank = active)">
        {SOURCES.map((s) => (
          <option key={s} value={s}>{s || '(active)'}</option>
        ))}
      </select>
    </>
  );
}

// ---------------------------------------------------------------- FACT
export function FACT({ args }: { args?: string }) {
  const { universe } = useTerminal();
  const [mode, setMode] = useState<'etf' | 'xs'>(args?.toLowerCase().includes('xs') ? 'xs' : 'etf');
  const [set, setSet] = useState(args?.toUpperCase().includes('JP') ? 'JP' : 'US');
  const [market, setMarket] = useState(args?.toUpperCase().includes('JP') ? 'japan' : 'america');
  const [source, setSource] = useState('');
  const etf = useAsync(() => (mode === 'etf' ? api.get<any>('/analytics/factors/etf', { set, source }) : Promise.resolve(null)), [mode, set, source]);
  const xs = useAsync(() => (mode === 'xs' ? api.get<any>('/analytics/factors/cross_section', { market, limit: 500 }) : Promise.resolve(null)), [mode, market]);
  const curves = useMemo(() => Object.entries(etf.data?.curves ?? {}).map(([name, data]) => ({ name, data: data as any })), [etf.data]);
  const W = ['1W', '1M', '3M', '6M', 'YTD', '1Y'];
  return (
    <div>
      <div className="toolbar">
        <button className={`tb ${mode === 'etf' ? 'on' : ''}`} onClick={() => setMode('etf')}>ETF PROXY</button>
        <button className={`tb ${mode === 'xs' ? 'on' : ''}`} onClick={() => setMode('xs')}>CROSS-SECTION</button>
        {mode === 'etf' ? (
          <>
            <span className="lbl">SET</span>
            {Object.keys(universe?.factor_sets ?? {}).map((k) => (
              <button key={k} className={`tb ${k === set ? 'on' : ''}`} onClick={() => setSet(k)}>{k}</button>
            ))}
            <SourcePick value={source} onChange={setSource} />
          </>
        ) : (
          <>
            <span className="lbl">MARKET</span>
            {['america', 'japan', 'europe', 'uk', 'germany', 'china', 'india'].map((m) => (
              <button key={m} className={`tb ${m === market ? 'on' : ''}`} onClick={() => setMarket(m)}>{m}</button>
            ))}
          </>
        )}
      </div>
      {mode === 'etf' && (
        <>
          {etf.loading && <Loading />}
          <ErrorBox error={etf.error} />
          {etf.data && (
            <>
              <div className="note">
                Excess return vs <span className="amber">{etf.data.benchmark}</span> (%pt). 1M leaders: <span className="up">{etf.data.leaders_1M.join(', ')}</span> · laggards: <span className="down">{etf.data.laggards_1M.join(', ')}</span>
              </div>
              <table className="t">
                <thead><tr><th className="l">FACTOR</th><th className="l">ETF</th>{W.map((w) => <th key={w}>{w}</th>)}</tr></thead>
                <tbody>
                  {etf.data.rows.map((r: any) => (
                    <tr key={r.factor}>
                      <td className="l amber">{r.factor}</td>
                      <td className="l muted">{shortSym(etf.data.symbols[r.factor] ?? '')}</td>
                      {r.error ? <td colSpan={W.length} className="l down">{r.error}</td> : W.map((w) => <td key={w} style={{ background: heat(r[w], 5) }}>{fmtNum(r[w], 2)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="note">Relative strength (factor / benchmark, start = 100)</div>
              <LineChart lines={curves} height={280} baseline={100} />
              {Object.keys(etf.data.errors ?? {}).length > 0 && <div className="note">unavailable: {Object.entries(etf.data.errors).map(([k, v]) => `${k}: ${v}`).join(' | ')}</div>}
            </>
          )}
        </>
      )}
      {mode === 'xs' && (
        <>
          {xs.loading && <Loading what="SCANNING UNIVERSE" />}
          <ErrorBox error={xs.error} />
          {xs.data && (
            <>
              <div className="note">
                Universe: top {xs.data.universe_size} stocks by market cap. Spread = top quintile − bottom quintile mean return (%pt); IC = Spearman(score, return).
                Strongest 1M: <span className="up">{xs.data.strongest_1M.join(', ')}</span> · weakest: <span className="down">{xs.data.weakest_1M.join(', ')}</span>
                <br />⚠ characteristics are as of today, returns are trailing — style attribution, not a backtest.
              </div>
              <table className="t">
                <thead><tr><th className="l">FACTOR</th><th className="l">DEFINITION</th><th>1W</th><th>1M</th><th>3M</th><th>IC 1W</th><th>IC 1M</th><th>IC 3M</th><th>N</th></tr></thead>
                <tbody>
                  {xs.data.factors.map((f: any) => (
                    <tr key={f.factor}>
                      <td className="l amber">{f.factor}</td>
                      <td className="l muted">{f.definition}</td>
                      {['1W', '1M', '3M'].map((w) => <td key={w} style={{ background: heat(f[w], 5) }}>{fmtNum(f[w], 2)}</td>)}
                      {['1W', '1M', '3M'].map((w) => <td key={w} className={cls(f[`ic_${w}`])}>{fmtNum(f[`ic_${w}`], 3)}</td>)}
                      <td className="muted">{f.n_1M}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Bars values={xs.data.factors.map((f: any) => f['1M'])} labels={xs.data.factors.map((f: any) => f.factor.split(' ')[0].slice(0, 6))} />
              <div className="note">SECTOR ROTATION (equal-weight mean return %)</div>
              <table className="t">
                <thead><tr><th className="l">SECTOR</th><th>N</th><th>1W</th><th>1M</th><th>3M</th></tr></thead>
                <tbody>
                  {xs.data.sectors.map((s: any) => (
                    <tr key={s.sector}>
                      <td className="l">{s.sector}</td>
                      <td className="muted">{s.count}</td>
                      {['1W', '1M', '3M'].map((w) => <td key={w} style={{ background: heat(s[w], 8) }}>{fmtPct(s[w])}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- LAG
export function LAG({ args, symbol }: { args?: string; symbol: string }) {
  const { universe, setSecurity } = useTerminal();
  const themes = universe?.themes ?? [];
  const [themeId, setThemeId] = useState(args && themes.some((t) => t.id === args) ? args : themes[0]?.id ?? 'us_semis_jp');
  const [custom, setCustom] = useState({ leader: '', followers: '', market: '' });
  const [useCustom, setUseCustom] = useState(false);
  const [resid, setResid] = useState(true);
  const [maxLag, setMaxLag] = useState(5);
  const [source, setSource] = useState('');
  const [pair, setPair] = useState<{ leader: string; follower: string; market?: string | null } | null>(null);
  const theme = themes.find((t) => t.id === themeId);
  const scan = useAsync(() => {
    if (useCustom) {
      if (!custom.leader || !custom.followers) return Promise.resolve(null);
      return api.get<any>('/analytics/leadlag/scan', { leader: custom.leader, followers: custom.followers, market: resid ? custom.market || undefined : undefined, max_lag: maxLag, source });
    }
    return api.get<any>(`/analytics/leadlag/theme/${themeId}`, { residualize: resid, max_lag: maxLag, source });
  }, [themeId, useCustom, custom.leader, custom.followers, custom.market, resid, maxLag, source]);
  const leader = useCustom ? custom.leader : theme?.leader;
  const market = useCustom ? custom.market : theme?.market;
  const detail = useAsync(
    () => (pair ? api.get<any>('/analytics/leadlag/pair', { leader: pair.leader, follower: pair.follower, market: pair.market ?? undefined, max_lag: maxLag, source }) : Promise.resolve(null)),
    [pair?.leader, pair?.follower, pair?.market, maxLag, source],
  );
  return (
    <div>
      <div className="toolbar">
        <button className={`tb ${!useCustom ? 'on' : ''}`} onClick={() => setUseCustom(false)}>THEMES</button>
        <button className={`tb ${useCustom ? 'on' : ''}`} onClick={() => setUseCustom(true)}>CUSTOM</button>
        {!useCustom ? (
          <select className="inp" value={themeId} onChange={(e) => (setThemeId(e.target.value), setPair(null))}>
            {themes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        ) : (
          <>
            <input className="inp" style={{ width: 120 }} placeholder="leader TVC:USOIL" value={custom.leader} onChange={(e) => setCustom({ ...custom, leader: e.target.value.toUpperCase() })} />
            <input className="inp" style={{ width: 240 }} placeholder="followers TSE:1605,TSE:5020" value={custom.followers} onChange={(e) => setCustom({ ...custom, followers: e.target.value.toUpperCase() })} />
            <input className="inp" style={{ width: 100 }} placeholder="market TVC:TOPIX" value={custom.market} onChange={(e) => setCustom({ ...custom, market: e.target.value.toUpperCase() })} />
            <button className="tb" onClick={() => setCustom({ ...custom, followers: [custom.followers, symbol].filter(Boolean).join(',') })}>+ {shortSym(symbol)}</button>
          </>
        )}
        <button className={`tb ${resid ? 'on' : ''}`} onClick={() => setResid(!resid)} title="remove market beta from followers (theme-specific effect)">RESIDUAL</button>
        <span className="lbl">MAX LAG</span>
        <select className="inp" value={maxLag} onChange={(e) => setMaxLag(+e.target.value)}>
          {[3, 5, 10, 20].map((x) => <option key={x}>{x}</option>)}
        </select>
        <SourcePick value={source} onChange={setSource} />
      </div>
      {!useCustom && theme && <div className="note">{theme.note} · leader <span className="amber">{theme.leader}</span>{resid && theme.market ? ` · residual vs ${theme.market}` : ''}</div>}
      <div className="note">lag +k = leader on day t−k vs follower on day t (daily, UTC-date aligned). US→Japan effects appear at lag +1. Significant = |corr| &gt; 2/√N.</div>
      {scan.loading && <Loading />}
      <ErrorBox error={scan.error} />
      {scan.data && (
        <table className="t">
          <thead><tr><th className="l">FOLLOWER</th><th>N</th><th>LAG0 CORR</th><th>BEST LAG</th><th>BEST CORR</th><th>±BAND</th><th>GRANGER p</th><th className="l">SIG</th></tr></thead>
          <tbody>
            {scan.data.rows.map((r: any) => (
              <tr key={r.symbol} className={`click ${pair?.follower === r.symbol ? 'sel' : ''}`} onClick={() => (setPair({ leader: leader!, follower: r.symbol, market: resid ? market : null }), setSecurity(r.symbol))}>
                <td className="l sym">{r.symbol}</td>
                {r.error ? <td colSpan={7} className="l down">{r.error}</td> : (
                  <>
                    <td className="muted">{r.observations}</td>
                    <td className={cls(r.lag0_corr)}>{fmtNum(r.lag0_corr, 3)}</td>
                    <td className="yellow">+{r.best_lag}</td>
                    <td className={cls(r.best_corr)}>{fmtNum(r.best_corr, 3)}</td>
                    <td className="muted">{fmtNum(r.band, 3)}</td>
                    <td className={r.granger_p != null && r.granger_p < 0.05 ? 'up' : 'muted'}>{fmtNum(r.granger_p, 4)}</td>
                    <td className="l">{r.significant ? <span className="badge pass">YES</span> : <span className="muted">no</span>}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {scan.data && Object.keys(scan.data.errors ?? {}).length > 0 && <div className="note">unavailable: {Object.entries(scan.data.errors).map(([k, v]) => `${k}: ${v}`).join(' | ')}</div>}
      {pair && (
        <div className="box" style={{ margin: 6 }}>
          <h4>PAIR {pair.leader} → {pair.follower} {pair.market ? `(residual vs ${pair.market})` : ''}</h4>
          {detail.loading && <Loading />}
          <ErrorBox error={detail.error} />
          {detail.data && !detail.data.error && (
            <>
              <div className="note">
                {detail.data.start} → {detail.data.end} · N={detail.data.observations}
                {detail.data.market_beta != null && ` · follower beta to market ${fmtNum(detail.data.market_beta, 2)}`}
              </div>
              <div style={{ overflowX: 'auto', padding: 6 }}>
                <div className="muted">CROSS-CORRELATION by lag (blue = ±2/√N)</div>
                <Bars values={detail.data.ccf.lags.map((l: any) => l.corr)} labels={detail.data.ccf.lags.map((l: any) => (l.lag > 0 ? `+${l.lag}` : String(l.lag)))} band={detail.data.ccf.band} />
              </div>
              <table className="t">
                <thead><tr><th className="l">GRANGER TEST</th><th>LAGS</th><th>F</th><th>p-value</th></tr></thead>
                <tbody>
                  {detail.data.granger.map((g: any) => (
                    <tr key={g.p}><td className="l">leader → follower</td><td>{g.p}</td><td>{fmtNum(g.f_stat, 3)}</td><td className={g.p_value < 0.05 ? 'up' : ''}>{fmtNum(g.p_value, 4)}</td></tr>
                  ))}
                  <tr><td className="l muted">follower → leader (reverse)</td><td>1</td><td>{fmtNum(detail.data.granger_reverse_lag1.f_stat, 3)}</td><td>{fmtNum(detail.data.granger_reverse_lag1.p_value, 4)}</td></tr>
                </tbody>
              </table>
              <div className="note">ROLLING {detail.data.window}D CORRELATION at lag +{detail.data.rolling_lag} (stability)</div>
              <LineChart lines={[{ name: `corr lag+${detail.data.rolling_lag}`, data: detail.data.rolling }]} height={180} baseline={0} />
            </>
          )}
          {detail.data?.error && <div className="err">{detail.data.error}</div>}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- CORR
export function CORR({ args }: { args?: string }) {
  const { universe } = useTerminal();
  const def = args || (universe?.lists.W ?? []).slice(0, 10).map((i) => i.symbol).join(',');
  const [syms, setSyms] = useState(def);
  const [input, setInput] = useState(def);
  const [iv, setIv] = useState('1D');
  const [bars, setBars] = useState(250);
  const [source, setSource] = useState('');
  const r = useAsync(() => api.get<any>('/analytics/correlation', { symbols: syms, interval: iv, bars, source }), [syms, iv, bars, source]);
  return (
    <div>
      <div className="toolbar">
        <input className="inp" style={{ flex: 1, minWidth: 200 }} value={input} onChange={(e) => setInput(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === 'Enter' && setSyms(input)} />
        <button className="tb" onClick={() => setSyms(input)}>RUN</button>
        {['60', '1D', '1W'].map((x) => <button key={x} className={`tb ${iv === x ? 'on' : ''}`} onClick={() => setIv(x)}>{x}</button>)}
        <select className="inp" value={bars} onChange={(e) => setBars(+e.target.value)}>
          {[60, 120, 250, 500, 1000].map((x) => <option key={x}>{x}</option>)}
        </select>
        <SourcePick value={source} onChange={setSource} />
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {r.data && (
        <>
          <div className="note">Pearson correlation of log returns · {r.data.observations} common observations</div>
          <table className="t">
            <thead><tr><th className="l" />{r.data.symbols.map((s: string) => <th key={s}>{shortSym(s)}</th>)}<th>VOL/bar</th></tr></thead>
            <tbody>
              {r.data.symbols.map((a: string, i: number) => (
                <tr key={a}>
                  <td className="l sym">{shortSym(a)}</td>
                  {r.data.matrix[i].map((v: number | null, j: number) => <td key={j} style={{ background: heat(v, 1) }}>{fmtNum(v, 2)}</td>)}
                  <td className="muted">{fmtPct((r.data.volatility[a] ?? 0) * 100, 2, false)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {Object.keys(r.data.errors ?? {}).length > 0 && <div className="note">unavailable: {Object.keys(r.data.errors).join(', ')}</div>}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- BT
export function BT({ symbol }: { symbol: string }) {
  const { universe } = useTerminal();
  const strategies = universe?.strategies ?? {};
  const [strategy, setStrategy] = useState('sma_cross');
  const [params, setParams] = useState<Record<string, number>>({});
  const [iv, setIv] = useState('1D');
  const [short, setShort] = useState(false);
  const [fee, setFee] = useState(5);
  const [run, setRun] = useState(0);
  const p = { ...(strategies[strategy] ?? {}), ...params };
  const r = useAsync(() => api.post<any>('/analytics/backtest', { symbol, interval: iv, bars: 1500, strategy, params: p, allow_short: short, fee_bps: fee }), [symbol, iv, strategy, short, fee, run]);
  const lines = useMemo(() => (r.data ? [{ name: 'strategy', data: r.data.equity }, { name: 'buy & hold', data: r.data.buy_hold, color: '#666' }] : []), [r.data]);
  const s = r.data?.stats;
  return (
    <div>
      <div className="toolbar">
        <select className="inp" value={strategy} onChange={(e) => (setStrategy(e.target.value), setParams({}))}>
          {Object.keys(strategies).map((k) => <option key={k}>{k}</option>)}
        </select>
        {Object.entries(p).map(([k, v]) => (
          <span key={k}>
            <span className="lbl">{k}</span>
            <input className="inp" style={{ width: 50 }} value={v} onChange={(e) => setParams({ ...params, [k]: +e.target.value })} />
          </span>
        ))}
        {['60', '1D', '1W'].map((x) => <button key={x} className={`tb ${iv === x ? 'on' : ''}`} onClick={() => setIv(x)}>{x}</button>)}
        <button className={`tb ${short ? 'on' : ''}`} onClick={() => setShort(!short)}>LONG/SHORT</button>
        <span className="lbl">FEE bps</span>
        <input className="inp" style={{ width: 40 }} value={fee} onChange={(e) => setFee(+e.target.value)} />
        <button className="tb green" onClick={() => setRun((x) => x + 1)}>RUN</button>
      </div>
      {r.loading && <Loading />}
      <ErrorBox error={r.error} />
      {s && (
        <>
          <div className="kv" style={{ gridTemplateColumns: 'repeat(4, max-content 1fr)' }}>
            <span>Total Return</span><span className={cls(s.total_return_pct)}>{fmtPct(s.total_return_pct)}</span>
            <span>Buy & Hold</span><span className={cls(s.buy_hold_return_pct)}>{fmtPct(s.buy_hold_return_pct)}</span>
            <span>CAGR</span><span>{fmtPct(s.cagr_pct)}</span>
            <span>Max DD</span><span className="down">{fmtPct(s.max_drawdown_pct)}</span>
            <span>Sharpe</span><span>{fmtNum(s.sharpe, 2)}</span>
            <span>Trades</span><span>{s.trades}</span>
            <span>Win Rate</span><span>{fmtPct(s.win_rate_pct, 1, false)}</span>
            <span>Exposure</span><span>{fmtPct(s.exposure_pct, 1, false)}</span>
          </div>
          <LineChart lines={lines} height={240} baseline={1} />
          <div className="note">signals at bar close, applied to the next bar (no look-ahead) · fee per unit of turnover</div>
          <table className="t">
            <thead><tr><th className="l">SIDE</th><th className="l">ENTRY</th><th>PRICE</th><th className="l">EXIT</th><th>PRICE</th><th>RETURN</th></tr></thead>
            <tbody>
              {[...r.data.trades].reverse().slice(0, 50).map((t: any, i: number) => (
                <tr key={i}>
                  <td className={`l ${t.side > 0 ? 'up' : 'down'}`}>{t.side > 0 ? 'LONG' : 'SHORT'}</td>
                  <td className="l muted">{new Date(t.entry_time * 1000).toISOString().slice(0, 16).replace('T', ' ')}</td>
                  <td>{fmtNum(t.entry, 2)}</td>
                  <td className="l muted">{new Date(t.exit_time * 1000).toISOString().slice(0, 16).replace('T', ' ')}{t.open ? ' (open)' : ''}</td>
                  <td>{fmtNum(t.exit, 2)}</td>
                  <td className={cls(t.return_pct)}>{fmtPct(t.return_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
