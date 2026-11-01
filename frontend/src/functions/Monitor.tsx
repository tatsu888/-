// Quote monitors: WEI / FX / RATES / CMDTY / CRYP (universe lists) and W (editable watchlists).
import { useEffect, useState } from 'react';
import { store } from '../lib/api';
import { useQuotes } from '../lib/feed';
import { cls, fmtBig, fmtPct, fmtPrice, fmtTime, shortSym } from '../lib/format';
import type { Quote, UniverseItem } from '../lib/types';
import { DelayBadge, Flash } from '../components/ui';
import { useTerminal } from '../ctx';

type SortKey = 'symbol' | 'last' | 'change_pct' | 'volume' | null;

export function QuoteTable({ items, groupBy, onRemove }: { items: UniverseItem[]; groupBy?: boolean; onRemove?: (s: string) => void }) {
  const { setSecurity, security, run } = useTerminal();
  const quotes = useQuotes(items.map((i) => i.symbol));
  const [sort, setSort] = useState<{ k: SortKey; dir: number }>({ k: null, dir: -1 });
  const rows = (() => {
    const r = items.map((it) => ({ it, q: quotes.get(it.symbol) }));
    if (sort.k) {
      const k = sort.k;
      r.sort((a, b) => {
        const va = k === 'symbol' ? a.it.symbol : (a.q?.[k] as number | undefined) ?? -Infinity;
        const vb = k === 'symbol' ? b.it.symbol : (b.q?.[k] as number | undefined) ?? -Infinity;
        return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
      });
    }
    return r;
  })(); // recomputed every render: quotes Map is mutated in place by the feed
  const th = (k: SortKey, label: string, l = false) => (
    <th className={`sort ${l ? 'l' : ''}`} onClick={() => setSort((s) => ({ k, dir: s.k === k ? -s.dir : -1 }))}>
      {label}
      {sort.k === k ? (sort.dir > 0 ? '▲' : '▼') : ''}
    </th>
  );
  let lastGroup = '';
  return (
    <table className="t">
      <thead>
        <tr>
          {th('symbol', 'SECURITY', true)}
          <th className="l">NAME</th>
          {th('last', 'LAST')}
          <th>NET CHG</th>
          {th('change_pct', '%CHG')}
          <th>HIGH</th>
          <th>LOW</th>
          {th('volume', 'VOLUME')}
          <th>TIME</th>
          <th>SRC</th>
          {onRemove && <th />}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ it, q }) => {
          const group = groupBy && it.region && it.region !== lastGroup && !sort.k ? it.region : null;
          if (group) lastGroup = it.region!;
          return [
            group && (
              <tr key={`g-${group}`} className="group">
                <td colSpan={onRemove ? 11 : 10}>{group}</td>
              </tr>
            ),
            <Row key={it.symbol} it={it} q={q} sel={security === it.symbol} onClick={() => setSecurity(it.symbol)} onDouble={() => run('GP', it.symbol)} onRemove={onRemove} />,
          ];
        })}
      </tbody>
    </table>
  );
}

function Row({ it, q, sel, onClick, onDouble, onRemove }: { it: UniverseItem; q?: Quote; sel: boolean; onClick: () => void; onDouble: () => void; onRemove?: (s: string) => void }) {
  return (
    <tr className={`click ${sel ? 'sel' : ''}`} onClick={onClick} onDoubleClick={onDouble} title="click: load security · double-click: chart">
      <td className="l sym">{shortSym(it.symbol)}</td>
      <td className="l name">{it.label || q?.name}</td>
      <Flash value={q?.last}>{fmtPrice(q?.last)}</Flash>
      <td className={cls(q?.change)}>{q?.change != null ? (q.change > 0 ? '+' : '') + fmtPrice(q.change, q.last) : '--'}</td>
      <td className={cls(q?.change_pct)}>{fmtPct(q?.change_pct)}</td>
      <td>{fmtPrice(q?.high)}</td>
      <td>{fmtPrice(q?.low)}</td>
      <td>{fmtBig(q?.volume)}</td>
      <td className="muted">{fmtTime(q?.time)}</td>
      <td>{q?.error ? <span className="badge fail" title={q.error}>ERR</span> : <DelayBadge q={q} />}</td>
      {onRemove && (
        <td>
          <span className="muted" style={{ cursor: 'pointer' }} onClick={(e) => (e.stopPropagation(), onRemove(it.symbol))}>
            ✕
          </span>
        </td>
      )}
    </tr>
  );
}

export function ListMonitor({ list }: { list: string }) {
  const { universe } = useTerminal();
  const items = universe?.lists[list] ?? [];
  return <QuoteTable items={items} groupBy={list === 'WEI'} />;
}

export function Watchlist() {
  const { universe, security } = useTerminal();
  const [lists, setLists] = useState<Record<string, string[]> | null>(null);
  const [cur, setCur] = useState('Main');
  const [add, setAdd] = useState('');
  useEffect(() => {
    store.get<Record<string, string[]>>('watchlists', {}).then((w) => {
      if (!Object.keys(w).length) w = { Main: (universe?.lists.W ?? []).map((i) => i.symbol) };
      setLists(w);
      setCur(Object.keys(w)[0]);
    });
  }, [universe]);
  const save = (w: Record<string, string[]>) => {
    setLists(w);
    store.set('watchlists', w);
  };
  if (!lists) return <div className="note">LOADING…</div>;
  const syms = lists[cur] ?? [];
  const label = (s: string) => Object.values(universe?.lists ?? {}).flat().find((i) => i.symbol === s)?.label ?? '';
  const addSym = (raw: string) => {
    const s = raw.trim().toUpperCase();
    if (!s) return;
    const full = s.includes(':') ? s : /^\d{4}$/.test(s) ? `TSE:${s}` : `NASDAQ:${s}`;
    save({ ...lists, [cur]: [...new Set([...syms, full])] });
    setAdd('');
  };
  return (
    <div>
      <div className="toolbar">
        {Object.keys(lists).map((n) => (
          <button key={n} className={`tb ${n === cur ? 'on' : ''}`} onClick={() => setCur(n)}>
            {n}
          </button>
        ))}
        <button
          className="tb"
          onClick={() => {
            const n = prompt('new watchlist name');
            if (n && !lists[n]) save({ ...lists, [n]: [] }), setCur(n);
          }}
        >
          + LIST
        </button>
        {Object.keys(lists).length > 1 && (
          <button className="tb red" onClick={() => confirm(`delete ${cur}?`) && (save(Object.fromEntries(Object.entries(lists).filter(([k]) => k !== cur))), setCur(Object.keys(lists)[0]))}>
            DEL LIST
          </button>
        )}
        <span className="lbl">ADD</span>
        <input className="inp" value={add} placeholder="NYSE:IBM / 6758" onChange={(e) => setAdd(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addSym(add)} />
        <button className="tb" onClick={() => addSym(security)}>
          + {shortSym(security)}
        </button>
      </div>
      <QuoteTable items={syms.map((s) => ({ symbol: s, label: label(s) }))} onRemove={(s) => save({ ...lists, [cur]: syms.filter((x) => x !== s) })} />
    </div>
  );
}
