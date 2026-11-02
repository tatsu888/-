// TOP — the information hub (Bloomberg TOP / NI / FIL style): feeds from central banks, governments, regulators and
// news; coverage / keyword hits; filings (EDINET, SEC EDGAR); company news (Google News); feeds, keywords, API keys.
import { useState } from 'react';
import { api } from '../lib/api';
import { ErrorBox, Loading, useAsync, useMenu } from '../components/ui';
import { useTerminal } from '../ctx';

const TABS = ['NEW', 'HITS', 'FIL', 'NEWS', 'FEEDS', 'WORDS', 'KEYS'] as const;
type Tab = (typeof TABS)[number];
const TAB_JA: Record<Tab, string> = { NEW: '新着', HITS: '当たり', FIL: '開示', NEWS: '銘柄ニュース', FEEDS: 'フィード', WORDS: 'キーワード', KEYS: '鍵' };
const HELP: Record<Tab, string> = {
  NEW: '中銀・政府・規制当局・ニュースのフィードの新着（20 分ごとに自動取得）。分類・地域で絞り込み。黄色＝カバレッジの銘柄、橙＝キーワード。',
  HITS: 'カバレッジの銘柄（ティッカー・社名）か、登録したキーワードが出てきた記事だけ。新しく見つかると画面に通知。',
  FIL: 'カバレッジ銘柄の開示（EDINET：大量保有・自己株買い・公開買付・有報・半期・臨時報告書。米国株は SEC EDGAR）。自動取得：EDINET は巡回ごとに今日と昨日、EDGAR は 1 日 1 回。',
  NEWS: '会社名や話題で Google ニュースを検索（1 時間キャッシュ）。STK の銘柄ページにも同じものが出る。',
  FEEDS: '取得しているフィードと状態。オン／オフ、追加（RSS / Atom の URL）、取得テスト。',
  WORDS: '通知するキーワード（1 行に 1 語）。カバレッジの銘柄は自動で対象。',
  KEYS: 'API キーをこの PC の .env に保存（すぐ有効、Git には入らない）。e-Stat・FRED・EDINET・SEC の連絡先。',
};
const when = (s?: string) => (s ? new Date(s.endsWith('Z') || s.includes('+') ? s : s + '+09:00').toLocaleString('ja-JP', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '');

export function TOP({ args }: { args?: string }) {
  const [tab, setTab] = useState<Tab>((TABS as readonly string[]).includes(args?.toUpperCase() || '') ? (args!.toUpperCase() as Tab) : 'NEW');
  const menu = useMenu((n) => TABS[n - 1] && setTab(TABS[n - 1]));
  return (
    <div ref={menu} data-menu>
      <div className="bb-head">
        <span className="bb-code">TOP</span><span className="bb-title">NEWS · FILINGS · SOURCES</span><span className="muted">情報ハブ</span>
        <InfoStatus />
      </div>
      <div className="bb-menu">
        {TABS.map((t, i) => (
          <button key={t} className={`bb-item ${tab === t ? 'on' : ''}`} onClick={() => setTab(t)} title={`${i + 1} と入力して Enter（${i + 1} <GO>）でも切り替え`}>
            <span className="bb-num">{i + 1})</span> {t} <span className="bb-ja">{TAB_JA[t]}</span>
          </button>
        ))}
      </div>
      <div className="bb-help">{HELP[tab]}</div>
      {(tab === 'NEW' || tab === 'HITS') && <Items hits={tab === 'HITS'} />}
      {tab === 'FIL' && <Filings />}
      {tab === 'NEWS' && <NewsSearch />}
      {tab === 'FEEDS' && <Feeds />}
      {tab === 'WORDS' && <Words />}
      {tab === 'KEYS' && <KeysPanel />}
    </div>
  );
}

function InfoStatus() {
  const { toast } = useTerminal();
  const st = useAsync(() => api.get<any>('/info/status'), []);
  const s = st.data;
  const run = async () => { try { const r = await api.post<any>('/info/update', {}); toast(r.started ? '情報の取得を開始' : '取得中です'); setTimeout(() => st.reload(), 2000); } catch (e: any) { toast(e.message); } };
  return (
    <span className="muted" style={{ fontSize: 10, marginLeft: 8 }}>
      <button className="tb" onClick={run}>⟳ 取得</button>
      {s && <> フィード {s.feeds.ok}/{s.feeds.enabled} OK{s.feeds.error ? <span className="down"> · エラー {s.feeds.error}</span> : null} · 記事 {s.items} · 最終 {s.state?.last_run?.replace('T', ' ').slice(5, 16) || '—'}
        {' · '}<label title={s.auto_env ? '' : 'TERMINAL_INFO_AUTO=0 で止めている'}><input type="checkbox" checked={!!s.config.auto && s.auto_env} disabled={!s.auto_env}
          onChange={(e) => api.put('/info/config', { auto: e.target.checked }).then(() => st.reload(), (er: any) => toast(er.message))} /> 自動</label>
        <select className="inp" value={s.config.every_min} disabled={!s.auto_env} onChange={(e) => api.put('/info/config', { every_min: +e.target.value }).then(() => st.reload(), (er: any) => toast(er.message))}>
          {[...new Set([10, 20, 30, 60, 180, s.config.every_min])].sort((a, b) => a - b).map((m) => <option key={m} value={m}>{m} 分ごと</option>)}</select>
        {!s.keys.EDINET_API_KEY && <span className="yellow"> · EDINET キー未設定</span>}</>}
    </span>
  );
}

