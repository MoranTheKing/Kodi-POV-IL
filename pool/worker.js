// Kodi POV IL — community AI-subtitle pool (Cloudflare Worker)
// ---------------------------------------------------------------------------
// Shares/pulls Hebrew AI translations. Telegram channel = file store, Workers
// KV = small index. Posts are formatted like a subtitle-release channel:
// poster + title + genre hashtags + season/episode + IMDb|TMDb + plot, then the
// .srt document.
//
// Routes:
//   GET  /health
//   GET  /lookup?tmdb=<id>&type=movie|episode&season=&episode=&lang=he
//   GET  /sub?tmdb=<id>&type=&season=&episode=&lang=he[&hash=<source_hash>]
//   POST /contribute  (X-API-Key)  body JSON {tmdb_id,imdb_id,type,season,episode,
//                       lang:"he",release,source_hash,source_lang,title,year,srt,
//                       kind:"ai"|"ktuvit"}  (kind defaults to "ai")
//
// Bindings: KV "POOL"; secrets BOT_TOKEN, CHANNEL_ID, API_KEY; optional TMDB_KEY.

const MAX_SRT = 2 * 1024 * 1024;
const MAX_VARIANTS = 25;
// Public TMDB v3 key bundled in jurialmunkey's tmdbhelper (same one the add-on
// uses). Override per-deployment by setting a TMDB_KEY variable.
const BUNDLED_TMDB_KEY = 'a07324c669cac4d96789197134ce272b';

const tg = (token, method) => `https://api.telegram.org/bot${token}/${method}`;

function keyFor(p) {
  const lang = (p.lang || 'he').toLowerCase();
  const id = String(p.tmdb || p.imdb || '').trim();
  const s = String(p.season || '0').trim() || '0';
  const e = String(p.episode || '0').trim() || '0';
  return `v1:${lang}:${id}:s${s}:e${e}`;
}

// --- Canonical media bucketing --------------------------------------------
// The same title must bucket the same way no matter which id the client sent.
// Live add-on shares of an episode usually carry only the show's imdb (Kodi
// exposes no tmdb for streamed episodes); manual web uploads carry only tmdb
// (picked from search). Keying by `tmdb||imdb` split those into two buckets
// that never saw each other. We resolve the missing id from TMDB (cached in
// KV), build BOTH candidate keys -- tmdb first as the canonical target -- and
// consolidate on write so contribute/lookup/sub all converge.

async function resolveIds(env, p) {
  let tmdb = String(p.tmdb || '').trim();
  let imdb = String(p.imdb || '').trim();
  const type = (p.type === 'episode') ? 'episode' : 'movie';
  if ((tmdb && imdb) || (!tmdb && !imdb)) return { tmdb, imdb };
  const cacheKey = `idmap:${type}:${tmdb ? 't' + tmdb : 'i' + imdb}`;
  try {
    const c = await env.POOL.get(cacheKey);
    if (c) { const m = JSON.parse(c); return { tmdb: tmdb || m.tmdb || '', imdb: imdb || m.imdb || '' }; }
  } catch (_) { /* ignore */ }
  const key = env.TMDB_KEY || BUNDLED_TMDB_KEY;
  try {
    if (!tmdb && /^tt\d+$/.test(imdb)) {
      const r = await fetch(`https://api.themoviedb.org/3/find/${imdb}` +
        `?api_key=${key}&external_source=imdb_id`);
      if (r.ok) {
        const d = await r.json();
        if (type === 'episode') {
          if (d.tv_results && d.tv_results.length) tmdb = String(d.tv_results[0].id || '');
          else if (d.tv_episode_results && d.tv_episode_results.length) tmdb = String(d.tv_episode_results[0].show_id || '');
        } else if (d.movie_results && d.movie_results.length) tmdb = String(d.movie_results[0].id || '');
      }
    } else if (tmdb && !imdb && /^\d+$/.test(tmdb)) {
      const base = (type === 'episode') ? 'tv' : 'movie';
      const r = await fetch(`https://api.themoviedb.org/3/${base}/${tmdb}/external_ids?api_key=${key}`);
      if (r.ok) { const d = await r.json(); if (d.imdb_id) imdb = String(d.imdb_id); }
    }
  } catch (_) { /* ignore */ }
  if (tmdb && imdb) {
    const map = JSON.stringify({ tmdb, imdb });
    const ttl = { expirationTtl: 60 * 60 * 24 * 180 };
    try { await env.POOL.put(`idmap:${type}:t${tmdb}`, map, ttl); } catch (_) { /* ignore */ }
    try { await env.POOL.put(`idmap:${type}:i${imdb}`, map, ttl); } catch (_) { /* ignore */ }
  }
  return { tmdb, imdb };
}

// Ordered candidate keys (tmdb-based first = canonical write target), deduped.
async function mediaKeys(env, p) {
  const lang = (p.lang || 'he').toLowerCase();
  const s = String(p.season || '0').trim() || '0';
  const e = String(p.episode || '0').trim() || '0';
  const { tmdb, imdb } = await resolveIds(env, p);
  const ids = [];
  if (/^\d+$/.test(String(tmdb || ''))) ids.push(String(tmdb));
  if (/^tt\d+$/.test(String(imdb || ''))) ids.push(String(imdb));
  const raw = String(p.tmdb || p.imdb || '').trim();
  if (raw && !ids.includes(raw)) ids.push(raw);
  const keys = [...new Set(ids.map(id => `v1:${lang}:${id}:s${s}:e${e}`))];
  return keys.length ? keys : [keyFor(p)];
}

