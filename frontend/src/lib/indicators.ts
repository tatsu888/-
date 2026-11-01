// Client-side indicators for the GP chart (recomputed on every live bar).
import type { Bar } from './types';

export type Pt = { time: number; value: number };

export function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let s = 0;
  for (let i = 0; i < values.length; i++) {
    s += values[i];
    if (i >= n) s -= values[i - n];
    if (i >= n - 1) out[i] = s / n;
  }
  return out;
}

export function ema(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < n) return out;
  const k = 2 / (n + 1);
  let prev = values.slice(0, n).reduce((a, b) => a + b, 0) / n;
  out[n - 1] = prev;
  for (let i = n; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

export function rsi(values: number[], n = 14): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length <= n) return out;
  let g = 0,
    l = 0;
  for (let i = 1; i <= n; i++) {
    const d = values[i] - values[i - 1];
    g += Math.max(d, 0);
    l += Math.max(-d, 0);
  }
  let ag = g / n,
    al = l / n;
  out[n] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  for (let i = n + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    ag = (ag * (n - 1) + Math.max(d, 0)) / n;
    al = (al * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  }
  return out;
}

export function macd(values: number[], f = 12, s = 26, sig = 9) {
  const ef = ema(values, f),
    es = ema(values, s);
  const line = values.map((_, i) => (ef[i] != null && es[i] != null ? ef[i]! - es[i]! : null));
  const start = line.findIndex((v) => v != null);
  const sigPart = start < 0 ? [] : ema(line.slice(start) as number[], sig);
  const signal = [...new Array(Math.max(start, 0)).fill(null), ...sigPart];
  const hist = line.map((v, i) => (v != null && signal[i] != null ? v - signal[i]! : null));
  return { line, signal, hist };
}

export function bollinger(values: number[], n = 20, k = 2) {
  const mid = sma(values, n);
  const upper: (number | null)[] = [],
    lower: (number | null)[] = [];
  for (let i = 0; i < values.length; i++) {
    if (mid[i] == null) {
      upper.push(null);
      lower.push(null);
      continue;
    }
    const w = values.slice(i - n + 1, i + 1);
    const m = mid[i]!;
    const sd = Math.sqrt(w.reduce((a, v) => a + (v - m) ** 2, 0) / n);
    upper.push(m + k * sd);
    lower.push(m - k * sd);
  }
  return { mid, upper, lower };
}

/** VWAP resetting each UTC day (intraday) — for daily+ bars it's a cumulative VWAP. */
export function vwap(bars: Bar[], intraday: boolean): (number | null)[] {
  let pv = 0,
    vol = 0,
    day = -1;
  return bars.map((b) => {
    const d = Math.floor(b.time / 86400);
    if (intraday && d !== day) {
      pv = 0;
      vol = 0;
      day = d;
    }
    const tp = (b.high + b.low + b.close) / 3;
    pv += tp * b.volume;
    vol += b.volume;
    return vol > 0 ? pv / vol : null;
  });
}

export function atr(bars: Bar[], n = 14): (number | null)[] {
  const tr = bars.map((b, i) =>
    i === 0 ? b.high - b.low : Math.max(b.high - b.low, Math.abs(b.high - bars[i - 1].close), Math.abs(b.low - bars[i - 1].close)),
  );
  const out: (number | null)[] = new Array(bars.length).fill(null);
  if (bars.length < n) return out;
  let a = tr.slice(0, n).reduce((x, y) => x + y, 0) / n;
  out[n - 1] = a;
  for (let i = n; i < bars.length; i++) {
    a = (a * (n - 1) + tr[i]) / n;
    out[i] = a;
  }
  return out;
}

export function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const close = (b.open + b.high + b.low + b.close) / 4;
    const open = i === 0 ? (b.open + b.close) / 2 : (out[i - 1].open + out[i - 1].close) / 2;
    out.push({ time: b.time, open, close, high: Math.max(b.high, open, close), low: Math.min(b.low, open, close), volume: b.volume });
  }
  return out;
}

export function toPts(bars: Bar[], vals: (number | null)[]): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i < bars.length; i++) if (vals[i] != null && isFinite(vals[i]!)) out.push({ time: bars[i].time, value: vals[i]! });
  return out;
}

/** Merge a live bar into a bar array (replace same time, append newer). */
export function mergeBar(bars: Bar[], bar: Bar): Bar[] {
  if (!bars.length) return [bar];
  const last = bars[bars.length - 1];
  if (bar.time === last.time) return [...bars.slice(0, -1), bar];
  if (bar.time > last.time) return [...bars, bar];
  return bars;
}
