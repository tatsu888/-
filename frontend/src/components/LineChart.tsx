// Generic multi-line time-series chart (factor RS curves, rolling correlation, equity curves).
import { useEffect, useRef } from 'react';
import { ColorType, LineSeries, createChart, type IChartApi, type UTCTimestamp } from 'lightweight-charts';

export const PALETTE = ['#ffa028', '#59e3ff', '#ff6ad5', '#2fd17a', '#ffd84a', '#a98bff', '#ff4545', '#5ea9ff', '#ffffff', '#ff9f43', '#7bed9f', '#c8d6e5'];

export interface LineDef {
  name: string;
  data: { time: number; value: number }[];
  color?: string;
}

export function LineChart({ lines, height = 260, baseline }: { lines: LineDef[]; height?: number; baseline?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  useEffect(() => {
    const c = createChart(el.current!, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: '#000' }, textColor: '#aaa', fontSize: 10, fontFamily: 'IBM Plex Mono, Consolas, monospace' },
      grid: { vertLines: { color: '#141414' }, horzLines: { color: '#141414' } },
      rightPriceScale: { borderColor: '#2a2a2a' },
      timeScale: { borderColor: '#2a2a2a' },
    });
    chart.current = c;
    return () => {
      chart.current = null; // series cleanup below must not touch a removed chart
      c.remove();
    };
  }, []);
  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const series = lines.map((l, i) => {
      const s = c.addSeries(LineSeries, { color: l.color ?? PALETTE[i % PALETTE.length], lineWidth: 2, title: l.name, priceLineVisible: false });
      const dedup = new Map<number, number>();
      for (const p of l.data) dedup.set(p.time, p.value);
      s.setData([...dedup.entries()].sort((a, b) => a[0] - b[0]).map(([t, v]) => ({ time: t as UTCTimestamp, value: v })));
      return s;
    });
    if (baseline != null && series[0]) series[0].createPriceLine({ price: baseline, color: '#555', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '' });
    c.timeScale().fitContent();
    return () => {
      if (chart.current === c) series.forEach((s) => c.removeSeries(s));
    };
  }, [lines, baseline]);
  return <div ref={el} style={{ height, position: 'relative' }} />;
}