// Merge variant lists across all candidate keys, deduping by file_id.
async function readMergedIndex(env, p) {
  const keys = await mediaKeys(env, p);
  const seen = new Set();
  const variants = [];
  for (const k of keys) {
    for (const v of await readIndex(env, k)) {
      const sig = v.file_id || v.result_hash;
      if (sig && seen.has(sig)) continue;
      if (sig) seen.add(sig);
      variants.push(v);
    }
  }
  return { variants, keys, primaryKey: keys[0] };
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status, headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

// --- Embedded-Hebrew registry --------------------------------------------
// A tiny per-media list of RELEASE NAMES known to ship a built-in (muxed)
// Hebrew subtitle track. Reported automatically by the add-on the moment it
// detects an embedded Hebrew stream at play start, keyed by release name (NOT
// debrid hash) so it matches across providers (TorBox / Real-Debrid / ... all
// expose the same release name for the same file). Stored under 'emb:<key>' so
// it never touches the subtitle index. Bounded so a value can't grow forever.
const EMB_MAX = 80;

function embKey(mediaKey) { return 'emb:' + mediaKey; }

async function readEmbedded(env, keys) {
  try {
    const seen = new Set();
    const out = [];
    for (const k of keys) {
      let raw;
      try { raw = await env.POOL.get(embKey(k)); } catch (_) { raw = null; }
      if (!raw) continue;
      let arr; try { arr = JSON.parse(raw); } catch { arr = null; }
      if (!Array.isArray(arr)) continue;
      for (const rel of arr) {
        const r = String(rel || '').trim();
        const low = r.toLowerCase();
        if (r && !seen.has(low)) { seen.add(low); out.push(r); }
      }
    }
    return out;
  } catch (_) { return []; }
}

async function recordEmbedded(env, body) {
  const rel = String(body.release || '').trim();
  if (!rel) return json({ ok: false, error: 'no release' }, 400);
  const ids = await resolveIds(env, {
    tmdb: body.tmdb_id, imdb: body.imdb_id, type: body.type,
  });
  const p = {
    tmdb: ids.tmdb, imdb: ids.imdb, type: body.type,
    season: body.season, episode: body.episode, lang: 'he',
  };
  const keys = await mediaKeys(env, p);
  const primary = keys[0];
  if (!primary) return json({ ok: false, error: 'no key' }, 400);
  const k = embKey(primary);
  let arr = [];
  try { const raw = await env.POOL.get(k); if (raw) arr = JSON.parse(raw) || []; } catch (_) { arr = []; }
  if (!Array.isArray(arr)) arr = [];
  const low = rel.toLowerCase();
  if (arr.some(x => String(x || '').toLowerCase() === low)) {
    return json({ ok: true, added: false });   // already known -> no write
  }
  arr.push(rel);
  if (arr.length > EMB_MAX) arr = arr.slice(arr.length - EMB_MAX);
  try { await env.POOL.put(k, JSON.stringify(arr)); } catch (_) { /* ignore */ }
  return json({ ok: true, added: true });
}

// --- Shared Ktuvit-availability registry ---------------------------------
// Ktuvit runs on ONE shared, rate-limited account, so it must NOT be queried
// per-user on every browse. Instead the FIRST add-on to browse a title checks
// Ktuvit once and reports the Hebrew release names here; everyone else reads
// them from this shared, persistent registry without ever touching Ktuvit.
// Stored as 'kt:<key>' -> { checked: <ts>, names: [...] }. The 'checked'
// timestamp lets clients treat it as fresh for a while (and re-check rarely),
// so new Hebrew that appears on Ktuvit is eventually picked up -- still at most
// ~once per title globally.
const KT_MAX = 120;

function ktKey(mediaKey) { return 'kt:' + mediaKey; }

async function readKtuvit(env, keys) {
  const seen = new Set();
  const names = [];
  let checked = 0;
  let changed = 0;   // when the list last GREW (a new release appeared)
  try {
    for (const k of keys) {
      let raw;
      try { raw = await env.POOL.get(ktKey(k)); } catch (_) { raw = null; }
      if (!raw) continue;
      let obj; try { obj = JSON.parse(raw); } catch { obj = null; }
      if (!obj) continue;
      const ts = Number(obj.checked || 0);
      if (ts > checked) checked = ts;
      const ch = Number(obj.changed || 0);
      if (ch > changed) changed = ch;
      for (const rel of (obj.names || [])) {
        const r = String(rel || '').trim();
        const low = r.toLowerCase();
        if (r && !seen.has(low)) { seen.add(low); names.push(r); }
      }
    }
  } catch (_) { /* ignore */ }
  return { names, checked, changed };
}

async function recordKtuvit(env, body) {
  const ids = await resolveIds(env, {
    tmdb: body.tmdb_id, imdb: body.imdb_id, type: body.type,
  });
  const p = {
    tmdb: ids.tmdb, imdb: ids.imdb, type: body.type,
    season: body.season, episode: body.episode, lang: 'he',
  };
  const keys = await mediaKeys(env, p);
  const primary = keys[0];
  if (!primary) return json({ ok: false, error: 'no key' }, 400);
  // Merge reported names with whatever's already stored, dedup, bound.
  let names = Array.isArray(body.names) ? body.names : [];
  const seen = new Set();
  let prev = {};
  try { const raw = await env.POOL.get(ktKey(primary)); if (raw) prev = JSON.parse(raw) || {}; } catch (_) { prev = {}; }
  const merged = [];
  for (const rel of [...(prev.names || []), ...names]) {
    const r = String(rel || '').trim();
    const low = r.toLowerCase();
    if (r && !seen.has(low)) { seen.add(low); merged.push(r); }
  }
  const bounded = merged.length > KT_MAX ? merged.slice(merged.length - KT_MAX) : merged;
  const now = Date.now() / 1000;
  // 'changed' marks when the list last GREW (or first contact), so clients
  // keep re-checking often while a title is still gaining subs, then back off
  // once it's been stable for a while.
  const prevCount = Array.isArray(prev.names) ? prev.names.length : 0;
  let changed = Number(prev.changed || 0);
  if (bounded.length > prevCount || !changed) changed = now;
  const obj = { checked: now, changed, names: bounded };
  try { await env.POOL.put(ktKey(primary), JSON.stringify(obj)); } catch (_) { /* ignore */ }
  return json({ ok: true, count: bounded.length, changed });
}

function looksLikeSrt(text) {
  if (!text || text.length < 30 || text.length > MAX_SRT) return false;
  return (text.match(/-->/g) || []).length >= 3;
}

// sha1 hex of a string (Web Crypto). Used to dedup by the Hebrew RESULT, so two
// byte-identical translations never get stored twice even when one has no
// source hash (e.g. a bulk "share my cache" upload).
async function sha1hex(text) {
  const buf = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(text || ''));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function hashtag(s) {
  const t = String(s).trim().replace(/[\s\-]+/g, '_').replace(/[^\wא-ת]/g, '');
  return t ? '#' + t : '';
}

async function readIndex(env, key) {
  const raw = await env.POOL.get(key);
  if (!raw) return [];
  try { const a = JSON.parse(raw); return Array.isArray(a) ? a : []; }
  catch { return []; }
}

// Resolve a usable numeric TMDB id. Prefer body.tmdb_id; if it's missing or
// non-numeric, look it up from the imdb id via TMDB /find. This is what rescues
// imdb-only shares -- the live add-on share of an episode often carries only
// the show's imdb id (Kodi's VideoPlayer.UniqueId(tmdb) is empty for streamed
// episodes), which previously left the Telegram post with no series name,
// poster, or plot. For episodes we want the SHOW's tmdb id (tv_results, or the
// show_id behind an episode-level imdb).
async function resolveTmdbId(env, body) {
  const direct = String(body.tmdb_id || '').trim();
  if (/^\d+$/.test(direct)) return direct;
  const imdb = String(body.imdb_id || '').trim();
  if (!/^tt\d+$/.test(imdb)) return '';
  const key = env.TMDB_KEY || BUNDLED_TMDB_KEY;
  try {
    const r = await fetch(`https://api.themoviedb.org/3/find/${imdb}` +
      `?api_key=${key}&external_source=imdb_id`);
    if (!r.ok) return '';
    const d = await r.json();
    if (body.type === 'episode') {
      if (d.tv_results && d.tv_results.length) return String(d.tv_results[0].id || '');
      if (d.tv_episode_results && d.tv_episode_results.length)
        return String(d.tv_episode_results[0].show_id || '');
    } else {
      if (d.movie_results && d.movie_results.length) return String(d.movie_results[0].id || '');
    }
  } catch (_) { /* ignore */ }
  return '';
}

async function tmdbMeta(env, body) {
  const key = env.TMDB_KEY || BUNDLED_TMDB_KEY;
  const id = await resolveTmdbId(env, body);
  if (!/^\d+$/.test(id)) return {};
  const isEp = body.type === 'episode';
  const base = isEp ? 'tv' : 'movie';
  try {
    const r = await fetch(`https://api.themoviedb.org/3/${base}/${id}` +
      `?api_key=${key}&language=he&append_to_response=external_ids`);
    if (!r.ok) return {};
    const d = await r.json();
    const meta = {
      tmdb_id: id,
      title: d.title || d.name || body.title || '',
      original_title: d.original_title || d.original_name || '',
      year: String(d.release_date || d.first_air_date || '').slice(0, 4) || body.year || '',
      overview: d.overview || '',
      poster_url: d.poster_path ? `https://image.tmdb.org/t/p/w500${d.poster_path}` : '',
      genres: (d.genres || []).map(g => g.name),
      imdb_id: (d.external_ids && d.external_ids.imdb_id) || d.imdb_id || body.imdb_id || '',
    };
    // The .srt filename needs a Latin title. For anime/foreign titles both the
    // native original_title (e.g. Japanese) and our he title are non-Latin and
    // strip to nothing in an ASCII filename -- which left names like
    // "tvtt10233448.S02E22.he.srt". Grab the English title with one more call
    // only when neither title we have carries Latin letters.
    let latin = meta.original_title || meta.title || '';
    if (!/[A-Za-z]/.test(latin)) {
      try {
        const enr = await fetch(`https://api.themoviedb.org/3/${base}/${id}` +
          `?api_key=${key}&language=en-US`);
        if (enr.ok) {
          const end = await enr.json();
          const en = end.title || end.name || '';
          if (/[A-Za-z]/.test(en)) latin = en;
        }
      } catch (_) { /* ignore */ }
    }
    meta.latin_title = latin;
    if (isEp && body.season && body.episode) {
      try {
        const er = await fetch(`https://api.themoviedb.org/3/tv/${id}/season/` +
          `${body.season}/episode/${body.episode}?api_key=${key}&language=he`);
        if (er.ok) {
          const ed = await er.json();
          if (ed.overview) meta.overview = ed.overview;
          if (ed.name) meta.ep_name = ed.name;
        }
      } catch (_) { /* ignore */ }
    }
    return meta;
  } catch (_) { return {}; }
}

// A real subtitle release name carries a year and/or a quality/source token
// (1080p, BluRay, x265, ...). The client's `release` can also be a tokenized
// stream/temp basename with none of those -- we reject those and fall back to
// the TMDB title so the Telegram filename stays meaningful.
function looksLikeRelease(s) {
  if (!s || s.length < 5) return false;
  if (/(?:^|[^0-9])(?:19|20)\d{2}(?:[^0-9]|$)/.test(s)) return true;
  if (/\b(2160p|1080p|720p|480p|bluray|blu-ray|webrip|web-dl|webdl|web|hdtv|brrip|bdrip|dvdrip|hdrip|x264|x265|h264|h265|hevc|xvid|aac|ac3|dts)\b/i.test(s)) return true;
  return false;
}

// Build a clean, human-readable .srt filename. Prefer a real release name (it
// tells you which video version the subtitle is synced to); otherwise use the
// English/original TMDB title + year (+ SxxEyy for episodes); fall back to the
// id. Cosmetic only -- the pool is indexed by id/season/episode, not the name.
function cleanFilename(body, meta) {
  const isEp = body.type === 'episode';
  const id = String(body.tmdb_id || body.imdb_id || '').trim();
  const rel = String(body.release || '')
    .replace(/[^A-Za-z0-9._-]/g, '.').replace(/\.{2,}/g, '.')
    .replace(/^\.+|\.+$/g, '').slice(0, 80);
  if (looksLikeRelease(rel)) return rel + '.he.srt';
  let base = (meta.latin_title || meta.original_title || meta.title || body.title || '')
    .replace(/[^A-Za-z0-9]+/g, '.').replace(/^\.+|\.+$/g, '').slice(0, 60);
  if (!base) base = (isEp ? 'tv' : 'movie') + (id || '');
  if (!isEp && meta.year) base += '.' + meta.year;
  if (isEp) {
    const pad = (n) => String(parseInt(n, 10) || 0).padStart(2, '0');
    base += `.S${pad(body.season)}E${pad(body.episode)}`;
  }
  return base + '.he.srt';
}

function buildCaption(body, meta) {
  const isEp = body.type === 'episode';
  const title = meta.title || body.title || 'Unknown';
  const lines = [];
  let head = `${isEp ? '📺' : '🎬'} <b>${escapeHtml(title)}</b>`;
  if (!isEp && meta.year) head += ` (${meta.year})`;
  lines.push(head);
  if (isEp) {
    lines.push(`עונה ${body.season} · פרק ${body.episode}` +
      (meta.ep_name ? ` — ${escapeHtml(meta.ep_name)}` : ''));
  }
  const tags = (meta.genres || []).slice(0, 5).map(hashtag).filter(Boolean);
  if (tags.length) lines.push(tags.join(' '));
  const links = [];
  if (meta.imdb_id) links.push(`<a href="https://www.imdb.com/title/${meta.imdb_id}/">IMDb</a>`);
  const tid = String(meta.tmdb_id || body.tmdb_id || '').trim();
  if (tid) links.push(`<a href="https://www.themoviedb.org/${isEp ? 'tv' : 'movie'}/${tid}">TMDb</a>`);
  if (links.length) lines.push(links.join(' | '));
  if (meta.overview) { lines.push(''); lines.push(escapeHtml(meta.overview.slice(0, 500))); }
  lines.push('');
  // Distinguish a human Ktuvit subtitle from a machine AI translation in the
  // channel itself, so it's unambiguous which kind each post is.
  if (body.kind === 'ktuvit') {
    lines.push('📥 כתובית · תרגום אנושי (לא AI) · #כתוביות_כתובית #עברית');
  } else {
    lines.push('🤖 תרגום AI · #כתוביות_AI #עברית');
  }
  let cap = lines.join('\n');
  if (cap.length > 1024) cap = cap.slice(0, 1020) + '…';
  return cap;
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

// Telegram rate-limits a bot per token / per chat (~20 msgs/min to a channel).
// On 429 it returns parameters.retry_after seconds. Do ONE bounded retry that
// honours retry_after (capped, so we never blow the Worker's request budget);
// if it's still throttled, the caller treats it as a failure and the client
// retries later. doFetch is a thunk so the request body (FormData) is rebuilt
// fresh for the retry.
async function tgRetry(doFetch) {
  let r = await doFetch();
  if (r.status === 429) {
    let wait = 2;
    try {
      const j = await r.clone().json();
      wait = (j.parameters && j.parameters.retry_after) || 2;
    } catch (_) { /* keep default */ }
    if (wait <= 12) { await sleep(wait * 1000 + 300); r = await doFetch(); }
  }
  return r;
}

async function sendPhoto(env, photoUrl, caption) {
  try {
    const r = await tgRetry(() => fetch(tg(env.BOT_TOKEN, 'sendPhoto'), {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ chat_id: String(env.CHANNEL_ID), photo: photoUrl, caption, parse_mode: 'HTML' }),
    }));
    return (await r.json()).ok;
  } catch (_) { return false; }
}

