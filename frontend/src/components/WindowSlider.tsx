// Time-window sliders shared by analysis panels: window length (with presets) + "as of" (step back in time).
// Values are committed after the drag pauses (debounced) so the backend is not hit on every pixel.
import { useEffect, useRef, useState } from 'react';

export interface WindowValue {
  length: number;
  offset: number;
}

const PRESETS_DAYS: [string, number][] = [['1W', 5], ['1M', 21], ['3M', 63], ['6M', 126], ['1Y', 252], ['2Y', 504], ['3Y', 756]];
const PRESETS_WEEKS: [string, number][] = [['4W', 4], ['8W', 8], ['13W', 13], ['26W', 26]];

export function WindowSlider({
  value, onChange, min, max, step = 1, unit = 'days', label = 'WINDOW', maxOffset = 0, asof, delay = 350,
}: {
  value: WindowValue;
  onChange: (v: WindowValue) => void;
  min: number;
  max: number;
  step?: number;
  unit?: 'days' | 'weeks';
  label?: string;
  maxOffset?: number;
  asof?: string | null;
  delay?: number;
}) {
  const [v, setV] = useState(value);
  const first = useRef(true);
  useEffect(() => setV(value), [value.length, value.offset]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (v.length === value.length && v.offset === value.offset) return;
    const t = setTimeout(() => onChange(v), delay);
    return () => clearTimeout(t);
  }, [v.length, v.offset]); // eslint-disable-line react-hooks/exhaustive-deps
  const u = unit === 'weeks' ? '週' : '日';
  const presets = (unit === 'weeks' ? PRESETS_WEEKS : PRESETS_DAYS).filter(([, n]) => n >= min && n <= max);
  return (
    <div className="wslider">
      <span className="lbl">{label}</span>
      <input type="range" min={min} max={max} step={step} value={v.length} onChange={(e) => setV({ ...v, length: +e.target.value })} />
      <span className="amber wval">{v.length}{u}</span>
      {presets.map(([k, n]) => <button key={k} className={`tb mini ${v.length === n ? 'on' : ''}`} onClick={() => setV({ ...v, length: n })}>{k}</button>)}
      {maxOffset > 0 && (
        <>
          <span className="lbl" title="右端 = 最新。左へ動かすと過去の時点で同じ分析を再計算（それ以降のデータは使わない）">AS OF</span>
          <input type="range" min={0} max={maxOffset} step={1} value={maxOffset - v.offset} onChange={(e) => setV({ ...v, offset: maxOffset - +e.target.value })} />
          <span className={`wval ${v.offset ? 'yellow' : 'muted'}`}>{v.offset ? `${v.offset}${u}前` : '最新'}{asof ? ` (${asof})` : ''}</span>
          {v.offset > 0 && <button className="tb mini" onClick={() => setV({ ...v, offset: 0 })}>最新</button>}
        </>
      )}
    </div>
  );
}
