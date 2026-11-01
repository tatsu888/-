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