async function uploadSrt(env, filename, srtText, caption, parseMode) {
  const buildFd = () => {
    const fd = new FormData();
    fd.append('chat_id', String(env.CHANNEL_ID));
    if (caption) fd.append('caption', String(caption).slice(0, 1024));
    if (parseMode) fd.append('parse_mode', parseMode);
    fd.append('document', new Blob([srtText], { type: 'application/x-subrip' }), filename);
    return fd;
  };
  const r = await tgRetry(() => fetch(tg(env.BOT_TOKEN, 'sendDocument'), { method: 'POST', body: buildFd() }));
  const data = await r.json();
  if (!data.ok) throw new Error('sendDocument: ' + JSON.stringify(data).slice(0, 300));
  return data.result && data.result.document && data.result.document.file_id;
}

// Edge-cached fetch of a stored SRT by its (immutable) Telegram file_id. The
// first pull downloads from Telegram and stores the bytes in Cloudflare's edge
// cache; subsequent pulls are served from the edge and never touch the Telegram
// getFile API -- which keeps many concurrent /sub requests off the bot's rate
// limit and makes pulls much faster.
async function downloadById(env, fileId) {
  const cache = caches.default;
  const cacheKey = new Request('https://pool-file-cache/' + encodeURIComponent(fileId));
  try {
    const hit = await cache.match(cacheKey);
    if (hit) return await hit.text();
  } catch (_) { /* fall through to live fetch */ }

  const gf = await tgRetry(() => fetch(tg(env.BOT_TOKEN, 'getFile') + '?file_id=' + encodeURIComponent(fileId)));
  const gd = await gf.json();
  if (!gd.ok || !gd.result || !gd.result.file_path) return null;
  const fr = await fetch(`https://api.telegram.org/file/bot${env.BOT_TOKEN}/${gd.result.file_path}`);
  if (!fr.ok) return null;
  const text = await fr.text();
  try {
    await cache.put(cacheKey, new Response(text, {
      headers: {
        'content-type': 'application/x-subrip; charset=utf-8',
        'cache-control': 'public, max-age=2592000',
      },
    }));
  } catch (_) { /* caching is best-effort */ }
  return text;
}

