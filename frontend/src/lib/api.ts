// Thin REST client for the FastAPI backend. All endpoints are documented in docs/API.md.
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : '';
}

export const api = {
  get: <T,>(path: string, params: Record<string, unknown> = {}) => fetch(`/api${path}${qs(params)}`).then(handle<T>),
  post: <T,>(path: string, body: unknown, params: Record<string, unknown> = {}) =>
    fetch(`/api${path}${qs(params)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle<T>),
  put: <T,>(path: string, body: unknown) =>
    fetch(`/api${path}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(
      handle<T>,
    ),
  patch: <T,>(path: string, body: unknown) =>
    fetch(`/api${path}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(
      handle<T>,
    ),
  del: <T,>(path: string) => fetch(`/api${path}`, { method: 'DELETE' }).then(handle<T>),
  url: (path: string, params: Record<string, unknown> = {}) => `/api${path}${qs(params)}`,
  async download(path: string, body: unknown, filename: string) {
    const r = await fetch(`/api${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new ApiError(r.status, await r.text());
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};

// generic persisted store (watchlists, portfolio, notes, layout, settings, excel_links)
export const store = {
  get: async <T,>(key: string, fallback: T): Promise<T> => {
    try {
      const r = await api.get<{ value: T | null }>(`/store/${key}`);
      return (r.value ?? fallback) as T;
    } catch {
      return fallback;
    }
  },
  set: <T,>(key: string, value: T) => api.put(`/store/${key}`, { value }),
};
