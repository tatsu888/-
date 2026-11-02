import { describe, expect, it } from 'vitest';
import { parseCommand, quickResolve } from './commands';
import { bollinger, ema, heikinAshi, macd, mergeBar, rsi, sma } from './indicators';
import { squarify } from './treemap';
import { renderValue } from './xlsfmt';

describe('indicators', () => {
  it('sma/ema/rsi', () => {
    const v = Array.from({ length: 20 }, (_, i) => i + 1);
    expect(sma(v, 5)[4]).toBe(3);
    expect(ema(v, 5)[4]).toBe(3);
    expect(rsi(v)[19]).toBe(100);
    expect(bollinger(v, 5).upper[4]).toBeGreaterThan(3);
    expect(macd(v.map((x) => 100 + Math.sin(x))).line.length).toBe(20);
  });
  it('heikin ashi + mergeBar', () => {
    const b = [{ time: 1, open: 1, high: 2, low: 0.5, close: 1.5, volume: 1 }];
    expect(heikinAshi(b)[0].close).toBe(1.25);
    expect(mergeBar(b, { ...b[0], close: 3 })[0].close).toBe(3);
    expect(mergeBar(b, { ...b[0], time: 2 }).length).toBe(2);
  });
});

describe('commands', () => {
  it('parses security + function', () => {
    expect(parseCommand('AAPL GP')).toEqual({ security: 'AAPL', fn: 'GP', args: undefined });
    expect(parseCommand('7203 JP Equity DES')).toEqual({ security: '7203', fn: 'DES', args: undefined });
    expect(parseCommand('LAG oil_energy')).toEqual({ fn: 'LAG', args: 'oil_energy' });
    expect(parseCommand('NASDAQ:NVDA')).toEqual({ security: 'NASDAQ:NVDA', fn: undefined, args: undefined });
  });
  it('quick resolves', () => {
    expect(quickResolve('7203')).toBe('TSE:7203');
    expect(quickResolve('usdjpy')).toBe('FX:USDJPY');
    expect(quickResolve('BTCUSDT')).toBe('BINANCE:BTCUSDT');
    expect(quickResolve('AAPL')).toBeNull();
  });
});

describe('excel number formats', () => {
  it('renders common formats', () => {
    expect(renderValue(1234.567, '#,##0.00').text).toBe('1,234.57');
    expect(renderValue(0.1234, '0.0%').text).toBe('12.3%');
    expect(renderValue(-1500, '#,##0;(#,##0)').text).toBe('(1,500)');
    expect(renderValue(-1500, '#,##0;[Red]-#,##0').color).toBe('#ff5050');
    expect(renderValue(1234567, '#,##0,,"M"').text).toBe('1M');
    expect(renderValue(12, '0.00"x"').text).toBe('12.00x');
    expect(renderValue('2024-03-05T00:00:00', 'yyyy/mm/dd').text).toBe('2024/03/05');
    expect(renderValue(0.5, 'General').text).toBe('0.5');
  });
});

describe('treemap', () => {
  it('fills the rectangle', () => {
    const r = squarify([{ value: 6, data: 'a' }, { value: 6, data: 'b' }, { value: 4, data: 'c' }, { value: 3, data: 'd' }, { value: 2, data: 'e' }, { value: 2, data: 'f' }, { value: 1, data: 'g' }], { x: 0, y: 0, w: 6, h: 4 });
    const area = r.reduce((a, b) => a + b.w * b.h, 0);
    expect(Math.abs(area - 24)).toBeLessThan(1e-9);
    expect(r.length).toBe(7);
  });
});

import { bs, impliedVol, normCdf } from './options';
describe('black-scholes', () => {
  it('matches textbook values and put-call parity', () => {
    expect(normCdf(0)).toBeCloseTo(0.5, 7);
    const p = { S: 100, K: 100, T: 1, r: 0.05, q: 0, sigma: 0.2 };
    const c = bs({ ...p, type: 'call' });
    const put = bs({ ...p, type: 'put' });
    expect(c.price).toBeCloseTo(10.4506, 3); // Hull example
    expect(put.price).toBeCloseTo(5.5735, 3);
    expect(c.price - put.price).toBeCloseTo(100 - 100 * Math.exp(-0.05), 6);
    expect(c.delta).toBeCloseTo(0.6368, 3);
    expect(impliedVol(c.price, { ...p, type: 'call' })!).toBeCloseTo(0.2, 6);
  });
});

import { buildConditionalFormats, buildValidations, selectionStats } from '../functions/XlsTools';
import { colLetter, parseAddr } from './xlsfmt';
describe('excel conditional formatting', () => {
  const vals: Record<string, number> = { A1: 0, A2: 50, A3: 100, B1: -5, B2: 3 };
  const v = (a: string) => vals[a];
  it('cellIs, colorScale and dataBar', () => {
    const out = buildConditionalFormats([
      { ranges: ['B1:B2'], type: 'cellIs', operator: 'lessThan', values: [0], fill: 'FFC7CE', font: '9C0006' },
      { ranges: ['A1:A3'], type: 'colorScale', cfvo: [{ type: 'min', val: null }, { type: 'max', val: null }], colors: ['000000', 'FFFFFF'] },
      { ranges: ['A1:A3'], type: 'dataBar', color: '638EC6' },
    ], v, parseAddr, colLetter);
    expect(out.B1).toMatchObject({ bg: '#FFC7CE', color: '#9C0006' });
    expect(out.B2).toBeUndefined();
    expect(out.A1.bg).toBe('#000000');
    expect(out.A2.bg).toBe('#808080');
    expect(out.A3.bar?.pct).toBe(100);
  });
  it('validations and stats', () => {
    expect(buildValidations([{ ranges: ['C1:C2'], options: ['Base', 'Bull'] }], parseAddr, colLetter).C2).toEqual(['Base', 'Bull']);
    expect(selectionStats([1, 2, 'x', null, 3])).toMatchObject({ count: 4, nums: 3, sum: 6, avg: 2, min: 1, max: 3 });
  });
});

import { atr, ichimoku, stochastic } from './indicators';
describe('stoch / atr / ichimoku', () => {
  const bars = Array.from({ length: 80 }, (_, i) => ({ time: i * 86400, open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i, volume: 1 }));
  it('computes', () => {
    const s = stochastic(bars);
    expect(s.k[79]).toBeCloseTo(((179.5 - 165) / (180 - 165)) * 100, 6); // close 179.5, 14-bar low 165, high 180
    expect(s.d[79]).not.toBeNull();
    expect(atr(bars)[79]).toBeCloseTo(2, 6);
    const ich = ichimoku(bars);
    expect(ich.spanA[ich.spanA.length - 1].time).toBe((79 + 26) * 86400); // projected 26 bars ahead
    expect(ich.chikou[0].time).toBe(0);
  });
});