function Items({ hits }: { hits: boolean }) {
  const { run } = useTerminal();
  const [f, setF] = useState({ category: '', region: '', q: '', days: 3 });
  const r = useAsync(() => api.get<any>('/info/items', { hits_only: hits, days: f.days, category: f.category || undefined, region: f.region || undefined, q: f.q || undefined }), [hits, f.category, f.region, f.days]);
  const rows: any[] = (r.data?.rows || []).filter((x: any) => !f.q || (x.title + x.summary).toLowerCase().includes(f.q.toLowerCase()));
  const symOf = (t: string) => r.data?.symbols?.[t] || (/^[0-9][0-9A-Z]{3}$/.test(t) ? `TSE:${t}` : t);
  return (
    <div>
      <div className="toolbar">
        <select className="inp" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}><option value="">分類（全部）</option>{(r.data?.categories || []).map((c: string) => <option key={c}>{c}</option>)}</select>
        <select className="inp" value={f.region} onChange={(e) => setF({ ...f, region: e.target.value })}><option value="">地域（全部）</option>{(r.data?.regions || []).map((c: string) => <option key={c}>{c}</option>)}</select>
        <select className="inp" value={f.days} onChange={(e) => setF({ ...f, days: +e.target.value })}>{[1, 3, 7, 30].map((d) => <option key={d} value={d}>{d} 日</option>)}</select>
        <input className="inp" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="絞り込み" />
        <span className="muted">{rows.length} 件</span>
      </div>
      {r.loading && !r.data && <Loading />}
      <ErrorBox error={r.error} />
      <table className="t" style={{ fontSize: 11 }}><tbody>{rows.map((x, i) => (
        <tr key={x.guid + i}>
          <td className="l muted nowrap">{when(x.published || x.fetched)}</td>
          <td className="l nowrap"><span className="bb-cc">{x.region}</span> <span className="muted">{x.feed_name}</span></td>
          <td className="l"><a href={x.link} target="_blank" rel="noreferrer" className={x.tickers?.length ? 'yellow' : x.keywords?.length ? 'amber' : ''}>{x.title}</a>
            {x.summary && <div className="muted" style={{ fontSize: 10 }}>{x.summary.slice(0, 160)}</div>}</td>
          <td className="nowrap">{(x.tickers || []).map((t: string) => <button key={t} className="tb mini" onClick={() => run('STK', symOf(t))}>{t}</button>)}
            {(x.keywords || []).map((k: string) => <span key={k} className="badge warn" style={{ marginLeft: 2 }}>{k}</span>)}</td>
        </tr>
      ))}</tbody></table>
      {r.data && !rows.length && <div className="note">記事がまだありません。「⟳ 取得」を押すか、自動取得を待ってください（フィードの状態は 5) FEEDS）。</div>}
    </div>
  );
}