// Shared contribution pipeline: validate, dedup (source + Hebrew-result hash,
// with lazy backfill), post the rich message + document to the channel, and
// index the variant. Used by both /contribute (add-on, X-API-Key) and
// /web-upload (manual web page, X-Upload-Token). Returns a json() Response.
async function contributeCore(env, body) {
  const lang = (body.lang || 'he').toLowerCase();
  if (lang !== 'he') return json({ ok: false, error: 'only he supported' }, 400);
  // 'kind' splits the same media bucket into human Ktuvit subs vs machine AI
  // translations. Anything that isn't an explicit 'ktuvit' stays 'ai' so all
  // legacy entries (which predate this field) keep behaving as AI.
  const kind = (body.kind === 'ktuvit') ? 'ktuvit' : 'ai';
  const srt = body.srt || '';
  if (!looksLikeSrt(srt)) return json({ ok: false, error: 'invalid srt' }, 400);
  const id = String(body.tmdb_id || body.imdb_id || '').trim();
  if (!id) return json({ ok: false, error: 'no id' }, 400);

  // Canonical bucketing: resolve the missing id and merge any legacy
  // tmdb/imdb-split buckets, writing back to one primary (tmdb-preferred) key.
  const mkeys = await mediaKeys(env, { lang, tmdb: body.tmdb_id, imdb: body.imdb_id, type: body.type, season: body.season, episode: body.episode });
  const key = mkeys[0];
  const hash = (body.source_hash || '').trim();
  const variants = [];
  {
    const seen = new Set();
    for (const k of mkeys) {
      for (const v of await readIndex(env, k)) {
        const sig = v.file_id || v.result_hash;
        if (sig && seen.has(sig)) continue;
        if (sig) seen.add(sig);
        variants.push(v);
      }
    }
  }
  const persist = async () => {
    await env.POOL.put(key, JSON.stringify(variants));
    for (const k of mkeys.slice(1)) { try { await env.POOL.delete(k); } catch (_) { /* ignore */ } }
  };

  // Dedup layer 1: same SOURCE hash already present (cheap, no downloads).
  if (hash && variants.some(v => v.hash === hash)) { await persist(); return json({ ok: true, dedup: true, key }); }

  // Dedup layer 2: same RESULT (Hebrew) already present. Catches uploads with
  // no source hash (bulk "share my cache", manual web upload) and prevents two
  // byte-identical Hebrew files coexisting. Old variants stored before this
  // layer have no result_hash, so backfill it lazily (download + hash, write
  // back) -- bounded by MAX_VARIANTS and only on this path.
  const resultHash = await sha1hex(srt);
  for (const v of variants) {
    if (!v.result_hash) {
      try {
        const existing = await downloadById(env, v.file_id);
        if (existing) { v.result_hash = await sha1hex(existing); }
      } catch (_) { /* leave it; just won't dedup by result for this one */ }
    }
  }
  if (variants.some(v => v.result_hash === resultHash)) {
    await persist();
    return json({ ok: true, dedup: true, key });
  }

  if (variants.length >= MAX_VARIANTS) {
    await persist();
    return json({ ok: false, error: 'too many variants' }, 429);
  }

  const meta = await tmdbMeta(env, body);
  const filename = cleanFilename(body, meta);
  const caption = buildCaption(body, meta);

  let fileId;
  try {
    if (meta.poster_url) {
      await sendPhoto(env, meta.poster_url, caption);
      fileId = await uploadSrt(env, filename, srt, `📄 <code>${escapeHtml(filename)}</code>`, 'HTML');
    } else {
      fileId = await uploadSrt(env, filename, srt, caption, 'HTML');
    }
  } catch (e) { return json({ ok: false, error: String(e).slice(0, 200) }, 502); }
  if (!fileId) return json({ ok: false, error: 'no file_id' }, 502);

  variants.push({ hash, result_hash: resultHash, release: body.release || '', source_lang: body.source_lang || '', kind, file_id: fileId, ts: Date.now() });
  await persist();
  return json({ ok: true, stored: true, key });
}

