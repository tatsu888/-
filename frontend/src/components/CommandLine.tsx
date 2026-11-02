import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { FUNCTIONS, parseCommand, quickResolve } from '../lib/commands';
import { useTerminal } from '../ctx';

interface Sug {
  key: string;
  desc: string;
  apply: string;
}

/** Bloomberg-style command line: "<SECURITY> <FUNCTION> <GO>". */
export function CommandLine() {
  const { run, toast } = useTerminal();
  const [text, setText] = useState('');
  const [sugs, setSugs] = useState<Sug[]>([]);
  const [sel, setSel] = useState(0);
  const ref = useRef<HTMLInputElement>(null);
  // command history (↑/↓ when no suggestion list is open), persisted per browser
  const [hist, setHist] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('term.history') ?? '[]');
    } catch {
      return [];
    }
  });
  const [hi, setHi] = useState(-1);
  const remember = (cmd: string) => {
    const h = [cmd, ...hist.filter((x) => x !== cmd)].slice(0, 50);
    setHist(h);
    setHi(-1);
    try {
      localStorage.setItem('term.history', JSON.stringify(h));
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // any printable key when nothing else is focused goes to the command line (terminal feel)
      const t = e.target as HTMLElement;
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || e.ctrlKey || e.metaKey || e.altKey) return;
      if (t.closest?.('[data-own-keys]')) return; // e.g. the XLS grid handles its own typing
      if (e.key.length === 1 || e.key === 'Backspace') ref.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    const t = text.trim();
    if (!t) return setSugs([]);
    const toks = t.split(/\s+/);
    const last = toks[toks.length - 1].toUpperCase();
    const fnSugs: Sug[] = FUNCTIONS.filter((f) => f.code.startsWith(last))
      .slice(0, 6)
      .map((f) => ({ key: f.code, desc: `${f.name} — ${f.desc}`, apply: [...toks.slice(0, -1), f.code].join(' ') }));
    if (toks.length > 1 || last.length < 1) return setSugs(fnSugs);
    let alive = true;
    const h = setTimeout(() => {
      api
        .get<{ symbol: string; description: string; type: string }[]>('/search', { q: toks[0], limit: 8 })
        .then((r) => {
          if (!alive) return;
          setSugs([...fnSugs, ...r.map((s) => ({ key: s.symbol, desc: `${s.description} ${s.type ? '· ' + s.type : ''}`, apply: s.symbol + ' ' }))]);
        })
        .catch(() => alive && setSugs(fnSugs));
    }, 180);
    setSugs(fnSugs);
    return () => {
      alive = false;
      clearTimeout(h);
    };
  }, [text]);

  async function submit(raw = text) {
    // "3 <GO>": a menu number for the focused panel (TOP, ECST …), like Bloomberg's numbered screens
    const menu = /^\d{1,2}$/.test(raw.trim()) ? document.querySelector('.panel.focused [data-menu]') : null;
    if (menu) {
      menu.dispatchEvent(new CustomEvent('menu', { detail: +raw.trim() }));
      setText('');
      setSugs([]);
      return;
    }
    const p = parseCommand(raw);
    if (!p.fn && !p.security) return;
    let sec: string | undefined;
    if (p.security) {
      sec = quickResolve(p.security) ?? undefined;
      if (!sec) {
        try {
          const r = await api.get<{ symbol: string }[]>('/search', { q: p.security, limit: 1 });
          sec = r[0]?.symbol ?? `NASDAQ:${p.security.toUpperCase()}`;
        } catch {
          sec = `NASDAQ:${p.security.toUpperCase()}`;
          toast(`search unavailable — assuming ${sec}`);
        }
      }
    }
    run(p.fn ?? '', sec, p.args);
    remember(raw.trim().toUpperCase());
    setText('');
    setSugs([]);
  }

  return (
    <div className="cmd">
      <input
        ref={ref}
        value={text}
        placeholder="例: AAPL GP · 7203 DES · USDJPY GP · WEI · LAG oil_energy · FACT · MODEL · HELP   [Enter=GO]"
        onChange={(e) => {
          setText(e.target.value);
          setSel(0);
          setHi(-1);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            if (sugs.length && sel > 0) {
              setText(sugs[sel - 1].apply);
              setSel(0);
            } else submit();
          } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (!sugs.length && hi >= 0) {
              const n = hi - 1;
              setHi(n);
              setText(n >= 0 ? hist[n] : '');
            } else setSel((s) => Math.min(s + 1, sugs.length));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if ((!text || hi >= 0) && hist.length && sel === 0) {
              const n = Math.min(hi + 1, hist.length - 1);
              setHi(n);
              setText(hist[n]);
              setSugs([]);
            } else setSel((s) => Math.max(s - 1, 0));
          } else if (e.key === 'Tab' && sugs.length) {
            e.preventDefault();
            setText(sugs[Math.max(sel - 1, 0)].apply);
          } else if (e.key === 'Escape') {
            setText('');
            setSugs([]);
          }
        }}
        spellCheck={false}
      />
      <button className="go" onClick={() => submit()}>
        GO
      </button>
      <button className="cancel" onClick={() => (setText(''), setSugs([]))}>
        CANCEL
      </button>
      {sugs.length > 0 && (
        <div className="suggest">
          {sugs.map((s, i) => (
            <div key={s.key + i} className={i + 1 === sel ? 'sel' : ''} onMouseDown={() => setText(s.apply)}>
              <span className="k">{s.key}</span>
              <span className="d">{s.desc}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