function Filings() {
  const { run } = useTerminal();
  const [kind, setKind] = useState('');
  const [days, setDays] = useState(30);
  const r = useAsync(() => api.get<any>('/info/filings', { kind: kind || undefined, days }), [kind, days]);
  const d = r.data;
  return (
    <div>
      <div className="toolbar">
        <select className="inp" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">種類（全部）</option>{(d?.kinds || []).map((k: string) => <option key={k}>{k}</option>)}</select>
        <select className="inp" value={days} onChange={(e) => setDays(+e.target.value)}>{[7, 30, 90, 365].map((x) => <option key={x} value={x}>{x} 日</option>)}</select>
        {d && <span className="muted" style={{ fontSize: 10 }}>EDINET 最終取得 {d.edinet_at?.replace('T', ' ').slice(0, 16) || '—'}{!d.keys.EDINET_API_KEY && <span className="yellow"> — EDINET の API キーが未設定（7) KEYS）</span>}</span>}
      </div>
      {r.loading && !d && <Loading />}
      <table className="t nowrap" style={{ fontSize: 11 }}>
        <thead><tr><th>提出</th><th className="l">銘柄</th><th className="l">種類</th><th className="l">書類</th><th className="l">提出者</th><th /></tr></thead>
        <tbody>{(d?.rows || []).map((x: any) => (
          <tr key={x.doc_id}>
            <td className="muted">{(x.at || x.date).replace('T', ' ').slice(5, 16)}</td>
            <td className="l"><span className="amber" style={{ cursor: 'pointer' }} onClick={() => run('STK', `TSE:${x.ticker}`)}>{x.ticker}</span> {x.name}</td>
            <td className={`l ${['大量保有', '自己株買い', '公開買付'].includes(x.kind) ? 'yellow' : ''}`}>{x.kind}</td>
            <td className="l">{x.desc}</td><td className="l muted">{x.filer}</td>
            <td><a className="tb mini" href={x.pdf} target="_blank" rel="noreferrer">PDF</a></td>
          </tr>
        ))}</tbody>
      </table>
      {d?.edgar?.length > 0 && (
        <div className="box" style={{ margin: 6 }}><h4>米国の開示（SEC EDGAR）</h4>
          <table className="t nowrap" style={{ fontSize: 11 }}><tbody>{d.edgar.slice(0, 80).map((x: any, i: number) => (
            <tr key={i}><td className="muted">{x.date}</td><td className="l amber">{x.ticker}</td><td className="l">{x.form} <span className="muted">{x.kind}</span></td>
              <td>{x.url && <a className="tb mini" href={x.url} target="_blank" rel="noreferrer">開く</a>}</td></tr>
          ))}</tbody></table>
        </div>
      )}
      {d && !d.rows.length && <div className="note">この期間のカバレッジ銘柄の開示はまだありません（EDINET の API キーを 7) KEYS に入れると自動で取得）。</div>}
    </div>
  );
}

function NewsSearch() {
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [lang, setLang] = useState('ja');
  const r = useAsync(() => (query ? api.get<any>('/info/news', { q: query, lang }) : Promise.resolve(null)), [query, lang]);
  return (
    <div>
      <div className="toolbar">
        <input className="inp" style={{ width: 260 }} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && setQuery(q)} placeholder="会社名・話題（例：アドバンテスト、HBM）" />
        <select className="inp" value={lang} onChange={(e) => setLang(e.target.value)}><option value="ja">日本語</option><option value="en">English</option></select>
        <button className="tb on" onClick={() => setQuery(q)}>検索</button>
      </div>
      {r.loading && query && <Loading />}
      <ErrorBox error={r.error} />
      <NewsList rows={r.data?.rows || []} />
    </div>
  );
}

export function NewsList({ rows }: { rows: any[] }) {
  return (
    <table className="t" style={{ fontSize: 11 }}><tbody>{rows.map((x: any) => (
      <tr key={x.guid}><td className="muted nowrap">{when(x.published)}</td><td className="l"><a href={x.link} target="_blank" rel="noreferrer">{x.title}</a></td></tr>
    ))}</tbody></table>
  );
}

