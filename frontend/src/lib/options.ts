// Black-Scholes-Merton (with continuous dividend yield q) — price, Greeks, implied volatility.
export type OptType = 'call' | 'put';
export interface OptIn { S: number; K: number; T: number; r: number; q: number; sigma: number; type: OptType }
export interface OptOut { price: number; delta: number; gamma: number; vega: number; theta: number; rho: number; d1: number; d2: number }

// Abramowitz-Stegun 7.1.26 based normal CDF (|err| < 7.5e-8)
export function normCdf(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2);
  const p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return x >= 0 ? 1 - p : p;
}
export const normPdf = (x: number) => 0.3989422804014327 * Math.exp((-x * x) / 2);

export function bs({ S, K, T, r, q, sigma, type }: OptIn): OptOut {
  if (T <= 0 || sigma <= 0) {
    const intrinsic = Math.max(type === 'call' ? S - K : K - S, 0);
    return { price: intrinsic, delta: type === 'call' ? (S > K ? 1 : 0) : S < K ? -1 : 0, gamma: 0, vega: 0, theta: 0, rho: 0, d1: NaN, d2: NaN };
  }
  const sq = Math.sqrt(T);
  const d1 = (Math.log(S / K) + (r - q + (sigma * sigma) / 2) * T) / (sigma * sq);
  const d2 = d1 - sigma * sq;
  const dfq = Math.exp(-q * T), dfr = Math.exp(-r * T);
  const call = type === 'call';
  const price = call ? S * dfq * normCdf(d1) - K * dfr * normCdf(d2) : K * dfr * normCdf(-d2) - S * dfq * normCdf(-d1);
  const delta = call ? dfq * normCdf(d1) : -dfq * normCdf(-d1);
  const gamma = (dfq * normPdf(d1)) / (S * sigma * sq);
  const vega = (S * dfq * normPdf(d1) * sq) / 100; // per 1 vol point
  const thetaYr = call
    ? (-S * dfq * normPdf(d1) * sigma) / (2 * sq) - r * K * dfr * normCdf(d2) + q * S * dfq * normCdf(d1)
    : (-S * dfq * normPdf(d1) * sigma) / (2 * sq) + r * K * dfr * normCdf(-d2) - q * S * dfq * normCdf(-d1);
  const rho = (call ? K * T * dfr * normCdf(d2) : -K * T * dfr * normCdf(-d2)) / 100; // per 1% rate
  return { price, delta, gamma, vega, theta: thetaYr / 365, rho, d1, d2 };
}

/** Implied volatility by bisection (robust, deterministic). Returns null if no solution in [0.0001, 5]. */
export function impliedVol(target: number, p: Omit<OptIn, 'sigma'>): number | null {
  let lo = 1e-4, hi = 5;
  const f = (s: number) => bs({ ...p, sigma: s }).price - target;
  if (f(lo) > 0 || f(hi) < 0) return null;
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2;
    if (f(mid) > 0) hi = mid;
    else lo = mid;
    if (hi - lo < 1e-10) break;
  }
  return (lo + hi) / 2;
}