// Manual-upload auth: a token separate from the add-on's API_KEY, so it can be
// shared with trusted contributors (and revoked) without exposing the add-on
// key. Set UPLOAD_TOKEN as a Worker secret.
function checkUploadToken(env, token) {
  return !!env.UPLOAD_TOKEN && String(token || '') === String(env.UPLOAD_TOKEN);
}

// Proxy a TMDB title search (so the upload page can resolve a name -> id
// without ever exposing the TMDB key to the browser).
async function tmdbSearch(env, query) {
  const key = env.TMDB_KEY || BUNDLED_TMDB_KEY;
  const q = (query || '').trim();
  if (!q) return [];
  try {
    const r = await fetch('https://api.themoviedb.org/3/search/multi?api_key=' +
      key + '&language=he&query=' + encodeURIComponent(q));
    if (!r.ok) return [];
    const d = await r.json();
    return (d.results || [])
      .filter(x => x.media_type === 'movie' || x.media_type === 'tv')
      .slice(0, 12)
      .map(x => ({
        id: x.id,
        type: x.media_type === 'tv' ? 'episode' : 'movie',
        title: x.title || x.name || '',
        year: String(x.release_date || x.first_air_date || '').slice(0, 4),
        poster: x.poster_path ? ('https://image.tmdb.org/t/p/w92' + x.poster_path) : '',
      }));
  } catch (_) { return []; }
}

const UPLOAD_HTML = `<!doctype html>
<html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>העלאת כתובית למאגר POV IL</title>
<style>
:root{color-scheme:dark}
body{font-family:system-ui,Arial,sans-serif;max-width:640px;margin:0 auto;padding:18px;background:#15171c;color:#e8eaed}
h1{font-size:20px;margin:0 0 6px}
.sub{color:#9aa0a6;font-size:13px;margin:0 0 18px}
label{display:block;margin:10px 0 4px;font-size:14px;color:#c8ccd0}
input,select,button{font-size:15px;padding:9px;border-radius:8px;border:1px solid #333;background:#1f232b;color:#e8eaed;box-sizing:border-box}
input,select{width:100%}
fieldset{border:1px solid #2a2f38;border-radius:10px;margin:14px 0;padding:12px}
legend{color:#9aa0a6;font-size:13px;padding:0 6px}
.row{display:flex;gap:10px}.row>div{flex:1}
button{cursor:pointer;background:#3b6;border-color:#3b6;color:#08140c;font-weight:600}
button.sec{background:#2a2f38;border-color:#3a4150;color:#e8eaed;font-weight:500}
#results{margin-top:8px;display:grid;gap:6px}
.res{display:flex;gap:8px;align-items:center;padding:6px;border:1px solid #2a2f38;border-radius:8px;cursor:pointer;background:#1b1f27}
.res:hover{border-color:#3b6}
.res img{width:38px;height:auto;border-radius:4px;background:#333}
.res small{color:#9aa0a6}
#status{margin-top:14px;padding:10px;border-radius:8px;font-size:14px;white-space:pre-wrap;display:none}
.ok{background:#16361f;border:1px solid #2c6}.err{background:#3a1c1c;border:1px solid #c55}
#submitBtn{width:100%;margin-top:16px;padding:12px}
</style></head><body>
<h1>העלאת כתובית עברית למאגר הקהילתי</h1>
<p class="sub">לתרגומים שעשית מחוץ לתוסף. בחר קובץ SRT, זהה את הסרט/פרק, ושלח. כפילויות נמנעות אוטומטית.</p>

<label for="token">טוקן מעלה</label>
<input id="token" placeholder="הדבק כאן את הטוקן שקיבלת" autocomplete="off">

<label for="file">קובץ כתובית (.srt)</label>
<input type="file" id="file" accept=".srt,.txt">

<fieldset>
<legend>זיהוי הסרט / הסדרה</legend>
<div class="row"><div><input id="q" placeholder="חיפוש לפי שם..."></div><div style="flex:0 0 90px"><button class="sec" id="searchBtn" type="button">חפש</button></div></div>
<div id="results"></div>
<div class="row" style="margin-top:8px">
<div><label for="tmdb_id">TMDB id</label><input id="tmdb_id" inputmode="numeric"></div>
<div><label for="imdb_id">IMDb id</label><input id="imdb_id" placeholder="tt..."></div>
</div>
</fieldset>

<div class="row">
<div><label for="type">סוג</label><select id="type"><option value="movie">סרט</option><option value="episode">פרק</option></select></div>
<div><label for="year">שנה</label><input id="year" inputmode="numeric"></div>
</div>
<div class="row" id="eprow" style="display:none">
<div><label for="season">עונה</label><input id="season" value="0" inputmode="numeric"></div>
<div><label for="episode">פרק</label><input id="episode" value="0" inputmode="numeric"></div>
</div>
<label for="title">כותרת (לתצוגה בערוץ)</label><input id="title">
<label for="source_lang">שפת מקור התרגום</label><input id="source_lang" value="en">

<button id="submitBtn" type="button">העלה למאגר</button>
<div id="status"></div>

<script>
var $=function(id){return document.getElementById(id)};
function showStatus(msg,ok){var s=$('status');s.textContent=msg;s.className=ok?'ok':'err';s.style.display='block'}
function syncEpRow(){$('eprow').style.display=$('type').value==='episode'?'flex':'none'}
$('type').addEventListener('change',syncEpRow);
try{var t=localStorage.getItem('povil_upload_token');if(t)$('token').value=t}catch(e){}
$('token').addEventListener('change',function(){try{localStorage.setItem('povil_upload_token',$('token').value.trim())}catch(e){}});

var lastFileName='';
$('file').addEventListener('change',function(){
  var f=this.files&&this.files[0];if(!f)return;lastFileName=f.name;
  var base=f.name.replace(/\\.[^.]+$/,'');
  var m=base.match(/S(\\d{1,2})[._\\s-]?E(\\d{1,2})/i)||base.match(/(\\d{1,2})x(\\d{1,2})/i);
  if(m){$('type').value='episode';$('season').value=String(parseInt(m[1],10));$('episode').value=String(parseInt(m[2],10))}
  var y=base.match(/(19|20)\\d{2}/);if(y)$('year').value=y[0];
  var cut=base.search(/[._\\s-](?:S\\d{1,2}[._\\s-]?E\\d{1,2}|\\d{1,2}x\\d{1,2}|(?:19|20)\\d{2}|2160p|1080p|720p|480p|web|bluray|brrip|bdrip|x264|x265|hevc)/i);
  var guess=(cut>0?base.slice(0,cut):base).replace(/[._]+/g,' ').trim();
  if(guess){if(!$('title').value)$('title').value=guess;$('q').value=guess}
  syncEpRow();
});

$('searchBtn').addEventListener('click',function(){
  var token=$('token').value.trim();if(!token){showStatus('צריך טוקן מעלה.',false);return}
  var q=$('q').value.trim();if(!q){showStatus('הקלד שם לחיפוש.',false);return}
  $('results').innerHTML='מחפש...';
  fetch('/tmdb-search?token='+encodeURIComponent(token)+'&q='+encodeURIComponent(q))
   .then(function(r){return r.json()}).then(function(d){
     if(!d.ok){$('results').innerHTML='';showStatus('חיפוש נכשל (טוקן שגוי?).',false);return}
     var R=$('results');R.innerHTML='';
     if(!d.results.length){R.textContent='לא נמצאו תוצאות.';return}
     d.results.forEach(function(it){
       var div=document.createElement('div');div.className='res';
       div.innerHTML=(it.poster?'<img src="'+it.poster+'">':'<img>')+'<div><b>'+it.title+'</b> <small>'+(it.year||'')+' · '+(it.type==='episode'?'סדרה':'סרט')+'</small></div>';
       div.addEventListener('click',function(){
         $('tmdb_id').value=it.id;$('imdb_id').value='';$('type').value=it.type;
         if(it.title)$('title').value=it.title;if(it.year)$('year').value=it.year;
         syncEpRow();showStatus('נבחר: '+it.title+' ('+it.year+')',true);
       });
       R.appendChild(div);
     });
   }).catch(function(){$('results').innerHTML='';showStatus('שגיאת רשת בחיפוש.',false)});
});

$('submitBtn').addEventListener('click',function(){
  var token=$('token').value.trim();if(!token){showStatus('צריך טוקן מעלה.',false);return}
  var f=$('file').files&&$('file').files[0];if(!f){showStatus('בחר קובץ SRT.',false);return}
  if(!$('tmdb_id').value.trim()&&!$('imdb_id').value.trim()){showStatus('זהה את הסרט/הסדרה (חיפוש או id).',false);return}
  var fd=new FormData();
  fd.append('srt',f,f.name);
  fd.append('release',lastFileName.replace(/\\.[^.]+$/,''));
  fd.append('tmdb_id',$('tmdb_id').value.trim());
  fd.append('imdb_id',$('imdb_id').value.trim());
  fd.append('type',$('type').value);
  fd.append('season',$('season').value.trim()||'0');
  fd.append('episode',$('episode').value.trim()||'0');
  fd.append('title',$('title').value.trim());
  fd.append('year',$('year').value.trim());
  fd.append('source_lang',$('source_lang').value.trim()||'en');
  $('submitBtn').disabled=true;showStatus('מעלה...',true);
  fetch('/web-upload',{method:'POST',headers:{'x-upload-token':token},body:fd})
   .then(function(r){return r.json()}).then(function(d){
     $('submitBtn').disabled=false;
     if(d.ok&&d.dedup)showStatus('כבר קיים במאגר — לא נוצרה כפילות. ✔',true);
     else if(d.ok)showStatus('הועלה למאגר בהצלחה! ✔',true);
     else showStatus('שגיאה: '+(d.error||'לא ידוע'),false);
   }).catch(function(){$('submitBtn').disabled=false;showStatus('שגיאת רשת בהעלאה.',false)});
});
syncEpRow();
</script></body></html>`;