function Feeds() {
  const { toast } = useTerminal();
  const r = useAsync(() => api.get<any>('/info/feeds'), []);
  const [nf, setNf] = useState({ name: '', url: '', category: 'ニュース', region: 'JP' });
  const [test, setTest] = useState<any>(null);
  const call = async (fn: () => Promise<any>, ok?: (x: any) => void) => { try { const x = await fn(); ok?.(x); r.reload(); } catch (e: any) { toast(e.message); } };
  return (
    <div>
      <table className="t nowrap" style={{ fontSize: 11 }}>
        <thead><tr><th>オン</th><th className="l">フィード</th><th className="l">分類</th><th>地域</th><th>状態</th><th className="l">最終</th><th /></tr></thead>
        <tbody>{(r.data?.rows || []).map((f: any) => (
          <tr key={f.id}>
            <td><input type="checkbox" checked={f.enabled} onChange={(e) => call(() => api.put(`/info/feeds/${f.id}`, { enabled: e.target.checked }))} /></td>
            <td className="l" title={f.url}>{f.name}</td><td className="l muted">{f.category}</td><td>{f.region}</td>
            <td>{f.at ? (f.ok ? <span className="badge pass">OK {f.n}</span> : <span className="badge fail" title={f.error}>エラー</span>) : <span className="badge delay">未取得</span>}</td>
            <td className="l muted" style={{ maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.ok === false ? f.error : f.at?.replace('T', ' ').slice(5, 16)}</td>
            <td>{f.custom && <button className="tb mini" onClick={() => call(() => api.del(`/info/feeds/${f.id}`))}>削除</button>}</td>
          </tr>
        ))}</tbody>
      </table>
      <div className="box" style={{ margin: 6 }}><h4>フィードを追加（RSS / Atom）</h4>
        <div className="toolbar">
          <input className="inp" value={nf.name} onChange={(e) => setNf({ ...nf, name: e.target.value })} placeholder="名前" />
          <input className="inp" style={{ width: 360 }} value={nf.url} onChange={(e) => setNf({ ...nf, url: e.target.value })} placeholder="https://…/rss.xml" />
          <select className="inp" value={nf.category} onChange={(e) => setNf({ ...nf, category: e.target.value })}>{['中銀', '政府・統計', '規制・取引所', 'ニュース', '国際機関', '企業 IR', 'その他'].map((c) => <option key={c}>{c}</option>)}</select>
          <select className="inp" value={nf.region} onChange={(e) => setNf({ ...nf, region: e.target.value })}>{['JP', 'US', 'EU', 'UK', 'CN', 'GLOBAL'].map((c) => <option key={c}>{c}</option>)}</select>
          <button className="tb" disabled={!nf.url} onClick={() => call(() => api.post('/info/feeds/test', { url: nf.url }), setTest)}>取得テスト</button>
          <button className="tb on" disabled={!nf.name || !nf.url} onClick={() => call(() => api.post('/info/feeds', nf), () => { toast('追加しました（次の取得から）'); setNf({ ...nf, name: '', url: '' }); })}>追加</button>
        </div>
        {test && <div className="pad" style={{ fontSize: 11 }}>{test.n} 件: {test.items.map((x: any) => x.title).join(' / ')}</div>}
      </div>
    </div>
  );
}

function Words() {
  const { toast } = useTerminal();
  const r = useAsync(() => api.get<any>('/info/keywords'), []);
  const [text, setText] = useState<string | null>(null);
  const v = text ?? (r.data?.words || []).join('\n');
  return (
    <div className="pad">
      <textarea className="inp" style={{ width: 420, height: 300 }} value={v} onChange={(e) => setText(e.target.value)} />
      <div className="toolbar">
        <button className="tb on" onClick={async () => { try { await api.put('/info/keywords', { words: v.split('\n') }); toast('保存しました'); setText(null); r.reload(); } catch (e: any) { toast(e.message); } }}>保存</button>
        <button className="tb" onClick={() => setText((r.data?.default || []).join('\n'))}>初期値に戻す</button>
      </div>
    </div>
  );
}

/** API keys → the local .env of this PC (applied at once; never shown in full; never committed). */
export function KeysPanel() {
  const { toast } = useTerminal();
  const r = useAsync(() => api.get<any>('/settings/keys'), []);
  const [val, setVal] = useState<Record<string, string>>({});
  const d = r.data;
  const save = async (k: string, v: string) => {
    try { await api.put('/settings/keys', { key: k, value: v }); toast(v ? `${k} を保存しました（すぐ有効）` : `${k} を消しました`); setVal({ ...val, [k]: '' }); r.reload(); } catch (e: any) { toast(e.message); }
  };
  if (!d) return <Loading />;
  return (
    <div className="box" style={{ margin: 6 }}>
      <h4>API キー（この PC の {d.file} に保存）</h4>
      <table className="t" style={{ fontSize: 11 }}><tbody>{Object.entries(d.keys).map(([k, x]: [string, any]) => (
        <tr key={k}>
          <td className="l nowrap"><span className="amber">{x.label}</span><div className="muted" style={{ fontSize: 9 }}>{k}</div></td>
          <td className="l" style={{ fontSize: 10 }}>{x.desc}</td>
          <td className="nowrap">{x.set ? (x.problem ? <span className="down">要確認</span> : <span className="up">設定済み {x.masked}</span>) : <span className="muted">未設定</span>}</td>
          <td className="nowrap"><input className="inp" style={{ width: 230 }} type={k === 'SEC_USER_AGENT' ? 'text' : 'password'} value={val[k] ?? ''} onChange={(e) => setVal({ ...val, [k]: e.target.value })} placeholder="貼り付けて保存" />
            <button className="tb mini" disabled={!val[k]} onClick={() => save(k, val[k])}>保存</button>
            {x.set && <button className="tb mini" onClick={() => save(k, '')}>消す</button>}</td>
        </tr>
      ))}</tbody></table>
      {Object.values(d.keys).some((x: any) => x.problem) && <div className="pad down" style={{ fontSize: 11 }}>{Object.values(d.keys).filter((x: any) => x.problem).map((x: any) => `${x.label}: ${x.problem}`).join(' / ')}</div>}
      <div className="note" style={{ fontSize: 10 }}>保存先は .env（Git の管理対象外）。画面には先頭と末尾の 4 文字だけを表示する。</div>
    </div>
  );
}
