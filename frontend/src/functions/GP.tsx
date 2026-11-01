// GP — price chart (lightweight-charts v5): chart types, intervals, indicators,
// compare overlay, log scale, drawings (h-line / trend / fib), alerts, CSV export.
import { useEffect, useRef, useState } from 'react';
import {
  AreaSeries, BarSeries, CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle,
  createChart, type IChartApi, type IPriceLine, type ISeriesApi, type MouseEventParams, type Time, type UTCTimestamp,
} from 'lightweight-charts';
import { api } from '../lib/api';
import { useBars, useQuotes } from '../lib/feed';
import { cls, fmtBig, fmtPct, fmtPrice, fmtTime } from '../lib/format';
import { bollinger, ema, heikinAshi, macd, mergeBar, rsi, sma, toPts, vwap } from '../lib/indicators';
import type { Bar } from '../lib/types';
import { DelayBadge } from '../components/ui';
import { useTerminal } from '../ctx';

const INTERVALS = ['1', '5', '15', '30', '60', '240', '1D', '1W', '1M'];
const IV_LABEL: Record<string, string> = { '1': '1m', '5': '5m', '15': '15m', '30': '30m', '60': '1H', '240': '4H', '1D': 'D', '1W': 'W', '1M': 'M' };
const TYPES = ['CANDLE', 'BAR', 'LINE', 'AREA', 'HA'] as const;
const INDS = ['VOL', 'SMA20', 'SMA50', 'SMA200', 'EMA20', 'BB', 'VWAP', 'RSI', 'MACD'] as const;
const COMPARE_COLORS = ['#59e3ff', '#ff6ad5', '#ffd84a', '#a98bff', '#ff9f43'];
type Ind = (typeof INDS)[number];
interface Drawings {
  hlines: number[];
  trends: { t1: number; p1: number; t2: number; p2: number }[];
  fibs: { p1: number; p2: number }[];
}

const t = (x: number) => x as UTCTimestamp;
const loadPref = <T,>(k: string, d: T): T => {
  try {
    const v = localStorage.getItem(k);
    return v ? (JSON.parse(v) as T) : d;
  } catch {
    return d;
  }
};
const savePref = (k: string, v: unknown) => {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* ignore */
  }
};