// ---- Usage telemetry (D1) ---------------------------------------------------
// Anonymous AI-translation events. The table is auto-created on first use. The
// dashboard counts only add-on versions >= the one that shipped the Arabic
// option default-ON; telemetry itself only exists from a later version, so the
// filter is always satisfied (kept explicit + future-proof).
const TELE_MIN_VER = '0.2.267';
function _ts(x) { return x === undefined || x === null ? '' : String(x); }
function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function _pct(n, d) { return d ? Math.round((n * 1000) / d) / 10 : 0; }

async function ensureTeleSchema(env) {
  await env.DB.prepare(
    `CREATE TABLE IF NOT EXISTS tr_events (
       id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, anon TEXT, v TEXT,
       type TEXT, title TEXT, season TEXT, episode TEXT, year TEXT, src TEXT,
       method TEXT, ok INTEGER, note TEXT, hinted INTEGER, model TEXT, think TEXT,
       reason TEXT, ar_cands INTEGER)`
  ).run();
  // Add the newer columns to a pre-existing table (D1 has no ADD COLUMN IF NOT
  // EXISTS, so ignore the "duplicate column" error).
  for (const col of ['reason TEXT', 'ar_cands INTEGER', 'dur INTEGER']) {
    try { await env.DB.prepare(`ALTER TABLE tr_events ADD COLUMN ${col}`).run(); } catch (e) { /* exists */ }
  }
}

