// Squarified treemap layout (Bruls et al.) for the HMAP heatmap.
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function squarify<T>(items: { value: number; data: T }[], rect: Rect): (Rect & { data: T })[] {
  const total = items.reduce((a, b) => a + b.value, 0);
  if (!total || rect.w <= 0 || rect.h <= 0) return [];
  const scale = (rect.w * rect.h) / total;
  const nodes = items.filter((i) => i.value > 0).map((i) => ({ area: i.value * scale, data: i.data })).sort((a, b) => b.area - a.area);
  const out: (Rect & { data: T })[] = [];
  let { x, y, w, h } = rect;
  let row: typeof nodes = [];
  const worst = (r: typeof nodes, side: number) => {
    const s = r.reduce((a, b) => a + b.area, 0);
    const mx = Math.max(...r.map((n) => n.area));
    const mn = Math.min(...r.map((n) => n.area));
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  const layout = (r: typeof nodes) => {
    const s = r.reduce((a, b) => a + b.area, 0);
    if (w >= h) {
      const cw = s / h;
      let cy = y;
      for (const n of r) {
        const nh = n.area / cw;
        out.push({ x, y: cy, w: cw, h: nh, data: n.data });
        cy += nh;
      }
      x += cw;
      w -= cw;
    } else {
      const ch = s / w;
      let cx = x;
      for (const n of r) {
        const nw = n.area / ch;
        out.push({ x: cx, y, w: nw, h: ch, data: n.data });
        cx += nw;
      }
      y += ch;
      h -= ch;
    }
  };
  for (const n of nodes) {
    const side = Math.min(w, h);
    if (!row.length || worst([...row, n], side) <= worst(row, side)) row.push(n);
    else {
      layout(row);
      row = [n];
    }
  }
  if (row.length) layout(row);
  return out;
}