export default function GP({ symbol }: { symbol: string }) {
  const { toast } = useTerminal();
  const [interval, setIv] = useState<string>(() => loadPref('gp.iv', '1D'));
  const [type, setType] = useState<(typeof TYPES)[number]>(() => loadPref('gp.type', 'CANDLE'));
  const [inds, setInds] = useState<Ind[]>(() => loadPref('gp.inds', ['VOL', 'SMA20', 'SMA50']));
  const [logScale, setLog] = useState(false);
  const [compare, setCompare] = useState<string[]>([]);
  const [cmpInput, setCmpInput] = useState('');
  const [mode, setMode] = useState<'none' | 'hline' | 'trend' | 'fib'>('none');
  const [bars, setBars] = useState<Bar[]>([]);
  const [cmpBars, setCmpBars] = useState<Record<string, Bar[]>>({});
  const [err, setErr] = useState<string>();
  const [legend, setLegend] = useState<Bar | null>(null);
  const [lastClick, setLastClick] = useState<number | null>(null);
  const [draw, setDraw] = useState<Drawings>(() => loadPref(`draw:${symbol}`, { hlines: [], trends: [], fibs: [] }));
  const pending = useRef<{ time: number; price: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const main = useRef<ISeriesApi<any> | null>(null);
  const extra = useRef<ISeriesApi<any>[]>([]);
  const lines = useRef<IPriceLine[]>([]);
  const barsRef = useRef<Bar[]>([]);
  const q = useQuotes([symbol]).get(symbol);

  useEffect(() => savePref('gp.iv', interval), [interval]);
  useEffect(() => savePref('gp.type', type), [type]);
  useEffect(() => savePref('gp.inds', inds), [inds]);
  useEffect(() => setDraw(loadPref(`draw:${symbol}`, { hlines: [], trends: [], fibs: [] })), [symbol]);
  useEffect(() => savePref(`draw:${symbol}`, draw), [symbol, draw]);

  // load history
  useEffect(() => {
    let alive = true;
    setErr(undefined);
    setBars([]);
    api
      .get<{ bars: Bar[] }>('/history', { symbol, interval, bars: interval.endsWith('M') || interval.endsWith('W') ? 500 : 800 })
      .then((r) => alive && setBars(r.bars))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [symbol, interval]);

  useEffect(() => {
    let alive = true;
    Promise.all(compare.map((s) => api.get<{ bars: Bar[] }>('/history', { symbol: s, interval, bars: 800 }).then((r) => [s, r.bars] as const)))
      .then((rs) => alive && setCmpBars(Object.fromEntries(rs)))
      .catch((e) => toast(`compare: ${e.message}`));
    return () => {
      alive = false;
    };
  }, [compare.join(','), interval]); // eslint-disable-line react-hooks/exhaustive-deps

  // create chart once
  useEffect(() => {
    const c = createChart(box.current!, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#000000' }, textColor: '#b0b0b0', fontFamily: 'IBM Plex Mono, Consolas, monospace', fontSize: 11, panes: { separatorColor: '#2a2a2a' } },
      grid: { vertLines: { color: '#141414' }, horzLines: { color: '#141414' } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: '#ffa028', labelBackgroundColor: '#ffa028' }, horzLine: { color: '#ffa028', labelBackgroundColor: '#ffa028' } },
      rightPriceScale: { borderColor: '#2a2a2a' },
      timeScale: { borderColor: '#2a2a2a', timeVisible: true, secondsVisible: false },
    });
    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
      main.current = null;
      extra.current = [];
    };
  }, []);

  // (re)build all series when data or settings change
  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    for (const s of [main.current, ...extra.current]) if (s) c.removeSeries(s);
    extra.current = [];
    lines.current = [];
    main.current = null;
    while (c.panes().length > 1) c.removePane(c.panes().length - 1);
    if (!bars.length) return;
    barsRef.current = bars;
    const pct = compare.length > 0;
    const up = '#2fd17a', down = '#ff4545';
    let m: ISeriesApi<any>;
    if (type === 'LINE') m = c.addSeries(LineSeries, { color: '#ffa028', lineWidth: 2 });
    else if (type === 'AREA') m = c.addSeries(AreaSeries, { lineColor: '#ffa028', topColor: 'rgba(255,160,40,0.35)', bottomColor: 'rgba(255,160,40,0.02)' });
    else if (type === 'BAR') m = c.addSeries(BarSeries, { upColor: up, downColor: down });
    else m = c.addSeries(CandlestickSeries, { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down });
    main.current = m;
    c.priceScale('right').applyOptions({ mode: pct ? 2 : logScale ? 1 : 0 });
    const add = (s: ISeriesApi<any>) => (extra.current.push(s), s);
    if (inds.includes('VOL')) {
      const v = add(c.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false }));
      c.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      (v as any)._kind = 'VOL';
    }
    const line = (color: string, kind: string, pane = 0, width = 1) => {
      const s = add(c.addSeries(LineSeries, { color, lineWidth: width as any, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false }, pane));
      (s as any)._kind = kind;
      return s;
    };
    if (inds.includes('SMA20')) line('#59e3ff', 'SMA20');
    if (inds.includes('SMA50')) line('#ff6ad5', 'SMA50');
    if (inds.includes('SMA200')) line('#ffffff', 'SMA200');
    if (inds.includes('EMA20')) line('#ffd84a', 'EMA20');
    if (inds.includes('BB')) {
      line('#5ea9ff', 'BBU');
      line('#5ea9ff', 'BBM');
      line('#5ea9ff', 'BBL');
    }
    if (inds.includes('VWAP')) line('#a98bff', 'VWAP', 0, 2);
    let pane = 1;
    if (inds.includes('RSI')) {
      const r = line('#ffa028', 'RSI', pane);
      r.createPriceLine({ price: 70, color: '#ff4545', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' });
      r.createPriceLine({ price: 30, color: '#2fd17a', lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' });
      pane++;
    }
    if (inds.includes('MACD')) {
      const h = add(c.addSeries(HistogramSeries, { lastValueVisible: false, priceLineVisible: false }, pane));
      (h as any)._kind = 'MACDH';
      line('#59e3ff', 'MACD', pane);
      line('#ff6ad5', 'MACDS', pane);
      pane++;
    }
    c.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 3 : 1));
    compare.forEach((s, i) => {
      const cs = line(COMPARE_COLORS[i % COMPARE_COLORS.length], `CMP:${s}`, 0, 2);
      cs.applyOptions({ lastValueVisible: true, title: s.split(':').pop() });
    });
    applyData(bars);
    // drawings
    for (const p of draw.hlines) lines.current.push(m.createPriceLine({ price: p, color: '#ffd84a', lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: 'H' }));
    for (const f of draw.fibs) {
      for (const lv of [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]) {
        const price = f.p2 + (f.p1 - f.p2) * lv;
        lines.current.push(m.createPriceLine({ price, color: '#a98bff', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: `${(lv * 100).toFixed(1)}%` }));
      }
    }
    for (const tr of draw.trends) {
      if (tr.t1 === tr.t2) continue;
      const pts = [{ time: t(tr.t1), value: tr.p1 }, { time: t(tr.t2), value: tr.p2 }].sort((a, b) => (a.time as number) - (b.time as number));
      const s = add(c.addSeries(LineSeries, { color: '#ffd84a', lineWidth: 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false }));
      s.setData(pts);
    }
    c.timeScale().fitContent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, type, inds.join(','), logScale, compare.join(','), cmpBars, draw]);

  function applyData(all: Bar[]) {
    const m = main.current;
    if (!m) return;
    const src = type === 'HA' ? heikinAshi(all) : all;
    if (type === 'LINE' || type === 'AREA') m.setData(all.map((b) => ({ time: t(b.time), value: b.close })));
    else m.setData(src.map((b) => ({ time: t(b.time), open: b.open, high: b.high, low: b.low, close: b.close })));
    const closes = all.map((b) => b.close);
    const intraday = !['1D', '1W', '1M'].includes(interval);
    const bb = inds.includes('BB') ? bollinger(closes) : null;
    const md = inds.includes('MACD') ? macd(closes) : null;
    for (const s of extra.current) {
      const k = (s as any)._kind as string | undefined;
      if (!k) continue;
      const pts = (vals: (number | null)[]) => toPts(all, vals).map((p) => ({ time: t(p.time), value: p.value }));
      if (k === 'VOL') s.setData(all.map((b) => ({ time: t(b.time), value: b.volume, color: b.close >= b.open ? 'rgba(47,209,122,0.45)' : 'rgba(255,69,69,0.45)' })));
      else if (k === 'SMA20') s.setData(pts(sma(closes, 20)));
      else if (k === 'SMA50') s.setData(pts(sma(closes, 50)));
      else if (k === 'SMA200') s.setData(pts(sma(closes, 200)));
      else if (k === 'EMA20') s.setData(pts(ema(closes, 20)));
      else if (k === 'BBU') s.setData(pts(bb!.upper));
      else if (k === 'BBM') s.setData(pts(bb!.mid));
      else if (k === 'BBL') s.setData(pts(bb!.lower));
      else if (k === 'VWAP') s.setData(pts(vwap(all, intraday)));
      else if (k === 'RSI') s.setData(pts(rsi(closes)));
      else if (k === 'MACD') s.setData(pts(md!.line));
      else if (k === 'MACDS') s.setData(pts(md!.signal));
      else if (k === 'MACDH') s.setData(toPts(all, md!.hist).map((p) => ({ time: t(p.time), value: p.value, color: p.value >= 0 ? '#2fd17a' : '#ff4545' })));
      else if (k.startsWith('CMP:')) {
        const cb = cmpBars[k.slice(4)] ?? [];
        s.setData(cb.map((b) => ({ time: t(b.time), value: b.close })));
      }
    }
  }

  // live bars
  useBars(symbol, interval, (bar) => {
    if (!barsRef.current.length) return;
    const merged = mergeBar(barsRef.current, bar);
    if (merged === barsRef.current) return;
    barsRef.current = merged;
    applyData(merged);
  });

  // crosshair legend + drawing clicks
  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const onMove = (p: MouseEventParams<Time>) => {
      if (!p.time) return setLegend(null);
      const b = barsRef.current.find((x) => x.time === (p.time as number));
      setLegend(b ?? null);
    };
    const onClick = (p: MouseEventParams<Time>) => {
      if (!main.current || !p.point) return;
      const price = main.current.coordinateToPrice(p.point.y);
      if (price == null) return;
      setLastClick(price);
      const time = (p.time as number) ?? barsRef.current[barsRef.current.length - 1]?.time;
      if (mode === 'hline') {
        setDraw((d) => ({ ...d, hlines: [...d.hlines, price] }));
        setMode('none');
      } else if (mode === 'trend' || mode === 'fib') {
        if (!pending.current) pending.current = { time, price };
        else {
          const a = pending.current;
          pending.current = null;
          if (mode === 'trend') setDraw((d) => ({ ...d, trends: [...d.trends, { t1: a.time, p1: a.price, t2: time, p2: price }] }));
          else setDraw((d) => ({ ...d, fibs: [...d.fibs, { p1: a.price, p2: price }] }));
          setMode('none');
        }
      }
    };
    c.subscribeCrosshairMove(onMove);
    c.subscribeClick(onClick);
    return () => {
      c.unsubscribeCrosshairMove(onMove);
      c.unsubscribeClick(onClick);
    };
  }, [mode]);

  const toggle = (k: Ind) => setInds((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));
  const lb = legend ?? bars[bars.length - 1];

  async function alertAt() {
    if (lastClick == null) return toast('chart をクリックして価格を選択してください');
    const cond = q?.last != null && lastClick > q.last ? 'cross_up' : 'cross_down';
    await api.post('/alerts', { symbol, condition: cond, value: Number(lastClick.toPrecision(6)), note: 'from chart' });
    toast(`ALERT ${symbol} ${cond} ${fmtPrice(lastClick)}`);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="toolbar">
        {INTERVALS.map((iv) => (
          <button key={iv} className={`tb ${iv === interval ? 'on' : ''}`} onClick={() => setIv(iv)}>
            {IV_LABEL[iv]}
          </button>
        ))}
        <span className="lbl">│</span>
        {TYPES.map((ty) => (
          <button key={ty} className={`tb ${ty === type ? 'on' : ''}`} onClick={() => setType(ty)}>
            {ty}
          </button>
        ))}
        <button className={`tb ${logScale ? 'on' : ''}`} onClick={() => setLog(!logScale)}>
          LOG
        </button>
        <span className="lbl">│</span>
        {INDS.map((k) => (
          <button key={k} className={`tb ${inds.includes(k) ? 'on' : ''}`} onClick={() => toggle(k)}>
            {k}
          </button>
        ))}
      </div>
      <div className="toolbar">
        <span className="lbl">DRAW</span>
        {(['hline', 'trend', 'fib'] as const).map((m) => (
          <button key={m} className={`tb ${mode === m ? 'on' : ''}`} onClick={() => ((pending.current = null), setMode(mode === m ? 'none' : m))}>
            {m.toUpperCase()}
          </button>
        ))}
        <button className="tb" onClick={() => setDraw({ hlines: [], trends: [], fibs: [] })}>
          CLEAR
        </button>
        <button className="tb" onClick={alertAt} title="クリックした価格でアラート作成">
          ALERT@{lastClick != null ? fmtPrice(lastClick) : '—'}
        </button>
        <span className="lbl">COMPARE</span>
        <input
          className="inp"
          style={{ width: 120 }}
          value={cmpInput}
          placeholder="SP:SPX"
          onChange={(e) => setCmpInput(e.target.value.toUpperCase())}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && cmpInput) {
              setCompare((c) => [...new Set([...c, cmpInput.includes(':') ? cmpInput : /^\d{4}$/.test(cmpInput) ? `TSE:${cmpInput}` : `NASDAQ:${cmpInput}`])]);
              setCmpInput('');
            }
          }}
        />
        {compare.map((c) => (
          <button key={c} className="tb" onClick={() => setCompare((x) => x.filter((y) => y !== c))} title="remove">
            {c} ✕
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <a className="tb" href={api.url('/history.csv', { symbol, interval, bars: 2000 })}>
          CSV
        </a>
      </div>
      <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
        <div className="legend">
          <span className="amber">{symbol}</span>
          <DelayBadge q={q} /> <span className={cls(q?.change)}>{fmtPrice(q?.last)}</span> <span className={cls(q?.change_pct)}>{fmtPct(q?.change_pct)}</span>
          {lb && (
            <>
              <br />
              <span className="muted">{fmtTime(lb.time, true)}</span>
              <span>O {fmtPrice(lb.open)}</span>
              <span>H {fmtPrice(lb.high)}</span>
              <span>L {fmtPrice(lb.low)}</span>
              <span className={cls(lb.close - lb.open)}>C {fmtPrice(lb.close)}</span>
              <span>V {fmtBig(lb.volume)}</span>
            </>
          )}
          {mode !== 'none' && <div className="yellow">{mode.toUpperCase()}: {mode === 'hline' ? 'click a price' : pending.current ? 'click 2nd point' : 'click 1st point'}</div>}
          {compare.length > 0 && <div className="muted">COMPARE MODE: % scale</div>}
        </div>
        {err && <div className="err" style={{ position: 'absolute', top: 40, zIndex: 6 }}>{err}</div>}
        <div ref={box} className="chart" />
      </div>
    </div>
  );
}