async function recordEvent(env, body, ts) {
  if (!env.DB) return json({ ok: true, stored: false }); // D1 not bound yet
  const b = body || {};
  try {
    await ensureTeleSchema(env);
    await env.DB.prepare(
      `INSERT INTO tr_events (ts,anon,v,type,title,season,episode,year,src,method,ok,note,hinted,model,think,reason,ar_cands,dur)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
    ).bind(
      ts, _ts(b.anon).slice(0, 40), _ts(b.v).slice(0, 16), _ts(b.type).slice(0, 12),
      _ts(b.title).slice(0, 160), _ts(b.season).slice(0, 8), _ts(b.episode).slice(0, 8),
      _ts(b.year).slice(0, 8), _ts(b.src).slice(0, 8), _ts(b.method).slice(0, 16),
      b.ok ? 1 : 0, _ts(b.note).slice(0, 80), Number(b.hinted) || 0,
      _ts(b.model).slice(0, 40), _ts(b.think).slice(0, 16),
      _ts(b.reason).slice(0, 24), Number(b.ar_cands) || 0, Number(b.dur) || 0
    ).run();
  } catch (e) { return json({ ok: false, error: String(e).slice(0, 160) }); }
  return json({ ok: true, stored: true });
}

async function renderStats(env) {
  if (!env.DB) return new Response('D1 not bound. Create a D1 DB and bind it as "DB".', { status: 500 });
  await ensureTeleSchema(env);
  const W = `WHERE v >= '${TELE_MIN_VER}'`;
  const q = async (sql) => ((await env.DB.prepare(sql).all()).results || []);
  const tot = (await q(`SELECT COUNT(*) n, COALESCE(SUM(ok),0) oks, COUNT(DISTINCT anon) users FROM tr_events ${W}`))[0] || { n: 0, oks: 0, users: 0 };
  const bm = await q(`SELECT method, COUNT(*) n, COALESCE(SUM(ok),0) oks FROM tr_events ${W} GROUP BY method`);
  const d1 = (await q(`SELECT COUNT(*) n FROM tr_events ${W} AND ts >= strftime('%s','now')-86400`))[0] || { n: 0 };
  const avg = (await q(`SELECT AVG(dur) a FROM tr_events ${W} AND dur > 0 AND ok=1`))[0] || { a: 0 };
  const days = await q(`SELECT date(ts,'unixepoch') d, COUNT(*) n, COALESCE(SUM(method='ai_ar'),0) ar FROM tr_events ${W} GROUP BY d ORDER BY d DESC LIMIT 14`);
  // WHY fallbacks happened (the key diagnostic) + source-language + version.
  const fbR = await q(`SELECT COALESCE(NULLIF(reason,''),'(unknown)') reason, COUNT(*) n FROM tr_events ${W} AND method='ai_fallback' GROUP BY reason ORDER BY n DESC`);
  const bySrc = await q(`SELECT COALESCE(NULLIF(src,''),'?') src, COUNT(*) n, COALESCE(SUM(method='ai_ar'),0) ar FROM tr_events ${W} GROUP BY src ORDER BY n DESC LIMIT 12`);
  const byVer = await q(`SELECT v, COUNT(*) n FROM tr_events ${W} GROUP BY v ORDER BY v DESC LIMIT 8`);
  const fails = await q(`SELECT ts,title,type,season,episode,src,reason,note,v FROM tr_events ${W} AND ok=0 ORDER BY ts DESC LIMIT 25`);
  const top = await q(`SELECT title, type, COUNT(*) n, COALESCE(SUM(method='ai_ar'),0) ar, COALESCE(SUM(method='ai_fallback'),0) fb, COALESCE(SUM(method='ai_plain'),0) pl FROM tr_events ${W} GROUP BY title ORDER BY n DESC LIMIT 30`);
  const rec = await q(`SELECT ts,title,type,season,episode,src,method,ok,reason,note,v FROM tr_events ${W} ORDER BY ts DESC LIMIT 60`);
  const m = { ai_ar: 0, ai_fallback: 0, ai_plain: 0 };
  bm.forEach(r => { m[r.method] = r.n; });
  const T = tot.n || 0;
  const newPct = _pct(m.ai_ar, T), fbPct = _pct(m.ai_fallback, T), plPct = _pct(m.ai_plain, T);
  const okPct = _pct(tot.oks, T);
  const failN = T - (tot.oks || 0);
  const REASONS = { option_off: 'option off (user)', no_arabic: 'no Arabic subtitle found', no_align: "Arabic didn't sync (alignment)", crash: 'error', no_source: 'no source parsed', ok: 'ok', '(unknown)': '(unknown)' };
  const bar = (label, n, p, col) => `<div class="row"><span class="lbl">${label}</span><div class="track"><div class="fill" style="width:${p}%;background:${col}"></div></div><span class="val">${n} · ${p}%</span></div>`;
  const ep = (r) => r.type === 'episode' ? ` S${String(r.season).padStart(2, '0')}E${String(r.episode).padStart(2, '0')}` : '';
  const fmtT = (s) => new Date(s * 1000).toISOString().replace('T', ' ').slice(0, 16);
  const mColor = { ai_ar: '#46c46a', ai_fallback: '#e0a93a', ai_plain: '#6fb6e0' };
  const recRows = rec.map(r => `<tr><td>${fmtT(r.ts)}</td><td>${_esc(r.title)}${ep(r)}</td><td>${_esc(r.src)}</td><td style="color:${mColor[r.method] || '#aaa'}">${_esc(r.method)}</td><td>${r.ok ? '✓' : '✗'}</td><td><small>${_esc(r.reason || '')} ${_esc(r.note || '')}</small></td></tr>`).join('');
  const topRows = top.map(r => `<tr><td>${_esc(r.title)}</td><td>${r.n}</td><td style="color:#46c46a">${r.ar}</td><td style="color:#e0a93a">${r.fb}</td><td style="color:#6fb6e0">${r.pl}</td></tr>`).join('');
  const avgSec = Math.round(avg.a || 0);
  const avgTxt = avgSec >= 60 ? `${Math.floor(avgSec / 60)}m ${avgSec % 60}s` : `${avgSec}s`;
  const dayChrono = days.slice().reverse();
  const maxDay = Math.max(1, ...dayChrono.map(r => r.n));
  const dayBars = dayChrono.map(r => {
    const h = Math.round((r.n / maxDay) * 120);
    const arh = Math.round((r.ar / maxDay) * 120);
    return `<div class="day"><div class="dn">${r.n}</div><div class="dbar" style="height:${h}px"><div class="dar" style="height:${arh}px"></div></div><div class="dl">${_esc(String(r.d).slice(5))}</div></div>`;
  }).join('');
  const fbTotal = fbR.reduce((a, r) => a + r.n, 0);
  const fbRows = fbR.map(r => bar(REASONS[r.reason] || r.reason, r.n, _pct(r.n, fbTotal), '#e0a93a')).join('');
  const srcRows = bySrc.map(r => `<tr><td>${_esc(r.src)}</td><td>${r.n}</td><td>${_pct(r.ar, r.n)}% Arabic</td></tr>`).join('');
  const verRows = byVer.map(r => `<tr><td>${_esc(r.v)}</td><td>${r.n}</td></tr>`).join('');
  const failRows = fails.map(r => `<tr><td>${fmtT(r.ts)}</td><td>${_esc(r.title)}${ep(r)}</td><td>${_esc(r.reason || '')}</td><td><small>${_esc(r.note || '')}</small></td></tr>`).join('') || '<tr><td colspan="4"><small>no failures 🎉</small></td></tr>';
  const html = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MoranSubs — Stats</title><style>
body{background:#0e1116;color:#e6edf3;font:14px/1.5 system-ui,Segoe UI,Arial;margin:0;padding:18px}
h1{font-size:18px;margin:0 0 4px}h2{font-size:14px;color:#9aa4b2;margin:22px 0 8px;text-transform:uppercase;letter-spacing:.5px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.card{background:#161b22;border:1px solid #232a33;border-radius:10px;padding:12px 16px;min-width:120px}
.card .big{font-size:26px;font-weight:700}.card .sub{color:#9aa4b2;font-size:12px}
.headline{font-size:30px;font-weight:800;color:#46c46a}
.row{display:flex;align-items:center;gap:10px;margin:6px 0}.lbl{width:120px}.val{width:110px;text-align:right;color:#9aa4b2}
.track{flex:1;background:#232a33;border-radius:6px;height:14px;overflow:hidden}.fill{height:100%}
table{width:100%;border-collapse:collapse;margin-top:6px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #232a33;font-size:13px}
th{color:#9aa4b2;font-weight:600}small{color:#9aa4b2}
.days{display:flex;gap:6px;align-items:flex-end;margin-top:10px;overflow-x:auto;padding-bottom:4px}
.day{display:flex;flex-direction:column;align-items:center;min-width:40px}
.day .dn{font-size:11px;color:#9aa4b2;margin-bottom:3px}
.dbar{width:26px;height:0;background:#2f6b3f;border-radius:4px 4px 0 0;position:relative;display:flex;align-items:flex-end}
.dar{width:26px;background:#46c46a;border-radius:4px 4px 0 0}
.day .dl{font-size:10px;color:#9aa4b2;margin-top:4px}
</style>
<h1>MoranSubs — Translation Stats</h1>
<small>add-on ≥ ${TELE_MIN_VER} · auto-refresh 30s</small>
<div class="cards">
<div class="card"><div class="big">${T}</div><div class="sub">AI translations</div></div>
<div class="card"><div class="big">${tot.users}</div><div class="sub">unique users</div></div>
<div class="card"><div class="big">${okPct}%</div><div class="sub">delivered ok</div></div>
<div class="card"><div class="big" style="color:${failN ? '#d0594f' : '#46c46a'}">${failN}</div><div class="sub">failures (no subtitle)</div></div>
<div class="card"><div class="big">${d1.n}</div><div class="sub">last 24h</div></div>
<div class="card"><div class="big">${avgTxt}</div><div class="sub">avg translation time</div></div>
</div>
<h2>Daily (last 14 days · green = used Arabic)</h2>
<div class="days">${dayBars || '<small>no data yet</small>'}</div>
<small>“delivered ok” = a Hebrew subtitle was produced (incl. fallback). It stays
~100% as long as translations succeed — the failures card is what to watch.</small>
<h2>New Arabic path vs old</h2>
<div class="headline">${newPct}% new (Arabic)</div>
${bar('🆕 ai_ar (new)', m.ai_ar, newPct, '#46c46a')}
${bar('↩︎ ai_fallback', m.ai_fallback, fbPct, '#e0a93a')}
${bar('▫︎ ai_plain (off)', m.ai_plain, plPct, '#6fb6e0')}
<h2>Why fallbacks happened (${fbTotal})</h2>
${fbRows || '<small>no fallbacks yet</small>'}
<h2>By source language</h2>
<table><tr><th>Lang</th><th>Total</th><th>% used Arabic</th></tr>${srcRows}</table>
<h2>By add-on version</h2>
<table><tr><th>Version</th><th>Translations</th></tr>${verRows}</table>
<h2>Failures</h2>
<table><tr><th>Time (UTC)</th><th>Title</th><th>Reason</th><th>Detail</th></tr>${failRows}</table>
<h2>Top titles</h2>
<table><tr><th>Title</th><th>Total</th><th>ai_ar</th><th>fallback</th><th>plain</th></tr>${topRows}</table>
<h2>Recent</h2>
<table><tr><th>Time (UTC)</th><th>Title</th><th>Src</th><th>Method</th><th>OK</th><th>Reason / detail</th></tr>${recRows}</table>
<script>setTimeout(function(){location.reload()},30000)</script>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    if (path === '/health') return json({ ok: true });

    if (path === '/lookup' && request.method === 'GET') {
      const p = Object.fromEntries(url.searchParams);
      const { variants, primaryKey, keys } = await readMergedIndex(env, p);
      const embedded = await readEmbedded(env, keys);
      const ktuvit = await readKtuvit(env, keys);
      return json({
        ok: true, key: primaryKey, count: variants.length,
        variants: variants.map(v => ({ hash: v.hash, release: v.release, source_lang: v.source_lang, kind: v.kind || 'ai', ts: v.ts })),
        embedded,
        ktuvit: ktuvit.names, ktuvit_checked: ktuvit.checked,
        ktuvit_changed: ktuvit.changed,
      });
    }

    // Add-on report: "this release ships a built-in Hebrew subtitle track."
    if (path === '/embedded' && request.method === 'POST') {
      if (request.headers.get('x-api-key') !== env.API_KEY)
        return json({ ok: false, error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ ok: false, error: 'bad json' }, 400); }
      return await recordEmbedded(env, body);
    }

    // Add-on report: Hebrew release names found on Ktuvit for this title (the
    // first browser checks once; everyone else reads it back via /lookup).
    if (path === '/ktuvit' && request.method === 'POST') {
      if (request.headers.get('x-api-key') !== env.API_KEY)
        return json({ ok: false, error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ ok: false, error: 'bad json' }, 400); }
      return await recordKtuvit(env, body);
    }

    if (path === '/sub' && request.method === 'GET') {
      const p = Object.fromEntries(url.searchParams);
      const { variants } = await readMergedIndex(env, p);
      if (!variants.length) return new Response('not found', { status: 404 });
      const want = (p.hash || '').trim();
      let v = want ? variants.find(x => x.hash === want) : null;
      if (!v) { if (want) return new Response('not found', { status: 404 }); v = variants[variants.length - 1]; }
      const srt = await downloadById(env, v.file_id);
      if (!srt) return new Response('fetch failed', { status: 502 });
      return new Response(srt, { headers: { 'content-type': 'application/x-subrip; charset=utf-8' } });
    }

    if (path === '/contribute' && request.method === 'POST') {
      if (request.headers.get('x-api-key') !== env.API_KEY)
        return json({ ok: false, error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ ok: false, error: 'bad json' }, 400); }
      return await contributeCore(env, body);
    }

    // Manual web upload (for translations made outside the add-on).
    if (path === '/upload' && request.method === 'GET') {
      return new Response(UPLOAD_HTML, {
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    if (path === '/tmdb-search' && request.method === 'GET') {
      if (!checkUploadToken(env, url.searchParams.get('token')))
        return json({ ok: false, error: 'unauthorized' }, 401);
      return json({ ok: true, results: await tmdbSearch(env, url.searchParams.get('q')) });
    }

    if (path === '/web-upload' && request.method === 'POST') {
      if (!checkUploadToken(env, request.headers.get('x-upload-token')))
        return json({ ok: false, error: 'unauthorized' }, 401);
      let form;
      try { form = await request.formData(); } catch { return json({ ok: false, error: 'bad form' }, 400); }
      const file = form.get('srt');
      let srt = '';
      try { srt = (file && typeof file.text === 'function') ? await file.text() : String(file || ''); } catch (_) {}
      const body = {
        tmdb_id: String(form.get('tmdb_id') || '').trim(),
        imdb_id: String(form.get('imdb_id') || '').trim(),
        type: String(form.get('type') || 'movie'),
        season: String(form.get('season') || '0'),
        episode: String(form.get('episode') || '0'),
        lang: 'he',
        release: String(form.get('release') || '').trim(),
        source_hash: '',
        source_lang: String(form.get('source_lang') || 'en'),
        title: String(form.get('title') || '').trim(),
        year: String(form.get('year') || '').trim(),
        srt: srt,
      };
      return await contributeCore(env, body);
    }

    // Anonymous usage telemetry from the add-on (one event per AI translation).
    if (path === '/ev' && request.method === 'POST') {
      if (request.headers.get('x-api-key') !== env.API_KEY)
        return json({ ok: false, error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ ok: false, error: 'bad json' }, 400); }
      return await recordEvent(env, body, Math.floor(Date.now() / 1000));
    }

    // Owner-only stats dashboard: /stats?key=<STATS_TOKEN>
    if (path === '/stats' && request.method === 'GET') {
      if (!env.STATS_TOKEN || url.searchParams.get('key') !== env.STATS_TOKEN)
        return new Response('unauthorized', { status: 401 });
      return await renderStats(env);
    }

    return new Response('Kodi POV IL — AI subtitle pool', { status: 200 });
  },
};
