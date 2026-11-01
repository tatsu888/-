// Subset of Excel number-format rendering so the XLS viewer looks like Excel.
// Supports: sections (pos;neg;zero;text), 0 / # / , / . / %, [Red]/[Color], literal "text" and \x,
// _x spacing, parentheses for negatives, currency symbols, E+ scientific, basic dates (yyyy mm dd hh:mm).
export interface Rendered {
  text: string;
  color?: string;
}

const COLORS: Record<string, string> = {
  red: '#ff5050', blue: '#5ea9ff', green: '#3fd27f', black: '#dddddd', white: '#ffffff', yellow: '#ffd84a',
  magenta: '#ff6ad5', cyan: '#5ff',
};

function splitSections(fmt: string): string[] {
  const out: string[] = [];
  let cur = '',
    q = false;
  for (let i = 0; i < fmt.length; i++) {
    const c = fmt[i];
    if (c === '"') q = !q;
    if (c === '\\' && !q) {
      cur += c + (fmt[i + 1] ?? '');
      i++;
      continue;
    }
    if (c === ';' && !q) {
      out.push(cur);
      cur = '';
    } else cur += c;
  }
  out.push(cur);
  return out;
}

function isDateFmt(f: string): boolean {
  const s = f.replace(/"[^"]*"/g, '').replace(/\[[^\]]*\]/g, '');
  return /[ymdhs]/i.test(s) && !/[0#]/.test(s);
}

function renderDate(iso: string | number, f: string): string {
  let d: Date;
  if (typeof iso === 'number') d = new Date(Math.round((iso - 25569) * 86400 * 1000));
  else d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  const p = (n: number, w = 2) => String(n).padStart(w, '0');
  const utc = typeof iso === 'number';
  const Y = utc ? d.getUTCFullYear() : d.getFullYear();
  const M = (utc ? d.getUTCMonth() : d.getMonth()) + 1;
  const D = utc ? d.getUTCDate() : d.getDate();
  const h = utc ? d.getUTCHours() : d.getHours();
  const mi = utc ? d.getUTCMinutes() : d.getMinutes();
  let s = f.replace(/\[[^\]]*\]/g, '').replace(/"([^"]*)"/g, '$1').replace(/\\(.)/g, '$1');
  s = s.replace(/yyyy/gi, String(Y)).replace(/yy/gi, p(Y % 100));
  s = s.replace(/hh/gi, p(h)).replace(/(h)(?=[^a-z]|$)/gi, String(h));
  s = s.replace(/(:)mm/gi, `$1${p(mi)}`).replace(/mm(?=:)/gi, p(mi));
  s = s.replace(/mmm/gi, d.toLocaleString('en-US', { month: 'short', timeZone: utc ? 'UTC' : undefined }));
  s = s.replace(/mm/gi, p(M)).replace(/(?<![a-z])m(?![a-z])/gi, String(M));
  s = s.replace(/dd/gi, p(D)).replace(/(?<![a-z])d(?![a-z])/gi, String(D));
  return s;
}

export function renderValue(v: unknown, nf?: string): Rendered {
  if (v == null) return { text: '' };
  if (typeof v === 'boolean') return { text: v ? 'TRUE' : 'FALSE' };
  if (typeof v === 'string') {
    if (nf && isDateFmt(nf) && /^\d{4}-\d{2}-\d{2}/.test(v)) return { text: renderDate(v, nf) };
    return { text: v };
  }
  if (typeof v !== 'number' || !isFinite(v)) return { text: String(v) };
  if (!nf || nf === 'General' || nf === '@') return { text: general(v) };
  const secs = splitSections(nf);
  let sec = secs[0];
  let val = v;
  if (secs.length > 1 && v < 0) {
    sec = secs[1];
    val = -v;
  } else if (secs.length > 2 && v === 0) sec = secs[2];
  let color: string | undefined;
  sec = sec.replace(/\[([^\]]+)\]/g, (_, c: string) => {
    const k = c.toLowerCase();
    if (COLORS[k]) color = COLORS[k];
    return '';
  });
  if (isDateFmt(sec)) return { text: renderDate(v, sec), color };
  return { text: formatNumber(val, sec, secs.length === 1 && v < 0), color };
}

function general(v: number): string {
  if (Number.isInteger(v) && Math.abs(v) < 1e15) return String(v);
  const s = v.toPrecision(10);
  return String(parseFloat(s));
}

function formatNumber(v: number, sec: string, neg: boolean): string {
  // collect literals vs number pattern
  let pre = '',
    post = '',
    pattern = '',
    phase = 0; // 0 before digits, 1 in digits, 2 after
  for (let i = 0; i < sec.length; i++) {
    const c = sec[i];
    if (c === '"') {
      const j = sec.indexOf('"', i + 1);
      const lit = sec.slice(i + 1, j < 0 ? undefined : j);
      if (phase === 0) pre += lit;
      else post += lit;
      if (phase === 1) phase = 2;
      i = j < 0 ? sec.length : j;
      continue;
    }
    if (c === '\\') {
      if (phase === 0) pre += sec[i + 1] ?? '';
      else {
        post += sec[i + 1] ?? '';
        phase = 2;
      }
      i++;
      continue;
    }
    if (c === '_') {
      if (phase === 0) pre += ' ';
      else post += ' ';
      i++;
      continue;
    }
    if (c === '*') {
      i++;
      continue;
    }
    if ('0#?.,'.includes(c) || ((c === 'E' || c === 'e') && phase === 1)) {
      if (phase === 2) {
        post += c;
        continue;
      }
      phase = 1;
      pattern += c;
      if (c === 'E' || c === 'e') {
        pattern += sec[i + 1] ?? '+';
        i++;
        while (sec[i + 1] === '0') {
          pattern += '0';
          i++;
        }
      }
      continue;
    }
    if (phase === 0) pre += c;
    else {
      post += c;
      phase = 2;
    }
  }
  const pctCount = (pre + post).split('%').length - 1;
  let x = v * Math.pow(100, pctCount);
  if (/E[+-]/i.test(pattern)) {
    const dec = (pattern.split('.')[1] ?? '').replace(/E.*/i, '').length;
    return (neg ? '-' : '') + pre + x.toExponential(dec).toUpperCase().replace(/E\+?(-?)(\d)$/, 'E+$1$2') + post;
  }
  // trailing commas scale by 1000
  let m = pattern.match(/,+$/);
  if (m) {
    x /= Math.pow(1000, m[0].length);
    pattern = pattern.slice(0, -m[0].length);
  }
  const [ip, dp = ''] = pattern.split('.');
  const minDec = (dp.match(/0/g) ?? []).length;
  const maxDec = dp.replace(/,/g, '').length;
  const grouping = ip.includes(',');
  const minInt = (ip.match(/0/g) ?? []).length;
  let s = x.toLocaleString('en-US', {
    minimumFractionDigits: minDec,
    maximumFractionDigits: maxDec,
    useGrouping: grouping,
    minimumIntegerDigits: Math.max(1, Math.min(minInt, 21)),
  });
  if (minInt === 0 && s.startsWith('0.')) s = s.slice(1);
  if (minInt === 0 && s === '0') s = '';
  return (neg ? '-' : '') + pre + s + post;
}

export function colLetter(n: number): string {
  let s = '';
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

export function parseAddr(a: string): [number, number] {
  const m = a.match(/^([A-Z]+)(\d+)$/)!;
  let c = 0;
  for (const ch of m[1]) c = c * 26 + ch.charCodeAt(0) - 64;
  return [parseInt(m[2], 10), c];
}
