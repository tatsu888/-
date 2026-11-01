// Live market-data feed over the backend websocket (/ws).
// Ref-counted subscriptions: components call useQuotes(symbols) / useBars(...) and the
// feed tells the server the union of what is on screen. Protocol: docs/API.md#websocket.
import { useEffect, useRef, useSyncExternalStore } from 'react';
import type { Bar, Health, Quote } from './types';

type Listener = () => void;
type BarListener = (bar: Bar) => void;
type MsgListener = (msg: any) => void;

class Feed {
  ws: WebSocket | null = null;
  quotes = new Map<string, Quote>();
  prev = new Map<string, number>(); // previous last price (for tick direction / flash)
  version = 0;
  connected = false;
  health: Health | null = null;
  private symRefs = new Map<string, number>();
  private barRefs = new Map<string, Set<BarListener>>();
  private listeners = new Set<Listener>();
  private msgListeners = new Set<MsgListener>();
  private retry = 500;
  private syncTimer: number | null = null;

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this.retry = 500;
      this.scheduleSync();
      for (const key of this.barRefs.keys()) {
        const [symbol, interval] = key.split('|');
        this.send({ op: 'subscribe_bars', symbol, interval });
      }
      this.emit();
    };
    ws.onclose = () => {
      this.connected = false;
      this.emit();
      setTimeout(() => this.connect(), this.retry);
      this.retry = Math.min(this.retry * 2, 10000);
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'quotes') {
        for (const q of msg.data as Quote[]) {
          const old = this.quotes.get(q.symbol);
          if (old?.last != null) this.prev.set(q.symbol, old.last);
          this.quotes.set(q.symbol, q);
        }
        this.emit();
      } else if (msg.type === 'bar') {
        this.barRefs.get(`${msg.symbol}|${msg.interval}`)?.forEach((fn) => fn(msg.bar));
      } else if (msg.type === 'hello' || msg.type === 'provider') {
        this.health = msg;
        if (msg.type === 'provider') this.quotes.clear();
        this.emit();
      }
      this.msgListeners.forEach((fn) => fn(msg));
    };
  }

  private send(m: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(m));
  }

  private scheduleSync() {
    if (this.syncTimer != null) return;
    this.syncTimer = window.setTimeout(() => {
      this.syncTimer = null;
      this.send({ op: 'set_symbols', symbols: [...this.symRefs.keys()] });
    }, 50);
  }

  private emit() {
    this.version++;
    this.listeners.forEach((l) => l());
  }

  subscribe = (l: Listener) => {
    this.listeners.add(l);
    return () => {
      this.listeners.delete(l);
    };
  };

  onMessage(fn: MsgListener): () => void {
    this.msgListeners.add(fn);
    return () => {
      this.msgListeners.delete(fn);
    };
  }

  addSymbols(symbols: string[]) {
    for (const s of symbols) this.symRefs.set(s, (this.symRefs.get(s) ?? 0) + 1);
    this.scheduleSync();
  }

  removeSymbols(symbols: string[]) {
    for (const s of symbols) {
      const n = (this.symRefs.get(s) ?? 0) - 1;
      if (n <= 0) this.symRefs.delete(s);
      else this.symRefs.set(s, n);
    }
    this.scheduleSync();
  }

  addBars(symbol: string, interval: string, fn: BarListener) {
    const key = `${symbol}|${interval}`;
    let set = this.barRefs.get(key);
    if (!set) {
      set = new Set();
      this.barRefs.set(key, set);
      this.send({ op: 'subscribe_bars', symbol, interval });
    }
    set.add(fn);
    return () => {
      set!.delete(fn);
      if (set!.size === 0) {
        this.barRefs.delete(key);
        this.send({ op: 'unsubscribe_bars', symbol, interval });
      }
    };
  }
}

export const feed = new Feed();

/** Live quotes for the given symbols (re-renders on every pushed update). */
export function useQuotes(symbols: string[]): Map<string, Quote> {
  const key = symbols.join(',');
  useEffect(() => {
    const syms = key ? key.split(',') : [];
    feed.addSymbols(syms);
    return () => feed.removeSymbols(syms);
  }, [key]);
  useSyncExternalStore(feed.subscribe, () => feed.version);
  return feed.quotes;
}

export function useFeedStatus() {
  useSyncExternalStore(feed.subscribe, () => feed.version);
  return { connected: feed.connected, health: feed.health };
}

export function useBars(symbol: string | undefined, interval: string, onBar: BarListener) {
  const ref = useRef(onBar);
  ref.current = onBar;
  useEffect(() => {
    if (!symbol) return;
    return feed.addBars(symbol, interval, (b) => ref.current(b));
  }, [symbol, interval]);
}

export function useFeedMessages(fn: MsgListener) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => feed.onMessage((m) => ref.current(m)), []);
}
